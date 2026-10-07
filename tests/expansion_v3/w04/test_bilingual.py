"""Bilingual pure-module checks. Synthetic assets, no production English/LLM QA."""
from dataclasses import replace
import json
from urllib.parse import quote
import pytest
from career_lab.contracts.v2 import (
    FileRef,ObjectRef,EvidenceRefV2,SourceFragment,MaterialV2,FactV2,DisclosurePolicy,
    RoleSpecV2,ScenarioStateV2,ProtocolError,TurnInput,digest,
)
from career_lab.runtime.context_v2 import (
    ScenarioKnowledge,RoleFrame,ContextPort,KnowledgeEvent,assemble_context,
    role_text,ROLE_PROMPT_REVISION,
)
from career_lab.runtime.roles_v2 import LocalRoleModel,RoleService
from career_lab.runtime.model_adapter import ScriptedModel,ModelReply
from career_lab.storage.role_memory import memory_from_generation,resolve_stance
from test_context import package,catalog,frame,owner,agent,point,share_receipt,make_view,FixedFrameFixture
from test_runtime import request,generate
from test_identifier_and_stance import proposal_for,ControlledSupport


def bilingual_fixture(language='en',role_id='tech_lead'):
    """Identical IDs, numeric facts, policies and times; authored test prose only."""
    materials=[];facts=[];approved={};raw={}
    roles=('tech_lead','business_lead','supervisor')
    def add(mid,fid,value,text,policy,version=1):
        ref=EvidenceRefV2(session_id='s',kind='material',object_id=mid,version=version,observed_at_seq=0)
        materials.append(MaterialV2(id=mid,version=version,title=mid,domain='fixture',fragments=(
            SourceFragment(ref=ref,text=text,channel='material',fact_ids=(fid,),disclosure=policy),)))
        facts.append(FactV2(id=fid,version=version,value=value,unit='count',source=ref,disclosure=policy))
    for version,limit in ((1,30),(2,40)):
        text=f'The approved pilot limit is {limit} seats.' if language=='en' else f'已批准的试点上限为{limit}个名额。'
        add('policy','capacity',limit,text,DisclosurePolicy(mode='public'),version)
    for i,role in enumerate(roles):
        approved[role]=(f'The {role.split("_")[0]} team requires an evidence check before changing the pilot.' if language=='en'
                        else f'该岗位第{i+1}组需要先核实证据再调整试点。')
        raw[role]=(f'Test-only private observation for role number {i+1}: sensitive detail.' if language=='en'
                   else f'第{i+1}号岗位的测试专用私有观察细节。')
        add(role+'_private',role+'_observation',i+1,raw[role],
            DisclosurePolicy(mode='paraphrase_only',actors=(role,),paraphrase=approved[role]))
    add('world_private','isolation_marker',17,
        'Test-only hidden calibration phrase.' if language=='en' else '测试专用隐藏校准原话。',DisclosurePolicy(mode='never'))
    specs=tuple(RoleSpecV2(id=role,name=role.replace('_',' ') if language=='en' else '测试角色'+str(i+1),
        responsibilities=('Check evidence and preserve source versions.' if language=='en' else '核对证据并保留来源版本。',),
        goals=('Keep the pilot grounded in verified facts.' if language=='en' else '试点应有核实事实依据。',),
        acceptable_conditions=('New verified evidence supports the change.' if language=='en' else '新核实证据支持变化。',),
        unacceptable_conditions=('Pressure without new evidence.' if language=='en' else '无新证据的施压。',),
        known_materials=('policy',role+'_private','world_private'),known_facts=(),disclosure_policy={},
        approval_authority=('approve_business',) if role=='supervisor' else (),event_subscriptions=('policy_changed',))
        for i,role in enumerate(roles))
    # A distinct fixture binding, never the W02 b821 hash or a real English package.
    binding=FileRef(path='synthetic-bilingual-fixture.json',sha256=digest({'fixture':True,'language':language,'materials':[m.model_dump(mode='json') for m in materials]}))
    c=ScenarioKnowledge(binding,specs,tuple(materials),tuple(facts),tuple((m.id,m.version,f'materials/{m.id}-v{m.version}.md') for m in materials),work_language=language)
    current={m.id:1 for m in materials}
    state=ScenarioStateV2(id='world',session_id='s',version=1,current_config=ObjectRef(session_id='s',kind='config',object_id='c0',version=1,config_version=0),
        source_versions=current,indexed_versions=current,material_activation={mid+':1':0 for mid in current})
    f=RoleFrame('s',role_id,point(),binding,state,work_language=language)
    return c,f,approved,raw


