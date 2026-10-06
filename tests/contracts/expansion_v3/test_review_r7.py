"""Replay scope regression: legacy unanchored results, real storage and Gateway."""
from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import select,update,delete,func
from fastapi.testclient import TestClient
from career_lab.contracts import v2 as C
from career_lab.storage.v2_store import Mutation,EventDraft
from career_lab.storage.v2_tables import v2_credentials,v2_external_refs,v2_request_meta,v2_objects,v2_transactions,v2_events
from career_lab.api.modules import ExtensionRegistry,Operation
from career_lab.api.app import create_app
from .conftest import command,product_plan

class ReadInput(C.V2):
    material:C.ObjectRef

def prepare(foundation,explicit=True):
    store,owner,*_=foundation;calls=[];file=C.FileRef(path='controlled.json',sha256=C.digest('controlled'))
    def resolver(a,r,p,b):calls.append('resolver');return C.ExternalReference(ref=r,source=file,content_hash=file.sha256)
    store.register_reference_resolver('material',resolver)
    grant=C.DelegationGrant(id='g',session_id=owner.session_id,actor_id='learner',executor=C.Executor(id='agent',kind='external_agent',delegation_id='g'),capabilities=('read','act'),allowed_objects=('policy',),allowed_actions=('read',),expires_at=datetime.now(timezone.utc)+timedelta(minutes=5))
    token=store.issue_delegation(owner,grant);auth=store.authenticate(owner.session_id,token)
    ref=C.ObjectRef(session_id=owner.session_id,kind='material',object_id='policy',version=1)
    cmd=command(store.view(owner),'read-once','read').model_copy(update={'payload':{'material':ref.model_dump(mode='json')} if explicit else {}})
    def handler(v,c,a):
        if ref.session_id!=a.session_id:raise C.ProtocolError('object_not_found',status=404)
        calls.append('handler');return Mutation(events=(EventDraft(type='material_read',visible_to=('learner',)),),result={'ref':ref.model_dump(mode='json'),'text':'CONTROLLED_SOURCE_CONTENT'})
    first=store.execute(auth,cmd,handler)
    with store.db.transaction() as c:
        c.execute(delete(v2_external_refs).where(v2_external_refs.c.session_id==owner.session_id))
        if not explicit:c.execute(update(v2_request_meta).where(v2_request_meta.c.session_id==owner.session_id).values(scope_refs='[]'))
    return store,owner,auth,token,cmd,handler,first,calls,resolver

def counts(store):
    with store.db.engine.connect() as c:return tuple(c.execute(select(func.count()).select_from(t)).scalar_one() for t in (v2_transactions,v2_events,v2_external_refs))
def forbidden(*_):raise AssertionError('handler reentered')
def entries(store,auth,cmd):return (lambda:store.execute(auth,cmd,forbidden),lambda:store.replay(auth,cmd),lambda:store.request_result(auth,cmd.request_id))

@pytest.mark.parametrize('explicit',[False,True])
def test_legacy_result_replay_rechecks_scope_without_anchor_or_callbacks(foundation,explicit):
    store,owner,auth,token,cmd,handler,first,calls,_=prepare(foundation,explicit);before=counts(store);seen=list(calls);state=store.view(owner).state
    assert store.execute(auth,cmd,forbidden).replayed
    assert store.replay(auth,cmd).result==first.result
    assert store.request_result(auth,cmd.request_id)[1].result==first.result
    with store.db.transaction() as c:c.execute(update(v2_credentials).where(v2_credentials.c.id==auth.credential_id).values(context=C.canonical(auth.model_copy(update={'allowed_objects':()}))))
    auth=store.authenticate(owner.session_id,token)
    for run in entries(store,auth,cmd):
        with pytest.raises(C.ProtocolError,match='object not found'):run()
    assert counts(store)==before and calls==seen and store.view(owner).state==state

@pytest.mark.parametrize('change',['revoked','expired'])
def test_revocation_and_expiry_block_every_replay_entry(foundation,change):
    store,owner,auth,token,cmd,handler,first,calls,_=prepare(foundation);before=counts(store);seen=list(calls)
    if change=='revoked':store.revoke_delegation(owner,auth.credential_id)
    else:
        auth=auth.model_copy(update={'expires_at':datetime.now(timezone.utc)-timedelta(seconds=1)})
        with store.db.transaction() as c:c.execute(update(v2_credentials).where(v2_credentials.c.id==auth.credential_id).values(context=C.canonical(auth)))
    for run in entries(store,auth,cmd):
        with pytest.raises(C.ProtocolError) as error:run()
        assert error.value.status==403
    assert counts(store)==before and calls==seen

def test_conflict_other_credential_and_missing_metadata_are_closed(foundation):
    store,owner,auth,token,cmd,handler,first,calls,_=prepare(foundation);seen=list(calls);altered=cmd.model_copy(update={'payload':cmd.payload|{'different':True}})
    for run in (lambda:store.execute(auth,altered,forbidden),lambda:store.replay(auth,altered),lambda:store.execute(owner,cmd,forbidden)):
        with pytest.raises(C.ProtocolError,match='request id reused'):run()
    with store.db.transaction() as c:c.execute(delete(v2_request_meta).where(v2_request_meta.c.session_id==owner.session_id))
    for run in entries(store,auth,cmd):
        with pytest.raises(C.ProtocolError,match='request not found'):run()
    assert calls==seen

