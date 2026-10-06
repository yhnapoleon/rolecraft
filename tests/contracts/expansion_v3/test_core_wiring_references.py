"""Public port boundary tests with a controlled source package, not W02 acceptance."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import hashlib
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from career_lab.contracts import v2 as C
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry,ScenarioRegistration,Operation
from career_lab.storage.v2_store import Mutation,ObjectWrite,EventDraft,references,full_references,validate_reference_times
from career_lab.storage.v2_tables import v2_external_refs,v2_events,v2_transactions
from career_lab.storage.v2_snapshot import SnapshotService
from .conftest import command,product_plan


class SourceAction(C.V2):
    kind: str
    material: C.ObjectRef | None = None
    evidence: C.EvidenceRefV2 | None = None
    extra: C.ObjectRef | None = None


@pytest.fixture
def contextual_api(tmp_path,foundation):
    root=tmp_path/'sources';root.mkdir();texts={('policy',1):'Public policy version one: 500.',('policy',2):'Public policy version two: 400.',('secret',1):'INTERNAL ONLY'}
    files={}
    for (oid,version),text in texts.items():
        name=f'{oid}-{version}.txt';raw=text.encode();(root/name).write_bytes(raw);files[(oid,version)]=C.FileRef(path=name,sha256=hashlib.sha256(raw).hexdigest())
    observed=[]
    def resolver(auth,ref,as_of,bindings,*,scenario_state):
        observed.append((ref,as_of,scenario_state))
        if ref.object_id=='secret':raise C.ProtocolError('material_unavailable',status=404)
        activation=scenario_state.material_activation.get(f'{ref.object_id}:{ref.version}')
        if activation is None or activation>as_of.business_seq:raise C.ProtocolError('material_unavailable',status=404)
        if isinstance(ref,C.EvidenceRefV2):
            if ref.valid_from_seq!=activation or not activation<=ref.observed_at_seq<=as_of.business_seq:raise C.ProtocolError('reference_time_mismatch',status=409)
            if ref.quote is not None:
                text=texts[(ref.object_id,ref.version)]
                if ref.span_start is None or ref.span_end is None or text[ref.span_start:ref.span_end]!=ref.quote:raise C.ProtocolError('reference_span_forbidden',status=403)
        file=files[(ref.object_id,ref.version)];C.read_file(root,file)
        bare=C.ObjectRef.model_validate({k:v for k,v in ref.model_dump(mode='json').items() if k in C.ObjectRef.model_fields})
        return C.ExternalReference(ref=bare,source=file,content_hash=file.sha256)
    bindings=C.SessionBindings(scenario=files[('policy',1)],runtime=files[('policy',1)],evaluation=files[('policy',1)])
    config=C.AssistantConfig(id='config',session_id='template',domains=('faq',))
    private=C.ScenarioStateV2(id='scenario',session_id='template',version=1,current_config=C.ObjectRef(session_id='template',kind='config',object_id='config',version=1,config_version=0),source_versions={'policy':1},indexed_versions={'policy':1},material_activation={'policy:1':0})
    registry=ExtensionRegistry();registry.register_scenario('source-port-fixture',ScenarioRegistration(bindings,config,{},private));registry.register_reference_resolver('material',resolver,contextual=True)
    def action(view,cmd,auth):
        body=SourceAction.model_validate(cmd.payload)
        if body.kind=='activate':
            old=view.private_scenario_state
            state=old.model_copy(update={'version':old.version+1,'source_versions':{'policy':2},'indexed_versions':{'policy':2},'material_activation':old.material_activation|{'policy:2':view.state.business_seq+1}})
            ref=C.ObjectRef(session_id=auth.session_id,kind='scenario_state',object_id=old.id,version=state.version)
            return Mutation(writes=(ObjectWrite(ref=ref,expected_head=old.version,content=state.model_dump(mode='json'),visible_to=('system',),dependencies=(state.current_config,)),),events=(EventDraft(type='policy_updated',visible_to=('learner',)),))
        refs=[r for r in (body.material,body.evidence,body.extra) if r is not None]
        return Mutation(events=(EventDraft(type='material_read',visible_to=('learner',)),),result={'fragments':[{'ref':ref.model_dump(mode='json'),'text':texts.get((ref.object_id,ref.version),'missing')} for ref in refs]})
    registry.register(Operation('actions','act',SourceAction,action,action_field='kind'))
    app=create_app(str(foundation[0].db.engine.url),extensions=registry)
    with TestClient(app) as client:
        s=client.post('/sessions',json={'schema_version':2,'scenario':'source-port-fixture'}).json();sid=s['session_id'];token=s['token'];headers={'Authorization':'Bearer '+token};store=app.state.v2_store;auth=store.authenticate(sid,token)
        yield app,client,store,auth,headers,observed
    app.state.store.close()


def request(api,key,kind='read',**payload):
    app,c,store,auth,h,_=api;state=store.view(auth).state
    body={'schema_version':2,'request_id':key,'operation':kind,'expected_version':state.business_seq,'expected_workspace_revision':state.workspace_revision,'payload':{'kind':kind,**payload}}
    return c.post(f'/sessions/{auth.session_id}/actions',headers=h,json=body),body


def material(auth,version=1,**extra):
    return C.ObjectRef(session_id=auth.session_id,kind='material',object_id='policy',version=version).model_dump(mode='json')|extra


def test_authoritative_activation_cannot_be_guessed_from_large_seq(contextual_api):
    api=contextual_api;auth=api[3]
    for n in range(6):assert request(api,f'idle-{n}')[0].status_code==200
    before=api[2].view(auth).state
    denied,_=request(api,'future',material=material(auth,2));assert denied.status_code==404
    assert api[2].view(auth).state==before
    assert api[5][-1][2].source_versions['policy']==1
    assert request(api,'activate','activate')[0].status_code==200
    allowed,body=request(api,'current',material=material(auth,2));assert allowed.status_code==200,allowed.text
    assert allowed.json()['result']['fragments'][0]['text'].endswith('400.')
    replay=api[1].post(f'/sessions/{auth.session_id}/actions',headers=api[4],json=body)
    assert replay.status_code==200 and replay.json()['replayed']
    assert api[5][-1][2].source_versions['policy']==2


def test_read_anchor_recovers_same_result_without_resolver_reentry(contextual_api):
    api=contextual_api;_,c,store,auth,h,calls=api
    read,body=request(api,'read-once',material=material(auth));assert read.status_code==200
    count=len(calls);before=store.view(auth).state
    for _ in range(3):
        got=c.get(f'/sessions/{auth.session_id}/requests/read-once',headers=h);assert got.status_code==200,got.text
        assert got.json()['response']==read.json()
    assert len(calls)==count and store.view(auth).state==before
    changed=c.post(f'/sessions/{auth.session_id}/actions',headers=h,json=body|{'payload':body['payload']|{'extra':material(auth,2)}})
    assert changed.status_code==409 and changed.json()['code']=='request_id_reused'
    snapshot=SnapshotService(store).export(store.research_context(auth.session_id),C.digest('source'))
    assert len(snapshot.external_references)==1 and snapshot.external_references[0].ref.object_id=='policy'
    restored,token=SnapshotService(store).restore(snapshot)
    child=store.authenticate(restored.session_id,token)
    ref=snapshot.external_references[0].ref.model_copy(update={'session_id':restored.session_id})
    assert store.resolve_reference(child,ref).source==snapshot.external_references[0].source


def test_contextual_historical_quote_gets_a_real_old_state(contextual_api):
    api=contextual_api;store=api[2];auth=api[3]
    old=material(auth,observed_at_seq=0,valid_from_seq=0,quote='Public',span_start=0,span_end=6)
    assert request(api,'first',evidence=old)[0].status_code==200
    assert request(api,'activate','activate')[0].status_code==200
    current=store.view(auth).state
    got,_=request(api,'history',evidence=old);assert got.status_code==200,got.text
    assert any(point.business_seq==0 and scenario.source_versions['policy']==1 for ref,point,scenario in api[5] if isinstance(ref,C.EvidenceRefV2))
    assert store.resolve_reference(auth,C.EvidenceRefV2.model_validate(old),storage_revision=0).ref.version==1
    assert store.view(auth).state.cycle_id==current.cycle_id
    bad=old|{'quote':'FAKE!!'};assert request(api,'bad-quote',evidence=bad)[0].status_code==403
    bad=old|{'observed_at_seq':1000};before_bad=store.view(auth).state
    denied=request(api,'future-time',evidence=bad)[0];assert denied.status_code==422 and denied.json()['code']=='future_evidence'
    assert store.view(auth).state==before_bad


def test_invalid_later_reference_rolls_back_anchor_event_and_request(contextual_api):
    api=contextual_api;store=api[2];auth=api[3];before=store.view(auth).state
    private=material(auth,object_id='secret')
    response,_=request(api,'mixed',material=material(auth),extra=private);assert response.status_code==404
    assert 'INTERNAL ONLY' not in response.text and store.view(auth).state==before
    with store.db.engine.connect() as c:
        assert c.execute(select(func.count()).select_from(v2_external_refs)).scalar_one()==0
        assert c.execute(select(func.count()).select_from(v2_events)).scalar_one()==0
        assert c.execute(select(func.count()).select_from(v2_transactions)).scalar_one()==0
    assert api[1].get(f'/sessions/{auth.session_id}/requests/mixed',headers=api[4]).status_code==404


def test_foreign_session_revocation_and_scope_cannot_restore_sources(contextual_api):
    api=contextual_api;_,c,store,auth,_,_=api
    assert request(api,'foreign',material=material(auth,session_id='another'))[0].status_code==404
    grant=C.DelegationGrant(id='source-reader',session_id=auth.session_id,actor_id='learner',executor=C.Executor(id='external',kind='external_agent',delegation_id='source-reader'),capabilities=('read','act'),allowed_objects=('policy',),allowed_actions=('read',),expires_at=datetime.now(timezone.utc)+timedelta(minutes=5))
    token=store.issue_delegation(auth,grant);header={'Authorization':'Bearer '+token};state=store.view(auth).state
    body={'schema_version':2,'request_id':'delegated-read','operation':'read','expected_version':state.business_seq,'expected_workspace_revision':state.workspace_revision,'payload':{'kind':'read','material':material(auth)}}
    read=c.post(f'/sessions/{auth.session_id}/actions',headers=header,json=body);assert read.status_code==200,read.text
    assert c.get(f'/sessions/{auth.session_id}/requests/delegated-read',headers=header).status_code==200
    store.revoke_delegation(auth,grant.id)
    assert c.get(f'/sessions/{auth.session_id}/requests/delegated-read',headers=header).status_code in {401,403}


def test_legacy_four_argument_resolver_retains_current_window(foundation):
    store,auth,*_=foundation;calls=[]
    def legacy(a,r,p,b):
        calls.append(p.business_seq);bare=C.ObjectRef.model_validate({k:v for k,v in r.model_dump(mode='json').items() if k in C.ObjectRef.model_fields})
        f=C.FileRef(path='legacy.json',sha256=C.digest('legacy'));return C.ExternalReference(ref=bare,source=f,content_hash=f.sha256)
    store.register_reference_resolver('material',legacy)
    store.execute(auth,command(store.view(auth),'advance'),lambda *_:Mutation(events=(EventDraft(type='read',visible_to=('learner',)),)))
    ref=C.EvidenceRefV2(session_id=auth.session_id,kind='material',object_id='m',version=1,observed_at_seq=0)
    assert store.can_reference(auth,ref) and calls==[1]


def test_validated_legacy_raw_is_inert_for_all_reference_scanners(foundation):
    store,auth,*_=foundation
    raw={'id':'old','kind':'text','session_id':'old-session','object_id':'missing','version':3,'observed_at_seq':999,'as_of':{'business_seq':1000}}
    legacy=C.LegacyProvenance(source_schema='browser-v1',source_session_id='old-session',original_id='old',original_kind='text',raw=raw,original_hash=C.digest(raw))
    data=legacy.model_dump(mode='json');assert references(data)==() and full_references(data)==[]
    validate_reference_times(data,0)
    plan=product_plan(store.view(auth),command(store.view(auth)),auth);write=plan.writes[0].model_copy(update={'content':plan.writes[0].content|{'legacy':data}})
    result=store.execute(auth,command(store.view(auth)),lambda *_:Mutation(writes=(write,)))
    assert store.read(auth,result.objects[0]).content['legacy']['raw']==raw


def test_request_recovery_rechecks_narrowed_scope_without_resolver(contextual_api):
    from sqlalchemy import update
    from career_lab.storage.v2_tables import v2_credentials
    api=contextual_api;_,c,store,owner,_,calls=api
    grant=C.DelegationGrant(id='narrow-source',session_id=owner.session_id,actor_id='learner',executor=C.Executor(id='narrow-agent',kind='external_agent',delegation_id='narrow-source'),capabilities=('read','act'),allowed_objects=('policy',),allowed_actions=('read',),expires_at=datetime.now(timezone.utc)+timedelta(minutes=5))
    token=store.issue_delegation(owner,grant);auth=store.authenticate(owner.session_id,token);h={'Authorization':'Bearer '+token};state=store.view(owner).state
    body={'schema_version':2,'request_id':'before-narrow','operation':'read','expected_version':state.business_seq,'expected_workspace_revision':state.workspace_revision,'payload':{'kind':'read','material':material(owner)}}
    assert c.post(f'/sessions/{owner.session_id}/actions',headers=h,json=body).status_code==200
    narrowed=auth.model_copy(update={'allowed_objects':()})
    with store.db.transaction() as conn:conn.execute(update(v2_credentials).where(v2_credentials.c.id==auth.credential_id).values(context=C.canonical(narrowed)))
    before=len(calls);denied=c.get(f'/sessions/{owner.session_id}/requests/before-narrow',headers=h)
    assert denied.status_code==404 and len(calls)==before
    assert 'Public policy version one' not in denied.text
