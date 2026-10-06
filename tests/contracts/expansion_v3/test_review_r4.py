"""Claude C-W01-01/02 regressions against real SQLite/PG transactions and Worker."""
from dataclasses import replace
from fastapi.testclient import TestClient
from sqlalchemy import select,update
import pytest
from career_lab.contracts import v2 as C
from career_lab.storage.v2_store import Mutation,ObjectWrite,JobRequest,references
from career_lab.storage.v2_lifecycle import record_submission,begin_revision,point
from career_lab.storage.v2_tables import v2_objects,v2_credentials
from career_lab.jobs.repository import JobRepository
from career_lab.jobs.worker import Worker,ClaimedHandler,WorkerClaim
from career_lab.api.modules import ExtensionRegistry,Gateway
from career_lab.api.app import create_app
from .conftest import command,product_plan


def worker_for(store,registry,gateway,kind):
    queue=JobRepository(store.db)
    return queue,Worker(queue,{kind:ClaimedHandler(lambda p,c:gateway.run_job(kind,p,claim=c))})


def submit_jobs(store,auth,registry,count):
    cmd=command(store.view(auth),'submit','submit').model_copy(update={'payload':C.SubmitInput(decision='no_go',products=()).model_dump(mode='json')})
    def submit(v,c,a):
        plan=record_submission(v,c,a)
        jobs=tuple(JobRequest(name='v2.feedback',command=cmd.model_copy(update={'request_id':f'feedback-{i}','operation':'feedback.create','payload':{'subject':plan.result['submission']}}),context_hash='0'*64) for i in range(count))
        return replace(plan,jobs=jobs)
    result=store.execute(auth,cmd,submit,capability='submit')
    def feedback(v,e,a):
        subject=C.ObjectRef.model_validate(e.command.payload['subject'])
        assert v.state.status=='submitted'  # frozen input even after a new revision
        assert v.get(subject).content['evaluation']==v.bindings.evaluation.model_dump(mode='json')
        f=C.FeedbackV2(id=e.command.request_id,session_id=a.session_id,subject=subject,evaluation=v.bindings.evaluation,as_of=point(v.state),items=(),business_response='synthetic feedback',next_options=(),verified_coverage=0,model_coverage=0)
        return Mutation(writes=(ObjectWrite(ref=C.ObjectRef(session_id=a.session_id,kind='feedback',object_id=f.id,version=1),expected_head=0,content=f.model_dump(mode='json'),dependencies=(subject,)),))
    registry.register_job('v2.feedback',feedback)
    return result


@pytest.mark.parametrize('revision',[False,True])
def test_multiple_feedbacks_survive_each_other_and_new_revision(foundation,revision):
    store,auth,*_=foundation;registry=ExtensionRegistry();gateway=Gateway(store,registry)
    result=submit_jobs(store,auth,registry,2);subject=C.ObjectRef.model_validate(result.result['submission']);original=store.read(auth,subject)
    if revision:
        cmd=command(store.view(auth),'revise','begin_revision').model_copy(update={'payload':C.BeginRevisionInput(parent_submission=subject,reason='improve').model_dump(mode='json')})
        store.execute(auth,cmd,begin_revision)
    before=store.view(auth).state
    queue,worker=worker_for(store,registry,gateway,'v2.feedback')
    assert worker.run_once() and worker.run_once() and not worker.run_once()
    assert all(queue.get(j)['status']=='completed' for j in result.result['queued_jobs'])
    assert sum(x.ref.kind=='feedback' for x in store.view(auth).objects)==2
    assert store.read(auth,subject)==original
    after=store.view(auth).state
    assert (after.status,after.cycle_id,after.business_seq)==(before.status,before.cycle_id,before.business_seq)
    assert gateway.request_result(auth,'submit').status=='completed'