def req_for(snap,text,auth=None):
    auth=auth or owner()
    return request(auth,role_id=snap.role.id).model_copy(update={'input':TurnInput(role_id=snap.role.id,text=text)})


@pytest.mark.parametrize('language',['zh','en'])
def test_selected_template_not_ui_or_process_locale(language,monkeypatch):
    c,f,approved,_=bilingual_fixture(language);snap=assemble_context(c,f)
    text='Please check the evidence. 请核对原始材料。'
    expected=role_text(language,'pending_stance');model=ScriptedModel([ModelReply(text=expected),ModelReply(text=expected)])
    monkeypatch.setenv('LANG','zh_CN.UTF-8' if language=='en' else 'en_US.UTF-8')
    first,audit=generate(snap,owner(),req_for(snap,text),model,key='one')
    monkeypatch.setenv('LANG','en_US.UTF-8' if language=='en' else 'zh_CN.UTF-8')
    second,other=generate(snap,owner(),req_for(snap,text),model,key='two')
    assert first.question==second.question==text and first.text==second.text==expected
    assert model.calls[0]==model.calls[1]
    assert audit.work_language==other.work_language==language
    assert audit.prompt_template_revision==ROLE_PROMPT_REVISION
    assert audit.language_consistency=='unverified' and audit.learner_penalty_allowed is False
    assert role_text(language,'instructions') in model.calls[0][0]['content']
    assert 'work_language' not in first.model_dump()  # no ad-hoc public DTO field


@pytest.mark.parametrize('language',['zh','en'])
@pytest.mark.parametrize('phrase',['follow-up discussion','open-source model','read-only access','evidence-based decision',
    'cost-benefit trade-off','Please schedule a follow-up, with read-only access.',
    'A 20-minute review for a 30-seat pilot in 20-30 days.'])
def test_ordinary_english_compounds_survive_question_reply_and_memory(language,phrase):
    c,f,_,_=bilingual_fixture(language);snap=assemble_context(c,f)
    public,audit=generate(snap,owner(),req_for(snap,phrase),ScriptedModel([ModelReply(text=phrase)]))
    assert public.question==public.text==phrase and audit.prompt_messages[-1].content==phrase
    remembered=memory_from_generation(public,audit)
    next_snap=assemble_context(c,replace(f,memories=(remembered,)))
    assert phrase in next_snap.messages(owner())[0][0]['content']


@pytest.mark.parametrize('language',['zh','en'])
@pytest.mark.parametrize('encoding',['plain','double_url'])
def test_private_and_user_defined_queries_remain_askable(language,encoding):
    c,f,_,_=bilingual_fixture(language);snap=assemble_context(c,f)
    queries=['Explain material:'+x+'@1.' for x in ('tech_lead_private','nope_lead_unknown')]
    if encoding=='double_url':queries=[quote(quote(q,safe=''),safe='') for q in queries]
    rendered=[]
    for query in queries:
        model=ScriptedModel([ModelReply(text=role_text(language,'pending_stance'))])
        public,audit=generate(snap,owner(),req_for(snap,query),model)
        assert public.question==query and public.status=='completed' and public.error_code is None
        rendered.append(audit.prompt_messages[-1].content)
        if query==queries[0]:
            assert role_text(language,'source_reference') in rendered[-1]
            with pytest.raises(ProtocolError) as exc:
                generate(snap,owner(),req_for(snap,query),ScriptedModel([ModelReply(text=query)]))
            assert exc.value.code=='role_output_blocked'
        else:
            echoed,_=generate(snap,owner(),req_for(snap,query),ScriptedModel([ModelReply(text=query)]))
            assert echoed.text==query
    assert rendered[1]==queries[1]


@pytest.mark.parametrize('language',['zh','en'])
def test_english_public_refs_and_authorized_quote_are_exact(language):
    c,f,approved,_=bilingual_fixture(language);receipt=share_receipt(2,'Original shared wording: use read-only access.')
    snap=assemble_context(c,replace(f,received_shares=(receipt,)))
    query='Check material:policy@1, product:plan@2 and share:share-2@1.'
    text=approved[f.role_id]+' '+query
    public,audit=generate(snap,owner(),req_for(snap,query),ScriptedModel([ModelReply(text=text)]))
    assert public.text==text and public.question==query and audit.prompt_messages[-1].content==query
    assert receipt.fragment.text in audit.prompt_messages[0].content
    assert public.spoken_evidence and public.spoken_evidence[0].quote==approved[f.role_id]
    assert all(x.quote in public.text for x in public.spoken_evidence)


