"""Actual c9 Gateway/credential/store with an explicit controlled public source port."""
from datetime import datetime,timedelta,timezone
from uuid import uuid4
from dataclasses import replace
import json,hashlib
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,insert
from career_lab.contracts import v2 as C
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry,ScenarioRegistration,Operation,V2Response
from career_lab.api.delegations_v2 import install_delegations
from career_lab.delegations.service import ToolService
from career_lab.delegations.catalog import SYNC_OPERATIONS
from career_lab.delegations.observation import PublicSources
from career_lab.workspace.extension import install_workspace_operations
from career_lab.storage.v2_store import Mutation,EventDraft,ObjectWrite
from career_lab.storage.v2_tables import v2_events,v2_objects,v2_heads
from career_lab.storage.v2_lifecycle import point,record_submission
from career_lab.storage.role_memory import RoleReply

PUBLIC='PUBLIC MATERIAL'
PRIVATE='PRIVATE_PROMPT_MUST_NOT_ESCAPE'


def make_app(path):
    reg=ExtensionRegistry();f=C.FileRef(path='controlled-source.txt',sha256=hashlib.sha256(PUBLIC.encode()).hexdigest())
    config=C.AssistantConfig(id='config',session_id='fixture',domains=('faq',))
    reg.register_scenario('controlled-w06',ScenarioRegistration(C.SessionBindings(scenario=f,runtime=f,evaluation=f),config,{}))
    def resolver(auth,ref,at,bindings):
        if ref.object_id!='public-material' or ref.version!=1:raise C.ProtocolError('material_unavailable',status=404)
        return C.ExternalReference(ref=C.ObjectRef(session_id=auth.session_id,kind='material',object_id=ref.object_id,version=1),source=f,content_hash=f.sha256)
    reg.register_reference_resolver('material',resolver)
    class ReadMaterial(C.V2):
        tool: __import__('typing').Literal['read_material']
        material: C.ObjectRef
    def read(view,command,auth):
        body=ReadMaterial.model_validate(command.payload)
        resolver(auth,body.material,point(view.state),view.bindings)
        return Mutation(events=(EventDraft(type='material_read',visible_to=('learner',),data={'material':body.material.model_dump(mode='json')}),),result={'text':PUBLIC})
    reg.register(Operation('actions','act',ReadMaterial,read,action_field='tool'))
    install_workspace_operations(reg,roles=('tech_lead',))
    reg.register(Operation('submissions.create','submit',C.SubmitInput,record_submission,action_name='submit'))
    def run_test(view,command,auth):
        body=C.TestRequestV2.model_validate(command.payload);cfg=next(r for r in view.objects if r.ref.kind=='config')
        config=C.AssistantConfig.model_validate(cfg.content)
        if body.config_version!=config.config_version:raise C.ProtocolError('config_not_found',status=404)
        result=C.TestResultV2(id=uuid4().hex,session_id=auth.session_id,query=body.query,config_ref=cfg.ref,
            execution=C.TestExecutionMetadata(executed_at=datetime.now(timezone.utc),executor=auth.executor,source_versions={},indexed_versions={},used_versions={},chunks=(),projection_actor='learner'),
            config=C.EffectiveConfig(requested=config,effective=config),status='fallback',answer='Controlled local lookup: no matching source.',citations=(),as_of=point(view.state))
        ref=C.ObjectRef(session_id=auth.session_id,kind='test',object_id=result.id,version=1)
        return Mutation(writes=(ObjectWrite(ref=ref,expected_head=0,content=result.model_dump(mode='json'),dependencies=(cfg.ref,)),),events=(EventDraft(type='test_completed',visible_to=('learner',),refs=(ref,)),),result={'test':ref.model_dump(mode='json')})
    reg.register(Operation('tests.create','act',C.TestRequestV2,run_test))
    # Controlled read adapter for privacy-channel regression, not a production
    # material/role aggregation contract.
    reg.register(Operation('materials.list','read',C.ResourcePage,
        lambda view,page,auth:V2Response(result={'items':[r.content for r in view.objects if r.ref.kind=='role_reply'][page.cursor:page.cursor+page.limit]}),
        mutates=False,response_model=V2Response))
    holder={}
    def feed(view,query,auth):
        # This test-only source adapter reads actual persisted events, not an
        # in-memory success log. Production timeline/source port is still missing.
        with holder['app'].state.v2_store.db.engine.connect() as conn:
            raw=conn.execute(select(v2_events.c.record).where(v2_events.c.session_id==auth.session_id,v2_events.c.seq>(query.since_seq or 0),v2_events.c.seq<=view.state.business_seq).order_by(v2_events.c.seq).limit(query.limit)).scalars().all()
            all_raw=conn.execute(select(v2_events.c.record).where(v2_events.c.session_id==auth.session_id,v2_events.c.seq<=view.state.business_seq).order_by(v2_events.c.seq)).scalars().all()
        scanned=[C.StoredEvent.model_validate_json(x) for x in raw];events=[];observed=[];versions=[]
        allowed=lambda ref:auth.allowed_objects is None or ref.object_id in auth.allowed_objects
        for event in scanned:
            if auth.actor_id in event.visible_to and all(allowed(r) and view.reference_allowed(r) for r in event.refs):events.append(C.PublicEvent.model_validate(event.model_dump(exclude={'visible_to','data'})|{'data':{}}))
        for raw in all_raw:
            event=C.StoredEvent.model_validate_json(raw)
            if event.type=='material_read' and auth.actor_id in event.visible_to and event.data.get('material') and allowed(C.ObjectRef.model_validate(event.data['material'])):
                ref=C.ObjectRef.model_validate(event.data['material']);evidence=C.EvidenceRefV2(**ref.model_dump(),observed_at_seq=event.seq,quote=PUBLIC)
                observed.append(C.ObservedFragment(ref=evidence,text=PUBLIC,channel='material',audience='learner',acquired_via='material_read',acquired_at_seq=event.seq,verification='verified'))
                versions.append(ref)
        public_replies={r.ref.object_id:r for r in view.objects if r.ref.kind=='role_reply'}
        for raw in all_raw:
            event=C.StoredEvent.model_validate_json(raw)
            if event.type!='dialogue_displayed' or auth.actor_id not in event.visible_to:continue
            for ref in event.refs:
                row=public_replies.get(ref.object_id)
                if row is None or row.ref!=ref:continue
                evidence=C.EvidenceRefV2(**ref.model_dump(),observed_at_seq=event.seq,quote=row.content['text'])
                observed.append(C.ObservedFragment(ref=evidence,text=row.content['text'],channel='dialogue',audience='learner',acquired_via='displayed',acquired_at_seq=event.seq,verification='verified'))
                versions.append(ref)
        catalog=(C.MaterialMetadata(id='public-material',version=1,title='Public source',domain='faq'),) if auth.allowed_objects is None or 'public-material' in auth.allowed_objects else ()
        return PublicSources(point(view.state),catalog,tuple(observed),(),tuple(versions),tuple(events),scanned[-1].seq if scanned else view.state.business_seq)
    bind=install_delegations(reg,source_provider=feed,synchronous=SYNC_OPERATIONS|{'actions','tests.create'})
    app=create_app('sqlite:///'+str(path),extensions=reg);holder['app']=app;app.state.w06=bind(app.state.gateway)
    return app


