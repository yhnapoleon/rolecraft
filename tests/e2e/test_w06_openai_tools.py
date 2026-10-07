"""Function adapter over real HTTP; service history remains the r3 test bridge."""
import importlib.util
import json
from pathlib import Path
import re

import pytest
from career_lab.delegations.http_client import RemoteFailure
from career_lab.mcp.protocol import Protocol, MODERN, VERSION, CAPABILITIES
from examples.byo_agent_client.service_check import ServiceCheck
from examples.byo_agent_client.workflow import save

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('w06_service_fixture', ROOT / 'tests/e2e/test_w06_service_check.py')
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
production, public_url = fixture.production, fixture.public_url
from career_lab.delegations.openai_tools import OpenAIFunctionClient, function_name



@pytest.fixture
def delegated(public_url, tmp_path):
    from datetime import datetime, timedelta, timezone
    check = ServiceCheck(public_url, tmp_path / 'owner')
    created = check.owner('POST', '/sessions', {'schema_version': 2, 'scenario': 'pm_pilot_v2'})
    check.sid, check.token = created['session_id'], created['token']
    configs = []
    def grant(capabilities=('read', 'act'), **scope):
        response = check.human('delegations.create', '/delegations', {
            'agent_label': 'Function adapter check', 'capabilities': list(capabilities),
            'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(), **scope})['result']['result']
        config = tmp_path / ('delegate-' + str(len(configs)) + '.json')
        save(config, {'api_url': public_url, 'session_id': check.sid, 'token': response['token']})
        configs.append(config)
        return OpenAIFunctionClient(config), response['delegation']['id']
    yield check, grant
    check.http.close()


@pytest.mark.parametrize('api', ['responses', 'chat_completions'])
def test_function_catalogue_matches_mcp_without_schema_changes(delegated, api):
    check, grant = delegated
    client, _ = grant()
    exported = client.tools(api=api)
    functions = [item if api == 'responses' else item['function'] for item in exported]
    raw = {t.name: t for t in client.backend.tools() if t.available}
    mcp = Protocol(client.backend).handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list',
        'params': {'_meta': {VERSION: MODERN, CAPABILITIES: {}}}})['tools']
    assert {f['name'] for f in functions} == {function_name(t['name']) for t in mcp}
    for source in raw.values():
        found = next(f for f in functions if f['name'] == function_name(source.name))
        assert re.fullmatch('[a-zA-Z0-9_-]{1,64}', found['name'])
        assert found['parameters'] == source.parameters
        assert found['strict'] is False
    # Modifying an exported descriptor never changes the authoritative schema.
    functions[0]['parameters'].clear()
    assert all(t.parameters for t in client.backend.tools())
    assert not any('delegations' in f['name'] or 'research' in f['name'] for f in functions)


def test_function_call_keeps_command_identity_executor_and_replay(delegated):
    check, grant = delegated
    client, _ = grant()
    command = check.command('work_products.create', {'kind': 'investigation', 'title': 'Source notes', 'content': 'User-requested notes'})
    arguments = {'session_id': check.sid, 'command': command}
    before = json.dumps(arguments, sort_keys=True)
    result = client.call(function_name('work_products.create'), json.dumps(arguments))
    assert json.dumps(arguments, sort_keys=True) == before
    obj = result['result']['object']
    assert obj['executor']['kind'] == 'external_agent' and obj['adoption']['status'] == 'unadopted'
    state = check.owner('GET', '/sessions/' + check.sid)
    replay = client.call(function_name('work_products.create'), arguments)
    assert replay['replayed'] and check.owner('GET', '/sessions/' + check.sid) == state
    recovered = client.call(function_name('requests.read'), {'session_id': check.sid, 'query': {'request_id': command['request_id']}})
    assert recovered['status'] == 'completed' and recovered['request_id'] == command['request_id']
    assert recovered['executor']['kind'] == 'external_agent'


def test_read_and_scoped_grants_cannot_gain_actions_from_function_names(delegated):
    check, grant = delegated
    reader, _ = grant(('read',))
    scoped, _ = grant(allowed_actions=['observation', 'tools', 'materials.list', 'requests.read'])
    command = check.command('work_products.create', {'kind': 'investigation', 'content': 'Forbidden write'})
    state = check.owner('GET', '/sessions/' + check.sid)
    for client in (reader, scoped):
        assert function_name('work_products.create') not in {f['name'] for f in client.tools()}
        with pytest.raises(RemoteFailure) as denied:
            client.call(function_name('work_products.create'), {'session_id': check.sid, 'command': command})
        assert denied.value.code in {'capability_forbidden', 'action_forbidden'}
    assert check.owner('GET', '/sessions/' + check.sid) == state


def test_revocation_invalidates_previously_exported_function_catalogue(delegated):
    check, grant = delegated
    client, identifier = grant()
    assert client.tools()
    check.human('delegations.revoke', '/delegations/' + identifier, {'delegation_id': identifier}, method='DELETE')
    with pytest.raises(RemoteFailure) as denied:
        client.call(function_name('observation'), {'session_id': check.sid})
    assert denied.value.status in {401, 403}


def test_aliases_do_not_collapse_and_malformed_calls_do_not_mutate(delegated):
    assert function_name('work.products') != function_name('work_products')
    assert len(function_name('x' * 120)) <= 64
    check, grant = delegated
    client, _ = grant()
    state = check.owner('GET', '/sessions/' + check.sid)
    for malformed in ('{', '[]', 'null', 1):
        with pytest.raises(RemoteFailure) as error:
            client.call(function_name('work_products.create'), malformed)
        assert error.value.code == 'tool_arguments_invalid'
    with pytest.raises(RemoteFailure) as error:
        client.call('unknown_function', {'session_id': check.sid})
    assert error.value.code == 'tool_unknown'
    assert check.owner('GET', '/sessions/' + check.sid) == state


def test_function_export_cli_uses_only_private_config_path(delegated):
    import subprocess
    import sys
    check, grant = delegated
    client, _ = grant()
    completed = subprocess.run([sys.executable, '-m', 'career_lab.delegations.openai_tools',
        '--config', str(client.backend.config_path), '--api', 'chat_completions'],
        cwd=ROOT, text=True, capture_output=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    tools = json.loads(completed.stdout)
    assert tools and all(item['type'] == 'function' and item['function']['strict'] is False for item in tools)
    token = json.loads(Path(client.backend.config_path).read_text())['token']
    assert token not in completed.stdout + completed.stderr
