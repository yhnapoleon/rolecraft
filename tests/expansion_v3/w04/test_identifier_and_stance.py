"""Explicit mechanical boundaries; controlled responses are not semantic QA."""
from dataclasses import replace
import json
from urllib.parse import quote
import pytest
from career_lab.contracts.v2 import ProtocolError,ObjectRef
from career_lab.runtime.context_v2 import assemble_context
from career_lab.runtime.model_adapter import ScriptedModel,ModelReply
from career_lab.storage.role_memory import memory_from_generation
from test_context import package,catalog,private_sample,disclosure_samples,frame,owner,share_receipt
from test_runtime import request,generate


def remembered_private_source(package,catalog,private_sample):
    snap=assemble_context(catalog,frame(package,catalog,private_sample['role'].id))
    auth=owner();req=request(auth,role_id=snap.role.id)
    reply,audit=generate(snap,auth,req,ScriptedModel([ModelReply(text='我先核对依据。')]),key='first')
    memory=memory_from_generation(reply,audit)
    assert any(ref.object_id==private_sample['fact'].source.object_id for ref in memory.provenance)
    second=assemble_context(catalog,frame(package,catalog,snap.role.id,memories=(memory,)))
    return second,req


def test_review_counterexample_neutralizes_private_mapping_without_erasing_knowledge(package,catalog,private_sample):
    snap,req=remembered_private_source(package,catalog,private_sample)
    private_ref=private_sample['fact'].source
    rendered=f'{private_ref.kind}:{private_ref.object_id}@{private_ref.version}'
    messages,_,mapping=snap.build_prompt(owner())
    prompt=json.dumps(messages,ensure_ascii=False)
    assert private_sample['approved'] in prompt
    assert private_ref.object_id not in prompt and rendered not in prompt
    assert mapping and any(ref.object_id==private_ref.object_id and ref.version==private_ref.version for ref,label in mapping)
    model=ScriptedModel([ModelReply(text='我的依据来源是 '+rendered)])
    with pytest.raises(ProtocolError) as exc:generate(snap,owner(),req,model)
    assert exc.value.code=='role_output_blocked' and private_ref.object_id not in str(exc.value)
    good,audit=generate(snap,owner(),req,ScriptedModel([ModelReply(text=private_sample['approved'])]))
    assert private_sample['approved'] in good.text
    assert audit.source_aliases and private_ref.object_id not in good.model_dump_json()


@pytest.mark.parametrize('style',['bare','qualified','upper','citation','encoded','chinese_adjacent'])
def test_private_identifier_text_citation_and_error_guards(package,catalog,private_sample,style):
    snap,req=remembered_private_source(package,catalog,private_sample)
    ref=private_sample['fact'].source;full=f'{ref.kind}:{ref.object_id}@{ref.version}'
    value={'bare':ref.object_id,'qualified':full,'upper':full.upper(),
           'citation':json.dumps({'citation':{'source':full}}),'encoded':quote(full,safe=''),
           'chinese_adjacent':'参考'+ref.object_id+'里的资料'}[style]
    with pytest.raises(ProtocolError) as exc:generate(snap,owner(),req,ScriptedModel([ModelReply(text=value)]))
    assert exc.value.code=='role_output_blocked' and ref.object_id not in str(exc.value)
    with pytest.raises(ProtocolError):snap.require_public({'citations':[value]})
    with pytest.raises(ProtocolError):snap.require_public({'error':value})


def test_public_and_shared_learner_source_versions_stay_usable(package,catalog):
    receipt=share_receipt(2,'已授权的第二版方案')
    snap=assemble_context(catalog,frame(package,catalog,shares=(receipt,)))
    prompt=snap.messages(owner())[0][0]['content']
    assert 'product:plan@2' in prompt and receipt.fragment.text in prompt
    public_material=next(m for m in catalog.materials if ('material',m.id) not in catalog.private_source_objects() and m.id in snap.role.known_materials)
    text=f'请核对 material:{public_material.id}@{public_material.version} 与 product:plan@2。'
    reply,_=generate(snap,owner(),request(owner()),ScriptedModel([ModelReply(text=text)]))
    assert reply.text==text


def test_missing_source_binding_stops_before_model_and_attempt_sink(package,catalog):
    snap=replace(assemble_context(catalog,frame(package,catalog)),source_binding=None)
    model=ScriptedModel([ModelReply(text='不应调用')]);attempts=[]
    with pytest.raises(ProtocolError) as exc:generate(snap,owner(),request(owner()),model,sink=attempts)
    assert exc.value.code=='role_stance_source_unavailable' and not model.calls and not attempts


