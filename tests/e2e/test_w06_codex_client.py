"""Installed official Codex MCP client, ephemeral session, no model turn."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time

import pytest
import uvicorn
from career_lab.contracts import v2 as C

ROOT=Path(__file__).parents[2]
source=importlib.util.spec_from_file_location('w06_actual_production',ROOT/'tests/integration/test_w06_production.py')
base=importlib.util.module_from_spec(source);source.loader.exec_module(base)
production=base.production
source=importlib.util.spec_from_file_location('w06_codex_client',ROOT/'examples/byo_agent_client/codex_client.py')
clients=importlib.util.module_from_spec(source);source.loader.exec_module(clients)


@pytest.mark.skipif(shutil.which('codex') is None,reason='Official Codex executable not installed')
def test_w06_official_codex_reads_writes_recovers_and_observes_revocation(production):
    e=production;ref=C.ObjectRef(session_id=e['sid'],kind='material',object_id='brief',version=1)
    e['send']('actions','read_material',{'tool':'read_material','material':ref.model_dump(mode='json')})
    safe,old,display,private=base.displayed_role_history(e)
    created=base.delegate(e)
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(32)
    server=uvicorn.Server(uvicorn.Config(e['app'],log_level='critical',access_log=False,lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    end=time.monotonic()+5
    while not server.started and time.monotonic()<end:time.sleep(.01)
    assert server.started
    config=e['tmp']/'codex-delegate.json'
    config.write_text(json.dumps({'api_url':f'http://127.0.0.1:{sock.getsockname()[1]}','session_id':e['sid'],'token':created['token']}));config.chmod(0o600)
    client=None
    try:
        client=clients.CodexMcpClient(config,cwd=ROOT)
        inventory=client.inventory()
        assert 'work_products.create' in json.dumps(inventory)
        observation=client.call('observation',{'session_id':e['sid']})
        assert not observation.get('isError'),observation
        data=observation['structuredContent']['result']
        assert data['actor']['kind']=='external_agent' and data['visible_sources']
        assert 'Public words only.' in json.dumps(data)
        assert all(secret not in json.dumps(data) for secret in (private,'prompt_messages','HIDDEN_SOURCE','legacy-reply'))
        actual=data['visible_sources'][0]['text']
        material_command=e['command']('read_material',{'tool':'read_material','material':ref.model_dump(mode='json')})
        material=client.call('read_material',{'session_id':e['sid'],'command':material_command})
        assert not material.get('isError'),material
        assert 'fact_ids' not in json.dumps(material) and material['structuredContent']['result']['fragments'][0]['text']==actual
        e['history'].responses.append(C.PublicTransactionResult.model_validate(material['structuredContent']))
        material_recovery=client.call('requests.read',{'session_id':e['sid'],'query':{'request_id':material_command['request_id']}})
        assert 'fact_ids' not in json.dumps(material_recovery)
        command=e['command']('work_products.create',{'kind':'investigation','title':'Explicit Codex MCP transport check','content':actual})
        first=client.call('work_products.create',{'session_id':e['sid'],'command':command})
        assert not first.get('isError'),first
        result=first['structuredContent'];product=result['result']['object']
        assert product['executor']['kind']=='external_agent' and product['adoption']['status']=='unadopted'
        recovered=client.call('requests.read',{'session_id':e['sid'],'query':{'request_id':command['request_id']}})
        assert recovered['structuredContent']['status']=='completed'
        test_command=e['command']('tests.create',{'query':'账号密码忘了怎么重置？','config_version':0})
        tested=client.call('tests.create',{'session_id':e['sid'],'command':test_command})
        assert not tested.get('isError'),tested
        assert tested['structuredContent']['result']['test']['execution']['executor']['kind']=='external_agent'
        e['history'].responses.append(C.PublicTransactionResult.model_validate(tested['structuredContent']))
        before=e['app'].state.v2_store.view(e['owner']).state
        replay=client.call('work_products.create',{'session_id':e['sid'],'command':command})
        assert replay['structuredContent']['replayed'] and e['app'].state.v2_store.view(e['owner']).state==before
        adopted=e['send']('work-products/'+product['product_id']+'/adoption','work_products.adopt',{'product_id':product['product_id'],'product_version':1,'expected_head':1,'status':'adopted'})
        submitted=e['send']('submissions','submit',{'decision':'defer_with_conditions','products':[adopted['result']['ref']]})
        assert submitted['executor']['kind']=='human' and submitted['state']['status']=='submitted'
        revoke=e['command']('delegations.revoke',{'delegation_id':created['delegation']['id']})
        response=e['client'].request('DELETE','/sessions/'+e['sid']+'/delegations/'+created['delegation']['id'],json=revoke)
        assert response.status_code==200,response.text
        before_revoked=e['app'].state.v2_store.view(e['owner']).state
        with pytest.raises(RuntimeError,match='codex_client_rpc_failed: 1001'):
            client.call('work_products.create',{'session_id':e['sid'],'command':command})
        assert e['app'].state.v2_store.view(e['owner']).state==before_revoked
        assert all(method!='turn/start' for method in client.calls)
        assert created['token'] not in json.dumps([inventory,observation,material,material_recovery,first,recovered,replay,tested])+''.join(client.stderr)
        if os.environ.get('W06_EVIDENCE_DIR'):
            import hashlib
            path=Path(os.environ['W06_EVIDENCE_DIR']);path.mkdir(parents=True,exist_ok=True)
            trace={'client':subprocess.check_output(['codex','--version'],text=True).strip(),
                'provider':None,'model':None,'model_turn_started':False,'ephemeral':True,
                'history_port':'test bridge of real committed public responses; c9 production port still missing',
                'scenario_package':'temporary official W02 build_seed output, not newly pinned production release',
                'package_sha256':hashlib.sha256((e['package']/'manifest.json').read_bytes()).hexdigest(),
                'calls':client.calls,'session_id':e['sid'],'observation':data,
                'material_request_id':material_command['request_id'],'material_response':material['structuredContent'],
                'product_request_id':command['request_id'],'product':product,
                'recovery_status':recovered['structuredContent']['status'],'replayed':replay['structuredContent']['replayed'],
                'test':tested['structuredContent']['result']['test'],'human_submission':{'executor':submitted['executor'],'status':submitted['state']['status']},'revocation_rpc_code':1001,'revoked_effect_unchanged':True}
            (path/'official-codex-mcp-trace.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2)+'\n')
    finally:
        if client is not None:client.close()
        server.should_exit=True;thread.join(5);sock.close()
        assert not thread.is_alive()
