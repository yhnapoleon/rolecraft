"""Paired deterministic language checks; no provider quality or production binding claim."""
import json,hashlib,re
from copy import deepcopy
import pytest
from test_w05_default_facts import history_payload,default_review,duty,point
from career_lab.contracts import v2 as C
from career_lab.api.reviews_v2 import create_review_evaluator
from career_lab.evidence.v2.assembler import purpose_of,EvidenceAssemblerV2,applicable
from career_lab.evidence.v2.ports import DEFAULT_POLICIES
from career_lab.evidence.v2.localization import EN,message


@pytest.mark.parametrize('text,expected',[
 ('TEST PLAN','plan'),(' Test   Plan\n','plan'),('test_plan','plan'),('test-plan','plan'),('测试计划','plan'),('plan','plan'),
 ('Result Report','result'),('result_report','result'),('结果报告','result'),('result','result'),
 ('PILOT DECISION','commitment'),(' pilot\tdecision ','commitment'),('试点决定','commitment'),('commitment','commitment'),
 ('a result report might be useful',None),('launch now',None),('I refuse to launch',None),('',None)])
def test_w05_purpose_aliases_match_exact_labels_only(text,expected):
    assert purpose_of(text)==expected


@pytest.mark.parametrize('purpose,alias',[('测试计划','Test Plan'),('结果报告','RESULT REPORT'),('试点决定','Pilot Decision'),('探索笔记','exploration'),('自由用途未明确','Unspecified custom purpose')])
@pytest.mark.parametrize('decision',[None,'launch','launch_narrow','no_go','defer_with_conditions'])
def test_w05_paired_purpose_decision_rule_and_history_matrix(tmp_path,purpose,alias,decision):
    raw=history_payload(investigated=True)
    raw['rule_snapshots'][0]['responsibilities']=[duty(raw,'actual_action',facts={'actual_participants':40,'capacity_at_action':30})]
    _,reader,auth,product=default_review(tmp_path,raw)
    results=[create_review_evaluator(reader,work_language=language).review(auth,(product,),purpose=p,decision=decision,requested_at=point(5))['reviews'][0] for language,p in [('zh',purpose),('en',alias)]]
    def facts(r):
        return {'items':[{k:i[k] for k in ('criterion','label','source','applicability','citations','rule_bound')} for i in r['feedback']['items']],
                'activity_totals':r['verified_facts']['activity_totals'],'references':r['verified_facts']['references'],
                'history':[{k:h[k] for k in ('criterion','kind','finding','scope','sources')} for h in r['historical_responsibilities']]}
    assert facts(results[0])==facts(results[1])
    assert results[1]['historical_responsibilities'][0]['finding']=='verified_breach'
    assert 'historical action' in results[1]['historical_responsibilities'][0]['explanation']
    english_generated=[*results[1]['verified_facts']['summary'],*results[1]['feedback']['next_options'],*[i['explanation'] for i in results[1]['feedback']['items']]]
    assert not re.search(r'[\u4e00-\u9fff]',' '.join(english_generated))
    assert results[0]['verified_facts']['summary']!=results[1]['verified_facts']['summary']


def test_w05_unknown_purpose_keeps_source_and_does_not_infer_commitment(tmp_path):
    raw=history_payload();raw['records'][0]['text']='LAUNCH NOW, already live, pilot decision!'
    _,reader,auth,p=default_review(tmp_path,raw)
    evaluator=create_review_evaluator(reader,work_language='en')
    result=evaluator.review(auth,(p,),purpose='My free-form reflection',requested_at=point(5))['reviews'][0]
    assert result['decision'] is None and result['decision_origin']=='unspecified'
    assert all(i['applicability']=='undetermined' for i in result['feedback']['items'])
    item=EvidenceAssemblerV2(reader,work_language='en').assemble(auth=auth,subject_id='p',subjects=(p,),evidence_refs=(),purpose='My free-form reflection',decision=None,as_of=point(3),policy=reader.policies()[0],snapshot=reader.snapshot(auth,p,point(3)))
    assert item.purpose=='My free-form reflection' and any(c.text==raw['records'][0]['text'] for c in item.candidate_evidence)


