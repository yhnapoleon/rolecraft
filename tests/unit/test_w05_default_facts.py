"""Actual immutable-file reader + default evaluator, with no model responses.

The persisted records are explicit synthetic test histories. These tests prove
factual processing, provenance and time boundaries, not W02/production ingestion.
"""
import hashlib,json
from pathlib import Path
import pytest
from career_lab.contracts.v2.core import AuthContext,Executor,ObjectRef,EvidenceRefV2,VersionPoint,ProtocolError
from career_lab.evidence.v2.ports import CriterionPolicy
from career_lab.evidence.v2.snapshot_reader import SnapshotEvidenceReader
from career_lab.api.reviews_v2 import create_review_evaluator
from career_lab.evidence.v2.assembler import EvidenceAssemblerV2
from career_lab.runtime.model_adapter import OpenAICompatibleModel


def point(n):return VersionPoint(business_seq=n,workspace_revision=n,storage_revision=n)
def ref(kind,oid,seq=1,version=1):return EvidenceRefV2(session_id='s',kind=kind,object_id=oid,version=version,observed_at_seq=seq)
def bare(r):return ObjectRef.model_validate({k:v for k,v in r.model_dump(mode='json').items() if k in ObjectRef.model_fields})
def human():return Executor(id='learner-human',kind='human')
def agent():return Executor(id='research-agent',kind='external_agent',delegation_id='delegation')
def record(r,text,seq,executor=None,declared=()):
    return {'ref':r.model_dump(mode='json'),'visible_to':['learner'],'text':text,'created_at':point(seq).model_dump(mode='json'),
            'declared_refs':[x.model_dump(mode='json') for x in declared],
            'author':human().model_dump(mode='json'),'executor':(executor or human()).model_dump(mode='json'),'adopter':None}


def history_payload(*,investigated=False,agent_work=False,complete=True,declared=True):
    p=ref('product','p',3);m=ref('material','m',1);proof=ref('event','ledger-proof',1)
    policies=[CriterionPolicy('R3.capacity','承诺容量','capacity',('commitment','result'),True),
        CriterionPolicy('R3.resources','资源责任','resources',('commitment','result'),True),
        CriterionPolicy('R4.functional_tests','验证要求','tests',('commitment','result'),True),
        CriterionPolicy('decision.rationale','判断依据',purposes=('exploration','option','plan','commitment','result'))]
    records=[record(p,'调查后建议暂缓；引用真实不代表理由必然成立。' if investigated else '未调查，直接放弃。',3,declared=(m,) if declared else ()),
             record(m,'容量为30。期限为7日。',1),record(proof,'当时有效容量30；计划人数0；未开放用户。',1)]
    activities=[];executor=agent() if agent_work else human()
    if investigated:
        specs=[('material_read','read',bare(m)),('test_run','run',None),('question_sent','question',None),
               ('reply_received','reply',bare(ref('event','question',2)))]
        for kind,oid,target in specs:
            r=ref('event',oid,2);event=record(r,kind+'的实际记录',2,executor)
            event.update(activity_kind=kind,activity_target=target.model_dump(mode='json') if target else None,actor_id='learner');records.append(event)
            activities.append({'ref':r.model_dump(mode='json'),'kind':kind,'occurred_at':point(2).model_dump(mode='json'),
                'executor':executor.model_dump(mode='json'),'actor_id':'learner','target':target.model_dump(mode='json') if target else None,
                'counterparty':'tech_lead' if kind in {'question_sent','reply_received'} else None})
    kinds=['material_read','test_run','question_sent','reply_received','learner_displayed']
    facts=[{'name':name,'value':value,'sources':[proof.model_dump(mode='json')]} for name,value in {'participants':0,'capacity':30,'required_dev_days':0,'available_dev_days':3,'requested_launch_day':0,'deadline_day':7,'test_ledger_complete':True}.items()]
    return {'schema_version':1,'session_id':'s','actor_id':'learner','captured_at':point(5).model_dump(mode='json'),
        'evaluation':{'path':'test-fixture-only-evaluation.json','sha256':'1'*64},'policies':[p.to_dict() for p in policies],
        'records':records,'activity_ledger':{'records':activities,'completeness':{k:complete for k in kinds},
            'covered_from':point(0).model_dump(mode='json'),'covered_through':point(5).model_dump(mode='json')},
        'rule_snapshots':[{'subject':bare(p).model_dump(mode='json'),'as_of':point(3).model_dump(mode='json'),'facts':facts,
            'logs_complete':True,'tests':[],'test_refs':[],'config_version':0,'responsibilities':[]}]}


