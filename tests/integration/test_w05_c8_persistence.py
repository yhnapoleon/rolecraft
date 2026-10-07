"""Owned evaluator + fixed store/API on controlled records; old c8 privacy counterexample retained."""
import hashlib,json
from datetime import datetime,timedelta,timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,update
from career_lab.contracts import v2 as C
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry,ScenarioRegistration,Operation
from career_lab.api.feedback_integration import install_feedback_recovery,record_feedback_response
from career_lab.api.reviews_v2 import create_review_evaluator,prepare_review_feedback,review_feedback_plan
from career_lab.workspace.extension import install_workspace_operations
from career_lab.storage.v2_lifecycle import record_review,record_submission,point
from career_lab.storage.v2_store import Mutation,ObjectWrite
from career_lab.storage.v2_tables import v2_objects,v2_snapshots,v2_credentials
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
    visible=product('visible-source','VISIBLE CONTROLLED QUOTE')
    visible_evidence=C.EvidenceRefV2(**visible.model_dump(),observed_at_seq=0,quote='VISIBLE CONTROLLED QUOTE',span_start=0,span_end=24)
    work=product('work','Consider a pause pending further evidence.',(evidence,visible_evidence))
    request=C.ReviewInput(subjects=(work,),purpose='result',scope=(),decision=None)
    result=store.execute(auth,cmd(store,auth,'reviews.create',request.model_dump(mode='json'),'review'),record_review);rref=result.objects[0]
    saved=C.ReviewRequest.model_validate(store.read(auth,rref).content)
    records=[];work_point=None
    for ref in (source,visible,work):
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
    yield dict(app=app,client=client,store=store,auth=auth,token=session['token'],source=source,visible=visible,work=work,review=rref,request=saved,feedback=feedback,prepared=prepared,evaluator=evaluator)
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
                assert facts.subject==e['work'] and facts.verified_source_count==2 and facts.requested_at==e['request'].as_of
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
    """Original c8 failure must pass on c9 without widening the grant."""
    e=prepared_env;owner=e['auth'];g=C.DelegationGrant(id='feedback-only',session_id=owner.session_id,actor_id='learner',executor=C.Executor(id='limited',kind='external_agent',delegation_id='feedback-only'),capabilities=('read',),allowed_objects=(e['feedback'].object_id,),expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
    token=e['store'].issue_delegation(owner,g);auth=e['store'].authenticate(owner.session_id,token)
    with pytest.raises(C.ProtocolError):e['store'].read(auth,e['work'])
    response=e['client'].get(f'/sessions/{owner.session_id}/feedback-records/{e["feedback"].object_id}',headers={'Authorization':'Bearer '+token})
    assert response.status_code in {403,404} and 'CONTROLLED SOURCE QUOTE' not in response.text


def raw_bytes(e,ref):
    with e['store'].db.engine.connect() as c:
        return c.execute(select(v2_objects.c.record).where(v2_objects.c.session_id==ref.session_id,v2_objects.c.kind==ref.kind,v2_objects.c.id==ref.object_id)).scalar_one()


def limited_reader(e,extra=()):
    owner=e['auth'];scope=tuple(r.object_id for r in (e['feedback'],e['review'],e['work'],e['visible']))+tuple(extra)
    grant=C.DelegationGrant(id='partial-reader',session_id=owner.session_id,actor_id='learner',executor=C.Executor(id='partial-agent',kind='external_agent',delegation_id='partial-reader'),capabilities=('read','act'),allowed_objects=scope,expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
    token=e['store'].issue_delegation(owner,grant)
    return e['store'].authenticate(owner.session_id,token),token


def assert_partial(e,value):
    text=C.canonical(value)
    assert 'CONTROLLED SOURCE QUOTE' not in text and e['source'].object_id not in text
    assert 'VISIBLE CONTROLLED QUOTE' in text


@pytest.mark.parametrize('path',['read','view','query','http'])
def test_w05_c9_partial_source_read_keeps_authorized_facts_and_original_bytes(prepared_env,path):
    e=prepared_env;auth,token=limited_reader(e);before=feedback_bytes(e)
    if path=='read':row=e['store'].read(auth,e['feedback']);value=row.content;assert_partial(e,row.model_dump(mode='json'))
    elif path in {'view','query'}:
        rows=e['store'].view(auth).objects if path=='view' else e['store'].query(auth,lambda v:v.objects)
        value=next(r.content for r in rows if r.ref==e['feedback'])
    else:
        response=e['client'].get(f'/sessions/{auth.session_id}/feedback-records/{e["feedback"].object_id}',headers={'Authorization':'Bearer '+token})
        assert response.status_code==200,response.text;value=response.json()['result']['result']['feedback']
    assert_partial(e,value);assert value['read_projection']=='partial'
    facts=value['verified_facts'][0]
    assert sum(r['verified_ref'] is not None for r in facts['references'])==1
    assert any(r['status']=='unavailable' for r in facts['references'])
    assert facts['source_snapshot_hash'] is None and facts['activity_totals']['material_read']['count'] is None
    assert feedback_bytes(e)==before


def test_w05_c9_partial_projection_cannot_be_persisted_or_quoted_as_original(prepared_env):
    e=prepared_env;auth,_=limited_reader(e);projected=e['store'].read(auth,e['feedback'])
    quoted=C.EvidenceRefV2(**e['feedback'].model_dump(),observed_at_seq=0,quote='CONTROLLED SOURCE QUOTE')
    with pytest.raises(C.ProtocolError):e['store'].can_reference(auth,quoted)
    content={**projected.content,'id':'cannot-rewrite-projection'}
    ref=e['feedback'].model_copy(update={'object_id':content['id']})
    with pytest.raises(C.ProtocolError,match='feedback projection not persistable'):
        e['store'].execute(e['auth'],cmd(e['store'],e['auth'],'feedback.request',{'subject':e['review'].model_dump(mode='json')},'projection-write'),lambda *_:Mutation(writes=(ObjectWrite(ref=ref,expected_head=0,content=content),)))


@pytest.mark.parametrize('path',['read','view','query','http','http_list','request_result','replay','execute','http_request'])
def test_w05_c9_supplement_scope_narrowing_preserves_allowed_evidence_and_original(prepared_env,path):
    e=prepared_env;store=e['store'];owner=e['auth']
    grant=C.DelegationGrant(id='response-author',session_id=owner.session_id,actor_id='learner',executor=C.Executor(id='response-agent',kind='external_agent',delegation_id='response-author'),capabilities=('read','act'),expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
    token=store.issue_delegation(owner,grant);author=store.authenticate(owner.session_id,token)
    evidence=tuple(C.EvidenceRefV2(**r.model_dump(),observed_at_seq=0,quote=q) for r,q in [(e['source'],'CONTROLLED SOURCE QUOTE'),(e['visible'],'VISIBLE CONTROLLED QUOTE')])
    body=C.FeedbackResponseCreate(feedback_id=e['feedback'].object_id,feedback_version=1,kind='supplement',text='CONTROLLED SOURCE QUOTE: please verify.',evidence=evidence)
    command=cmd(store,author,'feedback.responses.create',body.model_dump(mode='json'),'scoped-supplement')
    response=store.execute(author,command,record_feedback_response).objects[0]
    before=raw_bytes(e,response);before_feedback=feedback_bytes(e)
    scope=tuple(r.object_id for r in (e['feedback'],e['review'],e['work'],e['visible'],response))
    narrow=author.model_copy(update={'allowed_objects':scope})
    with store.db.transaction() as conn:conn.execute(update(v2_credentials).where(v2_credentials.c.id==author.credential_id).values(context=C.canonical(narrow)))
    auth=store.authenticate(owner.session_id,token)
    if path=='read':value=store.read(auth,response).model_dump(mode='json')
    elif path in {'view','query'}:
        rows=store.view(auth).objects if path=='view' else store.query(auth,lambda v:v.objects)
        value=next(r.model_dump(mode='json') for r in rows if r.ref==response)
    elif path in {'http','http_list','http_request'}:
        suffix=f'feedback-responses/{response.object_id}' if path=='http' else f'feedback/{e["feedback"].object_id}/responses' if path=='http_list' else 'requests/scoped-supplement'
        reply=e['client'].get(f'/sessions/{auth.session_id}/'+suffix,headers={'Authorization':'Bearer '+token})
        assert reply.status_code==200,reply.text;value=reply.json()
    elif path=='request_result':value=store.request_result(auth,'scoped-supplement')[1].model_dump(mode='json')
    elif path=='replay':value=store.replay(auth,command).model_dump(mode='json')
    else:value=store.execute(auth,command,lambda *_:pytest.fail('replay must not rerun handler')).model_dump(mode='json')
    assert_partial(e,value)
    assert raw_bytes(e,response)==before and feedback_bytes(e)==before_feedback
