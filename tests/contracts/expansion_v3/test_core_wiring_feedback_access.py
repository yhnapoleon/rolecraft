"""Owner/Agent scope changes on real stored feedback; no private fixture readers."""
from datetime import datetime,timedelta,timezone
from dataclasses import replace
import pytest
from sqlalchemy import select,update
from fastapi.testclient import TestClient
from career_lab.contracts import v2 as C
from career_lab.api.modules import ExtensionRegistry,Operation
from career_lab.api.app import create_app
from career_lab.api.feedback_integration import install_feedback_recovery,record_feedback_response
from career_lab.storage.v2_store import Mutation,ObjectWrite,references
from career_lab.storage.v2_tables import v2_credentials,v2_objects
from career_lab.storage.v2_snapshot import SnapshotService
from .conftest import command,product_plan
from .test_core_wiring_feedback import make_report,stored_bytes,send

SECRET='PRIVATE_SOURCE_QUOTE_9347'
SECRET_ID='restricted-source-9347'
SECRET_TITLE='PRIVATE_SOURCE_TITLE_9347'
VISIBLE='AUTHORIZED_SOURCE_QUOTE_8126'


def source_plan(view,cmd,auth,oid,text,title):
    plan=product_plan(view,cmd,auth,oid=oid);write=plan.writes[0]
    product=C.WorkProductVersion.model_validate(write.content).model_copy(update={'title':title,'content':text,'content_hash':C.digest({'content':text,'structured_payload':None})})
    return replace(plan,writes=(write.model_copy(update={'content':product.model_dump(mode='json')}),))


def setup_report(foundation,*,agent_writer=False,legacy=False):
    store,owner,owner_token,*_=foundation
    hidden=store.execute(owner,command(store.view(owner),'hidden-source'),lambda v,c,a:source_plan(v,c,a,SECRET_ID,SECRET,SECRET_TITLE)).objects[0]
    visible=store.execute(owner,command(store.view(owner),'visible-source'),lambda v,c,a:source_plan(v,c,a,'visible-source',VISIBLE,'Visible title')).objects[0]
    product,review,_,base=make_report(foundation)
    auth,token=owner,owner_token
    if agent_writer:
        grant=C.DelegationGrant(id='publisher',session_id=owner.session_id,actor_id='learner',executor=C.Executor(id='agent',kind='external_agent',delegation_id='publisher'),capabilities=('read','act'),expires_at=datetime.now(timezone.utc)+timedelta(minutes=10))
        token=store.issue_delegation(owner,grant);auth=store.authenticate(owner.session_id,token)
    secret_ref=C.EvidenceRefV2(**hidden.model_dump(),observed_at_seq=base.as_of.business_seq,quote=SECRET)
    visible_ref=C.EvidenceRefV2(**visible.model_dump(),observed_at_seq=base.as_of.business_seq,quote=VISIBLE)
    items=tuple(C.FeedbackItem(criterion=name,label='MET',applicability='applicable',source='verified_rule',explanation=text,citations=(ref,),rule_bound=C.RuleBound(lower='MET',upper='MET')) for name,text,ref in [('visible-check',VISIBLE,visible_ref),('hidden-check',SECRET+' '+SECRET_ID+' '+SECRET_TITLE,secret_ref)])
    facts=base.verified_facts[0].model_copy(update={'references':tuple(C.FeedbackReferenceCheck(submitted_reference_hash=C.digest(ref),status='exact_reference_verified',verified_ref=ref,valid_at_subject=True) for ref in (visible_ref,secret_ref)),'declared_citation_count':2,'declared_source_count':2,'verified_source_count':2,'summary':(SECRET+' '+SECRET_TITLE,)})
    historical=base.historical_responsibilities[0].model_copy(update={'entries':tuple(C.HistoricalResponsibilityFinding(criterion=name,kind='actual_action',state='active',occurred_at=base.as_of,evaluated_at=base.as_of,scope=(product,),finding='verified_within_limit',explanation=text,sources=(ref,),actor_id='learner',executor=owner.executor) for name,text,ref in [('visible-history',VISIBLE,visible_ref),('hidden-history',SECRET+' '+SECRET_TITLE,secret_ref)])})
    report=C.FeedbackV2.model_validate(base.model_copy(update={'id':'cited-feedback','items':items,'rule_items':None if legacy else items,'verified_facts':None if legacy else (facts,),'historical_responsibilities':None if legacy else (historical,),'business_response':SECRET+' '+SECRET_ID,'next_options':(SECRET_TITLE,),'verified_coverage':1}).model_dump(mode='json'))
    ref=C.ObjectRef(session_id=owner.session_id,kind='feedback',object_id=report.id,version=1)
    body=C.FeedbackInput(subject=review);cmd=command(store.view(auth),'publish','feedback.create').model_copy(update={'payload':body.model_dump(mode='json')});calls=[]
    def publish(*_):
        calls.append('handler')
        return Mutation(writes=(ObjectWrite(ref=ref,expected_head=0,content=report.model_dump(mode='json'),dependencies=references(report.model_dump(mode='json'))),),result={'saved_feedback':report.model_dump(mode='json'),'free_summary':SECRET+' '+SECRET_ID})
    store.execute(auth,cmd,publish)
    if legacy:
        record=store.read(owner,ref);content={k:v for k,v in record.content.items() if k not in {'verified_facts','historical_responsibilities','rule_items','read_projection'}}
        with store.db.transaction() as conn:conn.execute(update(v2_objects).where(v2_objects.c.session_id==owner.session_id,v2_objects.c.kind=='feedback',v2_objects.c.id==ref.object_id).values(record=C.canonical(record.model_copy(update={'content':content}))))
    registry=ExtensionRegistry();install_feedback_recovery(registry);registry.register(Operation('feedback.create','act',C.FeedbackInput,publish))
    app=create_app(str(store.db.engine.url),extensions=registry)
    return dict(store=store,owner=owner,auth=auth,token=token,product=product,review=review,hidden=hidden,visible=visible,feedback=ref,report=report,command=cmd,app=app,calls=calls)