def default_review(tmp_path,raw,*,purpose='result',decision=None,name='snapshot',requested=5):
    path=tmp_path/(name+'.json');data=json.dumps(raw,ensure_ascii=False).encode();path.write_bytes(data)
    reader=SnapshotEvidenceReader(path,hashlib.sha256(data).hexdigest())
    auth=AuthContext(session_id='s',actor_id='learner',executor=human(),capabilities=('read',),credential_id='verified-snapshot-consumer')
    product=bare(EvidenceRefV2.model_validate(raw['records'][0]['ref']))
    result=create_review_evaluator(reader).review(auth,(product,),purpose=purpose,decision=decision,requested_at=point(requested))
    return result['reviews'][0],reader,auth,product


def duty(raw,kind,*,criterion='R3.capacity',seq=2,state='active',facts=None,until=None):
    source=ref('event','duty-'+str(len(raw['records'])),seq)
    raw['records'].append(record(source,'由结构化历史记录提供的'+kind,seq))
    return {'criterion':criterion,'kind':kind,'state':state,'occurred_at':point(seq).model_dump(mode='json'),
        'valid_from':point(seq).model_dump(mode='json'),'valid_until':point(until).model_dump(mode='json') if until else None,
        'scope':[raw['rule_snapshots'][0]['subject']],'sources':[source.model_dump(mode='json')],
        'facts':[{'name':k,'value':v,'sources':[source.model_dump(mode='json')]} for k,v in (facts or {}).items()]}


def test_default_reader_distinguishes_verified_history_without_scoring_the_decision(tmp_path,monkeypatch):
    monkeypatch.setattr(OpenAICompatibleModel,'complete',lambda *_:pytest.fail('no model may be called'))
    rich,_,_,_=default_review(tmp_path,history_payload(investigated=True),name='with-records')
    empty,_,_,_=default_review(tmp_path,history_payload(investigated=False,declared=False),name='no-records')
    assert rich['verified_facts']['declared_source_count']==1 and empty['verified_facts']['declared_source_count']==0
    assert rich['verified_facts']['activity_totals']['material_read']['count']==1
    assert empty['verified_facts']['activity_totals']['material_read']['count']==0
    assert rich['verified_facts']['summary']!=empty['verified_facts']['summary']
    for item in [rich,empty]:
        quality=next(x for x in item['feedback']['items'] if x['criterion']=='decision.rationale')
        assert quality['source']=='pending' and quality['label']=='INSUFFICIENT'
        assert item['verified_facts']['conclusion_quality']=='not_scored'
        assert item['feedback']['independent_understanding']=='unobserved'
        assert item['evaluated_at']==point(3).model_dump(mode='json') and item['requested_at']==point(5).model_dump(mode='json')


def test_reference_counts_only_product_linked_sources_and_quote_occurrences(tmp_path):
    raw=history_payload(declared=False)
    m=EvidenceRefV2.model_validate(raw['records'][1]['ref'])
    a=m.model_copy(update={'quote':'容量为30。','span_start':0,'span_end':6})
    b=m.model_copy(update={'quote':'期限为7日。','span_start':6,'span_end':12})
    raw['records'][0]['declared_refs']=[a.model_dump(mode='json'),a.model_dump(mode='json'),b.model_dump(mode='json')]
    result,_,_,_=default_review(tmp_path,raw)
    facts=result['verified_facts'];assert facts['declared_source_count']==1 and facts['declared_citation_count']==2
    assert facts['verified_source_count']==1  # Product body and ledger proof are not citations.
    assert all(r['semantic_support']=='not_established' for r in facts['references'])


def test_incomplete_or_scoped_logs_are_unknown_not_zero(tmp_path):
    result,reader,auth,p=default_review(tmp_path,history_payload(declared=False,complete=False))
    assert all(v['status']=='unknown' and v['count'] is None for v in result['verified_facts']['activity_totals'].values())
    scoped=auth.model_copy(update={'allowed_objects':('p','m','ledger-proof')})
    other=create_review_evaluator(reader).review(scoped,(p,),purpose='result',requested_at=point(5))['reviews'][0]
    assert all(v['count'] is None for v in other['verified_facts']['activity_totals'].values())


def test_agent_question_reply_display_and_understanding_are_separate(tmp_path):
    result,_,_,_=default_review(tmp_path,history_payload(investigated=True,agent_work=True))
    facts=result['verified_facts'];assert facts['activity_totals']['question_sent']['count']==1
    assert facts['activity_totals']['reply_received']['count']==1 and facts['activity_totals']['learner_displayed']['count']==0
    assert all(r['executor']['kind']=='external_agent' for r in facts['activity_records'])
    assert facts['independent_understanding']=='unobserved' and any('不视为学员独立' in x for x in facts['summary'])


