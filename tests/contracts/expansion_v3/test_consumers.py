from datetime import datetime,timedelta,timezone
from dataclasses import replace
from pathlib import Path
import pytest
from pydantic import ValidationError
from career_lab.contracts import v2 as C
from career_lab.storage.v2_store import Mutation,ObjectWrite,references
from career_lab.storage.v2_lifecycle import point
from career_lab.storage.v2_snapshot import SnapshotPortAdapter,SnapshotService
from career_lab.storage.v2_remap import identity_key
from career_lab.contracts.v2.projection import project_fragments
from career_lab.api.modules import make_step_result
from .conftest import command,product_plan

@pytest.mark.parametrize('mode',['none','warn','fallback'])
def test_assistant_freshness_is_three_state_and_threshold_unvalidated(foundation,mode):
    _,_,_,_,base=foundation
    value=C.AssistantConfig.model_validate(base.model_dump(mode='json')|{'freshness_guard':mode,'min_score':.35,'manual_domains':['policy']})
    assert value.freshness_guard==mode and value.min_score_calibration is None
    with pytest.raises(ValidationError):C.AssistantConfig.model_validate(base.model_dump()|{'freshness_guard':True})
    with pytest.raises(ValidationError):C.AssistantConfig.model_validate(base.model_dump()|{'min_score':float('inf')})

def test_projection_roles_and_expired_history_are_explicit():
    ref=C.EvidenceRefV2(session_id='s',kind='material',object_id='secret',version=1,observed_at_seq=0,valid_until_seq=1,quote='SECRET',span_start=0,span_end=6)
    fragment=C.SourceFragment(ref=ref,text='SECRET',channel='memory',disclosure=C.DisclosurePolicy(mode='paraphrase_only',actors=('tech_lead',),paraphrase='可披露摘要'))
    assert project_fragments((fragment,),'learner',0)==()
    assert project_fragments((fragment,),'tech_lead',2)==()
    historical=project_fragments((fragment,),'tech_lead',2,include_expired=True)
    assert historical[0].text=='可披露摘要' and historical[0].ref.quote is None
    assert project_fragments((fragment,),'learner',2,include_expired=True)==()

def test_observation_requires_actual_learner_acquisition(foundation):
    store,auth,*_=foundation;p=point(store.view(auth).state)
    ref=C.EvidenceRefV2(session_id=auth.session_id,kind='material',object_id='brief',version=1,observed_at_seq=0)
    seen=C.ObservedFragment(ref=ref,text='已读文字',channel='memory',audience='learner',acquired_via='material_read',acquired_at_seq=0)
    assert C.Observation(session_id=auth.session_id,actor=auth.executor,as_of=p,visible_sources=(seen,),next_seq=0)
    for bad in [seen.model_copy(update={'audience':'role_private'}),seen.model_copy(update={'audience':'model_only'}),seen.model_copy(update={'acquired_at_seq':1})]:
        with pytest.raises(ValidationError):C.Observation(session_id=auth.session_id,actor=auth.executor,as_of=p,visible_sources=(bad,),next_seq=0)
    with pytest.raises(ValidationError):C.ObservedFragment.model_validate(seen.model_dump()|{'acquired_via':'role_reply','disclosure_ref':None})

def test_step_result_keeps_actual_id_and_trusted_request_association(foundation):
    store,auth,*_=foundation;r=store.execute(auth,command(store.view(auth),'request-real'),product_plan)
    obs=C.Observation(session_id=auth.session_id,actor=auth.executor,as_of=point(r.state),visible_sources=(),next_seq=r.state.business_seq)
    step=C.ObservedStep(id='independent-source-step-id',request_id='request-real',action='save',as_of=point(r.state),observations=(),evidence_refs=(),outcome='success')
    result=make_step_result(r,obs,step,C.ActualConsumption(actions=1))
    assert result.step.id=='independent-source-step-id' and result.request_id=='request-real'
    with pytest.raises(C.ProtocolError):make_step_result(r,obs,step.model_copy(update={'request_id':'forged'}),C.ActualConsumption())
    with pytest.raises(ValidationError):C.StepResult.model_validate(result.model_dump()|{'request_id':'different'})