def test_local_record_visibility_is_checked_on_every_replay(foundation):
    store,auth,*_=foundation;written=store.execute(auth,command(store.view(auth),'product'),product_plan);ref=written.objects[0]
    cmd=command(store.view(auth),'local-read','read').model_copy(update={'payload':{'ref':ref.model_dump(mode='json')}})
    store.execute(auth,cmd,lambda *_:Mutation(result={'ref':ref.model_dump(mode='json'),'text':'LOCAL_CONTENT'}))
    with store.db.transaction() as c:
        record=C.StoredObject.model_validate_json(c.execute(select(v2_objects.c.record).where(v2_objects.c.id==ref.object_id)).scalar_one())
        c.execute(update(v2_objects).where(v2_objects.c.id==ref.object_id).values(record=C.canonical(record.model_copy(update={'visible_to':('system',)}))))
    for run in entries(store,auth,cmd):
        with pytest.raises(C.ProtocolError,match='request not found'):run()

def test_gateway_post_and_get_share_authorization_and_no_side_effects(foundation):
    store,owner,auth,token,cmd,handler,first,calls,resolver=prepare(foundation)
    registry=ExtensionRegistry();registry.register_reference_resolver('material',resolver);registry.register(Operation('actions','act',ReadInput,handler,action_name='read'))
    client=TestClient(create_app(str(store.db.engine.url),extensions=registry));h={'Authorization':'Bearer '+token}
    body=cmd.model_copy(update={'request_id':'http-read','expected_version':store.view(owner).state.business_seq}).model_dump(mode='json');path=f'/sessions/{owner.session_id}'
    first=client.post(path+'/actions',headers=h,json=body);assert first.status_code==200,first.text
    seen=list(calls);before=counts(store)
    replay=client.post(path+'/actions',headers=h,json=body);assert replay.status_code==200 and replay.json()['replayed']
    assert client.get(path+'/requests/http-read',headers=h).json()['response']['result']==first.json()['result']
    with store.db.transaction() as c:c.execute(update(v2_credentials).where(v2_credentials.c.id==auth.credential_id).values(context=C.canonical(auth.model_copy(update={'allowed_objects':()}))))
    for response in (client.post(path+'/actions',headers=h,json=body),client.get(path+'/requests/http-read',headers=h)):
        assert response.status_code==404 and 'CONTROLLED_SOURCE_CONTENT' not in response.text
    assert calls==seen and counts(store)==before
    response=client.get('/sessions/another-session/requests/http-read',headers=h);assert response.status_code in {401,404}
    assert 'CONTROLLED_SOURCE_CONTENT' not in response.text


def test_explicit_private_reference_in_historical_result_cannot_be_replayed(foundation):
    from .test_review_r4 import role_plan
    from career_lab.storage.v2_store import TransactionResult
    store,auth,*_=foundation;cmd=command(store.view(auth),'private-context');plan=role_plan(store,auth,('system','tech_lead'))
    result=store.execute(auth,cmd,lambda *_:plan);ref=result.objects[0]
    # Model an older journal that accidentally included an internal reference.
    broken=result.model_copy(update={'result':{'ref':ref.model_dump(mode='json'),'text':'HISTORICAL_INTERNAL_QUOTE'}})
    with store.db.transaction() as c:c.execute(update(v2_transactions).where(v2_transactions.c.session_id==auth.session_id,v2_transactions.c.request_id==cmd.request_id).values(result=C.canonical(broken)))
    for run in entries(store,auth,cmd):
        with pytest.raises(C.ProtocolError,match='request not found'):run()


def test_recovery_uses_registered_projector_for_persisted_literal_action(foundation):
    store,owner,token,*_=foundation;handler_calls=[];projection_calls=[]
    def handler(view,cmd,auth):
        handler_calls.append(1)
        return Mutation(events=(EventDraft(type='material_read',visible_to=('learner',),data={'material_id':'policy','version':1,'private':'NEVER_SHOW'}),EventDraft(type='private_update',visible_to=('tech_lead',),data={'private':'NEVER_SHOW'})),result={'ack':True})
    def project(event,auth):
        projection_calls.append(event.type)
        return C.PublicEvent.model_validate(event.model_dump(mode='json',exclude={'visible_to','data'})|{'data':{k:event.data[k] for k in ('material_id','version') if k in event.data}})
    registry=ExtensionRegistry();registry.register(Operation('actions','act',C.ActionInput,handler,action_field='tool',event_projector=project))
    client=TestClient(create_app(str(store.db.engine.url),extensions=registry));h={'Authorization':'Bearer '+token};path=f'/sessions/{owner.session_id}'
    body=command(store.view(owner),'projected-read','read_material').model_copy(update={'payload':{'tool':'read_material'}}).model_dump(mode='json')
    first=client.post(path+'/actions',headers=h,json=body);assert first.status_code==200,first.text
    assert first.json()['events'][0]['data']=={'material_id':'policy','version':1}
    recovered=client.get(path+'/requests/projected-read',headers=h);assert recovered.status_code==200,recovered.text
    assert recovered.json()['response']==first.json()
    retried=client.post(path+'/actions',headers=h,json=body);assert retried.status_code==200 and retried.json()['replayed']
    assert retried.json()['events']==first.json()['events']
    assert handler_calls==[1] and set(projection_calls)=={'material_read'}
    assert 'NEVER_SHOW' not in first.text+recovered.text+retried.text
    # A second compatible registration must not redirect replay to another module.
    registry.register(Operation('approvals.resolve','act',C.ActionInput,handler,action_field='tool',event_projector=lambda e,a:None))
    denied=client.get(path+'/requests/projected-read',headers=h)
    assert denied.status_code==503 and denied.json()['code']=='event_projection_ambiguous'
    assert 'NEVER_SHOW' not in denied.text and handler_calls==[1]