def test_w05_english_followup_and_local_private_gap_preserve_exact_quotes(tmp_path):
    raw=history_payload();raw['records'][0]['declared_refs'][0].update(quote='容量为30。',span_start=0,span_end=6)
    raw['rule_snapshots'][0]['responsibilities']=[duty(raw,'actual_action',facts={'actual_participants':40,'capacity_at_action':30})]
    hidden=raw['records'][-1]['ref']['object_id']
    _,reader,auth,p=default_review(tmp_path,raw)
    scoped=auth.model_copy(update={'allowed_objects':tuple(r['ref']['object_id'] for r in raw['records'] if r['ref']['object_id']!=hidden)})
    request=C.ReviewRequest(id='r',session_id='s',subjects=(p,),purpose='Result Report',as_of=point(5),scope=(),evaluation=reader.evaluation,executor=auth.executor,decision=None,
        followup_of=(C.ObjectRef(session_id='s',kind='feedback_response',object_id='supplement',version=1),))
    result=create_review_evaluator(reader,work_language='en').handle(scoped,request,point(5));r=result['reviews'][0]
    assert result['followup_evidence_status']=='not_evaluated' and result['followup_status']=='linked_not_resolved'
    assert any('unverified by default' in x for x in r['feedback']['next_options'])
    assert r['verified_facts']['references'][0]['ref']['quote']=='容量为30。'
    assert r['historical_responsibilities'][0]['finding']=='unknown'
    assert hidden not in json.dumps(r['feedback']) and 'Some supporting evidence' in r['historical_responsibilities'][0]['explanation']


def test_w05_localization_catalog_has_same_format_placeholders():
    from string import Formatter
    fields=lambda text:{name for _,name,_,_ in Formatter().parse(text) if name is not None}
    assert all(fields(zh)==fields(en) for zh,en in EN.items())
    for language in ('auto','fr','English'):
        with pytest.raises(ValueError):message(language,'材料读取')


@pytest.mark.parametrize('language',['zh','en'])
def test_w05_judge_and_support_prompts_use_language_but_preserve_quoted_text(tmp_path,language):
    from career_lab.rubrics.v4.judge import AdvisoryJudge
    from career_lab.rubrics.v4.support import EvidenceSupportVerifier
    from career_lab.runtime.model_adapter import ModelReply
    raw=history_payload();_,reader,auth,p=default_review(tmp_path,raw)
    policy=next(x for x in reader.policies() if x.mechanism=='semantic')
    package=EvidenceAssemblerV2(reader,work_language=language).assemble(auth=auth,subject_id='p',subjects=(p,),evidence_refs=(),purpose='plan',decision='no_go',as_of=point(3),policy=policy,snapshot=reader.snapshot(auth,p,point(3)))
    candidate=package.candidate_evidence[0]
    class Model:
        retries=0;revision='controlled-script-no-real-provider'
        def __init__(self,body):self.body=body;self.calls=[]
        def complete(self,messages,tools):self.calls.append(messages);return ModelReply(text=json.dumps(self.body,ensure_ascii=False))
    support=Model({'relation':'SUPPORTED','reason':'受控支持' if language=='zh' else 'Controlled support.','spans':[{'id':candidate.id,'quote':candidate.text}]})
    judge=Model({'criterion':policy.id,'label':'PARTIAL','applicability':'applicable','explanation':'受控建议' if language=='zh' else 'Controlled advice.','citation_ids':[candidate.id]})
    outcome=AdvisoryJudge(judge,EvidenceSupportVerifier(support)).evaluate(package,work_language=language)
    assert outcome.attempts[0]['work_language']==language and len(outcome.attempts[0]['prompt_hash'])==64
    assert outcome.item.source=='model_advice' and outcome.item.citations[0].quote==candidate.text
    assert ('解释使用中文' if language=='zh' else 'Write explanation in English') in judge.calls[0][0]['content']
    assert ('解释使用中文' if language=='zh' else 'English reason') in support.calls[0][0]['content']
    assert json.loads(judge.calls[0][1]['content'])['candidate_evidence'][0]['text']==candidate.text
    assert json.loads(support.calls[0][1]['content'])['evidence'][0]['text']==candidate.text
    assert outcome.attempts[0]['support']['spans'][0]['quote']==candidate.text
