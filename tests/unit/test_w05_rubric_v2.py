"""Controlled typed evidence tests. Not W02 live-source or semantic-quality QA."""
from dataclasses import replace
from datetime import datetime,timezone
import hashlib,json
import pytest
from career_lab.contracts import v2 as C
from career_lab.evidence.v2.ports import VerifiedFact,ResponsibilityFact
from career_lab.evidence.v2.assembler import EvidenceAssemblerV2
from career_lab.rubrics.v4.rubric_v2 import policies,install_candidate,load_installed_policies,rubric_document
from career_lab.rubrics.v4.rules import run_rules
from career_lab.rubrics.v4.feedback import FeedbackEngine
from career_lab.rubrics.v4.judge import AdvisoryJudge
from career_lab.rubrics.v4.support import EvidenceSupportVerifier
from career_lab.rubrics.v4.provider import require_first_model_attempt
from career_lab.runtime.model_adapter import ScriptedModel,ModelReply
from career_lab.jobs.worker import WorkerClaim
from test_w05_pipeline import env,INITIAL,product_ref,advice

def build(env,cid,values=None,*,language='zh',purpose='commitment',decision='launch',tests=(),omit_proof=(),extra=()):
 a=env['authority'];snapshot=a.collect(None,env['auth'],(product_ref(),),INITIAL,decision)[0]
 source=a.sources[('event','ledger',1,None)].ref
 known={f.name:f for f in snapshot.facts}
 known.update({k:VerifiedFact(k,v,() if k in omit_proof else (source,)) for k,v in (values or {}).items()})
 refs=tuple(a.add('test',t.id,t.version,t.model_dump_json()) for t in tests)
 snapshot=replace(snapshot,facts=tuple(known.values()),tests=tests,test_refs=refs,responsibilities=extra)
 return EvidenceAssemblerV2(a,64000,work_language=language).assemble(auth=env['auth'],subject_id='fixed',subjects=(product_ref(),),evidence_refs=(),purpose=purpose,decision=decision,as_of=INITIAL,policy=next(p for p in policies(work_language=language) if p.id==cid),snapshot=snapshot)

def test_record(env,oid='dynamic',used=2,status='answered',at=INITIAL,category='dynamic'):
 config=C.AssistantConfig(id='config',session_id='s',domains=('faq',),participants=20)
 return C.TestResultV2(id=oid,session_id='s',query='current policy?',config=C.EffectiveConfig(requested=config,effective=config),
  config_ref=C.ObjectRef(session_id='s',kind='config',object_id='config',version=1,config_version=0),
  execution=C.TestExecutionMetadata(executed_at=datetime(2026,10,7,tzinfo=timezone.utc),executor=env['auth'].executor,source_versions={'policy':2},indexed_versions={'policy':used} if used else {},used_versions={'policy':used} if used else {},chunks=(),projection_actor='learner'),
  status=status,answer='controlled answer',citations=(),as_of=at,declared_category=category,declared_expected='claims it passes')
test_record.__test__=False

CHANGE={'change_log_complete':True,'policy_changed':True,'policy_change_seq':4,'change_affects_subject':True,
 'affected_material_versions':{'policy':2},'dynamic_test_ids':['dynamic'],'dynamic_classification_complete':True,
 'test_ledger_complete':True,'adjustment_appropriate_verified':True,'adjustment_action_count':1,'adjustment_log_complete':True,'passing_dynamic_test_ids':['dynamic']}

def test_install_has_exact_original_14_and_validates_bundle_hashes(tmp_path):
 expected=['R1.target','R1.metrics','R2.support','R2.unknowns','R2.failure_analysis','R3.capacity','R3.resources','R4.functional_tests','R4.staleness_test','R5.impact','R5.adjustment','R6.consistency','R6.operations','R6.alternatives']
 assert [p.id for p in policies()]==expected
 refs=install_candidate(tmp_path);assert install_candidate(tmp_path)==refs
 bundle=C.EvaluationBundle(id='candidate',revision='c1',rubric=refs['rubric'],rules=refs['rules'],graders=(),protocol=refs['rules'])
 raw=bundle.model_dump_json().encode();(tmp_path/'evaluation.json').write_bytes(raw)
 ref=C.FileRef(path='evaluation.json',sha256=hashlib.sha256(raw).hexdigest())
 assert [p.id for p in load_installed_policies(tmp_path,ref,work_language='en')]==expected
 assert rubric_document()['rule_calibration_target']['status']=='not_measured'
 (tmp_path/refs['rubric'].path).write_text('{}')
 with pytest.raises(C.ProtocolError):load_installed_policies(tmp_path,ref)

