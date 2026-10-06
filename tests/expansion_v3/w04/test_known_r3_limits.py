"""c4 blocked-port regressions; old filename retained without rewriting r1 evidence."""
from pathlib import Path
import subprocess
import types

import pytest
from career_lab.contracts.v2 import AssistantConfig,SessionBindings,Command,ObjectRef,ProtocolError,ProviderMessage
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.storage.v2_store import V2Store,Mutation,ObjectWrite
from career_lab.storage.v2_lifecycle import point
from career_lab.storage.role_memory import install_role_storage,object_write,parse_public_reply
from test_context import package,catalog


def test_frozen_w02_runtime_binding_is_not_forged(package):
    with pytest.raises(ProtocolError,match='runtime contract mismatch'):
        ScenarioModule(package.root)


def make_legacy_database(tmp_path,catalog):
    # The actual immutable r1 definitions create this historical fixture in an
    # isolated DB. They are never registered in a production service.
    import legacy_r1_fixture as module
    url='sqlite:///'+str(tmp_path/'legacy.db');old=V2Store(url)
    old.register_object('role_turn',module.RoleTurn);old.register_object('role_reply',module.RoleReply)
    bindings=SessionBindings(scenario=catalog.binding,runtime=catalog.binding,evaluation=catalog.binding)
    state,token=old.create_session(bindings,AssistantConfig(id='c0',session_id='template',domains=('fixture',)),{})
    auth=old.authenticate(state.session_id,token)
    from career_lab.contracts.v2 import TurnInput
    req=module.RoleTurn(id='old-turn',session_id=auth.session_id,input=TurnInput(role_id='tech_lead',text='原提问'),as_of=point(state),executor=auth.executor)
    reqwrite=object_write('role_turn',req)
    reply=module.RoleReply(id='old-reply',session_id=auth.session_id,role_id='tech_lead',request=reqwrite.ref,
          question='原提问',text='我还需要核对。',status='completed',context_hash='0'*64,prompt_hash='1'*64,
          prompt_messages=(ProviderMessage(role='system',content='UNSAID_R1_PRIVATE_PROMPT'),),history_revision='2'*64,
          as_of=point(state),model_revision='historical-fixture',executor=auth.executor)
    write=object_write('role_reply',reply,visible_to=('learner','tech_lead'))
    old.execute(auth,Command(schema_version=2,request_id='legacy-save',operation='fixture',expected_version=0,expected_workspace_revision=0),
                lambda *_:Mutation(writes=(reqwrite,write)))
    fresh=V2Store(url);install_role_storage(fresh)
    return fresh,auth,write.ref


def test_owned_legacy_decoder_rejects_real_r1_record(tmp_path,catalog):
    store,auth,ref=make_legacy_database(tmp_path,catalog)
    with pytest.raises(ProtocolError,match='role legacy reply requires projection'):
        parse_public_reply(store.read(auth,ref).content)


@pytest.mark.xfail(strict=True,reason='BLOCKED c4 common read/view lacks historical role_reply projection; P0 cannot be closed by W04 alone')
@pytest.mark.parametrize('path',['read','view'])
def test_common_historical_role_reply_guard_still_required(tmp_path,catalog,path):
    store,auth,ref=make_legacy_database(tmp_path,catalog)
    try:
        values=[store.read(auth,ref)] if path=='read' else list(store.view(auth).objects)
    except ProtocolError:
        return
    assert all('prompt_messages' not in record.content for record in values if record.ref.kind=='role_reply')
