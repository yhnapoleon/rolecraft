"""Historical r1 privacy through real c7 channels; no xfail or fixture-time refusal.

Only these isolated test databases receive historical rows directly. Production
writes are separately required to reject that same shape through execute().
"""
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert,select,update
from career_lab.contracts.v2 import (
    AssistantConfig,SessionBindings,Command,ObjectRef,ProtocolError,ProviderMessage,
    TurnInput,StoredObject,JobContextSnapshot,DelegationGrant,Executor,canonical,digest,
)
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.storage.v2_store import V2Store,Mutation,JobRequest
from career_lab.storage.v2_lifecycle import point
from career_lab.storage.v2_tables import v2_objects,v2_heads,v2_transactions,v2_request_meta
from career_lab.storage.v2_snapshot import SnapshotService
from career_lab.storage.role_memory import (
    RoleTurn,RoleReply,PublicSpokenEvidence,install_role_storage,object_write,
    parse_public_reply,read_replies,
)
from career_lab.api.app import create_app
from career_lab.api.modules import Gateway,ExtensionRegistry,Operation
from career_lab.jobs.repository import JobRepository,jobs
from test_context import package,catalog
import legacy_r1_fixture as legacy

SECRET='UNSAID_R1_PRIVATE_PROMPT'


def no_handler(*_):raise AssertionError('historical recovery must not run any handler/model')


def row_digest(store):
    with store.db.engine.connect() as conn:
        data={table.name:[dict(r) for r in conn.execute(select(table)).mappings()]
              for table in (v2_objects,v2_heads,v2_transactions,v2_request_meta,jobs)}
    return digest(data)


@dataclass
class HistoricalCase:
    store: V2Store
    actor: object
    token: str
    origin: Command
    effect: Command
    record: StoredObject
    job_id: str
    job_context: JobContextSnapshot
    body: dict


