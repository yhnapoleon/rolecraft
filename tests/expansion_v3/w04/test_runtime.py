"""Private/public plans and real common-store boundaries; no fake production port."""
from dataclasses import replace
from types import SimpleNamespace
from datetime import datetime,timezone
import json

import pytest
from career_lab.contracts.v2 import (
    AssistantConfig,SessionBindings,Command,ObjectRef,RoleContext,ProtocolError,
    TurnInput,ProviderMessage,PublicDisclosureRecord,digest,
)
from career_lab.api.modules import ExtensionRegistry,Gateway,JobEnvelope
from career_lab.jobs.repository import JobRepository
from career_lab.jobs.worker import Worker,ClaimedHandler
from career_lab.runtime.context_v2 import ContextPort,RoleFrame,assemble_context
from career_lab.runtime.roles_v2 import RoleService,RoleModelTransient,generate_plan,record_reply_display,displayed_disclosures
from career_lab.runtime.model_adapter import ScriptedModel,ModelReply
from career_lab.storage.role_memory import (
    RoleTurn,RoleReply,PublicSpokenEvidence,PrivateGeneration,install_role_storage,
    object_write,parse_public_reply,read_replies,memory_from_generation,PRIVATE_REPLY_FIELDS,
)
from career_lab.storage.v2_store import V2Store,Mutation,ObjectWrite,JobRequest
from career_lab.storage.v2_lifecycle import point as state_point
from test_context import package,catalog,point,owner,agent,frame,memory,share_receipt,make_view,FixedFrameFixture,disclosure_samples,private_sample


def request(auth,key='turn',shares=(),role_id='tech_lead'):
    return RoleTurn(id=key,session_id=auth.session_id,input=TurnInput(role_id=role_id,text='请接续上轮分析',shares=shares),
                    as_of=point(),executor=auth.executor)

def reply_ref(sid='s',key='reply'):
    return ObjectRef(session_id=sid,kind='role_reply',object_id=key,version=1)

def generate(snapshot,auth,req,model,key='reply',sink=None):
    attempts=[] if sink is None else sink
    return generate_plan(snapshot,auth,req,reply_ref(auth.session_id,key),model,record_attempt=lambda a,e:attempts.append((a,e)))


def test_public_reply_has_no_prompt_unsaid_material_or_private_mapping(package,catalog,private_sample):
    role=private_sample['role'].id
    snap=assemble_context(catalog,frame(package,catalog,role))
    req=request(owner(),role_id=role);model=ScriptedModel([ModelReply(text='我需要先看更多证据。')])
    public,private=generate(snap,owner(),req,model)
    raw=public.model_dump(mode='json')
    assert not PRIVATE_REPLY_FIELDS.intersection(raw)
    assert raw['text']=='我需要先看更多证据。' and not raw['spoken_evidence']
    assert private_sample['approved'] not in json.dumps(raw,ensure_ascii=False)
    assert private_sample['approved'] in private.prompt_messages[0].content
    assert 'acceptable_conditions' not in json.dumps(raw)
    assert 'acceptable_conditions' in private.prompt_messages[0].content
    assert private.context.sources and private.reply_ref==reply_ref()
    assert private.prompt_hash==digest(model.calls[0])


def test_actual_quote_mapping_is_private_public_display_uses_utterance(package,catalog,private_sample):
    role=private_sample['role'].id
    snap=assemble_context(catalog,frame(package,catalog,role))
    fact=private_sample['fact']
    summary=next(s.text for s in snap.context.sources if fact.id in s.fact_ids)
    assert summary==private_sample['approved']
    public,private=generate(snap,owner(),request(owner(),role_id=role),ScriptedModel([ModelReply(text=summary)]))
    assert private.context.actual_disclosures
    assert fact.id in {d.fact_id for d in private.context.actual_disclosures}
    assert private.context.actual_disclosures[0].displayed_at_seq is None
    assert fact.id not in public.model_dump_json()
    assert fact.source.object_id not in public.model_dump_json()
    shown=displayed_disclosures(public,reply_ref(),displayed_at_seq=4)
    assert shown and shown[0].source.kind=='role_reply'
    assert shown[0].source.quote is None and shown[0].source.span_start is None
    assert shown[0].quote==summary and shown[0].displayed_at_seq==4