def delegate(case,scope):
    store,owner=case['store'],case['owner']
    grant=C.DelegationGrant(id='reader',session_id=owner.session_id,actor_id='learner',executor=C.Executor(id='reader',kind='external_agent',delegation_id='reader'),capabilities=('read','act'),allowed_objects=scope,expires_at=datetime.now(timezone.utc)+timedelta(minutes=10))
    token=store.issue_delegation(owner,grant);return store.authenticate(owner.session_id,token),token


def allowed_scope(case):return tuple(case[k].object_id for k in ('feedback','review','product','visible'))

def assert_safe(value):
    text=C.canonical(value)
    for secret in (SECRET,SECRET_ID,SECRET_TITLE):assert secret not in text,text


@pytest.mark.parametrize('path',['read','historical_read','view','query','reference','http'])
def test_feedback_only_grant_cannot_bypass_formal_subject_authorization(foundation,path):
    case=setup_report(foundation);store=case['store'];ref=case['feedback'];auth,token=delegate(case,(ref.object_id,))
    try:
        if path in {'view','query'}:
            rows=store.view(auth).objects if path=='view' else store.query(auth,lambda view:view.objects)
            assert not any(row.ref==ref for row in rows);assert_safe([row.model_dump(mode='json') for row in rows])
        elif path=='http':
            with TestClient(case['app']) as client:
                response=client.get(f'/sessions/{auth.session_id}/feedback-records/{ref.object_id}',headers={'Authorization':'Bearer '+token});assert response.status_code==404;assert_safe(response.json())
        else:
            with pytest.raises(C.ProtocolError):
                if path=='read':store.read(auth,ref)
                elif path=='historical_read':store.read(auth,ref,storage_revision=store.view(case['owner']).state.storage_revision)
                else:store.can_reference(auth,ref)
    finally:case['app'].state.store.close()