@pytest.mark.parametrize('kind',['actual_action','commitment','completion_claim','unknown'])
@pytest.mark.parametrize('purpose',['exploration','option','plan','test_plan','result','commitment','unknown'])
def test_none_decision_and_responsibility_type_never_bypass_purpose(tmp_path,kind,purpose):
    raw=history_payload();raw['rule_snapshots'][0]['responsibilities']=[duty(raw,kind,facts={'actual_participants':0,'capacity_at_action':30,'claimed_participants':0,'actual_participants_at_claim':0})]
    result,_,_,_=default_review(tmp_path,raw,purpose=purpose)
    item=next(x for x in result['feedback']['items'] if x['criterion']=='R3.capacity')
    assert item['label'] not in {'MET','PARTIAL','NOT_MET'}
    assert len(result['historical_responsibilities'])==1


@pytest.mark.parametrize('decision',['no_go','defer_with_conditions'])
def test_withdrawn_commitment_no_actual_launch_is_not_failed_and_duties_coexist(tmp_path,decision):
    raw=history_payload(investigated=True)
    raw['rule_snapshots'][0]['responsibilities']=[duty(raw,'commitment',state='withdrawn'),
        duty(raw,'actual_action',facts={'actual_participants':0,'capacity_at_action':30}),
        duty(raw,'actual_action',criterion='R3.resources',facts={'actual_dev_days':0,'available_dev_days_at_action':3})]
    result,_,_,_=default_review(tmp_path,raw,purpose='commitment',decision=decision)
    assert all(i['label']!='NOT_MET' for i in result['feedback']['items'])
    assert [r['finding'] for r in result['historical_responsibilities']]==['recorded_commitment','verified_within_limit','verified_within_limit']


def test_actual_prior_breach_and_false_claim_are_separate_from_current_stop_grade(tmp_path):
    raw=history_payload();raw['rule_snapshots'][0]['responsibilities']=[duty(raw,'actual_action',facts={'actual_participants':40,'capacity_at_action':30}),
        duty(raw,'completion_claim',criterion='R4.functional_tests',facts={'valid_test_count_at_claim':0,'test_ledger_complete_at_claim':True})]
    result,_,_,_=default_review(tmp_path,raw,decision='no_go')
    assert all(i['label']!='NOT_MET' for i in result['feedback']['items'])
    assert [r['finding'] for r in result['historical_responsibilities']]==['verified_breach','verified_breach']
    raw['rule_snapshots'][0]['responsibilities'][1]['facts'][1]['value']=False
    incomplete,_,_,_=default_review(tmp_path,raw,decision='no_go',name='claim-log-gap')
    assert incomplete['historical_responsibilities'][1]['finding']=='unknown'


def test_later_responsibility_and_investigation_do_not_rewrite_old_work(tmp_path):
    raw=history_payload(declared=False);raw['rule_snapshots'][0]['responsibilities']=[duty(raw,'actual_action',seq=4,facts={'actual_participants':40,'capacity_at_action':30})]
    r=ref('event','later-read',4);raw['records'].append(record(r,'后来的调查',4))
    raw['activity_ledger']['records'].append({'ref':r.model_dump(mode='json'),'kind':'material_read','occurred_at':point(4).model_dump(mode='json'),'executor':human().model_dump(mode='json'),'actor_id':'learner'})
    result,reader,auth,p=default_review(tmp_path,raw,purpose='commitment')
    assert result['historical_responsibilities']==[] and result['verified_facts']['activity_totals']['material_read']['count']==0
    assert all(i['label']=='INSUFFICIENT' for i in result['feedback']['items'])
    from dataclasses import replace
    with pytest.raises(ProtocolError,match='subject point mismatch'):
        EvidenceAssemblerV2(reader).assemble(auth=auth,subject_id='p',subjects=(p,),evidence_refs=(),purpose='result',decision='no_go',as_of=point(5),policy=reader.policies()[0],snapshot=replace(reader.snapshot(auth,p,point(3)),as_of=point(5)))


def test_old_valid_record_is_judged_at_product_time_even_if_expired_by_review(tmp_path):
    raw=history_payload();raw['rule_snapshots'][0]['responsibilities']=[duty(raw,'commitment',state='withdrawn',until=4)]
    result,_,_,_=default_review(tmp_path,raw,decision='no_go')
    assert result['historical_responsibilities'][0]['finding']=='recorded_commitment'
    assert result['historical_responsibilities'][0]['evaluated_at']==point(3).model_dump(mode='json')