@pytest.mark.parametrize('language',['zh','en'])
@pytest.mark.parametrize('cid,values,label,lower,upper',[
 ('R1.target',{'content_review_complete':True,'target_present':False,'business_goal_present':True},'NOT_MET','NOT_MET','NOT_MET'),
 ('R1.metrics',{'content_review_complete':True,'metrics_count':0},'NOT_MET','NOT_MET','NOT_MET'),
 ('R1.metrics',{'content_review_complete':True,'metrics_count':1,'metric_definitions_complete':False,'metric_targets_complete':True},'PARTIAL','NOT_MET','PARTIAL'),
 ('R2.support',{},'INSUFFICIENT',None,None),
 ('R2.unknowns',{'unapproved_resource_excess':True,'current_obligation_verified':True},'NOT_MET','NOT_MET','NOT_MET'),
 ('R2.failure_analysis',{'failure_evidence_complete':True,'failure_evidence_count':0},'PARTIAL','NOT_MET','PARTIAL'),
 ('R3.capacity',{},'MET','MET','MET'),('R3.resources',{},'MET','MET','MET'),
 ('R4.functional_tests',{},'NOT_MET','NOT_MET','NOT_MET'),
 ('R4.staleness_test',CHANGE,'NOT_MET','NOT_MET','NOT_MET'),
 ('R5.impact',{'change_log_complete':True,'policy_changed':False},'NOT_APPLICABLE',None,None),
 ('R5.adjustment',{**CHANGE,'adjustment_action_count':0},'NOT_MET','NOT_MET','NOT_MET'),
 ('R6.consistency',{'numeric_conflict_verified':True},'PARTIAL','NOT_MET','PARTIAL'),
 ('R6.operations',{'content_review_complete':True,'operations_fields_verified':['owner','window','exit','actions']},'PARTIAL','PARTIAL','MET'),
 ('R6.alternatives',{'content_review_complete':True,'alternatives_count':1},'PARTIAL','NOT_MET','PARTIAL'),
])
def test_fourteen_rule_matrix(env,language,cid,values,label,lower,upper):
 item=run_rules(build(env,cid,values,language=language),work_language=language)
 assert item.label==label
 assert (item.rule_bound.lower if item.rule_bound else None)==lower
 assert (item.rule_bound.upper if item.rule_bound else None)==upper
 if item.rule_bound:assert item.citations

@pytest.mark.parametrize('cid',['R1.target','R1.metrics','R2.failure_analysis','R6.alternatives','R6.operations'])
def test_no_template_fields_or_kind_never_prove_absence(env,cid):
 result=run_rules(build(env,cid))
 assert result.label=='INSUFFICIENT' and result.rule_bound is None

@pytest.mark.parametrize('decision',['no_go','defer_with_conditions'])
@pytest.mark.parametrize('cid',['R3.capacity','R3.resources','R4.functional_tests','R4.staleness_test','R5.adjustment'])
def test_stop_has_no_automatic_launch_failure(env,decision,cid):
 item=run_rules(build(env,cid,{**CHANGE,'adjustment_action_count':0},decision=decision))
 assert item.label=='NOT_APPLICABLE' and item.rule_bound is None

@pytest.mark.parametrize('purpose',['exploration','option','plan','unknown自由说明'])
@pytest.mark.parametrize('cid',['R4.staleness_test','R5.adjustment'])
def test_investigation_and_unknown_purpose_not_launch_obligations(env,purpose,cid):
 item=run_rules(build(env,cid,CHANGE,purpose=purpose))
 assert item.label in {'NOT_APPLICABLE','INSUFFICIENT'} and item.rule_bound is None

@pytest.mark.parametrize('used,status,label',[(1,'answered','PARTIAL'),(2,'answered','MET'),(0,'fallback','INSUFFICIENT'),(2,'failed','INSUFFICIENT')])
def test_staleness_uses_actual_latest_dynamic_versions(env,used,status,label):
 item=run_rules(build(env,'R4.staleness_test',CHANGE,tests=(test_record(env,used=used,status=status),)))
 assert item.label==label