def test_policy_gates_are_independent_of_known_materials_and_other_guards():
    from career_lab.contracts.v2 import (DisclosurePolicy,SourceFragment,MaterialV2,RoleSpecV2,
                                       EvidenceRefV2,ScenarioStateV2,FileRef,digest)
    from career_lab.runtime.context_v2 import ScenarioKnowledge,RoleFrame
    from test_context import point
    def material(mid,text,policy):
        return MaterialV2(id=mid,version=1,title=mid,domain='fixture',fragments=(SourceFragment(
            ref=EvidenceRefV2(session_id='s',kind='material',object_id=mid,version=1,observed_at_seq=0),
            text=text,channel='material',disclosure=policy),))
    never=material('known-never','KNOWN_NEVER_RAW',DisclosurePolicy(mode='never'))
    scoped=material('known-role-only','OTHER_ROLE_ONLY_RAW',DisclosurePolicy(mode='role_only',actors=('business_lead','learner')))
    roles=tuple(RoleSpecV2(id=role,name=role,responsibilities=('fixture',),goals=('fixture',),
        known_materials=(never.id,scoped.id),known_facts=(),disclosure_policy={}) for role in ('tech_lead','business_lead'))
    binding=FileRef(path='synthetic-policy.json',sha256=digest('fixture'))
    c=ScenarioKnowledge(binding,roles,(never,scoped))
    state=ScenarioStateV2(id='world',session_id='s',version=1,current_config=ObjectRef(session_id='s',kind='config',object_id='c0',version=1,config_version=0),
        source_versions={never.id:1,scoped.id:1},indexed_versions={never.id:1,scoped.id:1},material_activation={never.id+':1':0,scoped.id+':1':0})
    tech=c.role('tech_lead')
    assert never.id in tech.known_materials and scoped.id in tech.known_materials
    assert c.approved_text(tech,never.fragments[0]) is None
    assert c.approved_text(tech,scoped.fragments[0]) is None
    snap=assemble_context(c,RoleFrame('s',tech.id,point(),binding,state))
    assert not snap.context.sources
    assert 'KNOWN_NEVER_RAW' not in snap.messages(owner())[0][0]['content']
    assert 'OTHER_ROLE_ONLY_RAW' not in snap.messages(owner())[0][0]['content']
    business=c.role('business_lead')
    assert c.approved_text(business,scoped.fragments[0])=='OTHER_ROLE_ONLY_RAW'
    positive=assemble_context(c,RoleFrame('s',business.id,point(),binding,state))
    assert 'OTHER_ROLE_ONLY_RAW' in positive.messages(owner())[0][0]['content']
    assert 'KNOWN_NEVER_RAW' not in positive.messages(owner())[0][0]['content']


def stance_scenario(package,catalog):
    from test_context import notice
    before=assemble_context(catalog,frame(package,catalog))
    next_frame=replace(frame(package,catalog,updated=True,events=(notice(),)),stance_state=before.stance_state)
    after=assemble_context(catalog,next_frame)
    novel=[f for f in after.stance_facts if f.key not in set(before.stance_state.considered_facts)]
    assert novel and all(f.acquired_at_seq==4 for f in novel)
    return before,after,novel[0]


def proposal_for(snapshot,fact=None,*,reason='用户要求改变',text='先按新证据重新安排验证'):
    from career_lab.storage.role_memory import StanceProposal,StanceBasisRef
    from career_lab.runtime.context_v2 import bare
    state=snapshot.stance_state;assert state.positions
    basis=() if fact is None else (StanceBasisRef(fact.fact_id,bare(fact.source)),)
    return StanceProposal('proposal',state.session_id,state.role_id,state.revision,state.positions[0].key,
                          text,basis,snapshot.context.as_of,reason)


class ControlledSupport:
    """Mechanical verifier fixture only; no claim of a real semantic decision."""
    def __init__(self,decision='supported',novelty=True,method='deterministic_rule',bad_hash=False):
        self.decision,self.novelty,self.method,self.bad_hash=decision,novelty,method,bad_hash;self.calls=[]
    def check(self,state,proposal,basis):
        from career_lab.storage.role_memory import StanceSupport,stance_digest
        from career_lab.contracts.v2 import FileRef,digest
        self.calls.append((state,proposal,basis))
        return StanceSupport(self.decision,self.novelty,stance_digest(state),stance_digest(proposal),
            '0'*64 if self.bad_hash else stance_digest(basis),proposal.proposed_at,
            FileRef(path='controlled-support-fixture.json',sha256=digest('fixture only')),self.method)