def test_three_rounds_non_echo_retains_exact_received_versions(package,catalog):
    auth=owner();req=request(auth)
    model=ScriptedModel([ModelReply(text='需要验证第一处假设。'),ModelReply(text='新证据回答了一部分问题。'),ModelReply(text='我们接着核对剩余问题。')])
    r1=share_receipt(1,'V1_BODY_ALPHA 原始假设')
    snap1=assemble_context(catalog,frame(package,catalog),new_shares=(r1,))
    public1,audit1=generate(snap1,auth,req,model,key='reply1')
    memo1=memory_from_generation(public1,audit1)
    r2=share_receipt(2,'V2_BODY_BETA 已修改假设')
    snap2=assemble_context(catalog,frame(package,catalog,shares=audit1.received_shares,memories=(memo1,)),new_shares=(r2,))
    public2,audit2=generate(snap2,auth,req.model_copy(update={'id':'turn2'}),model,key='reply2')
    memo2=memory_from_generation(public2,audit2)
    snap3=assemble_context(catalog,frame(package,catalog,shares=audit2.received_shares,memories=(memo1,memo2)))
    generate(snap3,auth,req.model_copy(update={'id':'turn3'}),model,key='reply3')
    second,third=(json.dumps(model.calls[i],ensure_ascii=False) for i in (1,2))
    assert all(text in second and text in third for text in ('V1_BODY_ALPHA','V2_BODY_BETA'))
    assert all('V1_BODY_ALPHA' not in p.text for p in (public1,public2))
    assert [(r.share.object_id,r.product.object_id,r.product.version,r.received_at.business_seq) for r in audit2.received_shares]==[('share-1','plan',1,0),('share-2','plan',2,0)]
    assert any(r.object_id=='plan' and r.version==1 and r.observed_at_seq==0 for r in memo1.provenance)
    # Scope applies to derived learner excerpts, not intrinsic colleague knowledge.
    denied=snap3.messages(agent(('faq',)))[0][0]['content']
    assert 'V1_BODY_ALPHA' not in denied and 'V2_BODY_BETA' not in denied
    intrinsic=next(s.text for s in snap3.context.sources if s.ref.object_id=='technical')
    assert intrinsic in denied
    assert snap3.permission_omissions(agent(('faq',)))>=2


def test_received_memory_survives_source_revoke_without_new_read(package,catalog):
    receipt=share_receipt(1,'PREVIOUSLY_RECEIVED_VERSION_ONE')
    snap=assemble_context(catalog,frame(package,catalog,shares=(receipt,)))
    assert 'PREVIOUSLY_RECEIVED_VERSION_ONE' in snap.messages(owner())[0][0]['content']
    # This path consumes a protected receipt only. No database/read_shared_product exists on the port.
    assert not hasattr(ContextPort(catalog),'store')


@pytest.mark.parametrize('sample_kind,error',[
    ('never_value','role_output_blocked'),('paraphrase_raw','role_output_blocked'),
    ('private_fact_id','role_output_blocked'),('empty','role_model_invalid')])
def test_deterministic_model_failure_has_stable_code_and_keeps_usage(package,catalog,disclosure_samples,private_sample,sample_kind,error):
    responses={'never_value':disclosure_samples['never'][0].value,
               'paraphrase_raw':private_sample['fragment'].text,
               'private_fact_id':private_sample['fact'].id,'empty':''}
    snap=assemble_context(catalog,frame(package,catalog));calls=[]
    model=ScriptedModel([ModelReply(text=responses[sample_kind],usage={'prompt_tokens':12,'completion_tokens':4})])
    with pytest.raises(ProtocolError) as exc:
        generate(snap,owner(),request(owner()),model,sink=calls)
    assert exc.value.code==error and exc.value.status==422
    assert calls[0][0].input_tokens==12 and calls[0][0].output_tokens==4 and calls[0][1]==error
    assert len(model.calls)==1


def test_timeout_is_transient_and_unknown_usage_is_explicit(package,catalog):
    class Timeout:
        revision='controlled-timeout'
        def complete(self,*_):raise TimeoutError('SECRET provider detail')
    calls=[]
    with pytest.raises(RoleModelTransient) as exc:
        generate(assemble_context(catalog,frame(package,catalog)),owner(),request(owner()),Timeout(),sink=calls)
    assert exc.value.error_code=='role_model_timeout'
    assert 'SECRET' not in str(exc.value)
    assert calls[0][0].status=='timeout' and not calls[0][0].usage_known and calls[0][0].input_tokens is None


