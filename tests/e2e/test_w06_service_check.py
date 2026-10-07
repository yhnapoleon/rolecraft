"""Public-only check consumer; this fixture's service history is still a test bridge.

Only a run against a separately pinned standard service can close production
mount acceptance. The executable itself contains no store/scenario/test imports.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import threading
import time

import pytest
import uvicorn
from career_lab.contracts import v2 as C
from examples.byo_agent_client.service_check import ServiceCheck, recover_requests, revoke_run

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location('w06_bridge_fixture', ROOT / 'tests/integration/test_w06_production.py')
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
production = base.production


def evidence(name, trace, recovery):
    if not os.environ.get('W06_EVIDENCE_DIR'): return
    target = Path(os.environ['W06_EVIDENCE_DIR'])
    target.mkdir(parents=True, exist_ok=True)
    value = {'service_origin': 'temporary W02 build_seed with exact r3 modules; not standard production service',
             'service_history': 'test bridge captures actual committed public HTTP responses',
             'trace': trace, 'recovery': recovery}
    (target / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


@pytest.fixture
def public_url(production):
    e = production
    # Persisted public responses are captured only in this fixture. No callback,
    # history list or application object is given to the client under test.
    async def capture(scope, receive, send):
        status, chunks = None, []
        async def forward(message):
            nonlocal status
            if message['type'] == 'http.response.start': status = message['status']
            if message['type'] == 'http.response.body' and scope.get('method') == 'POST' and status == 200:
                chunks.append(message.get('body', b''))
                if not message.get('more_body'):
                    value = json.loads(b''.join(chunks))
                    if 'boundary' in value:
                        e['history'].responses.append(C.PublicTransactionResult.model_validate(value))
            await send(message)
        await e['app'](scope, receive, forward)
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); sock.listen(32)
    server = uvicorn.Server(uvicorn.Config(capture, log_level='critical', access_log=False, lifespan='off'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True); thread.start()
    end = time.monotonic() + 5
    while not server.started and time.monotonic() < end: time.sleep(.01)
    assert server.started
    try: yield f'http://127.0.0.1:{sock.getsockname()[1]}'
    finally:
        server.should_exit = True; thread.join(5); sock.close()
        assert not thread.is_alive()


@pytest.mark.parametrize('transport', ['http', 'codex'])
def test_w06_public_client_acquires_returns_recovers_and_revokes(public_url, tmp_path, transport):
    if transport == 'codex' and shutil.which('codex') is None:
        pytest.skip('Official Codex executable not installed')
    target = tmp_path / transport
    check = ServiceCheck(public_url, target, transport=transport)
    result = check.run(scenario='pm_pilot_v2', query='账号密码忘了怎么重置？', config_version=0, material_id='brief')
    assert result['status'] == 'completed'
    assert not result['client_uses_history_bridge'] and result['service_history_source'] == 'unverified_by_client'
    trace = json.loads((target / 'trace.json').read_text())
    assert trace['initial_observation']['read_versions'] == []
    assert trace['acquired_observation']['read_versions']
    assert trace['revocation_denied'] and trace['revocation_http_status'] in {401, 403}
    assert trace['product_replay']['replayed']
    steps = [s for s in trace['steps'] if s['executor'] == 'external_agent']
    assert [s['operation'] for s in steps] == ['read_material', 'work_products.create', 'tests.create']
    assert all(s['status'] == 'completed' and s['recovered']['request_id'] == s['command']['request_id'] for s in steps)
    for file in ('owner.json', 'delegate.json'):
        credential = json.loads((target / file).read_text())
        assert credential['token'] not in json.dumps(result) + json.dumps(trace)
        assert (target / file).stat().st_mode & 0o077 == 0
    if transport == 'codex': assert 'turn/start' not in trace['codex_protocol_calls']
    original = (target / 'trace.json').read_bytes()
    recovery = recover_requests(target)
    assert not recovery['commands_reexecuted']
    assert all(r['status'] == 'completed' for r in recovery['requests'])
    assert len(recovery['requests']) == 3
    assert (target / 'trace.json').read_bytes() == original
    evidence(transport + '-public-client', trace, recovery)
    with pytest.raises(FileExistsError): ServiceCheck(public_url, target)


def test_w06_public_client_failure_keeps_original_request_and_does_not_submit(public_url, tmp_path):
    target = tmp_path / 'incomplete'
    check = ServiceCheck(public_url, target)
    from career_lab.delegations.http_client import RemoteFailure
    with pytest.raises(RemoteFailure):
        check.run(scenario='pm_pilot_v2', query='账号密码忘了怎么重置？', config_version=999, material_id='brief')
    trace = json.loads((target / 'trace.json').read_text())
    assert trace['status'] == 'incomplete'
    assert trace['steps'][-1]['operation'] == 'tests.create'
    assert trace['steps'][-1]['status'] == 'unconfirmed'
    assert trace['steps'][-1]['command']['request_id']
    assert not any(s['operation'] in {'submit', 'work_products.adopt'} for s in trace['steps'])
    assert all(secret not in json.dumps(trace) for secret in check.secrets)

    original = (target / 'trace.json').read_bytes()
    recovery = recover_requests(target)
    assert recovery['requests'][-1]['status'] == 'not_found_or_not_visible'
    assert not recovery['commands_reexecuted']
    assert (target / 'trace.json').read_bytes() == original
    evidence('incomplete-public-client', trace, recovery)


def interrupted_check(public_url, tmp_path):
    from career_lab.delegations.http_client import RemoteFailure
    target = tmp_path / 'interrupted'
    check = ServiceCheck(public_url, target)
    with pytest.raises(RemoteFailure):
        check.run(scenario='pm_pilot_v2', query='账号密码忘了怎么重置？', config_version=999, material_id='brief')
    return target, check


def test_w06_explicit_revoke_after_failure_preserves_work_and_recovery(public_url, tmp_path, monkeypatch):
    import httpx
    target, check = interrupted_check(public_url, tmp_path)
    original = (target / 'trace.json').read_bytes()
    trace = json.loads(original)
    product = next(step['response']['result']['ref'] for step in trace['steps'] if step['operation'] == 'work_products.create')
    with httpx.Client(base_url=public_url, headers={'Authorization': 'Bearer ' + check.token}) as http:
        before = http.get('/sessions/' + check.sid).json()
        report = revoke_run(target)
        assert report['status'] == 'completed' and report['revocation_acknowledged'] and report['delegate_denied']
        assert http.get('/sessions/' + check.sid).json() == before
        products = http.get('/sessions/' + check.sid + '/work-products').json()
        assert product['object_id'] in json.dumps(products)
    assert (target / 'trace.json').read_bytes() == original
    assert all(secret not in json.dumps(report) for secret in check.secrets)
    assert (target / 'revocation.json').stat().st_mode & 0o077 == 0
    recovery = recover_requests(target)
    assert recovery['requests'][0]['status'] == recovery['requests'][1]['status'] == 'completed'
    assert recovery['requests'][-1]['status'] == 'not_found_or_not_visible'
    # Re-reading an already confirmed local revocation never sends a command.
    def unexpected(*args, **kwargs): raise AssertionError('unexpected HTTP request')
    monkeypatch.setattr(httpx.Client, 'request', unexpected)
    assert revoke_run(target) == report
    evidence('explicit-revoke-after-failure', trace, {'revocation': report, 'recovery': recovery})


def test_w06_lost_revoke_response_requires_explicit_retry_with_original_key(public_url, tmp_path, monkeypatch):
    import httpx
    target, check = interrupted_check(public_url, tmp_path)
    original = (target / 'trace.json').read_bytes()
    request = httpx.Client.request
    sent = []
    def lose_first(self, method, url, **kwargs):
        response = request(self, method, url, **kwargs)
        if method == 'DELETE':
            sent.append(kwargs['json'])
            if len(sent) == 1:
                raise httpx.ReadError('response lost after committed revocation')
        return response
    monkeypatch.setattr(httpx.Client, 'request', lose_first)
    with pytest.raises(httpx.ReadError): revoke_run(target)
    first = json.loads((target / 'revocation.json').read_text())
    assert first['status'] == 'incomplete' and len(sent) == 1
    assert first['command']['request_id']
    second = revoke_run(target)  # A separate, explicit invocation, no automatic retry.
    assert second['status'] == 'completed' and len(sent) == 2
    assert sent[0] == sent[1] == first['command'] == second['command']
    assert (target / 'trace.json').read_bytes() == original
    assert not second['business_commands_reexecuted']
    evidence('explicit-revoke-lost-response', json.loads(original), {'revocation': second})


def test_w06_revoke_rejects_mixed_run_credentials_before_network(public_url, tmp_path, monkeypatch):
    import httpx
    from career_lab.delegations.http_client import RemoteFailure
    from examples.byo_agent_client.workflow import save
    target, check = interrupted_check(public_url, tmp_path)
    credentials = json.loads((target / 'owner.json').read_text())
    save(target / 'owner.json', {**credentials, 'session_id': 'another-session'})
    def unexpected(*args, **kwargs): raise AssertionError('unexpected HTTP request')
    monkeypatch.setattr(httpx.Client, 'request', unexpected)
    with pytest.raises(RemoteFailure) as error: revoke_run(target)
    assert error.value.code == 'recovery_session_mismatch'
    assert not (target / 'revocation.json').exists()


def test_w06_acknowledged_revoke_only_rechecks_denial_after_read_failure(public_url, tmp_path, monkeypatch):
    import httpx
    target, check = interrupted_check(public_url, tmp_path)
    request = httpx.Client.request
    calls = {'deletes': 0, 'verification': 0}
    def lose_verification(self, method, url, **kwargs):
        if method == 'DELETE': calls['deletes'] += 1
        if method == 'GET' and kwargs.get('headers', {}).get('Authorization') == 'Bearer ' + check.delegate_token:
            calls['verification'] += 1
            if calls['verification'] == 1: raise httpx.ReadError('verification unavailable')
        return request(self, method, url, **kwargs)
    monkeypatch.setattr(httpx.Client, 'request', lose_verification)
    with pytest.raises(httpx.ReadError): revoke_run(target)
    first = json.loads((target / 'revocation.json').read_text())
    assert first['status'] == 'incomplete' and first['attempts'][0]['status'] == 'acknowledged'
    final = revoke_run(target)
    assert final['status'] == 'completed' and 'failure_code' not in final
    assert calls == {'deletes': 1, 'verification': 2}
    assert final['command'] == first['command']
    evidence('explicit-revoke-verification-recovery', json.loads((target / 'trace.json').read_text()), {'revocation': final})
