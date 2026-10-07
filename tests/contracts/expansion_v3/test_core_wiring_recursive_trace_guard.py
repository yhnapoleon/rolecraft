"""Independent-review counterexamples: nested private DTO data and authoritative traces."""
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,update
from career_lab.contracts import v2 as C
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry
from career_lab.storage.role_memory import RoleReply,RoleTurn,object_write
from career_lab.storage.v2_store import Mutation,ObjectWrite,FeedbackReadTrace,TransactionResult,references,role_reply_has_private_fields
from career_lab.storage.v2_tables import v2_objects,v2_transactions,v2_credentials
from .conftest import command
from .test_core_wiring_feedback import stored_bytes
from .test_core_wiring_feedback_access import setup_report,SECRET,VISIBLE

NESTED_SECRET='NESTED_PRIVATE_AUDIT_8826'


def reply_fixture(foundation):
    store,auth,token,*_=foundation;store.register_object('role_turn',RoleTurn)
    point=C.VersionPoint(**store.view(auth).state.model_dump(include={'business_seq','workspace_revision','storage_revision'}))
    turn=RoleTurn(id='original-turn',session_id=auth.session_id,input=C.TurnInput(role_id='tech_lead',text='Q'),as_of=point,executor=auth.executor);write=object_write('role_turn',turn)
    store.execute(auth,command(store.view(auth),'turn'),lambda *_:Mutation(writes=(write,)))
    class LooseReply(C.V2):
        id:str
        session_id:str
        role_id:str='tech_lead'
        version:int=1
        model_config={'extra':'allow'}
    store.register_object('role_reply',LooseReply)
    reply=RoleReply(id='reply',session_id=auth.session_id,role_id='tech_lead',request=write.ref,question='Q',text='Only actual public words.',status='completed',as_of=point,executor=auth.executor)
    return store,auth,token,reply


@pytest.mark.parametrize('field',['as_of','executor','request'])
def test_loose_registration_cannot_bypass_recursive_fixed_dto_validation(foundation,field):
    store,auth,token,reply=reply_fixture(foundation);body=reply.model_dump(mode='json');body[field]['generation_audit']={'prompt_messages':[{'role':'system','content':NESTED_SECRET}]}
    assert role_reply_has_private_fields(body)
    ref=C.ObjectRef(session_id=auth.session_id,kind='role_reply',object_id=reply.id,version=1)
    before=store.view(auth).state
    with pytest.raises(C.ProtocolError,match='role reply private fields forbidden'):store.execute(auth,command(store.view(auth),'bad-nested'),lambda *_:Mutation(writes=(ObjectWrite(ref=ref,expected_head=0,content=body,dependencies=references(body),visible_to=('learner','tech_lead')),)))
    assert store.view(auth).state==before


def test_historical_nested_audit_is_denied_on_every_public_recovery_and_preserved_privately(foundation):
    store,auth,token,reply=reply_fixture(foundation);body=reply.model_dump(mode='json');ref=C.ObjectRef(session_id=auth.session_id,kind='role_reply',object_id=reply.id,version=1)
    cmd=command(store.view(auth),'reply');tx=store.execute(auth,cmd,lambda *_:Mutation(writes=(ObjectWrite(ref=ref,expected_head=0,content=body,dependencies=references(body),visible_to=('learner','tech_lead')),),result={'reply':ref.model_dump(mode='json'),'body':body}))
    malformed=deepcopy(body);malformed['as_of']['generation_audit']={'prompt_messages':[{'role':'system','content':NESTED_SECRET}]}
    row=store.read(auth,ref);historical=row.model_copy(update={'content':malformed})
    with store.db.transaction() as conn:
        conn.execute(update(v2_objects).where(v2_objects.c.session_id==auth.session_id,v2_objects.c.kind=='role_reply',v2_objects.c.id==ref.object_id).values(record=C.canonical(historical)))
        conn.execute(update(v2_transactions).where(v2_transactions.c.session_id==auth.session_id,v2_transactions.c.request_id==cmd.request_id).values(result=C.canonical(tx.model_copy(update={'result':{'reply':ref.model_dump(mode='json'),'body':malformed}}))))
    original=stored_bytes(store,ref)
    for call in (lambda:store.read(auth,ref),lambda:store.read(auth,ref,storage_revision=tx.state.storage_revision),lambda:store.request_result(auth,cmd.request_id),lambda:store.replay(auth,cmd),lambda:store.execute(auth,cmd,lambda *_:pytest.fail('reentry'))):
        with pytest.raises(C.ProtocolError) as error:call()
        assert NESTED_SECRET not in str(error.value)
    assert not any(r.ref==ref for r in store.view(auth).objects)
    assert not any(r.ref==ref for r in store.query(auth,lambda view:view.objects))
    app=create_app(str(store.db.engine.url),extensions=ExtensionRegistry())
    try:
        with TestClient(app) as client:
            response=client.get(f'/sessions/{auth.session_id}/requests/{cmd.request_id}',headers={'Authorization':'Bearer '+token});assert response.status_code==404 and NESTED_SECRET not in response.text
    finally:app.state.store.close()
    assert store.read(store.research_context(auth.session_id),ref).content==malformed
    assert store.read(store.role_reader(auth.session_id,'tech_lead'),ref).content==malformed
    assert stored_bytes(store,ref)==original