def test_private_scenario_state_and_scope_checks(foundation):
    store,owner,_,bindings,config=foundation
    scenario=C.ScenarioStateV2(id='scenario-state',session_id='template',version=1,current_config=C.ObjectRef(session_id='template',kind='config',object_id=config.id,version=1,config_version=0),source_versions={'faq':1,'policy':1},indexed_versions={'faq':1,'policy':1},material_activation={'faq:1':0,'policy:1':0})
    state,token=store.create_session(bindings,config,{'capacity':30},scenario_state=scenario);owner=store.authenticate(state.session_id,token)
    grant=C.DelegationGrant(id='scope',session_id=owner.session_id,actor_id='learner',executor=C.Executor(id='agent',kind='external_agent',delegation_id='scope'),capabilities=('read','act'),allowed_objects=('faq',config.id),expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
    auth=store.authenticate(owner.session_id,store.issue_delegation(owner,grant));view=store.view(auth)
    assert view.private_scenario_state is not None and not any(x.ref.kind=='scenario_state' for x in view.objects)
    def plan(v,cmd,a):
        updated=C.ScenarioStateV2.model_validate(v.private_scenario_state.model_dump()|{'version':2,'indexed_versions':{'faq':1,'policy':2}})
        ref=C.ObjectRef(session_id=a.session_id,kind='scenario_state',object_id=updated.id,version=2)
        return Mutation(writes=(ObjectWrite(ref=ref,expected_head=1,content=updated.model_dump(mode='json'),visible_to=('system',),dependencies=(updated.current_config,)),))
    with pytest.raises(C.ProtocolError,match='object scope forbidden'):store.execute(auth,command(view,'refresh','refresh_index'),plan)
    assert store.view(owner).private_scenario_state.indexed_versions['policy']==1

@pytest.mark.parametrize('order,mode,task',[([], 'singleton_or_empty','relation'),(['e1'],'singleton_or_empty','relation'),(['e1','e2'],'permutable','relation'),(['step1','step2'],'semantic_order','trajectory_diagnosis')])
def test_g2v_real_call_identity_and_non_permutable_inputs(order,mode,task):
    decision=C.AnnotationDecision(task_type=task,label='INSUFFICIENT' if task=='relation' else 'insufficient',evidence_evaluable=False,missing_reason='synthetic test only')
    actor=C.Executor(id='fixture-model',kind='system')
    def make(n,evidence):return C.AnnotationPass(id='pass-'+n,invocation_id='call-'+n,context_id='ctx-'+n,independence_method='fresh_context',independence_reason='Chronology or cardinality must be preserved' if mode!='permutable' else None,evidence_order_mode=mode,executor=actor,status='success',input_hash='0'*64,prompt_revision='prompt-'+n,model_revision='fixture',evidence_order=evidence,raw_output='synthetic output '+n,decision=decision)
    a=make('a',order);b=make('b',list(reversed(order)) if mode=='permutable' else order)
    good=C.AnnotationV2(record_id='r',annotation_version='v2',input_hash='0'*64,label_tier='G2v',status='accepted',passes=(a,b),final=decision)
    assert good.status=='accepted'
    for bad in [b.model_copy(update={'invocation_id':a.invocation_id}),b.model_copy(update={'context_id':a.context_id}),b.model_copy(update={'prompt_revision':a.prompt_revision})]:
        with pytest.raises(ValidationError):C.AnnotationV2.model_validate(good.model_dump()|{'passes':(a,bad)})
    if mode=='semantic_order':
        with pytest.raises(ValidationError):C.AnnotationV2.model_validate(good.model_dump()|{'passes':(a,b.model_copy(update={'evidence_order':tuple(reversed(order))}))})

def test_single_attempt_provider_controls_and_unknown_costs():
    calls=[];cap=C.ProviderCapabilities(seed_supported=True,decode_parameters=('temperature',),max_output_tokens=1024)
    def transport(request,remaining):
        calls.append((request.output_limit,request.seed,request.decode,remaining))
        return C.ProviderReply(provider='fixture',model_revision='r1',text='test output',input_tokens=10,output_tokens=4)
    provider=C.SingleAttemptProvider('fixture','r1',cap,transport)
    req=C.ProviderRequest(request_id='r',attempt_id='a',provider='fixture',model_revision='r1',prompt_revision='p',messages=(C.ProviderMessage(role='user',content='test'),),tools_digest=C.digest([]),deadline=datetime.now(timezone.utc)+timedelta(seconds=5),output_limit=100,seed=7,decode={'temperature':0})
    result=provider.call(req)
    assert result.status=='success' and len(calls)==1 and calls[0][:3]==(100,7,{'temperature':0})
    assert result.attempts[0].usage_known and result.attempts[0].cost is None
    assert provider.call(req.model_copy(update={'output_limit':2000})).attempts==() and len(calls)==1
    assert provider.call(req.model_copy(update={'deadline':datetime.now(timezone.utc)-timedelta(seconds=1)})).status=='timeout'
    def timeout(*_):raise TimeoutError()
    failed=C.SingleAttemptProvider('fixture','r1',cap,timeout).call(req)
    assert failed.status=='timeout' and len(failed.attempts)==1 and not failed.attempts[0].usage_known

def test_snapshot_port_exact_target_idempotency_and_structured_remap(foundation):
    store,auth,*_=foundation;created=store.execute(auth,command(store.view(auth)),product_plan)
    port=SnapshotPortAdapter(store,C.digest('source'))
    snapshot=port.export(auth.session_id,point(created.state));before=port.parent_digest(auth.session_id)
    a=port.restore(snapshot,'candidate-a','restore-a');b=port.restore(snapshot,'candidate-b','restore-b')
    assert (a.session_id,b.session_id)==('candidate-a','candidate-b') and a.id_map!=b.id_map
    assert port.restore(snapshot,'candidate-a','restore-a').replayed
    with pytest.raises(C.ProtocolError):port.restore(snapshot,'candidate-a','other-candidate')
    action=C.ActionProposal(id='a',tool='work_products.versions.create',arguments=C.ProductEdit(kind='text',product_id='product',expected_head=1,content='product must stay literal prose',task=None).model_dump(mode='json'),purpose='test')
    mapped=port.remap_action(action,a)
    assert mapped.arguments['product_id']==a.id_map[identity_key('product','product')] and mapped.arguments['content']=='product must stay literal prose'
    assert mapped.arguments['product_id']!=action.arguments['product_id']
    with pytest.raises(C.ProtocolError,match='environment adapter unavailable'):port.environment(a)
    assert port.parent_digest(auth.session_id)==before


def test_scenario_file_references_are_authorized_frozen_and_restored(foundation,tmp_path):
    store,auth,*_=foundation;source=tmp_path/'material.txt';source.write_text('public text\nSECRET')
    import hashlib
    file_ref=C.FileRef(path='material.txt',sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    def resolver(actor,ref,as_of,bindings):
        assert ref.session_id==actor.session_id
        if ref.object_id!='faq' or ref.version!=1:raise C.ProtocolError('object_not_found',status=404)
        if isinstance(ref,C.EvidenceRefV2) and ref.span_start is not None:
            if ref.span_end>len('public text') or ref.quote!=source.read_text()[ref.span_start:ref.span_end]:raise C.ProtocolError('object_not_found',status=404)
        C.read_file(tmp_path,file_ref)
        bare=C.ObjectRef.model_validate({k:v for k,v in ref.model_dump(mode='json').items() if k in C.ObjectRef.model_fields})
        return C.ExternalReference(ref=bare,source=file_ref,content_hash=file_ref.sha256)
    store.register_reference_resolver('material',resolver)
    cite=C.EvidenceRefV2(session_id=auth.session_id,kind='material',object_id='faq',version=1,observed_at_seq=0,span_start=0,span_end=6,quote='public')
    assert store.can_reference(auth,cite)
    def plan(v,c,a):
        result=product_plan(v,c,a);raw=result.writes[0].content|{'evidence_refs':[cite.model_dump(mode='json')]}
        return Mutation(writes=(result.writes[0].model_copy(update={'content':raw,'dependencies':references(raw)}),))
    result=store.execute(auth,command(store.view(auth),'with-source'),plan)
    snapshot=SnapshotService(store).export(store.research_context(auth.session_id),C.digest('source'))
    assert len(snapshot.external_references)==1
    clone,token=SnapshotService(store).restore(snapshot)
    clone_auth=store.authenticate(clone.session_id,token)
    product=store.read(clone_auth,C.ObjectRef(session_id=clone.session_id,kind='product',object_id=clone.id_map[identity_key('product','product')],version=1))
    assert product.dependencies[-1].session_id==clone.session_id
    with pytest.raises(C.ProtocolError):store.can_reference(auth,cite.model_copy(update={'span_start':12,'span_end':18,'quote':'SECRET'}))
    source.write_text('changed')
    with pytest.raises(C.ProtocolError,match='file hash mismatch'):store.can_reference(auth,C.ObjectRef(session_id=auth.session_id,kind='material',object_id='faq',version=1))


def test_task_scope_requires_explicit_creation_and_does_not_grant_existing_work(foundation):
    store,owner,*_=foundation;now=datetime.now(timezone.utc)
    task=C.WorkspaceTask(id='task',session_id=owner.session_id,title='委托事项',revision=1,created_at=now,updated_at=now)
    tref=C.ObjectRef(session_id=owner.session_id,kind='task',object_id='task',version=1)
    store.execute(owner,command(store.view(owner),'task'),lambda *_:Mutation(writes=(ObjectWrite(ref=tref,expected_head=0,content=task.model_dump(mode='json')),)))
    preexisting=store.execute(owner,command(store.view(owner),'existing'),lambda v,c,a:product_plan(v,c,a,'other-work'))
    def grant(gid,allow):
        value=C.DelegationGrant(id=gid,session_id=owner.session_id,actor_id='learner',executor=C.Executor(id=gid,kind='external_agent',delegation_id=gid),capabilities=('read','act'),allowed_objects=('task',),create_under_tasks=('task',) if allow else (),expires_at=now+timedelta(hours=1))
        return store.authenticate(owner.session_id,store.issue_delegation(owner,value))
    def create(v,c,a):
        cycle_ref=C.ObjectRef(session_id=a.session_id,kind='cycle',object_id=v.state.cycle_id,version=1)
        obj=C.WorkProductVersion(product_id='new-work',session_id=a.session_id,version=1,cycle=cycle_ref,task=tref,content='created under explicit task grant',author=a.executor,executor=a.executor,content_hash=C.digest({'content':'created under explicit task grant','structured_payload':None}),created_at=now)
        return Mutation(writes=(ObjectWrite(ref=C.ObjectRef(session_id=a.session_id,kind='product',object_id='new-work',version=1),expected_head=0,content=obj.model_dump(mode='json'),dependencies=(cycle_ref,tref)),))
    denied=grant('no-create',False)
    with pytest.raises(C.ProtocolError):store.execute(denied,command(store.view(denied),'no-create'),create)
    allowed=grant('create',True);result=store.execute(allowed,command(store.view(allowed),'create'),create)
    assert store.read(allowed,result.objects[0]).content['task']['object_id']=='task'
    with pytest.raises(C.ProtocolError):store.can_reference(allowed,preexisting.objects[0])


def test_proposed_request_basis_persists_without_apply_and_cannot_drift(foundation):
    store,auth,*_=foundation;before=store.view(auth);cfg=C.AssistantConfig.model_validate(next(x.content for x in before.objects if x.ref.kind=='config'))
    proposed=C.AssistantConfig.model_validate(cfg.model_dump()|{'participants':50,'update_strategy':'realtime'})
    basis=C.BusinessBasis(mode='proposed',config=proposed,content_hash=C.assistant_config_content_hash(proposed))
    request=C.BusinessRequest(basis=basis,id='request',session_id=auth.session_id,version=1,requested={'capacity':50},reason='先申请再决定是否应用',as_of=point(before.state),executor=auth.executor)
    ref=C.ObjectRef(session_id=auth.session_id,kind='business_request',object_id='request',version=1)
    result=store.execute(auth,command(before,'ask'),lambda *_:Mutation(writes=(ObjectWrite(ref=ref,expected_head=0,content=request.model_dump(mode='json')),)))
    assert result.state.config_version==0 and result.state.business_seq==0 and result.state.applied_milestones==()
    assert store.read(auth,ref).content['basis']==basis.model_dump(mode='json')
    other=C.AssistantConfig.model_validate(proposed.model_dump()|{'participants':40})
    changed=request.model_dump(mode='json')|{'version':2,'basis':C.BusinessBasis(mode='proposed',config=other,content_hash=C.assistant_config_content_hash(other)).model_dump(mode='json')}
    with pytest.raises(C.ProtocolError,match='request basis immutable'):
        store.execute(auth,command(store.view(auth),'rewrite'),lambda *_:Mutation(writes=(ObjectWrite(ref=ref.model_copy(update={'version':2}),expected_head=1,content=changed),)))
