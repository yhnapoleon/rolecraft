"""Real stored job windows with controlled role catalog/audits; no model activation."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import pytest
from career_lab.contracts import v2 as C
from career_lab.api.role_snapshot import FixedRoleSnapshotPort
from career_lab.api.modules import ExtensionRegistry,Gateway
from career_lab.runtime.context_v2 import ScenarioKnowledge,ContextPort
from career_lab.runtime.roles_v2 import RoleService
from career_lab.storage.role_memory import RoleTurn,RoleReply,install_role_storage,object_write
from career_lab.storage.v2_store import V2Store,Mutation,ObjectWrite,EventDraft,references
from career_lab.storage.v2_lifecycle import point
from career_lab.storage.v2_remap import NamespaceRemapper,identity_key
from career_lab.jobs.repository import JobRepository
from .conftest import command,product_plan


def environment(foundation):
    original,_,_,bindings,config=foundation
    roles=tuple(C.RoleSpecV2(id=role,name=role,responsibilities=('Inspect the cited version.',),goals=('Use actual received evidence.',),known_materials=('policy',),known_facts=(),disclosure_policy={},event_subscriptions=('policy_updated',)) for role in ('tech_lead','business_lead'))
    materials=tuple(C.MaterialV2(id='policy',version=v,title='Policy',fragments=(C.SourceFragment(ref=C.EvidenceRefV2(session_id='template',kind='material',object_id='policy',version=v,observed_at_seq=0),text=f'POLICY_VERSION_{v}',channel='material',disclosure=C.DisclosurePolicy(mode='public')),),domain='fixture') for v in (1,2))
    catalog=ScenarioKnowledge(bindings.scenario,roles,materials)
    scenario=C.ScenarioStateV2(id='scenario',session_id='template',version=1,current_config=C.ObjectRef(session_id='template',kind='config',object_id=config.id,version=config.version,config_version=config.config_version),source_versions={'policy':1},indexed_versions={'policy':1},material_activation={'policy:1':0})
    state,token=original.create_session(bindings,config,{},scenario_state=scenario);auth=original.authenticate(state.session_id,token);install_role_storage(original)
    port=FixedRoleSnapshotPort(original,catalog);service=RoleService(ContextPort(catalog,port))
    return original,auth,token,catalog,port,service


def queue(env,key,auth=None):
    store,owner,token,catalog,port,service=env;auth=auth or owner
    body=C.TurnInput(role_id='tech_lead',text='Please check the evidence.')
    cmd=command(store.view(auth),key,'turns.create').model_copy(update={'payload':body.model_dump(mode='json')})
    tx=store.execute(auth,cmd,service.enqueue);job=JobRepository(store.db).get(tx.result['queued_jobs'][0]);context=C.JobContextSnapshot.model_validate(job['payload']['context']);effect=C.Command.model_validate(job['payload']['command'])
    return context,effect,tx.objects[0]


def test_normal_view_cannot_access_role_private_projection(foundation):
    env=environment(foundation);store,auth,_,_,port,_=env
    with pytest.raises(C.ProtocolError,match='role job snapshot required'):port.project_fixed(store.view(auth),auth,'tech_lead')


def test_fixed_job_stays_at_queued_window_after_unrelated_writes(foundation):
    env=environment(foundation);store,auth,_,_,port,_=env;context,effect,turn=queue(env,'first')
    store.execute(auth,command(store.view(auth),'unrelated'),lambda *_:Mutation(result={'note':'later unrelated write'}))
    view=store.job_view(auth,context,command=effect);frame=port.project_fixed(view,auth,'tech_lead')
    assert frame.as_of==context.as_of and frame.as_of.storage_revision<store.view(auth).state.storage_revision
    assert frame.memories==() and frame.received_shares==()
    with pytest.raises(C.ProtocolError):port.project_fixed(view,auth,'business_lead')
    forged=replace(view,state=store.view(auth).state)
    with pytest.raises(C.ProtocolError,match='role snapshot identity invalid'):port.project_fixed(forged,auth,'tech_lead')


def test_events_and_activation_require_actual_role_receipt_in_fixed_window(foundation):
    env=environment(foundation);store,auth,_,catalog,port,_=env;old,effect,_=queue(env,'before')
    before=store.view(auth)
    scenario=before.private_scenario_state.model_copy(update={'version':2,'source_versions':{'policy':2},'material_activation':{'policy:1':0,'policy:2':1}})
    ref=C.ObjectRef(session_id=auth.session_id,kind='scenario_state',object_id=scenario.id,version=2)
    write=ObjectWrite(ref=ref,expected_head=1,visible_to=('system',),content=scenario.model_dump(mode='json'),dependencies=(scenario.current_config,))
    # Only the business role received this notice; tech must keep v1.
    store.execute(auth,command(before,'update'),lambda *_:Mutation(writes=(write,),events=(EventDraft(type='policy_updated',visible_to=('business_lead',),data={'before_versions':{'policy':1},'after_versions':{'policy':2},'notice':'UNTRUSTED_NOTICE_NOT_A_SOURCE'}),)))
    fixed=store.job_view(auth,old,command=effect);snap=ContextPort(catalog,port).capture(fixed,auth,C.TurnInput(role_id='tech_lead',text='Q'),as_of=old.as_of)
    assert any('POLICY_VERSION_1' in x.text for x in snap.context.sources) and all('VERSION_2' not in x.text for x in snap.context.sources)
    current,command2,_=queue(env,'after');view=store.job_view(auth,current,command=command2);snap=ContextPort(catalog,port).capture(view,auth,C.TurnInput(role_id='tech_lead',text='Q'))
    assert snap.context.known_events==() and all('VERSION_2' not in x.text for x in snap.context.sources)
    # A later actual event at seq2 cannot fabricate the activation at seq1.
    store.execute(auth,command(store.view(auth),'bad-notice'),lambda *_:Mutation(events=(EventDraft(type='policy_updated',visible_to=('tech_lead',),data={'before_versions':{'policy':1},'after_versions':{'policy':2}}),)))
    ctx,cmd,_=queue(env,'after-invalid-notice');view=store.job_view(auth,ctx,command=cmd);snap=ContextPort(catalog,port).capture(view,auth,C.TurnInput(role_id='tech_lead',text='Q'))
    assert all('VERSION_2' not in x.text for x in snap.context.sources)


def add_controlled_audit(env,context,effect,request):
    store,auth,*_=env;product_tx=store.execute(auth,command(store.view(auth),'controlled-product'),product_plan)
    product=product_tx.objects[0];product_record=store.read(auth,product)
    # Another queued window includes the product before the controlled receipt.
    at=point(store.view(auth).state)
    fragment=C.DisclosedFragment(ref=C.EvidenceRefV2(**product.model_dump(),observed_at_seq=at.business_seq),text=C.canonical({'title':product_record.content['title'],'content':product_record.content['content'],'purpose':product_record.content['purpose'],'structured_payload':product_record.content['structured_payload']}),channel='received_share',verification='verified')
    share=C.ProductShare(id='share',session_id=auth.session_id,version=1,product=product,recipient_role='tech_lead',shared_at=at)
    share_ref=C.ObjectRef(session_id=auth.session_id,kind='share',object_id='share',version=1)
    store.execute(auth,command(store.view(auth),'share'),lambda *_:Mutation(writes=(ObjectWrite(ref=share_ref,expected_head=0,content=share.model_dump(mode='json'),dependencies=(product,)),)))
    context,effect,request=queue(env,'audited-turn');at=context.as_of
    fragment=fragment.model_copy(update={'ref':fragment.ref.model_copy(update={'observed_at_seq':at.business_seq})})
    reply=RoleReply(id='reply',session_id=auth.session_id,role_id='tech_lead',request=request,question='Q',text='A reply that does not echo the attached draft.',status='completed',as_of=at,executor=auth.executor)
    reply_write=object_write('role_reply',reply,visible_to=('learner','tech_lead'))
    messages=(C.ProviderMessage(role='system',content='CONTROLLED_PRIVATE_PROMPT'),)
    audit=C.RoleGenerationAudit(phase='completed',job_id='controlled-job',job_attempt=1,request=request,reply=reply_write.ref,scope=C.RoleAuditScope(capabilities=auth.capabilities,actor_id=auth.actor_id,executor=auth.executor,credential_id=auth.credential_id,allowed_objects=auth.allowed_objects,allowed_actions=auth.allowed_actions),prompt_messages=messages,prompt_hash=C.digest([{'role':'system','content':'CONTROLLED_PRIVATE_PROMPT'}]),history_revision=C.digest('controlled history'),received_shares=(C.RoleAuditReceivedShare(share=share_ref,product=product,role_id='tech_lead',received_at=at,fragment=fragment),),used_sources=(fragment,))
    private=C.RoleContext(session_id=auth.session_id,role_id='tech_lead',as_of=at,sources=(),shared_products=(product,),sourced_memory=(fragment,),context_hash=C.digest('controlled context'),generation_audit=audit)
    ref=C.ObjectRef(session_id=auth.session_id,kind='role_context',object_id='private-context',version=1)
    store.execute(auth,command(store.view(auth),'controlled-audit'),lambda *_:Mutation(writes=(reply_write,ObjectWrite(ref=ref,expected_head=0,visible_to=('system','tech_lead'),content=private.model_dump(mode='json'),dependencies=references(private.model_dump(mode='json')))),result={}))
    return product,ref


def test_private_receipts_recover_exact_content_without_model_echo(foundation):
    env=environment(foundation);store,auth,token,catalog,port,_=env;ctx,cmd,request=queue(env,'first');product,private=add_controlled_audit(env,ctx,cmd,request)
    ctx,cmd,_=queue(env,'later');view=store.job_view(auth,ctx,command=cmd);frame=port.project_fixed(view,auth,'tech_lead')
    assert len(frame.received_shares)==1 and frame.received_shares[0].product==product
    assert len(frame.memories)==1 and frame.memories[0].learner_refs==(product,)
    assert 'draft with an uncertain claim' in frame.received_shares[0].fragment.text
    assert all(r.ref!=private for r in store.view(auth).objects)
    with pytest.raises(C.ProtocolError):store.read(auth,private)
    # Current restricted caller scope filters both the stored receipt and its derived conversation.
    restricted=auth.model_copy(update={'allowed_objects':()})
    from career_lab.runtime.context_v2 import assemble_context
    snap=assemble_context(catalog,frame,question='Q');selected=snap.generation_sources(restricted)
    assert all(x.ref.kind not in {'product','role_reply'} for x in selected)


def test_role_projection_rechecks_lifecycle(foundation):
    env=environment(foundation);store,auth,*_=env;context,effect,_=queue(env,'first');view=store.job_view(auth,context,command=effect)
    store.execute(auth,command(store.view(auth),'pause','pause'),lambda *_:Mutation(state_changes={'status':'paused'}))
    with pytest.raises(C.ProtocolError,match='job session inactive'):env[4].project_fixed(view,auth,'tech_lead')


def test_private_generation_stays_closed_and_new_scalar_ids_remap(foundation):
    env=environment(foundation);store,auth,_,catalog,port,service=env;ctx,cmd,_=queue(env,'first')
    class NeverCall:
        revision='not-invoked'
        def complete(self,*_):pytest.fail('private sink is unavailable; no model call permitted')
    service.model=NeverCall()
    with pytest.raises(C.ProtocolError,match='role private storage unavailable'):service.generate(store.job_view(auth,ctx,command=cmd),None,auth)
    mapping={identity_key('feedback','f'):'new-f',identity_key('feedback_response','r'):'new-r',identity_key('workspace_import','i'):'new-i'}
    remap=NamespaceRemapper('s','fork',mapping)
    body=C.FeedbackResponseCreate(feedback_id='f',feedback_version=1,kind='objection',text='Keep literal f and s text.')
    assert remap.model(body).feedback_id=='new-f' and remap.model(body).text==body.text
    page=remap.model(C.ResourcePage(feedback_id='f',response_id='r',import_id='i'))
    assert (page.feedback_id,page.response_id,page.import_id)==('new-f','new-r','new-i')


@pytest.mark.parametrize('tamper',['text','receipt_time'])
def test_persisted_receipt_must_match_actual_share_and_source_history(foundation,tamper):
    from sqlalchemy import select,update
    from career_lab.storage.v2_tables import v2_objects
    env=environment(foundation);store,auth,_,_,port,_=env;ctx,cmd,req=queue(env,'first');product,private=add_controlled_audit(env,ctx,cmd,req)
    with store.db.transaction() as conn:
        row=conn.execute(select(v2_objects.c.record).where(v2_objects.c.session_id==auth.session_id,v2_objects.c.kind=='role_context',v2_objects.c.id==private.object_id)).scalar_one()
        record=C.StoredObject.model_validate_json(row);content=record.content;receipt=content['generation_audit']['received_shares'][0]
        if tamper=='text':receipt['fragment']['text']='FORGED_PRIVATE_BODY'
        else:receipt['received_at']=C.VersionPoint(business_seq=0,workspace_revision=0,storage_revision=0).model_dump(mode='json')
        conn.execute(update(v2_objects).where(v2_objects.c.session_id==auth.session_id,v2_objects.c.kind=='role_context',v2_objects.c.id==private.object_id).values(record=C.canonical(record.model_copy(update={'content':content}))))
    ctx,cmd,_=queue(env,'later')
    with pytest.raises(C.ProtocolError) as error:port.project_fixed(store.job_view(auth,ctx,command=cmd),auth,'tech_lead')
    assert 'FORGED_PRIVATE_BODY' not in str(error.value)


def test_revoked_original_agent_cannot_use_retained_fixed_role_view(foundation):
    env=environment(foundation);store,owner,_,_,port,_=env
    grant=C.DelegationGrant(id='role-agent',session_id=owner.session_id,actor_id='learner',executor=C.Executor(id='agent',kind='external_agent',delegation_id='role-agent'),capabilities=('read','act'),allowed_actions=('turns.create',),expires_at=datetime.now(timezone.utc)+timedelta(minutes=10))
    auth=store.authenticate(owner.session_id,store.issue_delegation(owner,grant));ctx,cmd,_=queue(env,'agent-turn',auth);view=store.job_view(auth,ctx,command=cmd)
    assert port.project_fixed(view,auth,'tech_lead').as_of==ctx.as_of
    store.revoke_delegation(owner,grant.id)
    with pytest.raises(C.ProtocolError,match='credential revoked or invalid'):port.project_fixed(view,auth,'tech_lead')


def test_actual_received_event_updates_role_version_without_copying_event_body(foundation):
    env=environment(foundation);store,auth,_,catalog,port,_=env;before=store.view(auth)
    scenario=before.private_scenario_state.model_copy(update={'version':2,'source_versions':{'policy':2},'material_activation':{'policy:1':0,'policy:2':1}})
    ref=C.ObjectRef(session_id=auth.session_id,kind='scenario_state',object_id=scenario.id,version=2)
    store.execute(auth,command(before,'update'),lambda *_:Mutation(writes=(ObjectWrite(ref=ref,expected_head=1,visible_to=('system',),content=scenario.model_dump(mode='json'),dependencies=(scenario.current_config,)),),events=(EventDraft(type='policy_updated',visible_to=('tech_lead',),data={'before_versions':{'policy':1},'after_versions':{'policy':2},'notice':'DO_NOT_COPY_EVENT_BODY'}),)))
    ctx,cmd,_=queue(env,'after');view=store.job_view(auth,ctx,command=cmd);snap=ContextPort(catalog,port).capture(view,auth,C.TurnInput(role_id='tech_lead',text='Q'))
    assert [r.text for r in snap.context.sources]==['POLICY_VERSION_2']
    assert len(snap.context.known_events)==1 and 'DO_NOT_COPY_EVENT_BODY' not in snap.context.model_dump_json()
