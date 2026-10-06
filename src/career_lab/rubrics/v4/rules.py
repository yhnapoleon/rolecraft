from career_lab.contracts.v2.core import EvidenceRefV2, ProtocolError
from career_lab.contracts.v2.evaluation import FeedbackItem, RuleBound


def pending(item,reason):
    return FeedbackItem(criterion=item.criterion,label='INSUFFICIENT',applicability=item.applicability,
                        source='pending',explanation=reason,citations=())


def run_rules(item):
    if item.applicability=='not_applicable':
        return FeedbackItem(criterion=item.criterion,label='NOT_APPLICABLE',applicability=item.applicability,
            source='verified_rule',explanation='本次作品用途和评价时点暂不要求完成这一项。',citations=())
    if item.applicability=='undetermined':return pending(item,'用途或责任尚不明确，请先说明希望评审的内容。')
    ctx=item.rule_context;facts=ctx['facts'];proofs=ctx['fact_refs'];kind=ctx['mechanism']
    def numeric(names):
        if any(n not in facts or type(facts[n]) not in (int,float) or facts[n]<0 or not proofs.get(n) for n in names):return None
        return [facts[n] for n in names]
    def verified(label,reason,names=(),extra=(),upper=None):
        refs=list(extra)
        for n in names:
            refs.extend(EvidenceRefV2.model_validate(r) for r in proofs[n])
        refs=list({r.model_dump_json():r for r in refs}.values())
        return FeedbackItem(criterion=item.criterion,label=label,applicability='applicable',source='verified_rule',
            explanation=reason,citations=tuple(refs),rule_bound=RuleBound(lower=label,upper=upper or label))
    if kind=='capacity':
        names=('participants','capacity');v=numeric(names)
        if v is None:return pending(item,'当时人数或有效容量依据不完整，暂不判断责任是否满足。')
        return verified('MET' if 0<v[0]<=v[1] else 'NOT_MET',f'按评价时点核对：固定配置人数{v[0]}，有效容量{v[1]}。',names)
    if kind=='resources':
        names=('required_dev_days','available_dev_days','requested_launch_day','deadline_day');v=numeric(names)
        if v is None:return pending(item,'当时资源、批准或时限依据不完整，需补充核对。')
        okay=v[0]<=v[1] and 0<v[2]<=v[3]
        return verified('MET' if okay else 'NOT_MET',f'当时所需/可用人日为{v[0]}/{v[1]}，承诺日/有效期限为{v[2]}/{v[3]}。',names)
    if kind=='tests':
        if not ctx['logs_complete'] or item.missing_refs:return pending(item,'测试记录或日志缺失，无法据此判断未做测试。')
        tests=ctx['tests'];version=ctx['config_version']
        if version is None:return pending(item,'缺少评价时点的配置版本。')
        valid=[t for t in tests if t['record']['config']['effective']['config_version']==version and t['record']['status']!='failed']
        if not valid:
            if ctx['technical_failures'] or any(t['record']['status']=='failed' for t in tests):
                return pending(item,'测试受技术失败影响，不能据此判为用户未完成。')
            refs=tuple(EvidenceRefV2.model_validate(t['ref']) for t in tests)
            # An empty complete ledger is a trusted observation, not missing logs.
            ledger=proofs.get('test_ledger_complete',[])
            if not ledger or facts.get('test_ledger_complete') is not True:return pending(item,'没有足以确认测试缺失的完整记录。')
            return verified('NOT_MET','完整记录中没有相关配置下的有效测试。',('test_ledger_complete',),refs)
        refs=tuple(EvidenceRefV2.model_validate(t['ref']) for t in valid)
        # declared_category/expected and repeated FAQ labels never grant MET.
        return verified('PARTIAL','已有相关配置下的实际运行；覆盖面及其对判断的支持仍需核验。',extra=refs,upper='MET')
    return pending(item,'内容与证据关系仍需情境核验；模板、结论枚举和重复操作次数不直接决定评价。')
