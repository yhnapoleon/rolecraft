"""Restore historical r1-shaped data into a fresh standard runtime.

Only the legacy data fixture is synthetic. HTTP, public history, authorization,
object projection and official Codex MCP are the unchanged standard assembly.
"""
import importlib.util
import json
import os
from pathlib import Path
import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from career_lab.contracts import v2 as C
from career_lab.runtime.roles_v2 import record_reply_display
from examples.byo_agent_client.codex_client import CodexMcpClient
from examples.byo_agent_client.workflow import save


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ['W06_STANDARD_SOURCE']) if os.environ.get('W06_STANDARD_SOURCE') else None
pytestmark = pytest.mark.skipif(SOURCE is None, reason='requires exact independently pinned standard runtime source')


def test_standard_legacy_role_privacy_current_source_and_mcp(tmp_path):
    from career_lab.api.vertical_runtime import create_runtime_app
    import career_lab.api.vertical_runtime as runtime
    assert Path(runtime.__file__).resolve().is_relative_to(SOURCE)
    spec = importlib.util.spec_from_file_location('w06_legacy_fixture_only', ROOT / 'tests/e2e/test_w06_stdio.py')
    fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
    app = create_runtime_app('sqlite:///' + str(tmp_path / 'legacy.db'), provider='local',
        scenario_root=SOURCE / 'scenarios/pm_pilot/v2/installed/rubric-v2-a577-2.9.5/pm_pilot')
    with TestClient(app) as client:
        created = client.post('/sessions', json={'schema_version': 2, 'scenario': 'pm_pilot_v2', 'work_language': 'zh'}).json()
        sid, token = created['session_id'], created['token']; client.headers['Authorization'] = 'Bearer ' + token
        store = app.state.v2_store; owner = store.authenticate(sid, token)
        env = {'app': app, 'client': client, 'sid': sid, 'owner': owner, 'token': token}
        safe, old = fixture.seed_role_history(env)
        display = store.execute(owner, C.Command.model_validate(fixture.fixture.command(env, 'turns.display', {'ref': safe.model_dump(mode='json')})), record_reply_display).objects[0]
        modes = [('human', token)]
        readonly, _ = fixture.fixture.grant(env, ('read',)); modes.append(('read', readonly['token']))
        scoped, _ = fixture.fixture.grant(env, ('read', 'act'), allowed_objects=('safe-turn', safe.object_id, display.object_id))
        modes.append(('restricted_act', scoped['token']))
        results = []
        for who, secret in modes:
            for path in ('/observation?since_seq=0&limit=1', '/observation?since_seq=1&limit=1', '/tools',
                         '/objects/role_reply/legacy-reply/1', '/requests/legacy-request'):
                response = client.get('/sessions/' + sid + path, headers={'Authorization': 'Bearer ' + secret})
                assert response.status_code in (200, 404), (path, response.status_code, response.text)
                if path.startswith('/observation'):
                    assert response.status_code == 200
                    assert any(f['text'] == 'Public words only.' for f in response.json()['result']['visible_sources'])
                for forbidden in (fixture.fixture.PRIVATE, 'prompt_messages', 'HIDDEN_SOURCE', 'context_hash'):
                    assert forbidden not in response.text
                results.append({'actor': who, 'path': path, 'status': response.status_code})
        # Correct role/research private reads retain the restored historical data.
        assert fixture.fixture.PRIVATE in store.read(store.role_reader(sid, 'tech_lead'), old).model_dump_json()
        assert fixture.fixture.PRIVATE in store.read(store.research_context(sid), old).model_dump_json()
        sock = socket.socket(); sock.bind(('127.0.0.1', 0)); sock.listen(32)
        server = uvicorn.Server(uvicorn.Config(app, log_level='critical', access_log=False, lifespan='off'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True); thread.start()
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline: time.sleep(.01)
        assert server.started
        cfg = tmp_path / 'delegate.json'; save(cfg, {'api_url': f'http://127.0.0.1:{sock.getsockname()[1]}', 'session_id': sid, 'token': readonly['token']})
        mcp = None
        try:
            mcp = CodexMcpClient(cfg, cwd=ROOT)
            for name, query in [('observation', {'since_seq': 0, 'limit': 1}), ('requests.read', {'request_id': 'legacy-request'})]:
                response = mcp.call(name, {'session_id': sid, 'query': query})
                raw = json.dumps(response)
                for forbidden in (fixture.fixture.PRIVATE, 'prompt_messages', 'HIDDEN_SOURCE', 'context_hash', readonly['token']): assert forbidden not in raw
                assert response.get('structuredContent', {}).get('status') != 503
            assert 'turn/start' not in mcp.calls
        finally:
            if mcp: mcp.close()
            server.should_exit = True; thread.join(5); sock.close()
        evidence = {'source': str(SOURCE), 'standard_factory': True, 'history_bridge': False,
                    'historical_data_fixture': 'r1-shaped legacy metadata restored into fresh DB; not a newly generated production reply',
                    'http_checks': results, 'mcp_protocol_only': True, 'private_legacy_retained_for_role_and_research': True,
                    'normal_v4_verified': False, 'model_quality_verified': False}
        destination = Path(os.environ.get('W06_LEGACY_EVIDENCE', str(tmp_path / 'legacy-evidence.json')))
        destination.write_text(json.dumps(evidence, indent=2) + '\n')
    app.state.store.close(); app.state.v2_store.db.engine.dispose()


def test_standard_queue_expiry_revocation_and_atomic_limit(tmp_path):
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4
    from career_lab.api.vertical_runtime import create_runtime_app
    from career_lab.jobs.worker import Worker
    app = create_runtime_app('sqlite:///' + str(tmp_path / 'queue.db'), provider='local',
        scenario_root=SOURCE / 'scenarios/pm_pilot/v2/installed/rubric-v2-a577-2.9.5/pm_pilot')
    records = []
    with TestClient(app) as client:
        created = client.post('/sessions', json={'schema_version': 2, 'scenario': 'pm_pilot_v2', 'work_language': 'zh'}).json()
        sid, token = created['session_id'], created['token']; prefix = '/sessions/' + sid
        client.headers['Authorization'] = 'Bearer ' + token
        def command(operation, payload):
            state = client.get(prefix).json()['state']
            return {'schema_version': 2, 'request_id': uuid4().hex, 'operation': operation, 'payload': payload,
                    'expected_version': state['business_seq'], 'expected_workspace_revision': state['workspace_revision']}
        def grant(seconds):
            value = client.post(prefix + '/delegations', json=command('delegations.create', {
                'agent_label': 'queue-boundary', 'capabilities': ['read', 'act'],
                'expires_at': (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()}))
            assert value.status_code == 200
            return value.json()['result']['result']
        def enqueue(delegate):
            body = command('turns.create', {'role_id': 'tech_lead', 'text': '请说明当前系统限制。'})
            result = client.post(prefix + '/turns', json=body, headers={'Authorization': 'Bearer ' + delegate['token']})
            return body, result
        worker = Worker(app.state.jobs, app.state.handlers)
        expiring = grant(3); origin, result = enqueue(expiring); assert result.status_code == 200
        time.sleep(3.1)
        assert worker.run_once()
        recovered = client.get(prefix + '/requests/' + origin['request_id']).json()
        assert recovered['jobs'] and all(j['status'] == 'failed' and j['error_code'] == 'credential_expired' for j in recovered['jobs'])
        records.append({'case': 'expired-before-worker', 'request_id': origin['request_id'], 'jobs': recovered['jobs']})
        live = grant(120); accepted = []
        for _ in range(2):
            body, result = enqueue(live); assert result.status_code == 200; accepted.append(body)
        refused, result = enqueue(live)
        assert result.status_code == 429 and result.json()['code'] == 'delegation_job_limit_reached'
        records.append({'case': 'third-job-denied', 'http_status': result.status_code, 'code': result.json()['code'], 'request_id': refused['request_id']})
        revoke = client.request('DELETE', prefix + '/delegations/' + live['delegation']['id'],
            json=command('delegations.revoke', {'delegation_id': live['delegation']['id']}))
        assert revoke.status_code == 200
        for _ in accepted: assert worker.run_once()
        for body in accepted:
            recovered = client.get(prefix + '/requests/' + body['request_id']).json()
            assert recovered['jobs'] and all(j['status'] == 'failed' and j['error_code'] == 'credential_revoked_or_invalid' for j in recovered['jobs'])
            records.append({'case': 'revoked-before-worker', 'request_id': body['request_id'], 'jobs': recovered['jobs']})
        timeline = client.get(prefix + '/timeline').json()['result']['result']
        assert not [r for r in timeline['objects'] if r['ref']['kind'] == 'role_reply']
        assert not worker.run_once()
        dest = Path(os.environ.get('W06_QUEUE_EVIDENCE', str(tmp_path / 'queue-evidence.json')))
        dest.write_text(json.dumps({'standard_factory': True, 'custom_handlers': False, 'cases': records,
            'role_reply_count': 0, 'real_model_calls': 0, 'provider': 'local', 'normal_v4_verified': False,
            'mcp_queue_operations': 'remain unavailable until explicit standard adapter activation'}, indent=2) + '\n')
    app.state.store.close(); app.state.v2_store.db.engine.dispose()