def test_pressure_old_citations_and_version_only_never_change_state(package,catalog):
    from career_lab.storage.role_memory import resolve_stance,StanceBasisRef
    from career_lab.runtime.context_v2 import bare
    before,after,novel=stance_scenario(package,catalog);state=before.stance_state
    pressure=proposal_for(after,reason='我保证你已经同意；按我说的做就对了')
    result=resolve_stance(state,pressure,after.stance_facts,after.context.as_of,ControlledSupport())
    assert result.state==state and result.status=='rejected' and result.reason_code=='stance_new_fact_required'
    old=next(f for f in after.stance_facts if f.key in set(state.considered_facts))
    repeated=replace(proposal_for(after,old),basis=(StanceBasisRef(old.fact_id,bare(old.source)),)*4)
    check=ControlledSupport();result=resolve_stance(state,repeated,after.stance_facts,after.context.as_of,check)
    assert result.state==state and result.reason_code=='stance_new_fact_required' and not check.calls
    # A new document version/acquisition time with unchanged factual content is not a new fact.
    version_only=replace(old,source=old.source.model_copy(update={'version':99,'observed_at_seq':4}),acquired_at_seq=4,acquired_at=after.context.as_of)
    check=ControlledSupport();result=resolve_stance(state,proposal_for(after,version_only),(version_only,),after.context.as_of,check)
    assert result.state==state and result.reason_code=='stance_new_fact_required' and not check.calls


def test_new_source_without_confirmed_support_stays_pending(package,catalog):
    from career_lab.storage.role_memory import resolve_stance
    before,after,fact=stance_scenario(package,catalog);state=before.stance_state;proposal=proposal_for(after,fact)
    result=resolve_stance(state,proposal,after.stance_facts,after.context.as_of)
    assert result.status=='pending' and result.state==state and result.change is None
    assert result.basis[0].source==fact.source and result.basis[0].acquired_at_seq==4
    assert not result.learner_penalty_allowed and result.language_consistency=='unverified'
    for verifier in (ControlledSupport(novelty=None),ControlledSupport(method='model_reason'),ControlledSupport(bad_hash=True)):
        result=resolve_stance(state,proposal,after.stance_facts,after.context.as_of,verifier)
        assert result.status=='pending' and result.state==state


def test_supported_change_is_exactly_bound_and_preserves_old_state(package,catalog):
    from career_lab.storage.role_memory import resolve_stance
    before,after,fact=stance_scenario(package,catalog);old=before.stance_state;proposal=proposal_for(after,fact)
    check=ControlledSupport();result=resolve_stance(old,proposal,after.stance_facts,after.context.as_of,check)
    assert result.status=='changed' and result.state.revision==old.revision+1
    assert result.change.previous_text==old.positions[0].text
    assert result.change.new_text==proposal.proposed_text and result.change.basis[0].source==fact.source
    assert result.change.basis[0].acquired_at_seq==4 and result.change.effect=='role_stance_only'
    assert old.positions[0].text!=proposal.proposed_text and result.previous_state==old
    repeat=replace(proposal,parent_revision=result.state.revision,proposed_text='再让步一次')
    again=resolve_stance(result.state,repeat,after.stance_facts,after.context.as_of,check)
    assert again.state==result.state and again.reason_code=='stance_new_fact_required'


def test_future_missing_and_model_utterance_are_not_fact_basis(package,catalog):
    from career_lab.storage.role_memory import resolve_stance
    before,after,fact=stance_scenario(package,catalog)
    future=replace(fact,source=fact.source.model_copy(update={'observed_at_seq':5}),acquired_at_seq=5,acquired_at=after.context.as_of.model_copy(update={'business_seq':5}))
    result=resolve_stance(before.stance_state,proposal_for(after,future),(future,),after.context.as_of,ControlledSupport())
    assert result.reason_code=='stance_acquisition_time_unverified' and result.state==before.stance_state and result.status=='pending'
    model_reason=replace(fact,source=fact.source.model_copy(update={'kind':'role_reply','object_id':'model-claim'}))
    result=resolve_stance(before.stance_state,proposal_for(after,model_reason),(model_reason,),after.context.as_of,ControlledSupport())
    assert result.reason_code=='stance_basis_not_known' and result.state==before.stance_state


