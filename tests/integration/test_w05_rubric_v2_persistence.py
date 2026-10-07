"""Real API/SQLite/worker with controlled fact adapter, not final W02 QA."""
import hashlib
import pytest
from fastapi.testclient import TestClient
from career_lab.contracts import v2 as C
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry,ScenarioRegistration,Operation
from career_lab.api.feedback_integration import install_feedback_recovery
from career_lab.workspace.extension import install_workspace_operations
from career_lab.storage.v2_lifecycle import point
from career_lab.evidence.v2.ports import RuleSnapshot,VerifiedFact
from career_lab.evidence.v2.submission_evaluator import SubmissionEvaluator,submission_feedback_plan,submission_plan_with_feedback
from career_lab.rubrics.v4.rubric_v2 import install_candidate,create_installed_reader,policies
from career_lab.jobs.worker import Worker,ClaimedHandler
from career_lab.jobs.repository import JobRepository
from test_w05_c8_persistence import cmd

@pytest.mark.parametrize('language',['zh','en'])
@pytest.mark.parametrize('decision',['launch','no_go','defer_with_conditions'])
def test_frozen_14_items_persist_once_for_multiple_works_and_replay(tmp_path,language,decision):
 refs=install_candidate(tmp_path)
 evaluation=C.EvaluationBundle(id='controlled-rubric-v2',revision='candidate-1',rubric=refs['rubric'],rules=refs['rules'],graders=(),protocol=refs['rules'])
 raw=evaluation.model_dump_json().encode();(tmp_path/'evaluation.json').write_bytes(raw)
 f=C.FileRef(path='evaluation.json',sha256=hashlib.sha256(raw).hexdigest())
 registry=ExtensionRegistry();registry.register_scenario('w05-rubric-v2',ScenarioRegistration(C.SessionBindings(scenario=f,runtime=f,evaluation=f),C.AssistantConfig(id='config',session_id='controlled',domains=('faq',)),{}))
 install_workspace_operations(registry,roles=('tech_lead',));install_feedback_recovery(registry)
 registry.register(Operation('submissions.create','submit',C.SubmitInput,submission_plan_with_feedback,action_name='submit'))
 app=create_app(f'sqlite:///{tmp_path / "candidate.db"}',extensions=registry);client=TestClient(app)
 try:
  created=client.post('/sessions',json={'schema_version':2,'scenario':'w05-rubric-v2'}).json();sid=created['session_id'];client.headers['Authorization']='Bearer '+created['token']
  store=app.state.v2_store;auth=store.authenticate(sid,created['token']);works=[]
  for key,text in [('target','Target users: group A. Goal: reduce lookup time.'),('metrics','Metric: time per lookup, target under 30 seconds.')]:
   request=cmd(store,auth,'work_products.create',{'kind':'text','purpose':'commitment','content':text},key)
   response=client.post(f'/sessions/{sid}/work-products',json=request.model_dump(mode='json'));assert response.status_code==200,response.text
   works.append(C.ObjectRef.model_validate(response.json()['result']['ref']))
  calls=[]
  def aggregate(actor,submission):
   calls.append(tuple(submission.products));source=store.read(actor,works[0]);born=point(store.view(actor).state)
   proof=C.EvidenceRefV2(**works[0].model_dump(),observed_at_seq=0)
   # Controlled deterministic values exercise storage/aggregate scope only.
   # They are not an installed W02 content or semantic-quality result.
   values={'content_review_complete':True,'target_present':True,'business_goal_present':True,
     'metrics_count':1,'metric_definitions_complete':True,'metric_targets_complete':True,
     'change_log_complete':True,'policy_changed':True,'policy_change_seq':0,
     'change_affects_subject':True,'adjustment_action_count':0,'adjustment_log_complete':True,
     'test_ledger_complete':True,'dynamic_classification_complete':True,'dynamic_test_ids':[]}
   return RuleSnapshot(submission.as_of,facts=tuple(VerifiedFact(k,v,(proof,)) for k,v in values.items()),logs_complete=True,config_version=0)
  def generate(view,envelope,actor):
   ref=C.FeedbackInput.model_validate(envelope.command.payload).subject;submission=C.SubmissionV2.model_validate(view.get(ref).content)
   reader=create_installed_reader(store,actor,tmp_path,source_reader=None,rule_provider=None,submission_rule_provider=aggregate,work_language=language)
   prepared=SubmissionEvaluator(reader,work_language=language,model_bytes=64000).evaluate(actor,submission)
   return submission_feedback_plan(view,envelope.command,actor,prepared)
  registry.register_job('v2.submission-feedback',generate)
  request=cmd(store,auth,'submit',C.SubmitInput(decision=decision,products=tuple(works)).model_dump(mode='json'),'submit-candidate')
  response=client.post(f'/sessions/{sid}/submissions',json=request.model_dump(mode='json'));assert response.status_code==200,response.text
  job=response.json()['result']['queued_jobs'][0];queue=JobRepository(store.db);gateway=app.state.gateway
  worker=Worker(queue,{'v2.submission-feedback':ClaimedHandler(lambda payload,claim:gateway.run_job('v2.submission-feedback',payload,claim=claim))})
  assert worker.run_once();assert queue.get(job)['status']=='completed',queue.get(job)
  recovered=client.get(f'/sessions/{sid}/requests/submit-candidate').json();feedbacks=recovered['jobs'][0]['effect']['result']['feedbacks']
  assert len(feedbacks)==1 and calls==[tuple(works)]
  ref=C.ObjectRef.model_validate(feedbacks[0]);saved=store.read(auth,ref).content;before=C.canonical(saved)
  assert saved['mode']=='advisory' and len(saved['items'])==14 and len(saved['rule_items'])==14
  assert [i['criterion'] for i in saved['items']]==[p.id for p in policies()]
  assert len(saved['verified_facts'])==2 and saved['evaluation']==f.model_dump(mode='json')
  assert all(i['label']!='NOT_MET' for i in saved['items'] if i['criterion'] in {'R1.target','R1.metrics'})
  stale=next(i for i in saved['rule_items'] if i['criterion']=='R4.staleness_test')
  assert stale['label']==('NOT_MET' if decision=='launch' else 'NOT_APPLICABLE')
  text=' '.join(saved['verified_facts'][0]['summary']);assert ('Policy change recorded' if language=='en' else '政策变更记录') in text
  replay=client.post(f'/sessions/{sid}/submissions',json=request.model_dump(mode='json'));assert replay.json()['replayed']
  assert not worker.run_once() and calls==[tuple(works)]
  client.get(f'/sessions/{sid}/requests/submit-candidate');assert C.canonical(store.read(auth,ref).content)==before
 finally:
  client.close();app.state.store.close();store.db.engine.dispose()