@pytest.mark.parametrize('path',['read','view','query','http'])
def test_partial_support_is_redacted_without_discarding_authorized_feedback(foundation,path):
    case=setup_report(foundation);store=case['store'];before=stored_bytes(store,case['feedback']);auth,token=delegate(case,allowed_scope(case))
    try:
        if path=='http':
            with TestClient(case['app']) as client:
                response=client.get(f"/sessions/{auth.session_id}/feedback-records/{case['feedback'].object_id}",headers={'Authorization':'Bearer '+token});assert response.status_code==200,response.text
                value=response.json()['result']['result']['feedback']
        elif path=='read':
            row=store.read(auth,case['feedback']);assert_safe(row.model_dump(mode='json'));value=row.content
        else:
            rows=store.view(auth).objects if path=='view' else store.query(auth,lambda view:view.objects)
            row=next(row for row in rows if row.ref==case['feedback']);assert_safe(row.model_dump(mode='json'));value=row.content
        assert_safe(value);assert value['read_projection']=='partial'
        assert value['items'][0]['explanation']==VISIBLE and value['items'][0]['label']=='MET'
        assert value['items'][1]['source']=='pending' and value['items'][1]['citations']==[]
        if value.get('rule_items'):assert value['rule_items'][1]['source']=='pending'
        facts=value['verified_facts'][0];assert facts['references'][1]['verified_ref'] is None and facts['references'][1]['submitted_reference_hash'] is None
        assert facts['source_snapshot_hash'] is None and facts['activity_totals']['material_read']['count'] is None
        history=value['historical_responsibilities'][0];assert history['entries'][0]['explanation']==VISIBLE and history['entries'][1]['finding']=='unknown'
        assert history['entries'][1]['occurred_at'] is None
        assert stored_bytes(store,case['feedback'])==before
    finally:case['app'].state.store.close()


@pytest.mark.parametrize('path',['execute','replay','request_result','http_get','http_replay'])
def test_cached_results_recheck_shrunk_scope_and_drop_untyped_private_text(foundation,path):
    case=setup_report(foundation,agent_writer=True);store=case['store'];current=case['auth'].model_copy(update={'allowed_objects':allowed_scope(case)})
    with store.db.transaction() as conn:conn.execute(update(v2_credentials).where(v2_credentials.c.id==current.credential_id).values(context=C.canonical(current)))
    auth=store.authenticate(current.session_id,case['token']);cmd=case['command'];before=stored_bytes(store,case['feedback'])
    try:
        if path.startswith('http'):
            with TestClient(case['app']) as client:
                headers={'Authorization':'Bearer '+case['token']}
                response=client.get(f'/sessions/{auth.session_id}/requests/publish',headers=headers) if path=='http_get' else client.post(f'/sessions/{auth.session_id}/feedback',headers=headers,json=cmd.model_dump(mode='json'))
                assert response.status_code==200,response.text;value=response.json()
        elif path=='execute':value=store.execute(auth,cmd,lambda *_:pytest.fail('handler reran')).model_dump(mode='json')
        elif path=='replay':value=store.replay(auth,cmd).model_dump(mode='json')
        else:value=store.request_result(auth,'publish')[1].model_dump(mode='json')
        assert_safe(value);assert VISIBLE in C.canonical(value);assert case['calls']==['handler']
        assert stored_bytes(store,case['feedback'])==before
    finally:case['app'].state.store.close()


def test_full_authorized_read_and_old_feedback_stay_compatible(foundation):
    case=setup_report(foundation,legacy=True);store=case['store'];before=stored_bytes(store,case['feedback'])
    try:
        full,_=delegate(case,None);raw=store.read(full,case['feedback']).content
        assert SECRET in C.canonical(raw) and 'verified_facts' not in raw and 'read_projection' not in raw
        # The same already-issued identity gets narrowed, with no second token.
        narrow=full.model_copy(update={'allowed_objects':allowed_scope(case)})
        with store.db.transaction() as conn:conn.execute(update(v2_credentials).where(v2_credentials.c.id==full.credential_id).values(context=C.canonical(narrow)))
        value=store.read(narrow,case['feedback']).content;assert_safe(value);assert VISIBLE in C.canonical(value)
        assert stored_bytes(store,case['feedback'])==before
    finally:case['app'].state.store.close()


def test_read_projection_cannot_be_written_back_or_exported_by_a_public_token(foundation):
    case=setup_report(foundation);store=case['store'];auth,token=delegate(case,allowed_scope(case))
    try:
        projected=store.read(auth,case['feedback']);newref=projected.ref.model_copy(update={'object_id':'rewritten'});content=projected.content|{'id':'rewritten'}
        with pytest.raises(C.ProtocolError,match='feedback projection not persistable'):
            store.execute(case['owner'],command(store.view(case['owner']),'rewrite-projection'),lambda *_:Mutation(writes=(ObjectWrite(ref=newref,expected_head=0,content=content,dependencies=references(content)),)))
        with pytest.raises(C.ProtocolError):SnapshotService(store).export(auth,C.digest('controlled'))
        original=SnapshotService(store).export(store.research_context(auth.session_id),C.digest('controlled'))
        assert SECRET in next(row for row in original.objects if row.ref==case['feedback']).model_dump_json()
    finally:case['app'].state.store.close()