def common_store(tmp_path,catalog):
    store=V2Store('sqlite:///'+str(tmp_path/'roles.db'));install_role_storage(store)
    bindings=SessionBindings(scenario=catalog.binding,runtime=catalog.binding,evaluation=catalog.binding)
    cfg=AssistantConfig(id='c0',session_id='template',domains=('faq',))
    world,token=store.create_session(bindings,cfg,{'capacity':30})
    auth=store.authenticate(world.session_id,token)
    return store,auth


def save_public(store,auth,public_text='SAFE_REPLY'):
    view=store.view(auth);req=request(auth)
    reqwrite=object_write('role_turn',req)
    reply=RoleReply(id='reply',session_id=auth.session_id,role_id='tech_lead',request=reqwrite.ref,
                   question='SAFE_QUESTION',text=public_text,status='completed',as_of=state_point(view.state),executor=auth.executor)
    write=object_write('role_reply',reply,visible_to=('learner','tech_lead'))
    cmd=Command(schema_version=2,request_id='save',operation='fixture_reply',expected_version=view.state.business_seq,expected_workspace_revision=view.state.workspace_revision)
    result=store.execute(auth,cmd,lambda *_:Mutation(writes=(reqwrite,write),result={'reply':write.ref.model_dump(mode='json'),'text':reply.text}))
    return reply,write.ref,cmd,result


def test_new_public_store_view_read_envelope_and_replay_have_no_private_data(tmp_path,catalog):
    store,auth=common_store(tmp_path,catalog);reply,ref,cmd,result=save_public(store,auth)
    assert store.read(auth,ref).content==reply.model_dump(mode='json')
    assert all(not PRIVATE_REPLY_FIELDS.intersection(x.content) for x in store.view(auth).objects if x.ref.kind=='role_reply')
    registry=ExtensionRegistry();gateway=Gateway(store,registry)
    envelope=gateway.public_result(auth,result)
    replay=gateway.public_result(auth,store.replay(auth,cmd))
    recovered=gateway.request_result(auth,'save').model_dump(mode='json')
    exported=[r.model_dump(mode='json') for r in read_replies(store.view(auth))]
    for obj in (envelope,replay,recovered,exported):
        text=json.dumps(obj)
        assert 'prompt_messages' not in text and 'source_versions' not in text and 'context_hash' not in text


def test_legacy_owned_projection_fails_closed():
    with pytest.raises(ProtocolError,match='role legacy reply requires projection'):
        parse_public_reply({'prompt_messages':[{'role':'system','content':'UNSAID_SECRET'}],'context_hash':'0'*64})


def test_missing_private_port_prevents_model_call(package,catalog):
    model=ScriptedModel([ModelReply(text='should never run')]);service=RoleService(ContextPort(catalog),model)
    with pytest.raises(ProtocolError) as error:service.generate(None,None,owner())
    assert error.value.code=='role_private_storage_unavailable' and not model.calls


def test_common_worker_deterministic_error_calls_once(tmp_path,catalog):
    store,auth=common_store(tmp_path,catalog);view=store.view(auth)
    cmd=Command(schema_version=2,request_id='queue',operation='turns.create',expected_version=0,expected_workspace_revision=0)
    effect=cmd.model_copy(update={'request_id':'effect'})
    queued=store.execute(auth,cmd,lambda *_:Mutation(jobs=(JobRequest(name='v2.blocked_role',command=effect,context_hash=digest('fixture')),)))
    calls=[];registry=ExtensionRegistry()
    def blocked(*_):calls.append('attempt');raise ProtocolError('role_output_blocked',status=422)
    registry.register_job('v2.blocked_role',blocked);gateway=Gateway(store,registry)
    jobs=JobRepository(store.db);worker=Worker(jobs,{'v2.blocked_role':ClaimedHandler(lambda payload,claim:gateway.run_job('v2.blocked_role',payload,claim=claim))})
    worker.run_once();worker.run_once()
    row=jobs.get(queued.result['queued_jobs'][0])
    assert calls==['attempt'] and row['status']=='failed' and row['error']=='role_output_blocked'