def test_generation_records_pending_proposal_without_claiming_language_consistency(package,catalog):
    before,after,fact=stance_scenario(package,catalog);proposal=proposal_for(after,fact)
    snapshot=replace(after,stance_proposals=(proposal,))
    model=ScriptedModel([ModelReply(text='我已经改变立场。')])
    public,audit=generate(snapshot,owner(),request(owner()),model)
    assert public.text=='我已经改变立场。'  # Controlled text deliberately demonstrates the remaining semantic gap.
    assert audit.stance_state==before.stance_state and audit.stance_resolutions[0].status=='pending'
    assert audit.stance_resolutions[0].language_consistency=='unverified'
    assert audit.stance_resolutions[0].learner_penalty_allowed is False
    assert 'stance_state' not in public.model_dump_json() and not audit.context.actual_disclosures
    prompt=json.loads(model.calls[0][0]['content'].split('\nCONTEXT\n',1)[1])
    assert prompt['current_stance'][0]['position']==before.stance_state.positions[0].text


def test_declared_private_object_refs_are_neutralized_and_remain_auditable(package,catalog):
    receipt=share_receipt(2,'实际获准内容不应被清空')
    f=replace(frame(package,catalog,shares=(receipt,)),private_source_refs=(receipt.share,receipt.product))
    snap=assemble_context(catalog,f)
    messages,_,mapping=snap.build_prompt(owner())
    text=json.dumps(messages,ensure_ascii=False)
    assert receipt.fragment.text in text
    assert 'product:plan@2' not in text and 'share:share-2@1' not in text
    assert {ref for ref,label in mapping}>={receipt.product,receipt.share}
    with pytest.raises(ProtocolError):snap.require_public('product:plan@2')


def test_no_proposal_preserves_state_and_future_state_is_refused(package,catalog):
    before,after,fact=stance_scenario(package,catalog)
    public,audit=generate(after,owner(),request(owner()),ScriptedModel([ModelReply(text='继续核对已有证据。')]))
    assert audit.stance_state==before.stance_state and not audit.stance_resolutions
    assert audit.language_consistency=='unverified' and audit.learner_penalty_allowed is False
    future=replace(before.stance_state,established_at=before.stance_state.established_at.model_copy(update={'business_seq':99}))
    with pytest.raises(ProtocolError,match='role stance context invalid'):
        assemble_context(catalog,replace(frame(package,catalog),stance_state=future))


def test_confirmed_irrelevant_basis_and_forged_support_do_not_change_state(package,catalog):
    from career_lab.storage.role_memory import resolve_stance
    before,after,fact=stance_scenario(package,catalog);proposal=proposal_for(after,fact)
    unsupported=resolve_stance(before.stance_state,proposal,after.stance_facts,after.context.as_of,ControlledSupport(decision='unsupported'))
    assert unsupported.status=='rejected' and unsupported.state==before.stance_state
    class WrongTime(ControlledSupport):
        def check(self,*args):
            support=super().check(*args)
            return replace(support,checked_at=support.checked_at.model_copy(update={'business_seq':0}))
    result=resolve_stance(before.stance_state,proposal,after.stance_facts,after.context.as_of,WrongTime())
    assert result.status=='pending' and result.state==before.stance_state


