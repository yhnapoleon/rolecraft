"""Existing V2Store authorizes every body; real saved points anchor feedback."""
import pytest
from test_w05_c8_persistence import prepared_env,cmd
from career_lab.contracts import v2 as C
from career_lab.storage.v2_store import Mutation,EventDraft
from career_lab.storage.v2_lifecycle import point,record_submission,begin_revision
from career_lab.storage.role_memory import RoleTurn,RoleReply,RoleDisplay,object_write,install_role_storage
from career_lab.evidence.v2.store_reader import StoreEvidenceReader
from career_lab.evidence.v2.submission_evaluator import SubmissionEvaluator,submission_feedback_plan
from career_lab.evidence.v2.ports import DEFAULT_POLICIES
from career_lab.api.reviews_v2 import create_review_evaluator


def test_w05_actual_store_reader_uses_saved_work_point_and_current_permissions(prepared_env):
    e=prepared_env;store=e['store'];auth=e['auth']
    reader=StoreEvidenceReader(store,auth,policies=DEFAULT_POLICIES)
    source=reader.read(auth,e['work'],reader.captured_at)
    assert source.created_at.storage_revision==store.read(auth,e['work']).created_storage_revision
    result=create_review_evaluator(reader).review(auth,(e['work'],),purpose='result',requested_at=reader.captured_at)['reviews'][0]
    assert result['verified_facts']['verified_source_count']==2
    assert result['evaluated_at']==source.created_at.model_dump(mode='json')
    assert result['feedback']['verified_facts'][0]['summary'][0].startswith('当前可查记录')
    forged=auth.model_copy(update={'credential_id':'untrusted'})
    with pytest.raises(C.ProtocolError):reader.read(forged,e['work'],reader.captured_at)


def test_w05_real_questions_replies_and_display_are_separate_records(prepared_env):
    e=prepared_env;store=e['store'];auth=e['auth'];install_role_storage(store)
    at=point(store.view(auth).state)
    turn=RoleTurn(id='actual-turn',session_id=auth.session_id,input=C.TurnInput(role_id='tech_lead',text='先核对哪项依据？'),as_of=at,executor=auth.executor)
    tw=object_write('role_turn',turn)
    store.execute(auth,cmd(store,auth,'controlled-question',{},'actual-turn'),lambda *_:Mutation(writes=(tw,)))
    reply=RoleReply(id='actual-reply',session_id=auth.session_id,role_id='tech_lead',request=tw.ref,question=turn.input.text,text='受控公开回复：请核对原始依据。',status='completed',as_of=point(store.view(auth).state),executor=auth.executor)
    rw=object_write('role_reply',reply,visible_to=('learner','tech_lead'))
    store.execute(auth,cmd(store,auth,'controlled-reply',{},'actual-reply'),lambda *_:Mutation(writes=(rw,)))
    display=RoleDisplay(id='actual-display',session_id=auth.session_id,reply=rw.ref,as_of=point(store.view(auth).state),executor=auth.executor)
    dw=object_write('role_display',display)
    store.execute(auth,cmd(store,auth,'controlled-display',{},'actual-display'),lambda *_:Mutation(writes=(dw,)))
    reader=StoreEvidenceReader(store,auth,policies=DEFAULT_POLICIES)
    ledger=reader.activity_log(auth,reader.captured_at)
    assert [r.kind for r in ledger.records]==['question_sent','reply_received','learner_displayed']
    assert ledger.records[1].target==tw.ref and ledger.records[2].target==rw.ref
    assert not any('private' in r.ref.kind for r in reader.records.values())
    # A later formal submission can see these actions; a prior work review keeps
    # its earlier creation point and must not retroactively count them.
    report=create_review_evaluator(reader).review(auth,(e['work'],),purpose='result',requested_at=reader.captured_at)['reviews'][0]
    assert report['verified_facts']['activity_totals']['question_sent']['verified_records']==0
    submitted=store.execute(auth,cmd(store,auth,'submit',C.SubmitInput(decision='no_go',products=(e['work'],)).model_dump(mode='json'),'actual-submit'),record_submission,capability='submit')
    sref=next(r for r in submitted.objects if r.kind=='submission');submission=C.SubmissionV2.model_validate(store.read(auth,sref).content)
    reader=StoreEvidenceReader(store,auth,policies=DEFAULT_POLICIES)
    prepared=SubmissionEvaluator(reader).evaluate(auth,submission)
    facts=prepared['reports'][0].verified_facts[0]
    assert facts.as_of==submission.as_of and facts.activity_totals['question_sent'].verified_records==1
    assert facts.activity_totals['reply_received'].verified_records==1 and facts.activity_totals['learner_displayed'].verified_records==1
    assert '向同事提问' in facts.summary[0]
    assert all(i.label=='NOT_APPLICABLE' for i in prepared['reports'][0].rule_items if i.criterion.startswith('R3.'))
    saved=store.execute(auth,cmd(store,auth,'feedback.request',{'subject':sref.model_dump(mode='json')},'submission-feedback'),lambda v,c,a:submission_feedback_plan(v,c,a,prepared),derived_subject=sref)
    report=store.read(auth,saved.objects[0]).content
    assert report['subject']==sref.model_dump(mode='json') and report['as_of']==submission.as_of.model_dump(mode='json')