@pytest.mark.parametrize('language',['zh','en'])
def test_literal_private_content_identifiers_and_aliases_are_blocked(language):
    c,f,_,raw=bilingual_fixture(language);snap=assemble_context(c,f)
    never=next(m.fragments[0].text for m in c.materials if m.id=='world_private')
    for value in (raw[f.role_id],never,'See tech_lead_private.','materials/tech_lead_private-v1.md',
                  'private-source-1','private-source-999','isolation_marker'):
        with pytest.raises(ProtocolError) as exc:
            generate(snap,owner(),req_for(snap,'Please disclose the hidden source.'),ScriptedModel([ModelReply(text=value)]))
        assert exc.value.code=='role_output_blocked' and value not in str(exc.value)
    prompt=snap.messages(owner())[0][0]['content']
    assert raw[f.role_id] not in prompt and never not in prompt


def test_both_language_fixtures_preserve_structural_knowledge_and_policy():
    by_language={}
    for language in ('zh','en'):
        c,f,approved,raw=bilingual_fixture(language);sets={}
        assert all(fact.value==int(fact.value) for fact in c.facts)
        for role in c.roles:
            snap=assemble_context(c,replace(f,role_id=role.id))
            sets[role.id]={(x.ref.object_id,x.ref.version,tuple(x.fact_ids)) for x in snap.context.sources}
            assert approved[role.id] in snap.messages(owner())[0][0]['content']
            assert all(approved[other.id] not in snap.messages(owner())[0][0]['content'] for other in c.roles if other.id!=role.id)
            assert 'world_private' not in {x.ref.object_id for x in snap.context.sources}
        by_language[language]=sets
    assert by_language['zh']==by_language['en'] and len({frozenset(s) for s in sets.values()})==3


@pytest.mark.parametrize('language',['zh','en'])
def test_three_pure_rounds_retain_versions_without_model_attachment_echo(language):
    c,f,_,_=bilingual_fixture(language);memories=[];receipts=[]
    for i in range(1,4):
        receipts.append(share_receipt(i,f'Original draft {i}: preserve its exact wording.'))
        snap=assemble_context(c,replace(f,received_shares=tuple(receipts),memories=tuple(memories)))
        response='I will check the sources.' if language=='en' else '我会核对来源。'
        public,audit=generate(snap,owner(),req_for(snap,f'Please continue discussion round {i}.'),ScriptedModel([ModelReply(text=response)]),key='reply'+str(i))
        prompt=audit.prompt_messages[0].content
        assert audit.work_language==language
        for receipt in receipts:
            assert receipt.fragment.text in prompt and f'product:plan@{receipt.product.version}' in prompt
        assert all(receipt.fragment.text not in public.text for receipt in receipts)
        memory=memory_from_generation(public,audit);memories.append(memory)
        assert role_text(language,'history_meaning') in memory.fragment.text
        assert public.question in memory.fragment.text and public.text in memory.fragment.text
    assert audit.language_consistency=='unverified'


@pytest.mark.parametrize('language',['zh','en'])
def test_scope_omission_uses_bound_language_and_does_not_erase_role_knowledge(language):
    c,f,approved,_=bilingual_fixture(language);receipt=share_receipt(1,'RESTRICTED_LEARNER_WORK')
    snap=assemble_context(c,replace(f,received_shares=(receipt,)));auth=agent(allowed=())
    public,audit=generate(snap,auth,req_for(snap,'Continue.',auth),LocalRoleModel())
    assert role_text(language,'scope_omitted') in public.text
    assert 'RESTRICTED_LEARNER_WORK' not in public.text and 'RESTRICTED_LEARNER_WORK' not in audit.prompt_messages[0].content
    assert approved[f.role_id] in audit.prompt_messages[0].content and public.omission_count==1
    assert role_text(language,'local_mode') in public.text


