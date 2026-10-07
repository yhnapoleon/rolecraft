"""Advisory feedback with source-separated coverage; never auto-enable scoring."""
from career_lab.contracts.v2.core import digest, ProtocolError
from career_lab.contracts.v2.evaluation import FeedbackV2, FeedbackItem, RuleBound, EvidencePackageV2
from .judge import AdvisoryJudge
from .rules import run_rules
from career_lab.evidence.v2.assembler import purpose_of


class FeedbackEngine:
    def __init__(self,judge=None):self.judge=judge or AdvisoryJudge()

    def evaluate(self,session_id,subject,evaluation,as_of,packages,expected_model_revision=None):
        if subject.session_id!=session_id:raise ProtocolError('feedback_session_mismatch')
        if len({p.criterion for p in packages})!=len(packages):raise ProtocolError('duplicate_evaluation_criterion')
        if any(p.as_of!=as_of or p.task_type!='criterion' or any(r.session_id!=session_id for r in p.subjects) for p in packages):
            raise ProtocolError('evaluation_scope_mismatch')
        items=[];rule_items=[];attempts=[]
        for package in packages:
            package=EvidencePackageV2.model_validate(package.model_dump(mode='json'))
            rule=run_rules(package)
            rule_items.append(rule)
            interval=rule.rule_bound and rule.rule_bound.lower!=rule.rule_bound.upper
            if interval:
                bounded=package.model_dump(mode='json',exclude={'input_hash'})
                bounded['rule_bound']=rule.rule_bound.model_dump(mode='json');bounded['input_hash']=digest(bounded)
                result=self.judge.evaluate(EvidencePackageV2.model_validate(bounded),expected_model_revision)
                attempts.append({'criterion':package.criterion,'attempts':list(result.attempts)})
                if result.item.source=='model_advice' and result.item.label!='INSUFFICIENT':
                    items.append(result.item.model_copy(update={'explanation':f'规则已核验区间：{rule.rule_bound.lower}—{rule.rule_bound.upper}。'+rule.explanation+'\n模型建议（不改变规则区间）：'+result.item.explanation,
                        'citations':tuple({r.model_dump_json():r for r in [*rule.citations,*result.item.citations]}.values())}))
                else:items.append(rule)
            elif rule.source=='verified_rule' or package.applicability!='applicable' or package.rule_context['mechanism']!='semantic':items.append(rule)
            else:
                result=self.judge.evaluate(package,expected_model_revision)
                items.append(result.item);attempts.append({'criterion':package.criterion,'attempts':list(result.attempts)})
        # Coverage is over applicable criteria, not arbitrary numbers of citations.
        applicable=[i for i in items if i.applicability=='applicable']
        denominator=len(applicable)
        verified=sum(i.source=='verified_rule' and i.label!='INSUFFICIENT' and i.applicability=='applicable' for i in rule_items)
        model=sum(i.source=='model_advice' and i.label!='INSUFFICIENT' for i in applicable)
        business=list(dict.fromkeys(p.rule_context.get('business_response','') for p in packages if p.rule_context.get('business_response')))
        next_options=[]
        if any(p.applicability=='undetermined' and purpose_of(p.purpose) is None for p in packages):
            next_options.append('作品用途尚未明确；可说明希望评审的内容，已核验事实仍保留。')
        elif any(p.applicability=='undetermined' and p.rule_context.get('decision') is None for p in packages):
            next_options.append('作品用途已记录，本次决定尚未声明；可补充决定，也可保留未定状态继续查看事实反馈。')
        if any(p.rule_context.get('decision') is not None for p in packages):
            next_options.append('你的决定声明已记录；审批与执行不会由声明自动确认，仍按各自可核验记录展示。')
        if any(i.source=='pending' for i in items):
            next_options.append('待核验项尚未形成结论；已核验事实可继续查看，需要时可补证或另发评审。')
        if any(i.label in {'NOT_MET','PARTIAL'} for i in items):next_options.append('按具体依据补证、调整承诺或重测，并在新修订周期再次交付。')
        next_options.append('可以提出不同看法；反馈不代表业务批准，也不推断未观察到的独立掌握。')
        report=FeedbackV2(id=digest([session_id,subject.model_dump(mode='json'),evaluation.model_dump(mode='json'),'feedback-v2']),
            session_id=session_id,subject=subject,evaluation=evaluation,as_of=as_of,items=tuple(items),
            business_response='\n'.join(business) or '当前没有可核验的业务决定记录。',
            next_options=tuple(next_options),verified_coverage=verified/denominator if denominator else 0,
            model_coverage=model/denominator if denominator else 0,mode='advisory',independent_understanding='unobserved')
        return report,{'model_revision':self.judge.revision,'criterion_attempts':attempts,
                       'input_hashes':[p.input_hash for p in packages],
                       'verified_facts':list({digest(f):f for p in packages for f in p.rule_context.get('verified_facts',[])}.values()),
                       'historical_responsibilities':[h for p in packages for h in p.rule_context.get('historical_responsibilities',[])],
                       'rule_items':[i.model_dump(mode='json') for i in rule_items],
                       'score_bounds':score_bounds(rule_items)}


def score_bounds(items):
    """Criterion intervals only. No invented rubric weights or overall score."""
    order={'NOT_MET':0.0,'PARTIAL':0.5,'MET':1.0};eligible=[i for i in items if i.applicability=='applicable']
    intervals={}
    for item in eligible:
        if item.source=='verified_rule' and item.rule_bound is not None:
            low,high=order[item.rule_bound.lower],order[item.rule_bound.upper]
        else:low,high=0.0,1.0
        intervals[item.criterion]={'lower':low,'upper':high}
    only=next(iter(intervals.values())) if len(intervals)==1 else {'lower':None,'upper':None}
    return {**only,'criteria':intervals,'count':len(eligible),'mode':'advisory',
            'aggregation':'not_aggregated_without_frozen_weights'}


class FeedbackDispatcher:
    """Explicit legacy/v4 dispatch. Saved historical feedback is read unchanged."""
    def __init__(self,legacy_saved,legacy_generate,v4):
        self.legacy_saved,self.legacy_generate,self.v4=legacy_saved,legacy_generate,v4

    def get_or_generate(self,revision,session_id,subject_id):
        if revision=='rules-v4':return self.v4(session_id,subject_id)
        try:return self.legacy_saved(session_id,subject_id)
        except KeyError:pass
        if revision!='rules-v3':
            from career_lab.contracts.v2.core import ProtocolError
            raise ProtocolError('historical_rules_unavailable',status=422)
        return self.legacy_generate(session_id,subject_id)
