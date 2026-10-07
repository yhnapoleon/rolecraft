"""New installed bundles through the unmodified standard CLI/API/worker.

No custom registry, fact provider, history capture, or feedback handler. This is
real loopback service evidence, separately from normal v4 interaction evidence.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import pytest

from career_lab.contracts import v2 as C

ROOT = Path(__file__).resolve().parents[3]


def exercise_standard(scenario, language, tmp_path, *, revise):
    evidence = Path(os.environ.get('W02_STANDARD_EVIDENCE_DIR', str(tmp_path))) / (scenario + '-' + language)
    evidence.mkdir(parents=True, exist_ok=False)
    scene = ROOT / 'scenarios/pm_pilot/v2/installed/rubric-v2-a577-2.9.5' / scenario
    if language == 'en': scene = scene / 'locales/en'
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
    env.update(CAREER_LAB_SCENARIO_V2=str(scene), PYTHONDONTWRITEBYTECODE='1')
    db = 'sqlite:///' + str(evidence / 'standard.db')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    base = [sys.executable, '-m', 'career_lab.cli']
    with (evidence / 'api.log').open('w') as log:
        process = subprocess.Popen(base + ['serve', '--database-url', db, '--provider', 'local', '--port', str(port)],
                                   cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=20, trust_env=False) as client:
                for _ in range(100):
                    assert process.poll() is None, 'standard server exited'
                    try:
                        if client.get('/health').status_code == 200: break
                    except httpx.ConnectError: pass
                    time.sleep(.05)
                else: pytest.fail('standard server startup timeout')
                created = client.post('/sessions', json={'schema_version': 2, 'scenario': 'pm_pilot_v2', 'work_language': language})
                assert created.status_code == 200, created.text
                session = created.json(); sid = session['session_id']; prefix = '/sessions/' + sid
                client.headers['Authorization'] = 'Bearer ' + session['token']
                trace = {'session_id': sid, 'binding': session['binding'], 'steps': [],
                         'standard_cli_factory': True, 'normal_v4_verified': False, 'model_turn_started': False}
                assert session['binding']['workLanguage'] == language

                def get(path):
                    response = client.get(prefix + path); assert response.status_code == 200, response.text
                    return response.json()

                def command(path, operation, payload):
                    state = get('')['state']
                    body = {'schema_version': 2, 'request_id': uuid4().hex, 'operation': operation, 'payload': payload,
                            'expected_version': state['business_seq'], 'expected_workspace_revision': state['workspace_revision']}
                    response = client.post(prefix + path, json=body)
                    assert response.status_code == 200, response.text
                    value = response.json(); trace['steps'].append({'operation': operation, 'request_id': body['request_id'], 'response': value})
                    return value

                def workbench(): return get('/workbench')['result']['result']
                def config(): return workbench()['timeline']['workspace']['config']
                def config_ref():
                    value = config()
                    return {'session_id': sid, 'kind': 'config', 'object_id': value['id'],
                            'version': value['version'], 'config_version': value['config_version']}
                def test():
                    question = '住宿报销上限是多少？' if language == 'zh' else 'What is the hotel reimbursement limit per night?'
                    return command('/tests', 'tests.create', {'query': question, 'config_version': config()['config_version']})['result']['test']
                def feedback(subject):
                    with (evidence / 'worker.log').open('a') as worker_log:
                        result = subprocess.run(base + ['worker', '--once', '--database-url', db, '--provider', 'local'],
                                                cwd=ROOT, env=env, stdout=worker_log, stderr=subprocess.STDOUT, timeout=180)
                    assert result.returncode == 0
                    rows = get('/feedback/' + subject['object_id'])['result']['result']['items']
                    assert len(rows) == 1, rows
                    report = C.FeedbackV2.model_validate(rows[0])
                    assert len(report.items) == len(report.rule_items) == 14
                    return report

                initial = test(); assert '500' in initial['answer']
                before = config(); current_ref = {k: before[k] for k in ('version', 'config_version')}
                current_ref.update(session_id=sid, kind='config', object_id=before['id'])
                resources = workbench()['timeline']['workspace']['resources']
                command('/configuration', 'configuration.apply', {'base': current_ref,
                    'settings': {'participants': min(20, resources['capacity']), 'launch_day': resources['deadline_day'], 'freshness_guard': 'warn'}})
                stale = test(); assert '500' in stale['answer']
                command('/actions', 'refresh_index', {'tool': 'refresh_index'})
                fresh = test(); assert '400' in fresh['answer']
                refs = []
                for text in (['范围仍需核实；已按实际额度调整。', '已刷新政策并复测；其余假设保留待查。'] if language == 'zh'
                             else ['Scope needs further checking; adjusted to actual allocation.', 'Policy refreshed and retested; other assumptions remain open.']):
                    refs.append(command('/work-products', 'work_products.create', {'kind': 'text', 'purpose': 'plan', 'title': text, 'content': text})['result']['ref'])
                submitted = command('/submissions', 'submissions.create', {'decision': 'launch_narrow', 'products': refs, 'config': config_ref()})['result']['submission']
                report = feedback(submitted); original_hash = C.digest(report)
                labels = {item.criterion: item.label for item in report.rule_items}
                assert labels['R4.staleness_test'] == labels['R5.adjustment'] == 'MET', labels
                if not revise:
                    trace.update(initial=initial, stale=stale, fresh=fresh, feedback=report.model_dump(mode='json'),
                                 revision_verified=False, source='standard CLI / loopback HTTP / SQLite / separate standard worker')
                    (evidence / 'result.json').write_text(json.dumps(trace, ensure_ascii=False, indent=2) + '\n')
                    return
                command('/revision-cycles', 'begin_revision', {'parent_submission': submitted, 'reason': 'Reconsider remaining evidence.'})
                revised = command('/submissions', 'submissions.create', {'decision': 'defer_with_conditions', 'products': refs, 'config': config_ref()})['result']['submission']
                revised_report = feedback(revised)
                assert all(item.label == 'NOT_APPLICABLE' for item in revised_report.rule_items
                           if item.criterion in {'R3.capacity', 'R3.resources', 'R4.staleness_test', 'R5.adjustment'})
                assert C.digest(C.FeedbackV2.model_validate(get('/feedback/' + submitted['object_id'])['result']['result']['items'][0])) == original_hash
                trace.update(initial=initial, stale=stale, fresh=fresh, feedback=report.model_dump(mode='json'),
                             revised_feedback=revised_report.model_dump(mode='json'), original_feedback_sha256=original_hash,
                             source='standard CLI / loopback HTTP / SQLite / separate standard worker')
                (evidence / 'result.json').write_text(json.dumps(trace, ensure_ascii=False, indent=2) + '\n')
        finally:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)


@pytest.mark.parametrize('scenario', ['pm_pilot', 'pm_pilot_urgent', 'pm_pilot_capacity15'])
@pytest.mark.parametrize('language', ['zh', 'en'])
def test_standard_installed_language_policy_feedback(scenario, language, tmp_path):
    exercise_standard(scenario, language, tmp_path, revise=False)


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_standard_revision_preserves_original(language, tmp_path):
    exercise_standard('pm_pilot', language, tmp_path, revise=True)