def test_w05_submit_and_feedback_enqueue_are_atomic_and_common_worker_finishes(prepared_env):
    from career_lab.api.modules import Operation
    from career_lab.jobs.repository import JobRepository
    from career_lab.jobs.worker import Worker,ClaimedHandler
    from career_lab.evidence.v2.submission_evaluator import submission_plan_with_feedback
    e=prepared_env;app=e['app'];store=e['store'];auth=e['auth'];registry=app.state.gateway.registry
    registry.register(Operation('submissions.create','submit',C.SubmitInput,submission_plan_with_feedback,action_name='submit'))
    def generate(view,envelope,actor):
        subject=C.FeedbackInput.model_validate(envelope.command.payload).subject
        submission=C.SubmissionV2.model_validate(view.get(subject).content)
        reader=StoreEvidenceReader(store,actor,policies=DEFAULT_POLICIES)
        prepared=SubmissionEvaluator(reader).evaluate(actor,submission)
        return submission_feedback_plan(view,envelope.command,actor,prepared)
    registry.register_job('v2.submission-feedback',generate)
    command=cmd(store,auth,'submit',C.SubmitInput(decision='defer_with_conditions',products=(e['work'],)).model_dump(mode='json'),'atomic-submit')
    result=e['client'].post(f'/sessions/{auth.session_id}/submissions',json=command.model_dump(mode='json'));assert result.status_code==200,result.text
    body=result.json();jid=body['result']['queued_jobs'][0];assert body['state']['status']=='submitted'
    replay=e['client'].post(f'/sessions/{auth.session_id}/submissions',json=command.model_dump(mode='json')).json()
    assert replay['replayed'] and replay['result']['queued_jobs']==[jid]
    gateway=app.state.gateway;queue=JobRepository(store.db)
    worker=Worker(queue,{'v2.submission-feedback':ClaimedHandler(lambda payload,claim:gateway.run_job('v2.submission-feedback',payload,claim=claim))})
    assert worker.run_once() and queue.get(jid)['status']=='completed'
    recovered=e['client'].get(f'/sessions/{auth.session_id}/requests/atomic-submit').json()
    assert recovered['status']=='completed' and len(recovered['jobs'])==1
    feedback=recovered['jobs'][0]['effect']['result']['feedbacks'][0]
    saved=store.read(auth,C.ObjectRef.model_validate(feedback)).content
    assert saved['verified_facts'][0]['verified_source_count']==2
    assert saved['mode']=='advisory' and all(item['source']!='model_advice' for item in saved['items'])


def test_w05_real_material_read_event_and_test_object_enter_activity_ledger(prepared_env):
    from datetime import datetime,timezone
    from career_lab.storage.v2_store import ObjectWrite
    e=prepared_env;store=e['store'];auth=e['auth'];at=point(store.view(auth).state)
    material=C.ObjectRef(session_id=auth.session_id,kind='material',object_id='controlled-material',version=1)
    store.register_reference_resolver('material',lambda actor,ref,at,bindings:C.ExternalReference(ref=material,source=C.FileRef(path='controlled-material.txt',sha256='a'*64),content_hash='a'*64))
    store.execute(auth,cmd(store,auth,'read_material',{},'recorded-material-read'),lambda *_:Mutation(events=(EventDraft(type='material_read',visible_to=('learner',),data={'material_id':material.object_id,'version':1}),)))
    config_record=next(row for row in store.view(auth).objects if row.ref.kind=='config');config=C.AssistantConfig.model_validate(config_record.content)
    test=C.TestResultV2(id='actual-test',session_id=auth.session_id,query='受控验证',config_ref=config_record.ref,config=C.EffectiveConfig(requested=config,effective=config),status='fallback',answer='受控本地无命中。',citations=(),as_of=point(store.view(auth).state),
        execution=C.TestExecutionMetadata(executed_at=datetime.now(timezone.utc),executor=auth.executor,source_versions={},indexed_versions={},used_versions={},chunks=(),projection_actor='learner'))
    ref=C.ObjectRef(session_id=auth.session_id,kind='test',object_id=test.id,version=1)
    store.execute(auth,cmd(store,auth,'tests.create',{},'recorded-test'),lambda *_:Mutation(writes=(ObjectWrite(ref=ref,expected_head=0,content=test.model_dump(mode='json'),dependencies=(config_record.ref,)),)))
    reader=StoreEvidenceReader(store,auth,policies=DEFAULT_POLICIES)
    ledger=reader.activity_log(auth,reader.captured_at)
    assert [row.kind for row in ledger.records]==['material_read','test_run']
    assert reader.read(auth,ledger.records[0].ref,reader.captured_at).activity_target==material
    assert reader.read(auth,ledger.records[1].ref,reader.captured_at).executor==auth.executor
    assert reader.read(auth,ledger.records[1].ref,reader.captured_at).quote_scope=='explicit_only'
    assert reader.read(auth,ledger.records[0].ref,reader.captured_at).quote_scope=='explicit_only'
    assert all(complete is False for _,complete in ledger.completeness)