def test_unknown_formation_time_does_not_fall_back_to_request_time(tmp_path):
    raw=history_payload();raw['records'][0]['created_at']=None
    result,_,_,_=default_review(tmp_path,raw)
    assert result['feedback'] is None and result['evaluated_at'] is None and result['pending_reason']=='subject_point_unknown'


def test_real_reference_without_semantic_support_and_wrong_version_are_visible_facts(tmp_path):
    raw=history_payload();raw['records'][1]['text']='咖啡机维护说明，与该方案结论无关。'
    result,_,_,_=default_review(tmp_path,raw)
    assert result['verified_facts']['references'][0]['status']=='exact_reference_verified'
    assert result['verified_facts']['references'][0]['semantic_support']=='not_established'
    assert next(i for i in result['feedback']['items'] if i['criterion']=='decision.rationale')['source']=='pending'
    raw['records'][0]['declared_refs'][0]['version']=2
    bad,_,_,_=default_review(tmp_path,raw,name='missing-version')
    assert bad['pending_reason']=='declared_reference_unverified' and bad['verified_facts']['verified_source_count']==0


def test_snapshot_tampering_is_rejected_by_actual_reader(tmp_path):
    path=tmp_path/'tampered.json';path.write_text(json.dumps(history_payload()))
    with pytest.raises(ProtocolError,match='evidence snapshot hash mismatch'):SnapshotEvidenceReader(path,'0'*64)


def test_missing_event_or_misattributed_executor_makes_coverage_unknown(tmp_path):
    raw=history_payload(investigated=True)
    raw['records']=[r for r in raw['records'] if r['ref']['object_id']!='reply']
    result,_,_,_=default_review(tmp_path,raw)
    assert result['verified_facts']['activity_totals']['reply_received']['count'] is None
    raw=history_payload(investigated=True)
    next(r for r in raw['records'] if r['ref']['object_id']=='read')['executor']=agent().model_dump(mode='json')
    result,_,_,_=default_review(tmp_path,raw,name='wrong-executor')
    assert result['verified_facts']['activity_totals']['material_read']['status']=='unknown'


def test_reply_does_not_invent_display_and_bad_link_is_not_verified(tmp_path):
    raw=history_payload(investigated=True)
    event=next(a for a in raw['activity_ledger']['records'] if a['kind']=='reply_received')
    event['target']=bare(ref('material','m',1)).model_dump(mode='json')
    next(r for r in raw['records'] if r['ref']['object_id']=='reply')['activity_target']=event['target']
    result,_,_,_=default_review(tmp_path,raw)
    assert result['verified_facts']['activity_totals']['reply_received']['count'] is None
    assert result['verified_facts']['activity_totals']['learner_displayed']['count']==0


def test_later_policy_proof_cannot_create_an_earlier_actual_breach(tmp_path):
    raw=history_payload();action=duty(raw,'actual_action',seq=1,facts={'actual_participants':20,'capacity_at_action':10})
    later=ref('event','later-capacity',2);raw['records'].append(record(later,'后来容量改为10。',2))
    action['facts'][1]['sources']=[later.model_dump(mode='json')]
    raw['rule_snapshots'][0]['responsibilities']=[action]
    result,_,_,_=default_review(tmp_path,raw,decision='no_go')
    assert result['historical_responsibilities'][0]['finding']=='unknown'


def test_unshared_source_is_not_leaked_by_reference_validation(tmp_path):
    raw=history_payload();raw['records'][1]['visible_to']=['tech_lead'];raw['records'][1]['text']='SECRET-ROLE-ONLY'
    result,_,_,_=default_review(tmp_path,raw)
    assert result['pending_reason']=='declared_reference_unverified'
    assert result['verified_facts']['references'][0]['status']=='unavailable'
    assert 'SECRET-ROLE-ONLY' not in json.dumps(result)


def test_pure_reviewinput_handler_uses_default_facts_and_none_decision(tmp_path):
    from career_lab.contracts.v2.requests import ReviewInput
    raw=history_payload(investigated=True);_,reader,auth,p=default_review(tmp_path,raw)
    response=create_review_evaluator(reader).handle(auth,ReviewInput(subjects=(p,),purpose='commitment',scope=(),question='请核对'),point(5))
    result=response['reviews'][0]
    assert result['verified_facts']['verified_source_count']==1
    assert all(i['label']=='INSUFFICIENT' for i in result['feedback']['items'])