@pytest.fixture
def env(tmp_path):
    app=make_app(tmp_path/'w06.db');client=TestClient(app)
    response=client.post('/sessions',json={'schema_version':2,'scenario':'controlled-w06'});assert response.status_code==200
    created=response.json();client.headers['Authorization']='Bearer '+created['token']
    owner=app.state.v2_store.authenticate(created['session_id'],created['token'])
    yield dict(app=app,client=client,sid=created['session_id'],owner=owner,token=created['token'])
    client.close();app.state.store.close();app.state.v2_store.db.engine.dispose()


def command(env,operation,payload,key=None):
    state=env['app'].state.v2_store.view(env['owner']).state
    return C.Command(schema_version=2,request_id=key or uuid4().hex,expected_version=state.business_seq,expected_workspace_revision=state.workspace_revision,operation=operation,payload=payload).model_dump(mode='json')


def grant(env,capabilities=('read',),**kw):
    body=C.DelegationInput(capabilities=capabilities,expires_at=datetime.now(timezone.utc)+timedelta(minutes=30),agent_label='test-agent',**kw)
    cmd=command(env,'delegations.create',body.model_dump(mode='json'))
    r=env['client'].post(f'/sessions/{env["sid"]}/delegations',json=cmd);assert r.status_code==200,r.text
    return r.json()['result']['result'],cmd


