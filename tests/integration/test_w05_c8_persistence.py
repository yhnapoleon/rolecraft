"""Owned evaluator + actual c8 store/API on controlled records; no model/UI claim."""
import hashlib,json
from datetime import datetime,timedelta,timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from career_lab.contracts import v2 as C
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry,ScenarioRegistration,Operation
from career_lab.api.feedback_integration import install_feedback_recovery,record_feedback_response
from career_lab.api.reviews_v2 import create_review_evaluator,prepare_review_feedback,review_feedback_plan
from career_lab.workspace.extension import install_workspace_operations
from career_lab.storage.v2_lifecycle import record_review,record_submission,point
from career_lab.storage.v2_store import Mutation,ObjectWrite
from career_lab.storage.v2_tables import v2_objects,v2_snapshots
from career_lab.evidence.v2.snapshot_reader import SnapshotEvidenceReader
from career_lab.evidence.v2.ports import CriterionPolicy


def cmd(store,auth,operation,payload,key):
    state=store.view(auth).state
    return C.Command(schema_version=2,request_id=key,operation=operation,payload=payload,expected_version=state.business_seq,expected_workspace_revision=state.workspace_revision)


@pytest.fixture
def prepared_env(tmp_path):
    raw=b'controlled evaluation fixture';(tmp_path/'evaluation.json').write_bytes(raw)
    f=C.FileRef(path='evaluation.json',sha256=hashlib.sha256(raw).hexdigest());registry=ExtensionRegistry()
    registry.register_scenario('w05-owned-c8',ScenarioRegistration(C.SessionBindings(scenario=f,runtime=f,evaluation=f),C.AssistantConfig(id='config',session_id='fixture',domains=('faq',)),{}))
    install_workspace_operations(registry,roles=('tech_lead',));install_feedback_recovery(registry)
    registry.register(Operation('reviews.create','act',C.ReviewInput,record_review))
    app=create_app(f'sqlite:///{tmp_path / "records.db"}',extensions=registry);client=TestClient(app)
    session=client.post('/sessions',json={'schema_version':2,'scenario':'w05-owned-c8'}).json();sid=session['session_id'];client.headers['Authorization']='Bearer '+session['token']
    store=app.state.v2_store;auth=store.authenticate(sid,session['token'])
    def product(key,text,evidence=()):
        command=cmd(store,auth,'work_products.create',{'kind':'text','content':text,'evidence_refs':[r.model_dump(mode='json') for r in evidence]},key)
        response=client.post(f'/sessions/{sid}/work-products',json=command.model_dump(mode='json'));assert response.status_code==200,response.text
        return C.ObjectRef.model_validate(response.json()['result']['ref'])
    source=product('source','CONTROLLED SOURCE QUOTE')
    evidence=C.EvidenceRefV2(**source.model_dump(),observed_at_seq=0,quote='CONTROLLED SOURCE QUOTE',span_start=0,span_end=23)
    work=product('work','Consider a pause pending further evidence.',(evidence,))
    request=C.ReviewInput(subjects=(work,),purpose='result',scope=(),decision=None)
    result=store.execute(auth,cmd(store,auth,'reviews.create',request.model_dump(mode='json'),'review'),record_review);rref=result.objects[0]
    saved=C.ReviewRequest.model_validate(store.read(auth,rref).content)
    records=[];work_point=None
    for ref in (source,work):
        stored=store.read(auth,ref)
        with store.db.engine.connect() as conn:
            state=C.WorldStateV2.model_validate_json(conn.execute(select(v2_snapshots.c.state).where(v2_snapshots.c.session_id==sid,v2_snapshots.c.storage_revision==stored.created_storage_revision)).scalar_one())
        at=point(state)
        if ref==work:work_point=at
        records.append({'ref':C.EvidenceRefV2(**ref.model_dump(),observed_at_seq=at.business_seq).model_dump(mode='json'),
            'created_at':at.model_dump(mode='json'),'text':stored.content['content'],'visible_to':['learner'],
            'declared_refs':stored.content['evidence_refs'],'author':stored.content['author'],'executor':stored.content['executor'],'adopter':None})
    captured=point(store.view(auth).state)
    snapshot={'schema_version':1,'session_id':sid,'actor_id':'learner','captured_at':captured.model_dump(mode='json'),'evaluation':f.model_dump(mode='json'),
        'policies':[CriterionPolicy('decision.rationale','Do not score evidence quantity.').to_dict()],
        'records':records,'activity_ledger':{'records':[],'completeness':{k:True for k in ('material_read','test_run','question_sent','reply_received','learner_displayed')},
            'covered_from':C.VersionPoint(business_seq=0,workspace_revision=0,storage_revision=0).model_dump(mode='json'),'covered_through':captured.model_dump(mode='json')},
        'rule_snapshots':[{'subject':work.model_dump(mode='json'),'as_of':work_point.model_dump(mode='json'),'facts':[],'responsibilities':[]}]}
    path=tmp_path/'controlled-store-snapshot.json';data=json.dumps(snapshot).encode();path.write_bytes(data)
    evaluator=create_review_evaluator(SnapshotEvidenceReader(path,hashlib.sha256(data).hexdigest()))
    prepared=prepare_review_feedback(evaluator,auth,saved)
    result=store.execute(auth,cmd(store,auth,'feedback.request',{'subject':rref.model_dump(mode='json')},'store-feedback'),lambda v,c,a:review_feedback_plan(v,c,a,prepared),derived_subject=rref)
    feedback=result.objects[0]
    yield dict(app=app,client=client,store=store,auth=auth,token=session['token'],source=source,work=work,review=rref,request=saved,feedback=feedback,prepared=prepared,evaluator=evaluator)
    client.close();app.state.store.close();store.db.engine.dispose()