def queue_reply(store,auth,registry,*,head=(),state=(),handler=None):
    seen=[]
    def reply(v,e,a):
        seen.append((v.state,e))
        return product_plan(v,e.command,a,oid='reply')
    registry.register_job('v2.reply',handler or reply)
    cmd=command(store.view(auth),'turn','turns.create')
    job=JobRequest(name='v2.reply',command=cmd.model_copy(update={'request_id':'reply-effect'}),context_hash='0'*64,head_dependencies=head,state_dependencies=state)
    result=store.execute(auth,cmd,lambda *_:Mutation(jobs=(job,)))
    gateway=Gateway(store,registry);queue,worker=worker_for(store,registry,gateway,'v2.reply')
    return gateway,queue,worker,result,seen


def test_unrelated_save_before_and_during_generation_preserves_snapshot(foundation):
    store,auth,*_=foundation;registry=ExtensionRegistry();seen=[]
    def reply(v,e,a):
        seen.append(v)
        store.execute(auth,command(store.view(auth),'during'),lambda v,c,a:product_plan(v,c,a,oid='during'))
        return product_plan(v,e.command,a,oid='reply')
    g,q,w,result,_=queue_reply(store,auth,registry,handler=reply)
    store.execute(auth,command(store.view(auth),'before'),lambda v,c,a:product_plan(v,c,a,oid='before'))
    assert w.run_once();job=q.get(result.result['queued_jobs'][0]);assert job['status']=='completed',job
    assert seen[0].state==result.state
    assert not any(x.ref.object_id in {'before','during'} for x in seen[0].objects)
    assert len([x for x in store.view(auth).objects if x.ref.kind=='product'])==3


def test_relevant_head_change_parks_once_and_http_refresh_resumes(foundation):
    store,auth,token,*_=foundation;registry=ExtensionRegistry()
    source=store.execute(auth,command(store.view(auth),'source'),lambda v,c,a:product_plan(v,c,a,oid='source')).objects[0]
    g,q,w,result,seen=queue_reply(store,auth,registry,head=(source,))
    store.execute(auth,command(store.view(auth),'source2'),lambda v,c,a:product_plan(v,c,a,oid='source',expected_head=1))
    assert w.run_once() and not w.run_once()
    jid=result.result['queued_jobs'][0];blocked=q.get(jid)
    assert blocked['status']=='needs_context' and blocked['attempt']==1 and blocked['error']=='context_stale'
    assert not seen and g.request_result(auth,'turn').status=='needs_context'
    app=create_app(database_url=str(store.db.engine.url),extensions=registry)
    client=TestClient(app);headers={'Authorization':'Bearer '+token}
    cmd=command(store.view(auth),'refresh','jobs.refresh').model_copy(update={'payload':{'job_id':jid}})
    path=f'/sessions/{auth.session_id}/jobs/{jid}/refresh'
    response=client.post(path,headers=headers,json=cmd.model_dump(mode='json'))
    assert response.status_code==200,response.text
    assert client.post(path,headers=headers,json=cmd.model_dump(mode='json')).json()['replayed']
    refreshed=q.get(jid)
    assert refreshed['payload']['command']==blocked['payload']['command']
    assert refreshed['payload']['context']['sources']==blocked['payload']['context']['sources']
    assert refreshed['payload']['context']['head_dependencies'][0]['version']==2
    assert refreshed['payload']['context']['refresh_count']==1
    assert w.run_once() and q.get(jid)['status']=='completed'
    assert seen[0][0].storage_revision>result.state.storage_revision
    assert len([x for x in store.view(auth).objects if x.ref.object_id==jid])==2
    read=client.get(f'/sessions/{auth.session_id}/jobs/{jid}',headers=headers)
    assert read.status_code==200 and read.json()['result']['boundary']['request_id']=='reply-effect'
    assert g.request_result(auth,'turn').status=='completed'


def test_source_changes_during_generation_are_rechecked_before_commit(foundation):
    store,auth,*_=foundation;registry=ExtensionRegistry()
    source=store.execute(auth,command(store.view(auth),'source'),lambda v,c,a:product_plan(v,c,a,oid='source')).objects[0]
    def reply(v,e,a):
        store.execute(auth,command(store.view(auth),'source2'),lambda v,c,a:product_plan(v,c,a,oid='source',expected_head=1))
        return product_plan(v,e.command,a,oid='reply')
    g,q,w,result,_=queue_reply(store,auth,registry,head=(source,),handler=reply)
    assert w.run_once() and q.get(result.result['queued_jobs'][0])['status']=='needs_context'
    assert not any(x.ref.object_id=='reply' for x in store.view(auth).objects)