def test_w06_default_read_identity_and_control_plane_idempotence(env):
    created,cmd=grant(env);again=env['client'].post(f'/sessions/{env["sid"]}/delegations',json=cmd)
    assert again.json()['result']['result']==created
    auth=env['app'].state.v2_store.authenticate(env['sid'],created['token'])
    assert auth.executor.kind=='external_agent' and auth.capabilities==('read',) and auth.actor_id=='learner'
    response=env['client'].get(f'/sessions/{env["sid"]}/observation',headers={'Authorization':'Bearer '+created['token']});assert response.status_code==200,response.text
    obs=C.Observation.model_validate(response.json()['result']);assert obs.actor==auth.executor
    assert obs.catalog and not obs.visible_sources and not obs.read_versions
    tools={t.name:t for t in obs.tools};assert not tools['work_products.create'].available
    with pytest.raises(C.ProtocolError):env['app'].state.w06.call(env['sid'],created['token'],'work_products.create',{'session_id':env['sid'],'command':command(env,'work_products.create',{'content':'must not write'})})
    bad={**cmd,'request_id':'bad','payload':{**cmd['payload'],'capabilities':['research']}}
    assert env['client'].post(f'/sessions/{env["sid"]}/delegations',json=bad).status_code==422


def test_w06_act_is_not_submit_and_executor_cannot_be_forged(env):
    created,_=grant(env,('read','act'));service=env['app'].state.w06
    body=command(env,'work_products.create',{'kind':'text','content':'Agent draft'})
    result=service.call(env['sid'],created['token'],'work_products.create',{'session_id':env['sid'],'command':body})
    assert result['executor']['kind']=='external_agent' and result['result']['object']['executor']['kind']=='external_agent'
    assert service.call(env['sid'],created['token'],'work_products.create',{'session_id':env['sid'],'command':body})['replayed']
    spoof=command(env,'work_products.create',{'kind':'text','content':'fake','executor':{'kind':'human','id':'root'}})
    from pydantic import ValidationError
    with pytest.raises(ValidationError):service.call(env['sid'],created['token'],'work_products.create',{'session_id':env['sid'],'command':spoof})
    with pytest.raises(C.ProtocolError):service.call(env['sid'],created['token'],'submit',{'session_id':env['sid'],'command':command(env,'submit',{'decision':'no_go','products':[]})})


def test_w06_revocation_and_expiry_are_rechecked_and_history_remains(env):
    created,_=grant(env,('read','act'));service=env['app'].state.w06
    body=command(env,'work_products.create',{'kind':'text','content':'retained'})
    result=service.call(env['sid'],created['token'],'work_products.create',{'session_id':env['sid'],'command':body});pid=result['result']['ref']
    revoke=command(env,'delegations.revoke',{'delegation_id':created['delegation']['id']})
    assert env['client'].request('DELETE',f'/sessions/{env["sid"]}/delegations/{created["delegation"]["id"]}',json=revoke).status_code==200
    with pytest.raises(C.ProtocolError):service.call(env['sid'],created['token'],'work_products.create',{'session_id':env['sid'],'command':body})
    assert env['app'].state.v2_store.read(env['owner'],C.ObjectRef.model_validate(pid)).content['content']=='retained'
    expired=C.DelegationInput(expires_at=datetime.now(timezone.utc)-timedelta(seconds=1),agent_label='expired')
    assert env['client'].post(f'/sessions/{env["sid"]}/delegations',json=command(env,'delegations.create',expired.model_dump(mode='json'))).status_code==422


def test_w06_observation_cursor_preserves_private_gap_and_does_not_claim_catalog_read(env):
    store=env['app'].state.v2_store
    store.execute(env['owner'],C.Command.model_validate(command(env,'private-fixture',{})),lambda *_:Mutation(events=(EventDraft(type='PRIVATE_EVENT_NAME',visible_to=('system',),data={'private':PRIVATE}),)))
    ref=C.ObjectRef(session_id=env['sid'],kind='material',object_id='public-material',version=1)
    response=env['client'].post(f'/sessions/{env["sid"]}/actions',json=command(env,'read_material',{'tool':'read_material','material':ref.model_dump(mode='json')}));assert response.status_code==200,response.text
    first=env['client'].get(f'/sessions/{env["sid"]}/observation?since_seq=0&limit=1').json()['result']
    second=env['client'].get(f'/sessions/{env["sid"]}/observation?since_seq=1&limit=1').json()['result']
    assert first['next_seq']==1 and first['events']==[] and second['next_seq']==2 and len(second['events'])==1
    assert PRIVATE not in json.dumps([first,second]) and 'PRIVATE_EVENT_NAME' not in json.dumps([first,second])
    assert second['visible_sources'][0]['acquired_at_seq']==2 and second['visible_sources'][0]['audience']=='learner'