def test_invalid_response_keeps_received_partial_usage(package,catalog):
    class Invalid:
        revision='controlled-invalid'
        def complete(self,*_):return {'unexpected_field':'PRIVATE_PROVIDER_DETAIL','usage':{'prompt_tokens':123,'cost':.42}}
    calls=[]
    with pytest.raises(ProtocolError) as error:
        generate(assemble_context(catalog,frame(package,catalog)),owner(),request(owner()),Invalid(),sink=calls)
    assert error.value.code=='role_model_invalid' and 'PRIVATE_PROVIDER_DETAIL' not in str(error.value)
    assert calls[0][0].input_tokens==123 and calls[0][0].output_tokens is None and calls[0][0].cost==.42


def test_unrelated_write_does_not_invalidate_supplied_fixed_context(tmp_path,package,catalog):
    store,auth=common_store(tmp_path,catalog);initial=store.view(auth)
    req=request(auth);reqwrite=object_write('role_turn',req)
    cmd=Command(schema_version=2,request_id='queue-fixed',operation='turns.create',expected_version=0,expected_workspace_revision=0)
    effect=cmd.model_copy(update={'request_id':'fixed-effect'})
    queued=store.execute(auth,cmd,lambda *_:Mutation(writes=(reqwrite,),jobs=(JobRequest(name='v2.fixed_fixture',command=effect,sources=(reqwrite.ref,),context_hash=digest(req)),)))
    at_queue=state_point(queued.state)
    # Another durable transaction advances storage revision; it is not a dependency.
    other=Command(schema_version=2,request_id='unrelated',operation='fixture_note',expected_version=queued.state.business_seq,
                  expected_workspace_revision=queued.state.workspace_revision)
    store.execute(auth,other,lambda *_:Mutation(result={'note':'unrelated'}))
    calls=[];registry=ExtensionRegistry()
    def handle(view,envelope,a):
        from test_context import state
        scenario=state(package).model_copy(update={'session_id':a.session_id})
        scenario=scenario.model_copy(update={'current_config':scenario.current_config.model_copy(update={'session_id':a.session_id})})
        fixed=RoleFrame(a.session_id,'tech_lead',state_point(view.state),catalog.binding,scenario)
        # This is an explicitly labelled authority fixture, not the missing S02 port.
        snapshot=ContextPort(catalog,FixedFrameFixture(fixed)).capture(view,a,req.input,as_of=envelope.context.as_of)
        calls.append(snapshot.context.as_of)
        return Mutation(result={'fixture_status':'fixed_view_consumed'})
    registry.register_job('v2.fixed_fixture',handle);gateway=Gateway(store,registry);jobs=JobRepository(store.db)
    worker=Worker(jobs,{'v2.fixed_fixture':ClaimedHandler(lambda payload,claim:gateway.run_job('v2.fixed_fixture',payload,claim=claim))})
    worker.run_once()
    assert jobs.get(queued.result['queued_jobs'][0])['status']=='completed'
    assert calls==[at_queue]


def test_private_prompt_dump_is_deterministically_blocked(package,catalog):
    class Dump:
        revision='controlled-prompt-dump'
        def complete(self,messages,tools):return ModelReply(text=messages[0]['content'])
    calls=[]
    with pytest.raises(ProtocolError) as exc:
        generate(assemble_context(catalog,frame(package,catalog)),owner(),request(owner()),Dump(),sink=calls)
    assert exc.value.code=='role_output_blocked' and len(calls)==1


def test_legacy_invalid_error_does_not_return_raw_record():
    with pytest.raises(ProtocolError) as exc:parse_public_reply({'unexpected_private_field':'DO_NOT_ECHO_RAW_INPUT'})
    assert exc.value.code=='role_reply_record_invalid' and 'DO_NOT_ECHO_RAW_INPUT' not in str(exc.value)


def test_generation_identity_and_hidden_retry_budget_are_checked_before_call(package,catalog):
    snap=assemble_context(catalog,frame(package,catalog));model=ScriptedModel([ModelReply(text='not called')])
    with pytest.raises(ProtocolError,match='role generation identity invalid'):
        generate(snap,owner(),request(owner()).model_copy(update={'executor':agent().executor}),model)
    model.retries=2
    with pytest.raises(ProtocolError,match='role provider retry budget uncontrolled'):
        generate(snap,owner(),request(owner()),model)
    assert not model.calls