def test_response_and_new_objection_share_the_same_parent_scope_boundary(foundation):
    case=setup_report(foundation);store=case['store'];owner=case['owner']
    response=store.execute(owner,send(store,owner,'old-response',feedback_id=case['feedback'].object_id,text=SECRET+' '+SECRET_TITLE),record_feedback_response).objects[0]
    auth,token=delegate(case,(*allowed_scope(case),response.object_id))
    try:
        row=store.read(auth,response);assert_safe(row.model_dump(mode='json'));assert row.content['read_projection']=='partial'
        with store.db.transaction() as conn:
            narrowed=auth.model_copy(update={'allowed_objects':(case['feedback'].object_id,response.object_id)})
            conn.execute(update(v2_credentials).where(v2_credentials.c.id==auth.credential_id).values(context=C.canonical(narrowed)))
        with pytest.raises(C.ProtocolError):store.read(narrowed,response)
        with pytest.raises(C.ProtocolError):store.execute(narrowed,send(store,narrowed,'blind-response',feedback_id=case['feedback'].object_id),record_feedback_response)
    finally:case['app'].state.store.close()


@pytest.mark.parametrize('path',['execute','replay','request_result'])
def test_old_cached_report_without_object_refs_cannot_leak_untyped_body(foundation,path):
    from career_lab.storage.v2_tables import v2_transactions
    from career_lab.storage.v2_store import TransactionResult
    case=setup_report(foundation,agent_writer=True);store=case['store'];auth=case['auth'].model_copy(update={'allowed_objects':allowed_scope(case)})
    with store.db.transaction() as conn:
        conn.execute(update(v2_credentials).where(v2_credentials.c.id==auth.credential_id).values(context=C.canonical(auth)))
        raw=conn.execute(select(v2_transactions.c.result).where(v2_transactions.c.session_id==auth.session_id,v2_transactions.c.request_id=='publish')).scalar_one()
        result=TransactionResult.model_validate_json(raw).model_copy(update={'objects':(),'result':{'feedback_id':case['feedback'].object_id,'text':SECRET}})
        conn.execute(update(v2_transactions).where(v2_transactions.c.session_id==auth.session_id,v2_transactions.c.request_id=='publish').values(result=C.canonical(result)))
    try:
        if path=='execute':value=store.execute(auth,case['command'],lambda *_:pytest.fail('rerun'))
        elif path=='replay':value=store.replay(auth,case['command'])
        else:value=store.request_result(auth,'publish')[1]
        assert_safe(value.model_dump(mode='json'));assert VISIBLE in value.model_dump_json()
        assert case['calls']==['handler']
    finally:case['app'].state.store.close()


def test_partial_feedback_quote_cannot_be_referenced_or_copied_into_another_object(foundation):
    case=setup_report(foundation);store=case['store'];auth,_=delegate(case,allowed_scope(case));ref=case['feedback']
    quoted=C.EvidenceRefV2(**ref.model_dump(),observed_at_seq=case['report'].as_of.business_seq,quote=SECRET)
    try:
        assert store.can_reference(auth,ref)
        with pytest.raises(C.ProtocolError):store.can_reference(auth,quoted)
        assert not store.query(auth,lambda view:view.reference_allowed(quoted))
        payload=command(store.view(auth),'copy','copy').model_copy(update={'payload':{'evidence':quoted.model_dump(mode='json')}})
        with pytest.raises(C.ProtocolError,match='feedback evidence unavailable'):store.execute(auth,payload,lambda *_:Mutation(result={'copy':SECRET}))
    finally:case['app'].state.store.close()