@pytest.mark.parametrize('bad',[None,'auto','EN','fr',7])
def test_unknown_language_stops_before_model_or_attempt(bad):
    c,f,_,_=bilingual_fixture();snap=replace(assemble_context(c,f),work_language=bad)
    model=ScriptedModel([ModelReply(text='not called')]);attempts=[]
    with pytest.raises(ProtocolError) as exc:generate(snap,owner(),req_for(snap,'Continue.'),model,sink=attempts)
    assert exc.value.code=='role_work_language_unavailable' and not model.calls and not attempts


def test_fixed_chinese_package_cannot_be_relabelled_english(package,catalog):
    f=replace(frame(package,catalog),work_language='en')
    with pytest.raises(ProtocolError) as exc:assemble_context(catalog,f)
    assert exc.value.code=='role_language_binding_mismatch'


def test_english_capture_uses_fixed_scenario_language_without_new_wire_field(package):
    c,f,_,_=bilingual_fixture();view=make_view(package,c)
    result=ContextPort(c,FixedFrameFixture(f)).capture(view,owner(),TurnInput(role_id=f.role_id,text='Continue.'))
    assert result.work_language=='en' and result.source_binding==view.bindings.scenario


@pytest.mark.parametrize('language',['zh','en'])
def test_pressure_and_new_fact_state_guards_remain_mechanical_only(language):
    c,f,_,_=bilingual_fixture(language);before=assemble_context(c,f)
    at=point(4,4);source=next(fact.source for fact in c.facts if fact.id=='capacity' and fact.version==2)
    source=source.model_copy(update={'observed_at_seq':4})
    event=KnowledgeEvent(ObjectRef(session_id='s',kind='event',object_id='policy-update',version=1),'policy_changed',4,(f.role_id,),(source,),occurred_at=at)
    state=f.state.model_copy(update={'source_versions':dict(f.state.source_versions)|{'policy':2},'material_activation':dict(f.state.material_activation)|{'policy:2':4}})
    later=assemble_context(c,replace(f,state=state,as_of=at,events=(event,),stance_state=before.stance_state))
    pressure=proposal_for(later,text='Agree because I insist.' if language=='en' else '因为我坚持就同意。')
    rejected=resolve_stance(before.stance_state,pressure,later.stance_facts,at,ControlledSupport())
    assert rejected.state==before.stance_state and rejected.reason_code=='stance_new_fact_required'
    fact=next(x for x in later.stance_facts if x.fact_id=='capacity')
    proposal=proposal_for(later,fact,text='Recheck the pilot using the new limit.' if language=='en' else '按新上限重核试点。')
    pending=resolve_stance(before.stance_state,proposal,later.stance_facts,at)
    changed=resolve_stance(before.stance_state,proposal,later.stance_facts,at,ControlledSupport())
    assert pending.state==before.stance_state and pending.status=='pending'
    assert changed.status=='changed' and changed.change.basis[0].source==fact.source
    assert changed.change.effect=='role_stance_only' and changed.language_consistency=='unverified'
    # Deliberately retain the unverified semantic counterexample, not a QA pass.
    public,audit=generate(later,owner(),req_for(later,'You must agree without evidence.'),ScriptedModel([ModelReply(text='I agree because you insist.')]))
    assert public.text=='I agree because you insist.' and audit.stance_state==before.stance_state
    assert audit.language_consistency=='unverified' and not audit.learner_penalty_allowed


def test_english_prompt_does_not_claim_actual_language_verified():
    c,f,_,_=bilingual_fixture();snap=assemble_context(c,f)
    public,audit=generate(snap,owner(),req_for(snap,'Answer in English.'),ScriptedModel([ModelReply(text='这是一条故意违反语言要求的受控回复。')]))
    assert public.text.startswith('这是一条') and audit.work_language=='en'
    assert audit.language_consistency=='unverified'  # selection is not model-quality evidence


@pytest.mark.parametrize('language',['zh','en'])
def test_capture_reads_language_from_trusted_fixed_port(package,language):
    c,f,_,_=bilingual_fixture(language);view=make_view(package,c)
    class LanguagePort:
        def read_fixed(self,v,a):
            assert v is view and a.session_id==f.session_id
            return language
    port=ContextPort(c,FixedFrameFixture(f),language_port=LanguagePort())
    snap=port.capture(view,owner(),TurnInput(role_id=f.role_id,text='Original text remains unchanged.'))
    assert snap.work_language==language
    public,audit=generate(snap,owner(),req_for(snap,'Original text remains unchanged.'),LocalRoleModel())
    assert role_text(language,'local_mode') in public.text
    assert audit.work_language==language and audit.language_consistency=='unverified'
    assert public.question=='Original text remains unchanged.'