def feedback_bytes(e):
    r=e['feedback']
    with e['store'].db.engine.connect() as c:return c.execute(select(v2_objects.c.record).where(v2_objects.c.session_id==r.session_id,v2_objects.c.kind==r.kind,v2_objects.c.id==r.object_id)).scalar_one()


def test_w05_formal_sections_persist_and_reopen(prepared_env):
    e=prepared_env;r=e['feedback'];before=feedback_bytes(e)
    for _ in range(2):
        registry=ExtensionRegistry();install_feedback_recovery(registry);app=create_app(str(e['store'].db.engine.url),extensions=registry)
        try:
            with TestClient(app) as client:
                response=client.get(f'/sessions/{r.session_id}/feedback-records/{r.object_id}',headers={'Authorization':'Bearer '+e['token']});assert response.status_code==200,response.text
                result=response.json()['result']['result'];report=C.FeedbackV2.model_validate(result['feedback'])
                assert set(result['sections'].values())=={'recorded'} and report.rule_items is not None
                facts=report.verified_facts[0]
                assert facts.subject==e['work'] and facts.verified_source_count==1 and facts.requested_at==e['request'].as_of
                assert facts.activity_totals['material_read'].count==0 and facts.conclusion_quality=='not_scored'
                assert report.historical_responsibilities[0].completeness=='unknown'
        finally:app.state.store.close()
    assert feedback_bytes(e)==before