def test_latest_failed_test_does_not_fall_back_to_earlier_success(env):
 first=test_record(env,'first',at=C.VersionPoint(business_seq=4,workspace_revision=0,storage_revision=4))
 failed=test_record(env,status='failed')
 item=run_rules(build(env,'R4.staleness_test',{**CHANGE,'dynamic_test_ids':['first','dynamic']},tests=(first,failed)))
 assert item.label=='INSUFFICIENT'

@pytest.mark.parametrize('name',['change_log_complete','policy_changed','change_affects_subject','policy_change_seq','dynamic_classification_complete','affected_material_versions'])
def test_change_missing_proof_stays_unknown(env,name):
 assert run_rules(build(env,'R4.staleness_test',CHANGE,tests=(test_record(env),),omit_proof=(name,))).label=='INSUFFICIENT'

def test_adjustment_actual_pass_proposal_and_not_passed(env):
 assert run_rules(build(env,'R5.adjustment',CHANGE,tests=(test_record(env),))).label=='MET'
 assert run_rules(build(env,'R5.adjustment',{**CHANGE,'passing_dynamic_test_ids':[]},tests=(test_record(env),))).label=='PARTIAL'
 assert run_rules(build(env,'R5.adjustment',{**CHANGE,'adjustment_action_count':0,'adjustment_proposal_verified':True,'adjustment_completion_claim_verified':True})).label=='PARTIAL'

def test_declared_categories_do_not_grant_met(env):
 tests=(test_record(env,'a',category='normal'),test_record(env,'b',category='dynamic'))
 assert run_rules(build(env,'R4.functional_tests',tests=tests)).label=='INSUFFICIENT'
 result=run_rules(build(env,'R4.functional_tests',{'functional_classification_complete':True,'functional_categories_verified':['normal','dynamic'],'acceptance_criteria_verified':True},tests=tests))
 assert result.label=='MET'

def test_missing_facts_on_deterministic_criterion_cannot_be_filled_by_model(env):
 item=build(env,'R4.staleness_test',{})
 model=ScriptedModel([ModelReply(text=advice(item))])
 report,_=FeedbackEngine(AdvisoryJudge(model)).evaluate('s',product_ref(),env['authority'].bundle.evaluation,INITIAL,(item,))
 assert not model.calls and report.items[0].source=='pending'

def test_no_go_keeps_actual_historical_capacity_breach(env):
 a=env['authority'];proof=a.sources[('event','ledger',1,None)].ref
 history=ResponsibilityFact('R3.capacity','actual_action',INITIAL,INITIAL,(product_ref(),),(proof,),
  facts=(VerifiedFact('actual_participants',50,(proof,)),VerifiedFact('capacity_at_action',30,(proof,))))
 item=build(env,'R3.capacity',decision='no_go',extra=(history,))
 assert run_rules(item).label=='NOT_APPLICABLE'
 assert item.rule_context['historical_responsibilities'][0]['finding']=='verified_breach'

@pytest.mark.parametrize('failure',['parse','bad_citation','unsupported','support_parse','transport'])
def test_judge_and_support_never_automatically_retry(env,failure):
 item=build(env,'R2.support',{})
 reply=advice(item)
 if failure=='parse':reply='not json'
 if failure=='bad_citation':reply=json.dumps({**json.loads(reply),'citation_ids':['missing']})
 if failure=='transport':
  class Broken:
   revision='controlled';retries=0
   def __init__(self):self.calls=[]
   def complete(self,*args):self.calls.append(args);raise RuntimeError('secret-key')
  model=Broken()
 else:model=ScriptedModel([ModelReply(text=reply),ModelReply(text=advice(item))])
 support=ScriptedModel([ModelReply(text='broken'),ModelReply(text='{}')])
 verifier=(lambda *_:'unsupported') if failure=='unsupported' else EvidenceSupportVerifier(support)
 outcome=AdvisoryJudge(model,verifier).evaluate(item)
 assert len(model.calls)==1 and len(support.calls)<=1 and len(outcome.attempts)==1
 assert outcome.item.source=='pending' and 'secret-key' not in str(outcome)

def test_outer_claim_guard_requires_explicit_new_attempt():
 require_first_model_attempt(WorkerClaim('new-user-request','lease','worker',1))
 for claim in (None,WorkerClaim('same-request','lease2','worker2',2)):
  with pytest.raises(C.ProtocolError,match='model attempt requires explicit retry'):require_first_model_attempt(claim)


