"""Common database quota across queue/worker/refresh and independent processes."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json,os,subprocess,sys,time
import pytest
from sqlalchemy import select,func,delete
from fastapi.testclient import TestClient
from career_lab.contracts import v2 as C
from career_lab.storage.v2_store import V2Store,Mutation,JobRequest
from career_lab.storage.v2_tables import v2_objects,v2_transactions,v2_delegation_job_limits
from career_lab.jobs.repository import JobRepository,jobs
from career_lab.api.modules import ExtensionRegistry,Operation
from career_lab.api.private_roles import install_private_role_runtime
from career_lab.api.app import create_app
from .conftest import command,product_plan
from .test_core_wiring_role_snapshot import environment
from .test_core_wiring_private_roles import ControlledModel


def agent(foundation,name='agent',limit=2):
    store,owner,*_=foundation
    grant=C.DelegationGrant(id=name,session_id=owner.session_id,actor_id='learner',executor=C.Executor(id=name,kind='external_agent',delegation_id=name),capabilities=('read','act'),expires_at=datetime.now(timezone.utc)+timedelta(minutes=10))
    token=store.issue_delegation(owner,grant,max_active_jobs=limit)
    return store.authenticate(owner.session_id,token),token,grant


def enqueue(store,auth,key,n=1,with_write=False):
    cmd=command(store.view(auth),key,'quota.queue')
    def handler(view,c,a):
        planned=tuple(JobRequest(name='v2.quota_fixture',command=c.model_copy(update={'request_id':key+'-effect-'+str(i),'operation':'quota.job'}),context_hash=C.digest([key,i])) for i in range(n))
        if with_write:
            plan=product_plan(view,c,a,oid='should-not-save')
            return Mutation(writes=plan.writes,jobs=planned)
        return Mutation(jobs=planned)
    return store.execute(auth,cmd,handler),cmd


def count(store,table):
    with store.db.engine.connect() as conn:return conn.execute(select(func.count()).select_from(table)).scalar_one()


def test_two_slots_are_atomic_and_replay_does_not_consume_another(foundation):
    store,owner,*_=foundation;auth,token,_=agent(foundation)
    first,cmd=enqueue(store,auth,'two',2);state=store.view(owner).state;objects=count(store,v2_objects);transactions=count(store,v2_transactions)
    capacity=store.delegation_job_capacity(auth);assert (capacity.max_active_jobs,capacity.active_jobs,capacity.available_slots)==(2,2,0)
    assert store.execute(auth,cmd,lambda *_:pytest.fail('reentry')).replayed
    with pytest.raises(C.ProtocolError) as error:enqueue(store,auth,'third',with_write=True)
    assert error.value.code=='delegation_job_limit_reached' and error.value.status==429
    assert count(store,v2_objects)==objects and count(store,v2_transactions)==transactions and store.view(owner).state==state
    assert len(first.result['queued_jobs'])==2


def test_success_failure_and_transient_retry_have_explicit_capacity_semantics(foundation):
    store,_,*_=foundation;auth,_,_=agent(foundation);enqueue(store,auth,'two',2);repo=JobRepository(store.db)
    current=repo.claim_job('worker');assert store.delegation_job_capacity(auth).active_jobs==2
    repo.fail(current,'transient',retry=True);assert store.delegation_job_capacity(auth).active_jobs==2
    with pytest.raises(C.ProtocolError):enqueue(store,auth,'blocked')
    current=repo.claim_job('worker');repo.complete(current['id'],current['lease_token'],{})
    assert store.delegation_job_capacity(auth).active_jobs==1
    enqueue(store,auth,'replacement');current=repo.claim_job('worker');repo.fail(current,'deterministic',retry=False)
    assert store.delegation_job_capacity(auth).active_jobs==1


def test_parked_job_refresh_uses_original_delegate_limit_even_for_owner(foundation):
    store,owner,*_=foundation;auth,_,_=agent(foundation);first,_=enqueue(store,auth,'old');repo=JobRepository(store.db);current=repo.claim_job('worker');repo.needs_context(current,'context_stale')
    assert store.delegation_job_capacity(auth).active_jobs==0
    enqueue(store,auth,'fill',2);jid=first.result['queued_jobs'][0]
    cmd=command(store.view(owner),'refresh-full','jobs.refresh').model_copy(update={'payload':{'job_id':jid}});before=store.view(owner).state
    with pytest.raises(C.ProtocolError,match='委托后台任务'):store.refresh_job(owner,cmd,jid)
    assert repo.get(jid)['status']=='needs_context' and store.view(owner).state==before
    active=repo.claim_job('worker');repo.complete(active['id'],active['lease_token'],{})
    store.refresh_job(owner,cmd,jid);assert repo.get(jid)['status']=='queued' and store.delegation_job_capacity(auth).active_jobs==2


def test_persisted_configuration_and_legacy_default_survive_new_store_instances(foundation):
    store,owner,*_=foundation;auth,token,grant=agent(foundation,limit=1);enqueue(store,auth,'one')
    other=V2Store(str(store.db.engine.url));restored=other.authenticate(owner.session_id,token)
    assert other.delegation_job_capacity(restored).max_active_jobs==1
    with pytest.raises(C.ProtocolError):enqueue(other,restored,'second')
    with pytest.raises(C.ProtocolError,match='delegation id reused'):store.issue_delegation(owner,grant,max_active_jobs=2)
    legacy,legacy_token,legacy_grant=agent(foundation,'legacy')
    with store.db.transaction() as conn:conn.execute(delete(v2_delegation_job_limits).where(v2_delegation_job_limits.c.credential_id==legacy.credential_id))
    assert store.delegation_job_capacity(legacy).max_active_jobs==2
    assert store.issue_delegation(owner,legacy_grant)==legacy_token
    other.db.engine.dispose()


def test_delegates_have_separate_budgets_and_human_is_not_reclassified(foundation):
    store,owner,*_=foundation;a,_,_=agent(foundation,'a');b,_,_=agent(foundation,'b')
    enqueue(store,a,'a-two',2);enqueue(store,b,'b-two',2);enqueue(store,owner,'human-three',3)
    assert store.delegation_job_capacity(a).active_jobs==2 and store.delegation_job_capacity(b).active_jobs==2
    assert store.delegation_job_capacity(owner) is None


def test_bulk_overflow_rejects_the_whole_plan(foundation):
    store,owner,*_=foundation;auth,_,_=agent(foundation);before=store.view(owner).state
    with pytest.raises(C.ProtocolError):enqueue(store,auth,'three',3)
    assert count(store,jobs)==0 and store.view(owner).state==before


def test_three_independent_processes_cannot_overallocate_two_slots(foundation,tmp_path):
    store,owner,*_=foundation;auth,token,_=agent(foundation);JobRepository(store.db)
    program=tmp_path/'enqueue.py';program.write_text('''import os,time,json
from pathlib import Path
from career_lab.contracts import v2 as C
from career_lab.storage.v2_store import V2Store,Mutation,JobRequest
store=V2Store(os.environ['QUOTA_TEST_DB']);auth=store.authenticate(os.environ['QUOTA_TEST_SID'],os.environ['QUOTA_TEST_TOKEN'])
while not Path(os.environ['QUOTA_TEST_GO']).exists():time.sleep(.01)
key=os.environ['QUOTA_TEST_KEY'];cmd=C.Command(schema_version=2,request_id=key,operation='quota.queue',expected_version=0,expected_workspace_revision=0)
try:
 store.execute(auth,cmd,lambda *_:Mutation(jobs=(JobRequest(name='v2.quota_fixture',command=cmd.model_copy(update={'request_id':key+'-effect','operation':'quota.job'}),context_hash=C.digest(key)),)))
 print(json.dumps({'accepted':True}))
except C.ProtocolError as error:print(json.dumps({'accepted':False,'code':error.code}))
store.db.engine.dispose()
''')
    env=os.environ.copy();env['QUOTA_TEST_DB']=str(store.db.engine.url);env['QUOTA_TEST_SID']=owner.session_id;env['QUOTA_TEST_TOKEN']=token;env['QUOTA_TEST_GO']=str(tmp_path/'go');env['PYTHONPATH']=str(Path(__file__).resolve().parents[3]/'src');env['PYTHONDONTWRITEBYTECODE']='1'
    processes=[subprocess.Popen([sys.executable,str(program)],env=env|{'QUOTA_TEST_KEY':'process-'+str(i)},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for i in range(3)]
    (tmp_path/'go').touch();results=[]
    for process in processes:
        output,error=process.communicate(timeout=20);assert process.returncode==0,error;results.append(json.loads(output))
    assert sum(row['accepted'] for row in results)==2,results
    assert next(row['code'] for row in results if not row['accepted'])=='delegation_job_limit_reached'
    assert store.delegation_job_capacity(auth).active_jobs==2


def test_installed_but_closed_role_is_not_ready_and_queues_nothing(foundation):
    env=environment(foundation);store,auth,token,catalog,*_=env;model=ControlledModel();registry=ExtensionRegistry();install_private_role_runtime(registry,catalog,model)
    availability=registry.availability('turns.create');assert availability.installed and not availability.ready and availability.unavailable_code=='role_integration_not_accepted'
    for name in ('observation','tools'):assert not registry.availability(name).ready
    assert registry.availability('research.run').unavailable_code=='operation_not_public'
    assert registry.availability('requests.read').ready
    app=create_app(str(store.db.engine.url),extensions=registry)
    try:
        with TestClient(app) as client:
            body=command(store.view(auth),'closed','turns.create').model_copy(update={'payload':C.TurnInput(role_id='tech_lead',text='Q').model_dump(mode='json')})
            response=client.post(f'/sessions/{auth.session_id}/turns',headers={'Authorization':'Bearer '+token},json=body.model_dump(mode='json'))
            assert response.status_code==503 and response.json()['code']=='role_integration_not_accepted'
        assert count(store,jobs)==0 and not any(row.ref.kind=='role_turn' for row in store.view(auth).objects) and model.calls==[]
    finally:app.state.store.close()



def test_owner_refresh_and_agent_enqueue_share_lock_order_and_capacity(foundation):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    store,owner,owner_token,*_=foundation;auth,token,_=agent(foundation)
    parked,_=enqueue(store,auth,'park');repo=JobRepository(store.db);row=repo.claim_job('worker');repo.needs_context(row,'context_stale');enqueue(store,auth,'already-active')
    jid=parked.result['queued_jobs'][0];barrier=Barrier(2)
    def run(refresh):
        local=V2Store(str(store.db.engine.url));actor=local.authenticate(owner.session_id,owner_token if refresh else token)
        cmd=command(local.view(actor),'refresh-race','jobs.refresh').model_copy(update={'payload':{'job_id':jid}}) if refresh else None
        barrier.wait(timeout=10)
        try:
            if refresh:local.refresh_job(actor,cmd,jid)
            else:enqueue(local,actor,'enqueue-race')
            return 'accepted'
        except C.ProtocolError as error:return error.code
        finally:local.db.engine.dispose()
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,(True,False)))
    assert sorted(results)==['accepted','delegation_job_limit_reached'],results
    assert store.delegation_job_capacity(auth).active_jobs==2
