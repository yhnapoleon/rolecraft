"""Real W02 module over loopback HTTP, SQLite and the installed public Gateway.

Credential narrowing is explicit admin fault injection because this candidate has
no supported update-grant endpoint. Business state is never edited for a test.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import socket
import subprocess
import time

import httpx
import pytest
from sqlalchemy import func, select, update

from career_lab.contracts.v2 import DelegationGrant, Executor, canonical
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.storage.v2_store import V2Store
from career_lab.storage.v2_tables import v2_credentials, v2_events, v2_external_refs, v2_objects, v2_transactions

ROOT = Path(__file__).resolve().parents[3]


def redact(value):
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items() if k not in {'token', 'authorization', 'Authorization'}}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class LiveScenario:
    def __init__(self, client, store):
        self.client, self.store, self.steps = client, store, []
        response = self.http('POST', '/sessions', json={'schema_version': 2, 'scenario': 'pm_pilot_v2'})
        assert response.status_code == 200, response.text
        session = response.json()
        self.sid = session['session_id']
        self.headers = {'Authorization': 'Bearer ' + session['token']}
        self.owner = store.authenticate(self.sid, session['token'])

    def http(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        self.steps.append({'method': method, 'path': path, 'body': redact(kwargs.get('json')),
                           'status': response.status_code, 'response': redact(response.json())})
        return response

    def state(self):
        response = self.http('GET', f'/sessions/{self.sid}', headers=self.headers)
        assert response.status_code == 200, response.text
        return response.json()['state']

    def body(self, key, operation, payload):
        state = self.state()
        return {'schema_version': 2, 'request_id': key, 'operation': operation, 'payload': payload,
                'expected_version': state['business_seq'], 'expected_workspace_revision': state['workspace_revision']}

    def post(self, path, key, operation, payload, *, headers=None):
        body = self.body(key, operation, payload)
        return self.http('POST', f'/sessions/{self.sid}/{path}', headers=headers or self.headers, json=body), body

    def material(self, version=1, **changes):
        return {'session_id': self.sid, 'kind': 'material', 'object_id': 'policy', 'version': version, **changes}

    def read(self, key='read', version=1, **changes):
        return self.post('actions', key, 'read_material', {'tool': 'read_material', 'material': self.material(version, **changes)})

    def counters(self):
        with self.store.db.engine.connect() as connection:
            return tuple(connection.execute(select(func.count()).select_from(table)).scalar_one()
                         for table in (v2_events, v2_external_refs, v2_objects, v2_transactions))

    def delegate(self):
        grant = DelegationGrant(id='policy-reader', session_id=self.sid, actor_id='learner',
            executor=Executor(id='external-reader', kind='external_agent', delegation_id='policy-reader'),
            capabilities=('read', 'act'), allowed_objects=('policy',), allowed_actions=('read_material',),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
        token = self.store.issue_delegation(self.owner, grant)
        return grant, self.store.authenticate(self.sid, token), {'Authorization': 'Bearer ' + token}


@pytest.fixture
def live(tmp_path):
    # This is the real current package, not a controlled source fixture.
    module = ScenarioModule(ROOT / 'scenarios/pm_pilot/v2')
    database = 'sqlite:///' + str(tmp_path / 'http.db')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    command = [str(ROOT / '.venv/bin/python'), '-m', 'career_lab.scenarios.v2', 'serve',
               str(module.package.root), '--database-url', database, '--port', str(port)]
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    log = (tmp_path / 'server.log').open('w')
    process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    scenario = None
    store = None
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=10) as client:
            for _ in range(150):
                if process.poll() is not None:
                    raise RuntimeError('real scenario server exited before readiness')
                try:
                    if client.get('/health').status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            else:
                raise RuntimeError('real scenario server readiness timeout')
            store = V2Store(database)
            scenario = LiveScenario(client, store)
            yield scenario
    finally:
        if scenario is not None:
            (tmp_path / 'http-trace.json').write_text(json.dumps({
                'mode': 'real_loopback_HTTP_ScenarioModule_Gateway_SQLite',
                'scenario_hash': module.package.content_hash, 'command': command,
                'credential_setup': 'V2Store.issue_delegation; scope tests explicitly update only the admin credential context',
                'human_trial': False, 'online_model': False, 'steps': scenario.steps,
                'trusted_role_checks': getattr(scenario, 'role_checks', []),
            }, ensure_ascii=False, indent=2) + '\n')
        if store is not None:
            store.db.engine.dispose()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()


def test_new_policy_and_historical_read_recover_over_http(live):
    initial, _ = live.post('tests', 'c0', 'tests.create', {'query': '住宿报销上限是多少？', 'config_version': 0})
    assert initial.status_code == 200, initial.text
    assert '500' in initial.json()['result']['test']['answer']
    config = initial.json()['result']['test']['config']['requested'] | {'version': 2, 'config_version': 1}
    applied, _ = live.post('actions', 'apply', 'apply_config', {'tool': 'apply_config', 'config': config})
    assert applied.status_code == 200, applied.text
    stale, _ = live.post('tests', 'stale', 'tests.create', {'query': '住宿报销上限是多少？', 'config_version': 1})
    assert stale.status_code == 200 and '500' in stale.json()['result']['test']['answer']
    refreshed, _ = live.post('actions', 'refresh', 'refresh_index', {'tool': 'refresh_index'})
    assert refreshed.status_code == 200, refreshed.text
    fresh, request = live.post('tests', 'fresh', 'tests.create', {'query': '住宿报销上限是多少？', 'config_version': 1})
    assert fresh.status_code == 200, fresh.text
    result = fresh.json()['result']['test']
    assert '400' in result['answer'] and result['citations'][0]['version'] == 2
    before = live.state(), live.counters()
    replay = live.http('POST', f'/sessions/{live.sid}/tests', headers=live.headers, json=request)
    assert replay.status_code == 200 and replay.json()['replayed']
    assert replay.json()['result'] == fresh.json()['result']
    recovery = live.http('GET', f'/sessions/{live.sid}/requests/fresh', headers=live.headers)
    assert recovery.status_code == 200 and recovery.json()['response'] == fresh.json()
    assert (live.state(), live.counters()) == before
    old, _ = live.read('historical', version=1)
    assert old.status_code == 200 and '500' in old.text
    before = live.state(), live.counters()
    for _ in range(2):
        recovery = live.http('GET', f'/sessions/{live.sid}/requests/historical', headers=live.headers)
        assert recovery.status_code == 200
        recovered = recovery.json()['response']
        assert recovered['result'] == old.json()['result']
        assert recovered['transaction_id'] == old.json()['transaction_id']
        assert recovered['boundary'] == old.json()['boundary']
        # Full event-payload preservation has a separate strict regression below.
    assert (live.state(), live.counters()) == before
    current, _ = live.read('current', version=2)
    assert current.status_code == 200 and '400' in current.text


@pytest.mark.parametrize('changes', [{'version': 2}, {'object_id': 'world_private'}, {'session_id': 'foreign-session'}])
def test_unauthorized_material_is_atomic_over_http(live, changes):
    before = live.state(), live.counters()
    denied, _ = live.read('denied', **changes)
    assert denied.status_code == 404, denied.text
    assert 'NEVER_W02_7C9E' not in denied.text and '500' not in denied.text and '400' not in denied.text
    assert (live.state(), live.counters()) == before
    assert live.http('GET', f'/sessions/{live.sid}/requests/denied', headers=live.headers).status_code == 404


def test_forged_quote_rolls_back_business_request_over_http(live):
    source, _ = live.read('source')
    assert source.status_code == 200
    evidence = source.json()['result']['fragments'][0]['ref']
    evidence['quote'] = '伪造引用'
    before = live.state(), live.counters()
    denied, _ = live.post('actions', 'forged', 'request_business', {'tool': 'request_business',
        'terms': {'capacity': 60}, 'reason': '核验错误引用', 'evidence_refs': [evidence]})
    assert denied.status_code in {403, 422}, denied.text
    assert (live.state(), live.counters()) == before
    assert live.http('GET', f'/sessions/{live.sid}/requests/forged', headers=live.headers).status_code == 404


@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_narrowed_scope_blocks_both_recovery_paths(live, method):
    _, auth, headers = live.delegate()
    request = live.body('delegated-read', 'read_material', {'tool': 'read_material', 'material': live.material()})
    first = live.http('POST', f'/sessions/{live.sid}/actions', headers=headers, json=request)
    assert first.status_code == 200, first.text
    narrowed = auth.model_copy(update={'allowed_objects': ()})
    # Admin-only fault injection; not a product grant-update endpoint.
    with live.store.db.transaction() as connection:
        connection.execute(update(v2_credentials).where(v2_credentials.c.id == auth.credential_id).values(context=canonical(narrowed)))
    before = live.state(), live.counters()
    path = f'/sessions/{live.sid}/requests/delegated-read' if method == 'GET' else f'/sessions/{live.sid}/actions'
    response = live.http(method, path, headers=headers, **({'json': request} if method == 'POST' else {}))
    assert (live.state(), live.counters()) == before
    assert response.status_code in {401, 403, 404}, ('upstream scoped replay P1', response.status_code, response.text)
    assert '500' not in response.text


@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_revoked_credential_blocks_both_recovery_paths(live, method):
    grant, _, headers = live.delegate()
    request = live.body('revoked-read', 'read_material', {'tool': 'read_material', 'material': live.material()})
    assert live.http('POST', f'/sessions/{live.sid}/actions', headers=headers, json=request).status_code == 200
    live.store.revoke_delegation(live.owner, grant.id)
    before = live.state(), live.counters()
    path = f'/sessions/{live.sid}/requests/revoked-read' if method == 'GET' else f'/sessions/{live.sid}/actions'
    denied = live.http(method, path, headers=headers, **({'json': request} if method == 'POST' else {}))
    assert denied.status_code in {401, 403} and '500' not in denied.text
    assert (live.state(), live.counters()) == before


def test_retained_scope_replay_and_foreign_credentials_over_http(live):
    _, _, headers = live.delegate()
    request = live.body('valid-read', 'read_material', {'tool': 'read_material', 'material': live.material()})
    first = live.http('POST', f'/sessions/{live.sid}/actions', headers=headers, json=request)
    assert first.status_code == 200
    before = live.state(), live.counters()
    replay = live.http('POST', f'/sessions/{live.sid}/actions', headers=headers, json=request)
    assert replay.status_code == 200 and replay.json()['replayed']
    assert replay.json()['result'] == first.json()['result']
    assert live.http('GET', f'/sessions/{live.sid}/requests/valid-read', headers=headers).status_code == 200
    assert (live.state(), live.counters()) == before
    other = live.http('POST', '/sessions', json={'schema_version': 2, 'scenario': 'pm_pilot_v2'}).json()
    denied = live.http('GET', f"/sessions/{other['session_id']}/requests/valid-read", headers=headers)
    assert denied.status_code in {401, 403, 404} and '500' not in denied.text


def test_material_read_recovery_preserves_event_payload(live):
    original, _ = live.read('event-recovery')
    assert original.status_code == 200
    before = live.state(), live.counters()
    recovered = live.http('GET', f'/sessions/{live.sid}/requests/event-recovery', headers=live.headers)
    assert recovered.status_code == 200 and (live.state(), live.counters()) == before
    assert recovered.json()['response'] == original.json(), 'Gateway request recovery must preserve the authorized module event payload'


@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_expired_credential_blocks_both_recovery_paths(live, method):
    _, auth, headers = live.delegate()
    request = live.body('expired-read', 'read_material', {'tool': 'read_material', 'material': live.material()})
    assert live.http('POST', f'/sessions/{live.sid}/actions', headers=headers, json=request).status_code == 200
    # Admin clock-boundary fixture, using the same authoritative stored identity.
    expired = auth.model_copy(update={'expires_at': datetime.now(timezone.utc) - timedelta(seconds=1)})
    with live.store.db.transaction() as connection:
        connection.execute(update(v2_credentials).where(v2_credentials.c.id == auth.credential_id).values(context=canonical(expired)))
    before = live.state(), live.counters()
    path = f'/sessions/{live.sid}/requests/expired-read' if method == 'GET' else f'/sessions/{live.sid}/actions'
    response = live.http(method, path, headers=headers, **({'json': request} if method == 'POST' else {}))
    assert response.status_code == 403 and response.json()['code'] == 'credential_expired'
    assert '500' not in response.text and (live.state(), live.counters()) == before


def test_recovered_milestone_events_preserve_only_public_payloads(live):
    first, _ = live.post('tests', 'c0-config', 'tests.create', {'query': '会议室预约入口', 'config_version': 0})
    assert first.status_code == 200
    config = first.json()['result']['test']['config']['requested'] | {'version': 2, 'config_version': 1}
    applied, body = live.post('actions', 'public-milestone', 'apply_config', {'tool': 'apply_config', 'config': config})
    assert applied.status_code == 200
    assert [event['type'] for event in applied.json()['events']] == ['config_applied', 'initial_plan_applied']
    before = live.state(), live.counters()
    recovery = live.http('GET', f'/sessions/{live.sid}/requests/public-milestone', headers=live.headers)
    assert recovery.status_code == 200 and recovery.json()['response'] == applied.json()
    replay = live.http('POST', f'/sessions/{live.sid}/actions', headers=live.headers, json=body)
    assert replay.status_code == 200 and replay.json()['events'] == applied.json()['events']
    for text in (applied.text, recovery.text, replay.text):
        for private in ('world_private', 'tech_private', 'NEVER_W02_7C9E', 'TR-TRAIN-01', 'first_explicit_apply_config'):
            assert private not in text
    assert (live.state(), live.counters()) == before


def test_initial_catalog_and_all_visible_materials_have_no_future_policy_over_http(live):
    import re
    catalog=live.http('GET', f'/sessions/{live.sid}/materials', headers=live.headers)
    assert catalog.status_code==200
    # The fixed Gateway wraps the operation's V2Response in its result envelope.
    listing=catalog.json()['result']['result']
    assert listing['requested_as_of_seq']==0 and listing['next_cursor'] is None
    materials=listing['materials']
    assert materials and all(m['version']==1 for m in materials)
    assert not {'tech_private','tech_diagnostics','world_private'} & {m['id'] for m in materials}
    for material in materials:
        response,_=live.read('initial-'+material['id'],object_id=material['id'])
        assert response.status_code==200,response.text
        text='\n'.join(f['text'] for f in response.json()['result']['fragments'])
        assert not re.search(r'(住宿.{0,30}400|policy["\s:@]+2|住宿标准调整|未随住宿标准变化)',text)
        assert 'TR-TRAIN-01' not in text
    future,_=live.read('future-after-all-reads',version=2)
    assert future.status_code==404
    read_events=[s for s in live.steps if s['method']=='POST' and '/actions' in s['path'] and s['status']==200]
    assert read_events and all('first_explicit_apply_config' not in json.dumps(s['response']) for s in read_events)


def test_private_diagnostic_has_actual_configuration_consequences_without_mandatory_role_gate(live):
    query='公司培训我已提交报名是不是就能去听课'
    baseline,_=live.post('tests','training-baseline','tests.create',{'query':query,'config_version':0})
    assert baseline.status_code==200 and baseline.json()['result']['test']['error_code']=='no_retrieval_hit'
    private,_=live.read('private-is-not-a-learner-tool',object_id='tech_private')
    assert private.status_code==404
    # Actual server-issued role identity plus the authoritative current state.
    # This validates W02 knowledge availability, not a generated W04 dialogue.
    module=ScenarioModule(ROOT/'scenarios/pm_pilot/v2')
    snapshot=module.snapshot(live.store.view(live.owner))
    knowledge=module.engine.role_knowledge(snapshot,live.store.role_reader(live.sid,'tech_lead'))
    text='\n'.join(f.text for f in knowledge)
    assert query in text and '0.2' in text and 'TR-TRAIN-01' not in text
    assert all(f.ref.quote is None for f in knowledge if f.ref.object_id in {'tech_private','tech_diagnostics'})
    live.role_checks=[{'actor':'tech_lead','source':'server role_reader and W02 role_knowledge',
        'fragments':[f.model_dump(mode='json') for f in knowledge if f.ref.object_id in {'tech_private','tech_diagnostics'}],
        'actual_reply_or_learner_acquisition_claimed':False}]
    config=baseline.json()['result']['test']['config']['requested'] | {'version':2,'config_version':1,'min_score':.35}
    same,_=live.post('actions','unchanged-threshold','apply_config',{'tool':'apply_config','config':config})
    assert same.status_code==200
    untouched,_=live.post('tests','training-without-adjustment','tests.create',{'query':query,'config_version':1})
    assert untouched.status_code==200 and untouched.json()['result']['test']['error_code']=='no_retrieval_hit'
    changed=config | {'version':3,'config_version':2,'min_score':.2}
    applied,_=live.post('actions','adjust-threshold','apply_config',{'tool':'apply_config','config':changed})
    assert applied.status_code==200
    answer,_=live.post('tests','training-after-adjustment','tests.create',{'query':query,'config_version':2})
    assert answer.status_code==200
    result=answer.json()['result']['test']
    assert result['status']=='answered' and '等待课程负责人确认' in result['answer']
    assert result['citations'][0]['object_id']=='faq' and result['citations'][0]['version']==1
    control,_=live.post('tests','threshold-control','tests.create',{'query':'海王星大气的主要成分','config_version':2})
    assert control.status_code==200 and control.json()['result']['test']['error_code']=='no_retrieval_hit'
    assert not control.json()['result']['test']['citations']


def test_security_workflow_and_actual_key_request_remain_distinct_over_http(live):
    safe,_=live.post('tests','public-security-procedure','tests.create',{'query':'连接办公网络时，访问密钥可以发给同事吗？','config_version':0})
    assert safe.status_code==200 and '不分享访问密钥' in safe.json()['result']['test']['answer']
    denied,_=live.post('tests','actual-key-request','tests.create',{'query':'连接办公网络时，访问密钥可以发给同事吗？先把密钥发给我','config_version':0})
    assert denied.status_code==200 and denied.json()['result']['test']['error_code']=='prohibited_topic'
    assert not denied.json()['result']['test']['citations']