def test_saved_v4_candidate_feedback_never_regenerates():
 from career_lab.rubrics.v4.feedback import FeedbackDispatcher
 old={'items':[{'criterion':'R6.comparison','label':'INSUFFICIENT'}]}
 dispatch=FeedbackDispatcher(lambda *_:old,lambda *_:pytest.fail('legacy generation'),lambda *_:pytest.fail('candidate generation'))
 assert dispatch.get_or_generate('rules-v4','s','old') is old
 assert dispatch.get_or_generate('rules-v4-rubric-v2-c1','s','saved') is old

def test_exploration_missing_target_is_not_final_obligation(env):
 item=build(env,'R1.target',{'content_review_complete':True,'target_present':False,'business_goal_present':False},purpose='exploration')
 assert run_rules(item).label=='INSUFFICIENT'

def test_claim_only_adjustment_has_upper_bound_not_confirmed_partial(env):
 item=run_rules(build(env,'R5.adjustment',{**CHANGE,'adjustment_action_count':0,'adjustment_proposal_verified':True,'adjustment_completion_claim_verified':True}))
 assert item.rule_bound.lower=='NOT_MET' and item.rule_bound.upper=='PARTIAL'


@pytest.mark.parametrize('language',['zh','en'])
@pytest.mark.parametrize('purpose',['exploration','option','plan','commitment','result','unknown private note'])
def test_candidate_applicability_matrix_and_explanations(env,language,purpose):
 from career_lab.evidence.v2.assembler import applicable
 from career_lab.rubrics.v4.applicability import applicability_note
 nonlaunch={'R1.target','R2.support','R2.unknowns','R2.failure_analysis','R6.consistency'}
 allowed={'exploration':nonlaunch,'option':nonlaunch|{'R6.alternatives'},
  'plan':nonlaunch|{'R1.metrics','R5.impact','R6.operations','R6.alternatives'},
  'commitment':{p.id for p in policies()},
  'result':{p.id for p in policies() if not p.launch_only}}
 for decision in ('no_go','defer_with_conditions','launch_narrow',None):
  for policy in policies(work_language=language):
   result=applicable(policy,purpose,decision)
   if purpose not in allowed:expected='undetermined'
   elif policy.id not in allowed[purpose]:expected='not_applicable'
   elif policy.launch_only and decision in {'no_go','defer_with_conditions'}:expected='not_applicable'
   elif policy.launch_only and decision is None:expected='undetermined'
   else:expected='applicable'
   assert result==expected,(purpose,decision,policy.id,result)
   note=applicability_note(policy,purpose,decision,language)
   assert note
   if language=='en':assert not any('\u4e00'<=ch<='\u9fff' for ch in note)

@pytest.mark.parametrize('language',['zh','en'])
def test_three_decision_feedbacks_differ_without_grading_the_enum(env,language):
 from career_lab.rubrics.v4.applicability import decision_note
 for decision in ('no_go','defer_with_conditions','launch_narrow'):
  item=build(env,'R2.support',language=language,decision=decision)
  report,_=FeedbackEngine().evaluate('s',product_ref(),env['authority'].bundle.evaluation,INITIAL,(item,),work_language=language)
  assert decision_note(decision,language) in report.next_options
  assert report.items[0].label=='INSUFFICIENT' and report.mode=='advisory'
 assert len({decision_note(d,language) for d in ('no_go','defer_with_conditions','launch_narrow')})==3

def test_exploratory_failure_note_does_not_acquire_final_case_obligation(env):
 item=build(env,'R2.failure_analysis',{'failure_evidence_complete':True,'failure_evidence_count':0},purpose='exploration')
 assert run_rules(item).label=='INSUFFICIENT' and run_rules(item).rule_bound is None

@pytest.mark.parametrize('decision',['no_go','defer_with_conditions','launch_narrow',None])
def test_judge_and_verifier_receive_only_the_declared_decision(env,decision):
 from career_lab.evidence.v2.assembler import model_input
 item=build(env,'R2.support',decision=decision)
 payload=model_input(item)
 assert payload['declared_decision']==decision and 'facts' not in payload and 'rule_context' not in payload
 model=ScriptedModel([ModelReply(text=advice(item))]);support=ScriptedModel([ModelReply(text='{}')])
 outcome=AdvisoryJudge(model,EvidenceSupportVerifier(support)).evaluate(item)
 assert json.loads(model.calls[0][1]['content'])['declared_decision']==decision
 assert json.loads(support.calls[0][1]['content'])['declared_decision']==decision
 assert len(model.calls)==len(support.calls)==1 and outcome.item.label=='INSUFFICIENT'
