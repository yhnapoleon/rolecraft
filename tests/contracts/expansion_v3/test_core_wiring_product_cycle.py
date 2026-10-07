"""Cycle metadata is an association of the authorized product, never a read grant."""
from datetime import datetime,timedelta,timezone
from dataclasses import replace
import pytest
from sqlalchemy import update
from career_lab.contracts import v2 as C
from career_lab.storage.v2_store import Mutation
from career_lab.storage.v2_tables import v2_credentials
from .conftest import command,product_plan
from .test_core_wiring_workspace import removed_write


def setup(foundation,scope):
    store,owner,*_=foundation;product=store.execute(owner,command(store.view(owner),'product'),product_plan).objects[0]
    grant=C.DelegationGrant(id='editor',session_id=owner.session_id,actor_id='learner',executor=C.Executor(id='agent',kind='external_agent',delegation_id='editor'),capabilities=('read','act'),allowed_objects=(product.object_id,) if scope else None,expires_at=datetime.now(timezone.utc)+timedelta(minutes=10))
    auth=store.authenticate(owner.session_id,store.issue_delegation(owner,grant));cycle=C.WorkProductVersion.model_validate(store.read(owner,product).content).cycle
    return store,owner,auth,product,cycle


def test_product_cycle_metadata_is_kept_on_every_replay_without_cycle_read_permission(foundation):
    store,owner,auth,product,cycle=setup(foundation,True);calls=[]
    cmd=command(store.view(auth),'remove','work_products.versions.create')
    def handler(view,cmd,auth):
        calls.append('handler');plan=removed_write(view,cmd,auth,product.object_id)
        return replace(plan,result={'object':plan.writes[0].content,'ref':plan.writes[0].ref.model_dump(mode='json')})
    first=store.execute(auth,cmd,handler)
    for value in (store.execute(auth,cmd,handler),store.replay(auth,cmd),store.request_result(auth,'remove')[1]):
        assert value.result['object']['cycle']==cycle.model_dump(mode='json')
        assert value.result==first.result
    with pytest.raises(C.ProtocolError):store.read(auth,cycle)
    assert auth.allowed_objects==(product.object_id,) and calls==['handler']


@pytest.mark.parametrize('extra',['explicit_source','forged_body','direct_cycle_object'])
def test_cycle_data_and_unproven_product_shapes_never_get_metadata_exemption(foundation,extra):
    from career_lab.storage.v2_tables import v2_transactions
    from career_lab.storage.v2_store import TransactionResult
    from sqlalchemy import select
    store,owner,auth,product,cycle=setup(foundation,False)
    cmd=command(store.view(auth),'remove','work_products.versions.create')
    def handler(view,cmd,auth):
        plan=removed_write(view,cmd,auth,product.object_id);body={'object':plan.writes[0].content}
        if extra=='explicit_source':body['cycle_source']=cycle.model_dump(mode='json')
        if extra=='forged_body':body['object']=body['object']|{'title':'not the saved object'}
        return replace(plan,result=body)
    store.execute(auth,cmd,handler)
    current=auth.model_copy(update={'allowed_objects':(product.object_id,)})
    with store.db.transaction() as conn:
        conn.execute(update(v2_credentials).where(v2_credentials.c.id==auth.credential_id).values(context=C.canonical(current)))
        if extra=='direct_cycle_object':
            raw=conn.execute(select(v2_transactions.c.result).where(v2_transactions.c.session_id==auth.session_id,v2_transactions.c.request_id=='remove')).scalar_one()
            txn=TransactionResult.model_validate_json(raw);txn=txn.model_copy(update={'objects':(*txn.objects,cycle)})
            conn.execute(update(v2_transactions).where(v2_transactions.c.session_id==auth.session_id,v2_transactions.c.request_id=='remove').values(result=C.canonical(txn)))
    for call in (lambda:store.execute(current,cmd,lambda *_:pytest.fail('reentry')),lambda:store.replay(current,cmd),lambda:store.request_result(current,'remove')):
        with pytest.raises(C.ProtocolError):call()