def test_w06_removed_lifecycle_cannot_be_smuggled_through_generic_edit(env):
    created,_=grant(env,('read','act'));service=env['app'].state.w06
    p=service.call(env['sid'],created['token'],'work_products.create',{'session_id':env['sid'],'command':command(env,'work_products.create',{'kind':'text','content':'work'})})['result']['object']
    body=command(env,'work_products.versions.create',{'product_id':p['product_id'],'expected_head':1,'kind':'text','content':'work','removed':True})
    with pytest.raises(C.ProtocolError,match='lifecycle permission unavailable'):service.call(env['sid'],created['token'],'work_products.versions.create',{'session_id':env['sid'],'command':body})
    # Existing common HTTP path has not acquired the new lifecycle rule yet.
    # Owner removes in the controlled test; W06 must not restore it by defaults.
    assert env['client'].post(f'/sessions/{env["sid"]}/work-products/{p["product_id"]}/versions',json=body).status_code==200
    restore=command(env,'work_products.versions.create',{'product_id':p['product_id'],'expected_head':2,'kind':'text','content':'work'})
    with pytest.raises(C.ProtocolError,match='lifecycle permission unavailable'):service.call(env['sid'],created['token'],'work_products.versions.create',{'session_id':env['sid'],'command':restore})


def test_w06_fixed_transport_routes_match_mounted_public_routes(env):
    from career_lab.delegations.catalog import ROUTES
    mounted={(method,route.path) for route in env['app'].routes for method in getattr(route,'methods',())}
    assert not {(route.method,'/sessions/{session_id}'+route.path) for route in ROUTES.values()}-mounted


def test_w06_real_queued_job_cannot_write_after_http_revocation(env):
    from career_lab.storage.v2_store import JobRequest
    from career_lab.jobs.worker import Worker,ClaimedHandler
    from career_lab.jobs.repository import JobRepository
    created,_=grant(env,('read','act'));store=env['app'].state.v2_store;auth=store.authenticate(env['sid'],created['token'])
    cmd=C.Command.model_validate(command(env,'controlled_queue',{}))
    job=JobRequest(name='v2.w06-controlled',command=cmd.model_copy(update={'request_id':'controlled-effect'}),context_hash='0'*64)
    result=store.execute(auth,cmd,lambda *_:Mutation(jobs=(job,)));jid=result.result['queued_jobs'][0]
    called=[];env['app'].state.gateway.registry.register_job('v2.w06-controlled',lambda *_:called.append(True))
    revoke_cmd=command(env,'delegations.revoke',{'delegation_id':created['delegation']['id']})
    assert env['client'].request('DELETE',f'/sessions/{env["sid"]}/delegations/{created["delegation"]["id"]}',json=revoke_cmd).status_code==200
    repository=JobRepository(store.db);gateway=env['app'].state.gateway
    worker=Worker(repository,{'v2.w06-controlled':ClaimedHandler(lambda payload,claim:gateway.run_job('v2.w06-controlled',payload,claim=claim))})
    assert worker.run_once() and called==[]
    record=repository.get(jid);assert record['status']=='failed'
    assert not any(x.ref.kind=='product' for x in store.view(env['owner']).objects)
    assert created['token'] not in json.dumps(record)


def test_w06_explicit_submit_capability_and_unavailable_uninstalled_operations(env):
    from career_lab.api.modules import Operation
    env['app'].state.gateway.registry.register(Operation('feedback.create','act',C.V2,lambda *_:(_ for _ in ()).throw(AssertionError('disabled handler ran'))))
    actor,_=grant(env,('read','act','submit'));service=env['app'].state.w06
    obs=env['client'].get(f'/sessions/{env["sid"]}/observation',headers={'Authorization':'Bearer '+actor['token']}).json()['result']
    entries={x['name']:x for x in obs['tools']};assert entries['feedback.create']['unavailable_code']=='private_worker_unavailable'
    assert 'arbitrary_shell' not in entries and 'research' not in entries
    submitted=service.call(env['sid'],actor['token'],'submit',{'session_id':env['sid'],'command':command(env,'submit',{'decision':'no_go','products':[]})})
    assert submitted['state']['status']=='submitted' and submitted['executor']['kind']=='external_agent'
    recovered=service.call(env['sid'],actor['token'],'requests.read',{'session_id':env['sid'],'query':{'request_id':submitted['boundary']['request_id']}})
    assert recovered['status']=='completed'