def mixed_trace_report(foundation):
    case=setup_report(foundation,agent_writer=True);store=case['store'];auth=case['auth'];old=case['report']
    mixed=old.items[0].model_copy(update={'explanation':SECRET+' from uncited dependency'})
    independent=old.items[0].model_copy(update={'criterion':'independent'})
    history=old.historical_responsibilities[0];entry=history.entries[0].model_copy(update={'explanation':SECRET+' historical uncited dependency'})
    stable=history.entries[0].model_copy(update={'criterion':'independent-history'})
    history=history.model_copy(update={'entries':(entry,history.entries[1],stable)})
    report=old.model_copy(update={'id':'mixed-trace','items':(mixed,old.items[1],independent),'rule_items':(mixed,old.items[1],independent),'historical_responsibilities':(history,)})
    ref=case['feedback'].model_copy(update={'object_id':report.id});paths=('/items/0/explanation','/rule_items/0/explanation','/historical_responsibilities/0/entries/0/explanation')
    traces=tuple(FeedbackReadTrace(ref,path,(case['visible'],case['hidden'])) for path in paths)
    cmd=command(store.view(auth),'mixed-publish','feedback.create').model_copy(update={'payload':C.FeedbackInput(subject=case['review']).model_dump(mode='json')})
    store.execute(auth,cmd,lambda *_:Mutation(writes=(ObjectWrite(ref=ref,expected_head=0,content=report.model_dump(mode='json'),dependencies=references(report.model_dump(mode='json'))),),result={'feedback':ref.model_dump(mode='json')},feedback_read_traces=traces))
    narrowed=auth.model_copy(update={'allowed_objects':tuple([ref.object_id,*[case[key].object_id for key in ('review','product','visible')]])})
    with store.db.transaction() as conn:conn.execute(update(v2_credentials).where(v2_credentials.c.id==auth.credential_id).values(context=C.canonical(narrowed)))
    case.update(auth=narrowed,feedback=ref,command=cmd);return case


@pytest.mark.parametrize('path',['read','view','query','replay','request','execute','http-feedback','http-request','http-post'])
def test_visible_citations_never_short_circuit_hidden_complete_trace(foundation,path):
    case=mixed_trace_report(foundation);store=case['store'];auth=case['auth'];ref=case['feedback'];cmd=case['command'];before=stored_bytes(store,ref)
    try:
        if path=='read':value=store.read(auth,ref).content
        elif path=='view':value=next(r.content for r in store.view(auth).objects if r.ref==ref)
        elif path=='query':value=store.query(auth,lambda view:view.get(ref).content)
        elif path=='replay':value=store.replay(auth,cmd).model_dump(mode='json')
        elif path=='request':value=store.request_result(auth,cmd.request_id)[1].model_dump(mode='json')
        elif path=='execute':value=store.execute(auth,cmd,lambda *_:pytest.fail('handler reran')).model_dump(mode='json')
        else:
            with TestClient(case['app']) as client:
                headers={'Authorization':'Bearer '+case['token']}
                if path=='http-feedback':response=client.get(f'/sessions/{auth.session_id}/feedback-records/{ref.object_id}',headers=headers)
                elif path=='http-request':response=client.get(f'/sessions/{auth.session_id}/requests/{cmd.request_id}',headers=headers)
                else:response=client.post(f'/sessions/{auth.session_id}/feedback',headers=headers,json=cmd.model_dump(mode='json'))
                assert response.status_code==200,response.text;value=response.json()
        text=C.canonical(value);assert SECRET not in text and VISIBLE in text
        if path in {'read','view','query'}:
            assert value['items'][0]['source']=='pending' and value['items'][0]['citations'][0]['quote']==VISIBLE
            assert value['rule_items'][0]['source']=='pending'
            assert value['historical_responsibilities'][0]['entries'][0]['finding']=='unknown'
            assert value['items'][2]['explanation']==VISIBLE
            assert value['historical_responsibilities'][0]['entries'][2]['explanation']==VISIBLE
        assert stored_bytes(store,ref)==before
    finally:case['app'].state.store.close()


@pytest.mark.parametrize('limited',[False,True])
def test_cited_text_hash_failure_remains_pending_even_when_all_sources_are_readable(foundation,limited):
    from career_lab.contracts.v2.projection import project_feedback_content
    case=mixed_trace_report(foundation);store=case['store']
    try:
        raw=C.StoredObject.model_validate_json(stored_bytes(store,case['feedback'])).content
        for key in ('items','rule_items'):raw[key][0]['explanation']='ALTERED_AFTER_TRACE'
        raw['historical_responsibilities'][0]['entries'][0]['explanation']='ALTERED_AFTER_TRACE'
        result,partial=project_feedback_content(raw,lambda _:True,limited_scope=limited)
        assert partial and 'ALTERED_AFTER_TRACE' not in C.canonical(result)
        assert result['items'][0]['citations'][0]['quote']==VISIBLE
        assert result['items'][2]['explanation']==VISIBLE
    finally:case['app'].state.store.close()