def test_w05_real_provider_slot_is_configuration_only_until_execution(monkeypatch):
    from career_lab.rubrics.v4.provider import create_feedback_engine
    from career_lab.runtime.model_adapter import OpenAICompatibleModel
    from career_lab.rubrics.v4.feedback import FeedbackEngine
    monkeypatch.setattr(OpenAICompatibleModel,'complete',lambda *_:pytest.fail('configuration must not call a provider'))
    placeholder=FeedbackEngine();assert placeholder.judge.model is None
    configured=create_feedback_engine(api_key='synthetic-key-not-a-real-credential',base_url='https://provider.invalid/v1',model='configured-judge',support_model='configured-support')
    assert configured.judge.model.retries==0 and configured.judge.support_check.model.retries==0
    assert configured.judge.revision!=placeholder.judge.revision


def test_w05_delegates_public_business_events_without_treating_them_as_objects(prepared_env):
    from career_lab.evidence.v2.ports import SourceRecord
    e=prepared_env;store=e['store'];auth=e['auth'];at=point(store.view(auth).state);seen=[]
    ref=C.EvidenceRefV2(session_id=auth.session_id,kind='event',object_id='public-policy-update',version=1,observed_at_seq=at.business_seq)
    def resolve(actor,requested,window):
        seen.append((actor,requested,window));return SourceRecord(ref,'Authorized public event',at)
    reader=StoreEvidenceReader(store,auth,policies=DEFAULT_POLICIES,source_reader=resolve)
    assert reader.read(auth,ref,at).text=='Authorized public event'
    assert seen==[(auth,ref,at)]
    with pytest.raises(C.ProtocolError):reader.read(auth.model_copy(update={'credential_id':'invalid'}),ref,at)
    assert len(seen)==1


@pytest.mark.parametrize('bad',['version','future','scope'])
def test_w05_delegated_sources_keep_identity_window_and_scope(prepared_env,bad):
    from career_lab.evidence.v2.ports import SourceRecord
    e=prepared_env;store=e['store'];auth=e['auth'];at=point(store.view(auth).state)
    ref=C.EvidenceRefV2(session_id=auth.session_id,kind='event',object_id='policy-event',version=1,observed_at_seq=at.business_seq)
    def resolve(actor,requested,window):
        if bad=='scope':raise C.ProtocolError('object_scope_denied',status=404)
        result=ref.model_copy(update={'version':2}) if bad=='version' else ref
        born=at.model_copy(update={'storage_revision':at.storage_revision+1}) if bad=='future' else at
        return SourceRecord(result,'Never expose mismatched/future source',born)
    reader=StoreEvidenceReader(store,auth,policies=DEFAULT_POLICIES,source_reader=resolve)
    with pytest.raises(C.ProtocolError):reader.read(auth,ref,at)


def test_w05_existing_config_uses_authorized_source_port_when_installed(prepared_env):
    from career_lab.evidence.v2.ports import SourceRecord
    e=prepared_env;store=e['store'];auth=e['auth'];base=StoreEvidenceReader(store,auth,policies=DEFAULT_POLICIES)
    ref=next(r.ref for r in store.view(auth).objects if r.ref.kind=='config')
    local=base.read(auth,ref,base.captured_at);calls=[]
    def resolve(actor,requested,window):calls.append(requested);return local
    reader=StoreEvidenceReader(store,auth,policies=DEFAULT_POLICIES,source_reader=resolve)
    resolved=reader.read(auth,ref,reader.captured_at)
    assert resolved.text==local.text and resolved.ref==local.ref and resolved.quote_scope=='explicit_only' and calls==[ref]


def test_w05_external_source_does_not_invent_a_whole_document_quote(prepared_env):
    from career_lab.evidence.v2.ports import SourceRecord
    from career_lab.evidence.v2.assembler import EvidenceAssemblerV2
    e=prepared_env;store=e['store'];auth=e['auth'];at=point(store.view(auth).state)
    ref=C.EvidenceRefV2(session_id=auth.session_id,kind='event',object_id='authorized-event',version=1,observed_at_seq=at.business_seq)
    reader=StoreEvidenceReader(store,auth,policies=DEFAULT_POLICIES,source_reader=lambda *_:SourceRecord(ref,'Heading\nOriginal sentence',at))
    assembler=EvidenceAssemblerV2(reader)
    bare=assembler.resolve(auth,ref,at)
    assert bare.ref.quote is None and bare.text=='Heading\nOriginal sentence'
    explicit=ref.model_copy(update={'quote':'Original sentence','span_start':8,'span_end':25})
    located=assembler.resolve(auth,explicit,at)
    assert located.ref.quote=='Original sentence' and located.text=='Original sentence'