def test_common_worker_transient_error_keeps_code_and_uses_common_budget(tmp_path,catalog):
    store,auth=common_store(tmp_path,catalog)
    cmd=Command(schema_version=2,request_id='queue-timeout',operation='turns.create',expected_version=0,expected_workspace_revision=0)
    queued=store.execute(auth,cmd,lambda *_:Mutation(jobs=(JobRequest(name='v2.timeout_fixture',command=cmd.model_copy(update={'request_id':'timeout-effect'}),context_hash=digest('fixture')),)))
    calls=[];registry=ExtensionRegistry()
    def timeout(*_):calls.append('attempt');raise RoleModelTransient('role_model_timeout')
    registry.register_job('v2.timeout_fixture',timeout);gateway=Gateway(store,registry);jobs=JobRepository(store.db)
    worker=Worker(jobs,{'v2.timeout_fixture':ClaimedHandler(lambda payload,claim:gateway.run_job('v2.timeout_fixture',payload,claim=claim))})
    for _ in range(4):worker.run_once()
    row=jobs.get(queued.result['queued_jobs'][0])
    assert len(calls)==3 and row['status']=='failed' and row['error']=='role_model_timeout'


@pytest.mark.parametrize('role_id',['supervisor','business_lead','tech_lead'])
def test_explained_business_stance_is_spoken_opinion_not_world_fact(package,catalog,role_id):
    role=catalog.role(role_id)
    assert role.goals and role.acceptable_conditions
    quote=role.goals[0]
    snap=assemble_context(catalog,frame(package,catalog,role_id),question='你在意哪些业务取舍？')
    public,audit=generate(snap,owner(),request(owner(),role_id=role_id),ScriptedModel([ModelReply(text='我的关注点是：'+quote)]))
    assert quote in public.text
    matches=[o for o in audit.opinions if o.quote==quote]
    assert matches and matches[0].source_field=='goals' and matches[0].source_index==0
    assert matches[0].source_binding==catalog.binding
    assert matches[0].assertion_type=='role_opinion' and matches[0].verification=='verbatim_match_only'
    assert not audit.context.actual_disclosures  # no claim of a verified world fact or G0
    assert not public.spoken_evidence
    assert 'source_field' not in public.model_dump_json()
    assert 'acceptable_conditions' not in public.model_dump_json()
    _,silent=generate(snap,owner(),request(owner(),role_id=role_id),ScriptedModel([ModelReply(text='我先核对你提供的资料。')]))
    assert not silent.opinions


def test_prompt_exposes_only_in_scope_memory_object_versions_and_times(package,catalog):
    first=share_receipt(1,'first version body','share-one')
    second=share_receipt(2,'second version body','share-two')
    snap=assemble_context(catalog,frame(package,catalog,shares=(first,second)))
    payload=json.loads(snap.messages(owner())[0][0]['content'].split('\nCONTEXT\n',1)[1])
    received=[row for row in payload['sources'] if row['channel']=='received_share']
    assert {row['source_object'] for row in received}=={'product:plan@1','product:plan@2'}
    assert all(row['source_time']['observed_at_seq']==0 for row in received)
    assert {row['received_via'][0]['share'] for row in received}=={'share:share-one@1','share:share-two@1'}
    public,audit=generate(snap,owner(),request(owner()),ScriptedModel([ModelReply(text='请继续核对差异。')]),key='memory-reply')
    history=memory_from_generation(public,audit)
    third=assemble_context(catalog,frame(package,catalog,memories=(history,)))
    rows=json.loads(third.messages(owner())[0][0]['content'].split('\nCONTEXT\n',1)[1])['sources']
    row=next(x for x in rows if x['channel']=='memory')
    assert row['source_object']=='role_reply:memory-reply@1'
    assert {'product:plan@1','product:plan@2'}<={p['object'] for p in row['based_on']}
    hidden=third.messages(agent(('faq',)))[0][0]['content']
    assert 'memory-reply' not in hidden and 'product:plan@' not in hidden