def test_capture_rejects_mismatched_fixed_language_before_model(package):
    c,f,_,_=bilingual_fixture();view=make_view(package,c)
    class LanguagePort:
        def read_fixed(self,v,a):return 'zh'
    with pytest.raises(ProtocolError) as exc:
        ContextPort(c,FixedFrameFixture(f),language_port=LanguagePort()).capture(view,owner(),TurnInput(role_id=f.role_id,text='Continue.'))
    assert exc.value.code=='role_language_binding_mismatch'


def test_package_language_is_hash_bound_and_cannot_be_relabelled(tmp_path,package):
    from types import SimpleNamespace
    from career_lab.contracts.v2 import FileRef
    raw=b'{"locale":"en"}'
    (tmp_path/'locale.json').write_bytes(raw)
    import hashlib
    ref=FileRef(path='locale.json',sha256=hashlib.sha256(raw).hexdigest())
    bundle=package.bundle.model_copy(update={'files':(*package.bundle.files,ref)})
    body=bundle.model_dump_json().encode();(tmp_path/'manifest.json').write_bytes(body)
    reference=SimpleNamespace(root=tmp_path,content_hash=hashlib.sha256(body).hexdigest(),bundle=bundle,
        materials=package.materials,facts=package.facts,rules=package.rules,locale='en')
    assert ScenarioKnowledge.from_package(reference).work_language=='en'
    reference.locale='zh'
    with pytest.raises(ProtocolError):ScenarioKnowledge.from_package(reference)
    reference.locale='en';(tmp_path/'locale.json').write_text('{"locale":"zh"}')
    with pytest.raises(ProtocolError):ScenarioKnowledge.from_package(reference)


@pytest.mark.parametrize('language',['zh','en'])
def test_reply_review_binds_work_language_and_preserves_original_quotes(tmp_path,language):
    from career_lab.runtime.roles_v2 import ModelReplyVerifier,generate_plan
    from test_identifier_and_stance import FileReviewPort
    from test_runtime import reply_ref
    c,f,_,_=bilingual_fixture(language);snap=assemble_context(c,f)
    text='原话是 "follow-up"；依据仍待核实。' if language=='zh' else 'You wrote "后续跟进". The supporting evidence is still pending.'
    reviewer=ScriptedModel([ModelReply(text=json.dumps({'decision':'consistent','language_match':True,'quote':text,'reason':'Controlled quotation case.'}))])
    port=FileReviewPort(tmp_path)
    public,audit=generate_plan(snap,owner(),req_for(snap,'Continue the discussion.'),reply_ref(),ScriptedModel([ModelReply(text=text)]),
        record_attempt=lambda *x:None,reply_verifier=ModelReplyVerifier(reviewer,port))
    assert public.text==text and audit.work_language==language and audit.language_consistency=='unverified'
    assert port.records[0]['inputs']['work_language']==language
    assert 'original wording' in reviewer.calls[0][0]['content']