@pytest.mark.parametrize('path',['execute','replay','request_result'])
def test_cached_feedback_denies_an_inaccessible_primary_subject(foundation,path):
    case=setup_report(foundation,agent_writer=True);store=case['store'];auth=case['auth'].model_copy(update={'allowed_objects':(case['feedback'].object_id,)})
    with store.db.transaction() as conn:conn.execute(update(v2_credentials).where(v2_credentials.c.id==auth.credential_id).values(context=C.canonical(auth)))
    try:
        with pytest.raises(C.ProtocolError):
            if path=='execute':store.execute(auth,case['command'],lambda *_:pytest.fail('reran'))
            elif path=='replay':store.replay(auth,case['command'])
            else:store.request_result(auth,'publish')
        assert case['calls']==['handler']
    finally:case['app'].state.store.close()


@pytest.mark.parametrize('subject_allowed',[True,False])
def test_worker_fixed_view_uses_current_feedback_projection(foundation,subject_allowed):
    from career_lab.storage.v2_store import JobRequest
    from career_lab.jobs.repository import JobRepository
    case=setup_report(foundation,agent_writer=True);store=case['store'];auth=case['auth']
    effect=command(store.view(auth),'read-effect','inspect_feedback')
    queued=store.execute(auth,command(store.view(auth),'queue'),lambda *_:Mutation(jobs=(JobRequest(name='v2.feedback_projection_fixture',command=effect,sources=(case['feedback'],),context_hash=C.digest('controlled read')),)))
    job=JobRepository(store.db).get(queued.result['queued_jobs'][0]);ctx=C.JobContextSnapshot.model_validate(job['payload']['context'])
    current=auth.model_copy(update={'allowed_objects':allowed_scope(case) if subject_allowed else (case['feedback'].object_id,)})
    with store.db.transaction() as conn:conn.execute(update(v2_credentials).where(v2_credentials.c.id==auth.credential_id).values(context=C.canonical(current)))
    try:
        if subject_allowed:
            view=store.job_view(current,ctx,command=effect);row=view.get(case['feedback']);assert_safe(row.model_dump(mode='json'));assert VISIBLE in row.model_dump_json()
        else:
            with pytest.raises(C.ProtocolError):store.job_view(current,ctx,command=effect)
    finally:case['app'].state.store.close()


def test_external_feedback_read_reuses_verified_actor_anchor_without_resolver_rerun(foundation):
    store,owner,_,bindings,*_=foundation;product,review,_,base=make_report(foundation);calls=[]
    external=C.EvidenceRefV2(session_id=owner.session_id,kind='material',object_id='external-doc',version=1,observed_at_seq=0,quote=SECRET)
    def resolver(auth,ref,at,bindings):
        calls.append('verification')
        bare=C.ObjectRef.model_validate({k:v for k,v in ref.model_dump(mode='json').items() if k in C.ObjectRef.model_fields})
        file=C.FileRef(path='controlled-source.json',sha256=C.digest('controlled source'))
        return C.ExternalReference(ref=bare,source=file,content_hash=file.sha256)
    store.register_reference_resolver('material',resolver)
    item=C.FeedbackItem(criterion='external',label='INSUFFICIENT',applicability='applicable',source='pending',explanation=SECRET,citations=(external,))
    report=base.model_copy(update={'id':'external-feedback','items':(item,),'verified_facts':None,'historical_responsibilities':None,'rule_items':None})
    ref=C.ObjectRef(session_id=owner.session_id,kind='feedback',object_id=report.id,version=1)
    store.execute(owner,command(store.view(owner),'external-publish'),lambda *_:Mutation(writes=(ObjectWrite(ref=ref,expected_head=0,content=report.model_dump(mode='json'),dependencies=references(report.model_dump(mode='json'))),)))
    checked=len(calls);assert checked>0
    assert SECRET in store.read(owner,ref).model_dump_json();assert len(calls)==checked
    grant=C.DelegationGrant(id='external-reader',session_id=owner.session_id,actor_id='learner',executor=C.Executor(id='agent',kind='external_agent',delegation_id='external-reader'),capabilities=('read',),allowed_objects=(ref.object_id,review.object_id,product.object_id),expires_at=datetime.now(timezone.utc)+timedelta(minutes=10))
    auth=store.authenticate(owner.session_id,store.issue_delegation(owner,grant));value=store.read(auth,ref)
    assert SECRET not in value.model_dump_json() and 'external-doc' not in value.model_dump_json()
    assert value.content['items'][0]['source']=='pending' and len(calls)==checked