def test_expected_output_head_still_fences_async_write(foundation):
    store,auth,*_=foundation;registry=ExtensionRegistry()
    g,q,w,result,_=queue_reply(store,auth,registry)
    store.execute(auth,command(store.view(auth),'conflict'),lambda v,c,a:product_plan(v,c,a,oid='reply'))
    assert w.run_once();job=q.get(result.result['queued_jobs'][0])
    assert job['status']=='failed' and job['error']=='job_result_identity_conflict'
    assert sum(x.ref.object_id=='reply' for x in store.view(auth).objects)==1


def test_refresh_does_not_revive_revoked_actor(foundation):
    from datetime import datetime,timedelta,timezone
    store,owner,*_=foundation;registry=ExtensionRegistry()
    grant=C.DelegationGrant(id='d',session_id=owner.session_id,actor_id='learner',executor=C.Executor(id='agent',kind='external_agent',delegation_id='d'),capabilities=('read','act'),expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
    auth=store.authenticate(owner.session_id,store.issue_delegation(owner,grant))
    source=store.execute(auth,command(store.view(auth),'source'),lambda v,c,a:product_plan(v,c,a,oid='source')).objects[0]
    g,q,w,result,_=queue_reply(store,auth,registry,head=(source,))
    store.execute(auth,command(store.view(auth),'source2'),lambda v,c,a:product_plan(v,c,a,oid='source',expected_head=1))
    w.run_once();jid=result.result['queued_jobs'][0];store.revoke_delegation(owner,'d')
    cmd=command(store.view(owner),'refresh','jobs.refresh').model_copy(update={'payload':{'job_id':jid}})
    with pytest.raises(C.ProtocolError,match='credential revoked'):g.dispatch(owner,'jobs.refresh',cmd.model_dump(mode='json'),{'job_id':jid})
    assert q.get(jid)['status']=='needs_context'


def role_plan(store,auth,audience,role='tech_lead'):
    source=store.view(auth).current_cycle.ref
    raw=C.EvidenceRefV2(**source.model_dump(exclude={'schema_version'}),observed_at_seq=0,quote='SYNTHETIC_PRIVATE_QUOTE')
    d=C.DisclosureRecord(fact_id='fact',source=raw,reply_ref=source,quote='Safe paraphrase',verification='model_extracted',displayed_at_seq=0)
    context=C.RoleContext(session_id=auth.session_id,role_id=role,as_of=point(store.view(auth).state),sources=(),actual_disclosures=(d,),context_hash='0'*64)
    ref=C.ObjectRef(session_id=auth.session_id,kind='role_context',object_id='ctx',version=1)
    return Mutation(writes=(ObjectWrite(ref=ref,expected_head=0,content=context.model_dump(mode='json'),visible_to=audience,dependencies=references(context.model_dump(mode='json'))),))


@pytest.mark.parametrize('audience,role',[(('learner',),'tech_lead'),(('system','learner'),'tech_lead'),(('business_owner',),'tech_lead'),(('learner',),'learner')])
def test_role_context_rejects_public_or_wrong_role_audience(foundation,audience,role):
    store,auth,*_=foundation;plan=role_plan(store,auth,audience,role)
    with pytest.raises(C.ProtocolError,match='role context private'):store.execute(auth,command(store.view(auth)),lambda *_:plan)
    assert not any(x.ref.kind=='role_context' for x in store.view(auth).objects)


def test_private_role_context_is_never_learner_readable_even_bad_legacy_visibility(foundation):
    store,auth,*_=foundation;plan=role_plan(store,auth,('system','tech_lead'))
    result=store.execute(auth,command(store.view(auth)),lambda *_:plan);ref=result.objects[0]
    with pytest.raises(C.ProtocolError):store.read(auth,ref)
    role=store.role_reader(auth.session_id,'tech_lead');assert 'SYNTHETIC_PRIVATE_QUOTE' in store.read(role,ref).model_dump_json()
    # Simulate an older invalid record; new read defense must still prevent disclosure.
    with store.db.transaction() as c:
        raw=c.execute(select(v2_objects.c.record).where(v2_objects.c.id=='ctx')).scalar_one()
        obj=C.StoredObject.model_validate_json(raw).model_copy(update={'visible_to':('learner','tech_lead')})
        c.execute(update(v2_objects).where(v2_objects.c.id=='ctx').values(record=C.canonical(obj)))
    with pytest.raises(C.ProtocolError):store.read(auth,ref)
    assert not any(x.ref.kind=='role_context' for x in store.view(auth).objects)


def test_reverse_registration_cannot_alias_external_namespace(foundation):
    store,*_=foundation;store.register_reference_resolver('custom',lambda *_:None)
    with pytest.raises(ValueError):store.register_object('custom',C.RoleContext)


def test_declared_config_change_parks_without_spending_model_call(foundation):
    store,auth,*_=foundation;registry=ExtensionRegistry()
    g,q,w,result,seen=queue_reply(store,auth,registry,state=('config_version',))
    old=next(x for x in store.view(auth).objects if x.ref.kind=='config')
    cfg=C.AssistantConfig.model_validate(old.content).model_copy(update={'version':2,'config_version':1})
    ref=old.ref.model_copy(update={'version':2,'config_version':1})
    store.execute(auth,command(store.view(auth),'config'),lambda *_:Mutation(writes=(ObjectWrite(ref=ref,expected_head=1,content=cfg.model_dump(mode='json')),),state_changes={'config_version':1}))
    assert w.run_once() and not seen
    assert q.get(result.result['queued_jobs'][0])['error']=='context_stale'


def test_original_credential_narrowing_cannot_leak_job_result(foundation):
    from datetime import datetime,timedelta,timezone
    store,owner,*_=foundation;registry=ExtensionRegistry()
    grant=C.DelegationGrant(id='narrow',session_id=owner.session_id,actor_id='learner',executor=C.Executor(id='agent',kind='external_agent',delegation_id='narrow'),capabilities=('read','act'),expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
    token=store.issue_delegation(owner,grant);auth=store.authenticate(owner.session_id,token)
    g,q,w,result,_=queue_reply(store,auth,registry)
    assert w.run_once();jid=result.result['queued_jobs'][0]
    restricted=auth.model_copy(update={'allowed_objects':()})
    with store.db.transaction() as c:c.execute(update(v2_credentials).where(v2_credentials.c.id==auth.credential_id).values(context=C.canonical(restricted)))
    client=TestClient(create_app(database_url=str(store.db.engine.url),extensions=registry))
    response=client.get(f'/sessions/{auth.session_id}/jobs/{jid}',headers={'Authorization':'Bearer '+token})
    assert response.status_code==404,response.text
    assert 'draft with an uncertain claim' not in response.text


def test_r3_queued_context_without_new_defaults_remains_executable(foundation):
    from career_lab.jobs.repository import jobs
    store,auth,*_=foundation;registry=ExtensionRegistry()
    g,q,w,result,_=queue_reply(store,auth,registry);jid=result.result['queued_jobs'][0]
    payload=q.get(jid)['payload']
    for key in ('head_dependencies','state_dependencies','refresh_count'):payload['context'].pop(key)
    with store.db.transaction() as c:c.execute(update(jobs).where(jobs.c.id==jid).values(payload=C.canonical(payload)))
    assert w.run_once() and q.get(jid)['status']=='completed'


def test_legacy_worker_keeps_original_error_wire_shape(foundation):
    from career_lab.errors import CodedValueError
    store,*_=foundation;queue=JobRepository(store.db)
    jid=queue.enqueue('legacy','legacy',{})
    def old_handler(payload):raise CodedValueError('old failure',code='business_code')
    worker=Worker(queue,{'legacy':old_handler});assert worker.run_once()
    assert queue.get(jid)['error']=='CodedValueError'