@pytest.mark.parametrize('state',['active','paused','submitted'])
def test_w05_objection_supplement_preserve_prior_record_and_state(prepared_env,state):
    e=prepared_env;store=e['store'];auth=e['auth'];fid=e['feedback'].object_id;sid=auth.session_id
    if state=='paused':store.execute(auth,cmd(store,auth,'pause',{},'pause'),lambda *_:Mutation(state_changes={'status':'paused'}))
    if state=='submitted':store.execute(auth,cmd(store,auth,'submit',C.SubmitInput(decision='no_go',products=(e['work'],)).model_dump(mode='json'),'submit'),record_submission,capability='submit')
    before=feedback_bytes(e);world=store.view(auth).state
    body=C.FeedbackResponseCreate(feedback_id=fid,feedback_version=1,kind='objection',section='rule_items',criterion='decision.rationale',text='Please inspect this version.')
    command=cmd(store,auth,'feedback.responses.create',body.model_dump(mode='json'),'objection')
    r=e['client'].post(f'/sessions/{sid}/feedback/{fid}/responses',json=command.model_dump(mode='json'));assert r.status_code==200,r.text
    response_ref=C.ObjectRef.model_validate(r.json()['result']['response'])
    assert e['client'].post(f'/sessions/{sid}/feedback/{fid}/responses',json=command.model_dump(mode='json')).json()['replayed']
    supplement=C.FeedbackResponseCreate(feedback_id=fid,feedback_version=1,kind='supplement',text='Exact evidence, not automatic resolution.',evidence=(C.EvidenceRefV2(**e['source'].model_dump(),observed_at_seq=0),))
    r=e['client'].post(f'/sessions/{sid}/feedback/{fid}/responses',json=cmd(store,auth,'feedback.responses.create',supplement.model_dump(mode='json'),'supplement').model_dump(mode='json'));assert r.status_code==200,r.text
    assert e['client'].get(f'/sessions/{sid}/feedback-responses/{response_ref.object_id}').status_code==200
    assert len(e['client'].get(f'/sessions/{sid}/feedback/{fid}/responses').json()['result']['result']['items'])==2
    after=store.view(auth).state
    assert (after.status,after.cycle_id,after.business_seq)==(world.status,world.cycle_id,world.business_seq) and feedback_bytes(e)==before


def test_w05_followup_review_stores_explicit_decision_without_resolving_objection(prepared_env):
    e=prepared_env;store=e['store'];auth=e['auth'];before=feedback_bytes(e)
    response=store.execute(auth,cmd(store,auth,'feedback.responses.create',C.FeedbackResponseCreate(feedback_id=e['feedback'].object_id,feedback_version=1,kind='objection',text='Different reading.').model_dump(mode='json'),'respond'),record_feedback_response).objects[0]
    body=C.ReviewInput(subjects=(e['work'],),purpose='plan',scope=(),decision='no_go',followup_of=(response,))
    ref=store.execute(auth,cmd(store,auth,'reviews.create',body.model_dump(mode='json'),'followup'),record_review).objects[0]
    saved=C.ReviewRequest.model_validate(store.read(auth,ref).content)
    assert saved.decision=='no_go' and saved.followup_of==(response,) and feedback_bytes(e)==before


def test_w05_private_process_carrier_guard_is_not_bypassed(prepared_env):
    e=prepared_env
    class PrivateInput(C.V2):
        id:str
        session_id:str
        version:int=1
        secret:str
    e['store'].register_object('w05-private-guard-probe',PrivateInput)
    value=PrivateInput(id='internal-only',session_id=e['auth'].session_id,secret='PRIVATE_INPUT');r=C.ObjectRef(session_id=e['auth'].session_id,kind='w05-private-guard-probe',object_id=value.id,version=1)
    with pytest.raises(C.ProtocolError,match='private object channel required'):
        e['store'].execute(e['auth'],cmd(e['store'],e['auth'],'feedback.request',{'subject':e['review'].model_dump(mode='json')},'private-input'),lambda *_:Mutation(writes=(ObjectWrite(ref=r,expected_head=0,content=value.model_dump(mode='json'),visible_to=('system',)),)))


def test_w05_c8_feedback_only_permission_boundary_requires_shared_fix(prepared_env):
    """Expected security invariant; c8 is known to fail. Never xfail it."""
    e=prepared_env;owner=e['auth'];g=C.DelegationGrant(id='feedback-only',session_id=owner.session_id,actor_id='learner',executor=C.Executor(id='limited',kind='external_agent',delegation_id='feedback-only'),capabilities=('read',),allowed_objects=(e['feedback'].object_id,),expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
    token=e['store'].issue_delegation(owner,g);auth=e['store'].authenticate(owner.session_id,token)
    with pytest.raises(C.ProtocolError):e['store'].read(auth,e['work'])
    response=e['client'].get(f'/sessions/{owner.session_id}/feedback-records/{e["feedback"].object_id}',headers={'Authorization':'Bearer '+token})
    assert response.status_code in {403,404} and 'CONTROLLED SOURCE QUOTE' not in response.text