def test_private_stance_roundtrip_survives_sqlite_reopen_and_two_rounds(tmp_path,package,catalog):
    """Controlled carrier/support, not a claim of a deployed production writer."""
    import sqlite3,json
    from test_context import notice
    from career_lab.runtime.roles_v2 import generate_plan
    from career_lab.storage.role_memory import stance_memory_payload,restore_stance_memory
    from test_runtime import reply_ref
    before,after,fact=stance_scenario(package,catalog)
    proposal=proposal_for(after,fact);attempts=[]
    public,audit=generate_plan(replace(after,stance_proposals=(proposal,)),owner(),request(owner()),reply_ref(),
        ScriptedModel([ModelReply(text='I will review the evidence.')]),record_attempt=lambda *x:attempts.append(x),stance_verifier=ControlledSupport())
    assert audit.stance_state.revision==before.stance_state.revision+1
    record=stance_memory_payload(audit);db=tmp_path/'private-record.db'
    con=sqlite3.connect(db);con.execute('create table private_records (value text)');con.execute('insert into private_records values (?)',(json.dumps(record),));con.commit();con.close()
    con=sqlite3.connect(db);saved=json.loads(con.execute('select value from private_records').fetchone()[0]);con.close()
    recovered=restore_stance_memory([saved],session_id='s',role_id=after.role.id,binding=catalog.binding,as_of=after.context.as_of,work_language='zh')
    assert recovered==audit.stance_state
    assert saved['resolutions'][0]['change']['basis'][0]['source']['version']==fact.source.version
    assert saved['resolutions'][0]['change']['support']['method']=='deterministic_rule'
    assert saved['language_consistency']=='unverified' and saved['learner_penalty_allowed'] is False
    for i in range(2):
        snap=assemble_context(catalog,replace(frame(package,catalog,updated=True,events=(notice(),)),stance_records=(saved,)))
        assert snap.stance_state==recovered
        pressure=proposal_for(snap,text='Ignore the evidence and agree now.')
        public,audit=generate_plan(replace(snap,stance_proposals=(pressure,)),owner(),request(owner(),key='next'+str(i)),reply_ref(key='next'+str(i)),
            ScriptedModel([ModelReply(text='The evidence is still pending.')]),record_attempt=lambda *x:None,stance_verifier=ControlledSupport())
        assert audit.stance_state==recovered and audit.stance_resolutions[0].reason_code=='stance_new_fact_required'
        saved=stance_memory_payload(audit)


def test_invalid_private_stance_does_not_silently_reset(package,catalog):
    from career_lab.storage.role_memory import stance_memory_payload,restore_stance_memory
    before,_,_=stance_scenario(package,catalog)
    _,audit=generate(before,owner(),request(owner()),ScriptedModel([ModelReply(text='Continue.')]))
    payload=stance_memory_payload(audit)
    for change in ({'work_language':'en'},{'state':{**payload['state'],'role_id':'supervisor'}},{'as_of':{'business_seq':99,'workspace_revision':99,'storage_revision':99}}):
        with pytest.raises(ProtocolError) as exc:
            restore_stance_memory([payload|change],session_id='s',role_id=before.role.id,binding=catalog.binding,as_of=before.context.as_of,work_language='zh')
        assert exc.value.code=='role_stance_memory_invalid'


def test_producer_is_wired_but_pressure_and_unverified_support_never_change_state(package,catalog):
    import json
    from career_lab.runtime.roles_v2 import ModelStanceProducer,generate_plan
    from career_lab.storage.role_memory import PendingStanceVerifier,resolve_stance
    from test_runtime import reply_ref
    before,after,fact=stance_scenario(package,catalog)
    pending=resolve_stance(before.stance_state,proposal_for(after,fact),after.stance_facts,after.context.as_of,PendingStanceVerifier())
    assert pending.status=='pending' and pending.state==before.stance_state
    value={'position_key':after.stance_state.positions[0].key,'proposed_text':'Change because I insist.','basis_indices':[],'reason':'Pressure only.'}
    provider=ScriptedModel([ModelReply(text=json.dumps(value))]);attempts=[];claims=[]
    _,audit=generate_plan(after,owner(),request(owner()),reply_ref(),ScriptedModel([ModelReply(text='We still need evidence.')]),
        record_attempt=lambda a,e:attempts.append((a,e)),stance_producer=ModelStanceProducer(provider),
        stance_verifier=ControlledSupport(),begin_call=lambda phase,revision:claims.append(phase))
    assert len(provider.calls)==1 and len(attempts)==2 and claims==['stance_proposal','role_reply']
    assert audit.stance_state==before.stance_state and audit.stance_resolutions[0].reason_code=='stance_new_fact_required'


def test_model_and_support_retry_budgets_do_not_call_providers(package,catalog):
    from career_lab.runtime.roles_v2 import ModelStanceProducer
    from career_lab.storage.role_memory import resolve_stance
    before,after,fact=stance_scenario(package,catalog)
    model=ScriptedModel([ModelReply(text='unused')]);model.retries=1
    with pytest.raises(ProtocolError):ModelStanceProducer(model)
    verifier=ControlledSupport();verifier.retries=1
    result=resolve_stance(before.stance_state,proposal_for(after,fact),after.stance_facts,after.context.as_of,verifier)
    assert result.status=='pending' and not verifier.calls and not model.calls