@pytest.mark.parametrize('language',['zh','en'])
def test_private_extension_reopens_with_exact_new_fact_and_two_later_rounds(tmp_path,language):
    import sqlite3
    from career_lab.runtime.roles_v2 import generate_plan
    from career_lab.storage.role_memory import generation_audit_extension,read_generation_audit_extension,stance_digest
    from test_runtime import reply_ref
    c,f,_,_=bilingual_fixture(language);first=assemble_context(c,f)
    proof=EvidenceRefV2(session_id='s',kind='material',object_id='policy',version=2,observed_at_seq=4)
    event=KnowledgeEvent(ObjectRef(session_id='s',kind='event',object_id='update',version=1),'policy_changed',4,(f.role_id,),(proof,),occurred_at=point(4))
    state=f.state.model_copy(update={'source_versions':{**f.state.source_versions,'policy':2},'material_activation':{**f.state.material_activation,'policy:2':4}})
    next_frame=replace(f,state=state,as_of=point(4),events=(event,),stance_state=first.stance_state)
    snap=assemble_context(c,next_frame);fact=next(x for x in snap.stance_facts if x.source.object_id=='policy' and x.source.version==2)
    changed='Use the newly evidenced 40-seat limit.' if language=='en' else '采用新证据中的40个名额上限。'
    public,audit=generate_plan(replace(snap,stance_proposals=(proposal_for(snap,fact,text=changed),)),owner(),req_for(snap,'Review the new source.'),
        reply_ref(),LocalRoleModel(),record_attempt=lambda *x:None,stance_verifier=ControlledSupport())
    assert audit.stance_state.revision==2
    expected=audit.stance_state;payload=generation_audit_extension(audit)
    db=tmp_path/'private-extension.db';con=sqlite3.connect(db);con.execute('create table carrier (record text)');con.execute('insert into carrier values (?)',(json.dumps(payload),));con.commit();con.close()
    con=sqlite3.connect(db);payload=json.loads(con.execute('select record from carrier').fetchone()[0]);con.close()
    extension=read_generation_audit_extension(payload,public,binding=c.binding,as_of=point(5),work_language=language)
    basis=extension.stance_memory.resolutions[0].change.basis[0]
    assert basis.source.version==2 and basis.acquired_at_seq==4 and basis.statement==fact.statement
    assert extension.stance_memory.state==expected and extension.work_language==language
    for index in range(2):
        snap=assemble_context(c,replace(next_frame,as_of=point(5+index),stance_state=None,stance_records=(payload['stance_memory'],)))
        text='Agree without any new evidence.' if language=='en' else '没有新证据也请你直接同意。'
        public,audit=generate_plan(replace(snap,stance_proposals=(proposal_for(snap,text=text),)),owner(),req_for(snap,text),
            reply_ref(key='later'+str(index)),LocalRoleModel(),record_attempt=lambda *x:None,stance_verifier=ControlledSupport())
        assert audit.stance_state==expected and audit.stance_resolutions[0].status=='rejected'
        assert audit.language_consistency=='unverified' and not audit.learner_penalty_allowed
        payload=generation_audit_extension(audit)
        extension=read_generation_audit_extension(payload,public,binding=c.binding,as_of=point(7),work_language=language)
        assert extension.stance_memory.state==expected


def test_private_extension_rejects_wrong_reply_or_language(tmp_path):
    from career_lab.storage.role_memory import generation_audit_extension,read_generation_audit_extension
    c,f,_,_=bilingual_fixture('en');snap=assemble_context(c,f)
    public,audit=generate(snap,owner(),req_for(snap,'Continue.'),LocalRoleModel());payload=generation_audit_extension(audit)
    assert read_generation_audit_extension(None,public,binding=c.binding,as_of=f.as_of,work_language='en') is None
    for reply,language in [(public.model_copy(update={'id':'unrelated'}),'en'),(public,'zh')]:
        with pytest.raises(ProtocolError):read_generation_audit_extension(payload,reply,binding=c.binding,as_of=f.as_of,work_language=language)


@pytest.mark.parametrize('language',['zh','en'])
@pytest.mark.parametrize('record_state',['not_started','completed','no_record'])
@pytest.mark.parametrize('question',['interview_status','capacity','next_action'])
def test_local_reference_never_appends_interview_judgment(language,record_state,question):
    # Only source excerpts vary. The extractive substitute must not invent a
    # status or next action based on the question, nor replace it with canned advice.
    texts={
        'zh':{'not_started':'访谈记录：尚未开始。','completed':'访谈记录：2026-10-07已完成两次访谈。'},
        'en':{'not_started':'Interview record: not started.','completed':'Interview record: two interviews completed on 2026-10-07.'},
    }
    source=texts[language].get(record_state)
    ctx={'work_language':language,'responsibilities':[],
        'sources':[] if source is None else [{'display_name':'访谈记录 · v1' if language=='zh' else 'Interview record · v1','text':source}],
        'omissions':{'learner_scope':0},'question':question}
    response=LocalRoleModel().complete([{'role':'system','content':'Source reference\nCONTEXT\n'+json.dumps(ctx,ensure_ascii=False)}],[])
    assert role_text(language,'local_mode') in response.text
    assert '访谈尚未执行，可先整理为待办建议' not in response.text
    assert 'Interviews have not been carried out' not in response.text
    assert 'may be proposed as follow-up tasks' not in response.text
    assert '以上供讨论' not in response.text and 'This is for discussion.' not in response.text
    if source is not None:assert source in response.text
    else:assert '访谈' not in response.text and 'Interview' not in response.text
    if record_state=='completed':assert texts[language]['not_started'] not in response.text
