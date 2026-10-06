from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import select
from career_lab.contracts.v2 import Command,JobContextSnapshot,Executor,DelegationGrant,ProtocolError
from career_lab.api.modules import ExtensionRegistry,Gateway
from career_lab.storage.v2_store import Mutation,JobRequest
from career_lab.jobs.repository import JobRepository,jobs
from career_lab.jobs.worker import Worker, WorkerClaim, ClaimedHandler
from .conftest import command,product_plan


def test_job_enqueue_is_atomic_replayed_and_real_worker_commits(foundation):
    store,auth,*_=foundation;queue=JobRepository(store.db);registry=ExtensionRegistry();gateway=Gateway(store,registry)
    registry.register_job('v2.contract-product',lambda view,envelope,actor:product_plan(view,envelope.command,actor))
    cmd=command(store.view(auth),'queue','save')
    job=JobRequest(name='v2.contract-product',command=cmd.model_copy(update={'request_id':'worker-save'}),context_hash='0'*64)
    def enqueue(*_):return Mutation(jobs=(job,))
    def fail(stage):
        if stage=='before_commit':raise RuntimeError('crash before commit')
    with pytest.raises(RuntimeError):store.execute(auth,cmd,enqueue,fault=fail)
    with store.db.engine.connect() as c:assert c.execute(select(jobs)).all()==[]
    result=store.execute(auth,cmd,enqueue);jid=result.result['queued_jobs'][0]
    assert store.execute(auth,cmd,enqueue).result['queued_jobs']==[jid]
    worker=Worker(queue,{'v2.contract-product':ClaimedHandler(lambda payload,claim:gateway.run_job('v2.contract-product',payload,claim=claim))})
    assert worker.run_once()
    assert queue.get(jid)['status']=='completed'
    assert len([x for x in store.view(auth).objects if x.ref.kind=='product'])==1


def test_revoked_delegation_cannot_complete_queued_job(foundation):
    store,owner,*_=foundation;registry=ExtensionRegistry();gateway=Gateway(store,registry)
    grant=DelegationGrant(id='d',session_id=owner.session_id,actor_id='learner',executor=Executor(id='agent',kind='external_agent',delegation_id='d'),capabilities=('read','act'),expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
    token=store.issue_delegation(owner,grant);auth=store.authenticate(owner.session_id,token)
    queue=JobRepository(store.db);cmd=command(store.view(auth),'q','save')
    job=JobRequest(name='v2.contract-product',command=cmd.model_copy(update={'request_id':'work'}),context_hash='0'*64)
    result=store.execute(auth,cmd,lambda *_:Mutation(jobs=(job,)))
    called=[];registry.register_job('v2.contract-product',lambda *args:called.append(True))
    store.revoke_delegation(owner,'d')
    leased=queue.claim_job('worker')
    with pytest.raises(ProtocolError):gateway.run_job('v2.contract-product',leased['payload'],claim=WorkerClaim.from_job(leased))
    assert called==[] and not any(x.ref.kind=='product' for x in store.view(owner).objects)


def test_auth_control_plane_retry_preserves_token_and_scope(foundation):
    store,owner,*_=foundation
    grant=DelegationGrant(id='same-grant',session_id=owner.session_id,actor_id='learner',executor=Executor(id='agent',kind='external_agent',delegation_id='same-grant'),capabilities=('read',),expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
    token=store.issue_delegation(owner,grant)
    assert store.issue_delegation(owner,grant)==token
    with pytest.raises(ProtocolError):store.issue_delegation(owner,grant.model_copy(update={'capabilities':('read','act')}))
    auth=store.authenticate(owner.session_id,token)
    with pytest.raises(ProtocolError):store.execute(auth,command(store.view(auth)),product_plan,capability='read')
    store.revoke_delegation(owner,grant.id)
    with pytest.raises(ProtocolError):store.issue_delegation(owner,grant)


def test_committed_job_replays_after_ack_loss_without_regeneration(foundation):
    store,auth,*_=foundation;queue=JobRepository(store.db);registry=ExtensionRegistry();gateway=Gateway(store,registry);calls=[]
    def handler(view,envelope,actor):calls.append('generation');return product_plan(view,envelope.command,actor)
    registry.register_job('v2.product',handler)
    cmd=command(store.view(auth),'q','save');job=JobRequest(name='v2.product',command=cmd.model_copy(update={'request_id':'job-effect'}),context_hash='0'*64)
    enqueued=store.execute(auth,cmd,lambda *_:Mutation(jobs=(job,)))
    leased=queue.claim_job('worker')
    first=gateway.run_job('v2.product',leased['payload'],claim=WorkerClaim.from_job(leased))
    # Simulate crash between authoritative commit and job acknowledgement, without changing records.
    second=gateway.run_job('v2.product',leased['payload'],claim=WorkerClaim.from_job(leased))
    assert second['replayed'] and second['transaction_id']==first['transaction_id'] and calls==['generation']
    queue.complete(leased['id'],leased['lease_token'],second)
    assert queue.get(enqueued.result['queued_jobs'][0])['status']=='completed'


def test_lease_takeover_fences_stale_worker_side_effects(foundation):
    import time
    store,auth,*_=foundation;queue=JobRepository(store.db);registry=ExtensionRegistry();gateway=Gateway(store,registry)
    def handler(view,envelope,actor):
        newer=queue.claim_job('new-worker',now=time.time()+61)
        assert newer is not None
        return product_plan(view,envelope.command,actor)
    registry.register_job('v2.product',handler)
    cmd=command(store.view(auth),'q','save');job=JobRequest(name='v2.product',command=cmd.model_copy(update={'request_id':'job-effect'}),context_hash='0'*64)
    store.execute(auth,cmd,lambda *_:Mutation(jobs=(job,)))
    leased=queue.claim_job('old-worker')
    with pytest.raises(ProtocolError,match='worker lease lost'):gateway.run_job('v2.product',leased['payload'],claim=WorkerClaim.from_job(leased))
    assert not any(x.ref.kind=='product' for x in store.view(auth).objects)