def make_legacy_database(tmp_path,catalog,external=False):
    url='sqlite:///'+str(tmp_path/'legacy.db');store=V2Store(url);install_role_storage(store)
    bindings=SessionBindings(scenario=catalog.binding,runtime=catalog.binding,evaluation=catalog.binding)
    world,token=store.create_session(bindings,AssistantConfig(id='c0',session_id='fixture',domains=('fixture',)),{})
    owner=store.authenticate(world.session_id,token);actor=owner
    if external:
        grant=DelegationGrant(id='legacy-agent',session_id=owner.session_id,actor_id='learner',
            executor=Executor(id='agent',kind='external_agent',delegation_id='legacy-agent'),capabilities=('read','act'),
            allowed_objects=('old-turn','old-reply','new-reply'),allowed_actions=('turns.create',),
            expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
        token=store.issue_delegation(owner,grant);actor=store.authenticate(owner.session_id,token)
    body=TurnInput(role_id='tech_lead',text='原提问').model_dump(mode='json')
    turn=RoleTurn(id='old-turn',session_id=actor.session_id,input=TurnInput.model_validate(body),as_of=point(world),executor=actor.executor)
    turn_write=object_write('role_turn',turn)
    origin=Command(schema_version=2,request_id='origin',operation='turns.create',expected_version=0,expected_workspace_revision=0,payload=body)
    effect=origin.model_copy(update={'request_id':'effect','payload':{'subject':turn_write.ref.model_dump(mode='json')}})
    queued=store.execute(actor,origin,lambda *_:Mutation(writes=(turn_write,),jobs=(JobRequest(name='v2.role_turn',command=effect,
        sources=(turn_write.ref,),context_hash=digest(turn)),),result={'turn':turn_write.ref.model_dump(mode='json'),'question':turn.input.text}))
    job_id=queued.result['queued_jobs'][0];repo=JobRepository(store.db);job=repo.get(job_id)
    effect=Command.model_validate(job['payload']['command'])
    before_effect=store.view(actor)
    committed=store.execute(actor,effect,lambda *_:Mutation(result={'historical_effect_placeholder':True}))
    old=legacy.RoleReply(id='old-reply',session_id=actor.session_id,role_id='tech_lead',request=turn_write.ref,
        question='原提问',text='我还需要核对。',status='completed',context_hash='0'*64,prompt_hash='1'*64,
        prompt_messages=(ProviderMessage(role='system',content=SECRET),),history_revision='2'*64,
        as_of=point(before_effect.state),model_revision='historical-r1-fixture',executor=actor.executor)
    ref=ObjectRef(session_id=actor.session_id,kind='role_reply',object_id=old.id,version=1)
    record=StoredObject(ref=ref,content=old.model_dump(mode='json'),visible_to=('learner','tech_lead'),dependencies=(turn_write.ref,),
                        created_storage_revision=committed.state.storage_revision)
    # Existing historical rows are inserted as data. No legacy public reply passes
    # through execute(), so a write guard cannot masquerade as a successful read test.
    historical_result=committed.model_copy(update={'objects':(ref,),
        'result':{'reply':ref.model_dump(mode='json'),'legacy_body':old.model_dump(mode='json')}})
    unsafe_job_result={'reply':ref.model_dump(mode='json'),'raw_prompt':SECRET}
    with store.db.transaction() as conn:
        conn.execute(insert(v2_objects).values(session_id=actor.session_id,kind=ref.kind,id=ref.object_id,version=1,
            record=canonical(record),created_revision=record.created_storage_revision))
        conn.execute(insert(v2_heads).values(session_id=actor.session_id,kind=ref.kind,id=ref.object_id,version=1))
        conn.execute(update(v2_transactions).where(v2_transactions.c.session_id==actor.session_id,v2_transactions.c.request_id=='effect')
            .values(result=canonical(historical_result)))
        # Historical scope metadata may be incomplete; result references must suffice.
        conn.execute(update(v2_request_meta).where(v2_request_meta.c.session_id==actor.session_id,v2_request_meta.c.request_id=='effect').values(scope_refs='[]'))
        conn.execute(update(jobs).where(jobs.c.id==job_id).values(status='completed',result=canonical({'output_hash':digest(unsafe_job_result),'value':unsafe_job_result})))
    context=JobContextSnapshot.model_validate(job['payload']['context']).model_copy(update={'as_of':point(committed.state)})
    with store.db.engine.connect() as conn:
        persisted=conn.execute(select(v2_objects.c.record).where(v2_objects.c.session_id==actor.session_id,v2_objects.c.id==ref.object_id)).scalar_one()
    assert persisted==canonical(record) and SECRET in persisted  # prove the fixture actually contains the risk
    assert record.created_storage_revision<=context.as_of.storage_revision
    return HistoricalCase(store,actor,token,origin,effect,record,job_id,context,body)


def test_frozen_w02_runtime_binding_is_not_forged(package):
    with pytest.raises(ProtocolError,match='runtime contract mismatch'):ScenarioModule(package.root)


@pytest.mark.parametrize('external',[False,True])
@pytest.mark.parametrize('path',['read','historical_read','view','can_reference','request_result','replay','execute','job_view','list_export','snapshot_export'])
def test_historical_private_reply_is_denied_in_existing_public_channels(tmp_path,catalog,external,path):
    case=make_legacy_database(tmp_path,catalog,external);store,actor=case.store,case.actor
    before=row_digest(store)
    denied={
        'read':lambda:store.read(actor,case.record.ref),
        'historical_read':lambda:store.read(actor,case.record.ref,storage_revision=case.record.created_storage_revision),
        'can_reference':lambda:store.can_reference(actor,case.record.ref),
        'request_result':lambda:store.request_result(actor,'effect'),
        'replay':lambda:store.replay(actor,case.effect),
        'execute':lambda:store.execute(actor,case.effect,no_handler),
        'snapshot_export':lambda:SnapshotService(store).export(actor,digest('privacy-fixture')),
    }
    if path in denied:
        with pytest.raises(ProtocolError) as exc:denied[path]()
        assert exc.value.code in {'object_not_found','request_not_found','capability_forbidden'},exc.value.code
        assert SECRET not in str(exc.value)
    elif path=='view':assert case.record.ref not in [r.ref for r in store.view(actor).objects]
    elif path=='job_view':assert case.record.ref not in [r.ref for r in store.job_view(actor,case.job_context,command=case.effect).objects]
    elif path=='list_export':assert read_replies(store.view(actor))==()
    assert row_digest(store)==before


@pytest.mark.parametrize('external',[False,True])
def test_actual_http_jobs_request_recovery_and_replay_redact_historical_result(tmp_path,catalog,external):
    case=make_legacy_database(tmp_path,catalog,external);before=row_digest(case.store)
    registry=ExtensionRegistry();registry.register(Operation('turns.create','act',TurnInput,no_handler))
    app=create_app(str(case.store.db.engine.url),extensions=registry)
    try:
        with TestClient(app) as client:
            base=f'/sessions/{case.actor.session_id}';headers={'Authorization':'Bearer '+case.token}
            origin=client.get(base+'/requests/origin',headers=headers)
            assert origin.status_code==200 and origin.json()['jobs'][0]['effect'] is None,origin.text
            effect=client.get(base+'/requests/effect',headers=headers)
            assert effect.status_code==404,effect.text
            job=client.get(base+'/jobs/'+case.job_id,headers=headers)
            assert job.status_code==200 and job.json()['result'] is None,job.text
            replay=client.post(base+'/turns',headers=headers,json=case.origin.model_dump(mode='json'))
            assert replay.status_code==200 and replay.json()['replayed'],replay.text
            for response in (origin,effect,job,replay):
                assert SECRET not in response.text and 'prompt_messages' not in response.text
    finally:app.state.store.close()
    assert row_digest(case.store)==before


def test_legitimate_role_and_audit_retain_exact_original_history(tmp_path,catalog):
    case=make_legacy_database(tmp_path,catalog);store=case.store;before=row_digest(store)
    role=store.role_reader(case.actor.session_id,'tech_lead')
    assert store.read(role,case.record.ref)==case.record
    assert store.read(role,case.record.ref,storage_revision=case.record.created_storage_revision)==case.record
    assert case.record.ref in [r.ref for r in store.view(role).objects]
    with pytest.raises(ProtocolError):store.read(store.role_reader(case.actor.session_id,'business_lead'),case.record.ref)
    audit=store.research_context(case.actor.session_id)
    exported=SnapshotService(store).export(audit,digest('privacy-fixture'))
    assert next(r for r in exported.objects if r.ref==case.record.ref)==case.record
    # Public decoder stays fail-closed even when a privileged reader legitimately
    # obtained the original. Continuing old sessions needs a dedicated safe plan.
    with pytest.raises(ProtocolError,match='role legacy reply requires projection'):
        parse_public_reply(store.read(role,case.record.ref).content)
    assert row_digest(store)==before


def test_new_legacy_shape_is_rejected_by_real_write_guard(tmp_path,catalog):
    case=make_legacy_database(tmp_path,catalog);store=case.store
    # Registering the actual historical model in this isolated fixture proves the
    # common privacy guard acts before normal model validation, not as a DTO trick.
    old=V2Store(str(store.db.engine.url));old.register_object('role_reply',legacy.RoleReply)
    payload=dict(case.record.content);payload['id']='new-reply'
    record=legacy.RoleReply.model_validate(payload);write=object_write('role_reply',record,visible_to=('learner','tech_lead'))
    view=old.view(case.actor);cmd=Command(schema_version=2,request_id='new-unsafe',operation='turns.create',
        expected_version=view.state.business_seq,expected_workspace_revision=view.state.workspace_revision)
    before=row_digest(old)
    with pytest.raises(ProtocolError) as exc:old.execute(case.actor,cmd,lambda *_:Mutation(writes=(write,)))
    assert exc.value.code=='role_reply_private_fields_forbidden'
    assert row_digest(old)==before


@pytest.mark.parametrize('external',[False,True])
def test_new_safe_reply_remains_readable_and_replayable(tmp_path,catalog,external):
    case=make_legacy_database(tmp_path,catalog,external);store,actor=case.store,case.actor;view=store.view(actor)
    public=RoleReply(id='new-reply',session_id=actor.session_id,role_id='tech_lead',request=case.record.content['request'],
        question='可公开的问题',text='这是实际说出的内容。',status='completed',as_of=point(view.state),executor=actor.executor,
        spoken_evidence=(PublicSpokenEvidence(label='utterance-1',quote='实际说出的内容',verification='verified'),))
    write=object_write('role_reply',public,visible_to=('learner','tech_lead'))
    cmd=Command(schema_version=2,request_id='new-safe',operation='turns.create',expected_version=view.state.business_seq,
                expected_workspace_revision=view.state.workspace_revision)
    result=store.execute(actor,cmd,lambda *_:Mutation(writes=(write,),result={'reply':write.ref.model_dump(mode='json'),'text':public.text}))
    assert store.read(actor,write.ref).content==public.model_dump(mode='json')
    assert write.ref in [r.ref for r in store.view(actor).objects]
    assert store.replay(actor,cmd).replayed
    assert store.request_result(actor,'new-safe')[1].result==result.result
    assert SECRET not in json.dumps([r.model_dump(mode='json') for r in read_replies(store.view(actor))])
