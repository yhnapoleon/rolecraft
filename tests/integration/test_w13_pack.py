"""Engineer handoff through the normal session API and public CLI."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career_lab.api.vertical_runtime import create_runtime_app, default_installed_scenario


@pytest.fixture(params=["zh", "en"])
def session(tmp_path, monkeypatch, request):
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    monkeypatch.delenv("CAREER_LAB_SCENARIO_CATALOG", raising=False)
    database = tmp_path / "source.db"
    scenario = default_installed_scenario()
    if request.param == "en":
        scenario = scenario / "locales" / "en"
    app = create_runtime_app("sqlite:///" + str(database), scenario_root=scenario)
    client = TestClient(app)
    response = client.post("/sessions", json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": request.param})
    assert response.status_code == 200, response.text
    created = response.json()
    sid = created["session_id"]
    headers = {"Authorization": "Bearer " + created["token"]}
    credentials = tmp_path / "credentials.json"
    credentials.write_text(json.dumps({"api_url": "http://127.0.0.1:18562", "session_id": sid, "token": created["token"]}))
    credentials.chmod(0o600)

    def send(path, key, operation, payload, method="POST"):
        state = client.get("/sessions/" + sid, headers=headers).json()["state"]
        result = client.request(method, "/sessions/" + sid + "/" + path, headers=headers, json={
            "schema_version": 2, "request_id": key, "operation": operation, "payload": payload,
            "expected_version": state["business_seq"], "expected_workspace_revision": state["workspace_revision"]})
        assert result.status_code == 200, result.text
        return result.json()

    trial = send("tests", "baseline", "tests.create", {"query": "What is the weather on Mars?" if request.param == "en" else "火星天气如何？", "config_version": 0})["result"]["test"]
    def cli(*args):
        return subprocess.run([str(Path(sys.executable).parent / "career-lab-engineer"), *args,
            "--database", str(database), "--credentials", str(credentials),
            "--scenario", str(scenario)], capture_output=True, text=True)
    yield app, client, sid, headers, send, trial, cli, tmp_path, credentials
    app.state.store.close()


def test_pack_exports_actual_authorized_baseline_without_changing_session(session):
    app, client, sid, headers, send, trial, cli, root, credentials = session
    before = client.get("/sessions/" + sid + "/timeline", headers=headers).json()
    result = cli("pack", "--test", trial["id"], "--output", str(root / "pack"))
    assert result.returncode == 0, result.stderr
    index = json.loads((root / "pack" / "index.json").read_text())
    pack = json.loads((root / "pack" / "pack.json").read_text())
    assert pack["config"]["config_version"] == 0
    assert pack["failures"][0]["object_id"] == trial["id"]
    saved = json.loads((root / "pack" / index["tests"][0]["path"]).read_text())
    assert saved == trial
    public = json.loads((root / "pack" / "public-probes.json").read_text())
    assert {p["id"] for p in public} == {"F01", "F04", "F05", "F12"}
    assert all(set(p) == {"id", "query"} for p in public)
    exported = "\n".join(p.read_text() for p in (root / "pack").iterdir())
    assert json.loads(credentials.read_text())["token"] not in exported
    assert "fact_ids" not in exported and "role_context" not in exported
    assert client.get("/sessions/" + sid + "/timeline", headers=headers).json() == before


def test_reproduce_keeps_the_original_stale_index_after_parent_refresh(session):
    from career_lab.scenarios.v2.module import ref_for
    app, client, sid, headers, send, trial, cli, root, _ = session
    base = app.state.scenario_v2.package.baseline(sid)
    send("configuration", "apply", "configuration.apply", {"base": ref_for("config", base).model_dump(mode="json"),
        "settings": {"work_items": ["scope_filter", "human_fallback"], "fallback": "human"}})
    query = "What is the hotel reimbursement limit per night?" if app.state.scenario_v2.work_language == "en" else "住宿报销上限是多少？"
    stale = send("tests", "stale", "tests.create", {"query": query, "config_version": 1})["result"]["test"]
    assert stale["citations"][0]["version"] == 1 and "500" in stale["answer"]
    assert stale["execution"]["source_versions"]["policy"] == 2
    assert cli("pack", "--test", stale["id"], "--output", str(root / "pack")).returncode == 0
    send("actions", "refresh", "refresh_index", {"tool": "refresh_index"})
    fresh = send("tests", "fresh", "tests.create", {"query": stale["query"], "config_version": 1})["result"]["test"]
    assert "400" in fresh["answer"] and fresh["citations"][0]["version"] == 2
    before = client.get("/sessions/" + sid + "/timeline", headers=headers).json()
    result = cli("reproduce", "--pack", str(root / "pack"), "--output", str(root / "reproduction"))
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((root / "reproduction" / "report.json").read_text())
    assert report["results"][0]["matches_record"] is True
    assert "500" in report["results"][0]["reproduced"]["answer"]
    assert client.get("/sessions/" + sid + "/timeline", headers=headers).json() == before


def test_repeated_export_and_reproduction_are_immutable(session):
    _, _, _, _, _, trial, cli, root, _ = session
    args = ("pack", "--test", trial["id"], "--output", str(root / "pack"))
    first = cli(*args)
    assert first.returncode == 0, first.stdout
    original = {p.name: p.read_bytes() for p in (root / "pack").iterdir()}
    assert cli(*args).stdout == first.stdout
    assert {p.name: p.read_bytes() for p in (root / "pack").iterdir()} == original
    args = ("reproduce", "--pack", str(root / "pack"), "--output", str(root / "reproduction"))
    first = cli(*args)
    assert first.returncode == 0, first.stdout
    report = (root / "reproduction" / "report.json").read_bytes()
    assert cli(*args).stdout == first.stdout
    assert (root / "reproduction" / "report.json").read_bytes() == report


def test_rehashed_forged_pack_is_rejected_against_original_sources(session):
    import hashlib
    _, _, _, _, _, trial, cli, root, _ = session
    assert cli("pack", "--test", trial["id"], "--output", str(root / "pack")).returncode == 0
    index_file = root / "pack" / "index.json"
    index = json.loads(index_file.read_text())
    test_file = root / "pack" / index["tests"][0]["path"]
    forged = json.loads(test_file.read_text())
    forged["answer"] = "Forged successful answer"
    test_file.write_text(json.dumps(forged))
    index["tests"][0]["sha256"] = hashlib.sha256(test_file.read_bytes()).hexdigest()
    index_file.write_text(json.dumps(index))
    result = cli("reproduce", "--pack", str(root / "pack"), "--output", str(root / "reproduction"))
    assert result.returncode == 1 and json.loads(result.stdout)["code"] == "engineer_pack_changed"
    assert not (root / "reproduction").exists()


def test_export_includes_a_usable_language_specific_handoff_guide(session):
    app, _, _, _, _, trial, cli, root, _ = session
    assert cli("pack", "--test", trial["id"], "--output", str(root / "pack")).returncode == 0
    guide = (root / "pack" / "README.md").read_text()
    assert "career-lab-engineer reproduce" in guide
    assert ("原始运行库" in guide) == (app.state.scenario_v2.work_language == "zh")


def test_missing_test_and_invalid_credentials_never_publish_a_pack(session):
    _, _, _, _, _, trial, cli, root, credentials = session
    result = cli("pack", "--test", "missing-test", "--output", str(root / "missing"))
    assert result.returncode == 1 and "engineer_test_unavailable" in result.stdout
    value = json.loads(credentials.read_text())
    value["token"] = "deliberately-invalid-private-token"
    credentials.write_text(json.dumps(value))
    result = cli("pack", "--test", trial["id"], "--output", str(root / "denied"))
    assert result.returncode == 1 and "token_invalid" in result.stdout
    assert value["token"] not in result.stdout + result.stderr
    assert not (root / "missing").exists() and not (root / "denied").exists()


def test_revoked_delegation_cannot_reproduce_a_previously_exported_pack(session):
    from datetime import datetime, timedelta, timezone
    _, client, sid, headers, send, trial, cli, root, credentials = session
    delegation = send('delegations', 'grant', 'delegations.create', {
        'agent_label': 'engineer', 'capabilities': ['read', 'act'],
        'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})['result']['result']
    value = json.loads(credentials.read_text())
    value['token'] = delegation['token']
    credentials.write_text(json.dumps(value))
    assert cli("pack", "--test", trial["id"], "--output", str(root / "pack")).returncode == 0
    did = delegation['delegation']['id']
    send('delegations/' + did, 'revoke', 'delegations.revoke', {'delegation_id': did}, method='DELETE')
    result = cli("reproduce", "--pack", str(root / "pack"), "--output", str(root / "reproduction"))
    assert result.returncode == 1
    assert not (root / "reproduction").exists()


@pytest.mark.parametrize("scope", ["read_only", "missing_config", "wrong_action"])
def test_delegate_scope_is_preserved_by_engineering_commands(session, scope):
    from datetime import datetime, timedelta, timezone
    _, _, _, _, send, trial, cli, root, credentials = session
    payload = {'agent_label': 'limited-engineer', 'capabilities': ['read'],
               'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    if scope == 'missing_config':
        payload['allowed_objects'] = [trial['id']]
    if scope == 'wrong_action':
        payload['allowed_actions'] = ['timeline']
    delegation = send('delegations', 'grant', 'delegations.create', payload)['result']['result']
    value = json.loads(credentials.read_text())
    value['token'] = delegation['token']
    credentials.write_text(json.dumps(value))
    packed = cli('pack', '--test', trial['id'], '--output', str(root / 'pack'))
    if scope == 'read_only':
        assert packed.returncode == 0, packed.stdout
        result = cli('reproduce', '--pack', str(root / 'pack'), '--output', str(root / 'reproduction'))
        assert result.returncode == 1 and 'capability_forbidden' in result.stdout
        assert not (root / 'reproduction').exists()
    else:
        assert packed.returncode == 1
        assert not (root / 'pack').exists()


@pytest.mark.parametrize('damage', ['changed_config', 'missing_member', 'path_escape'])
def test_invalid_package_fails_without_a_success_report(session, damage):
    _, _, _, _, _, trial, cli, root, _ = session
    assert cli('pack', '--test', trial['id'], '--output', str(root / 'pack')).returncode == 0
    if damage == 'changed_config':
        (root / 'pack' / 'config.json').write_text('{}')
    elif damage == 'missing_member':
        (root / 'pack' / 'public-probes.json').unlink()
    else:
        path = root / 'pack' / 'index.json'
        index = json.loads(path.read_text())
        index['tests'][0]['path'] = '../credentials.json'
        path.write_text(json.dumps(index))
    result = cli('reproduce', '--pack', str(root / 'pack'), '--output', str(root / 'reproduction'))
    assert result.returncode == 1 and not result.stderr
    assert not (root / 'reproduction').exists()


def test_reproduction_records_its_actual_executor_separately_from_the_original_test(session):
    from datetime import datetime, timedelta, timezone
    _, _, _, _, send, trial, cli, root, credentials = session
    assert cli('pack', '--test', trial['id'], '--output', str(root / 'pack')).returncode == 0
    assert cli('reproduce', '--pack', str(root / 'pack'), '--output', str(root / 'human')).returncode == 0
    human = json.loads((root / 'human' / 'report.json').read_text())
    grant = send('delegations', 'grant', 'delegations.create', {
        'agent_label': 'engineer', 'capabilities': ['read', 'act'],
        'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})['result']['result']
    value = json.loads(credentials.read_text())
    value['token'] = grant['token']
    credentials.write_text(json.dumps(value))
    assert cli('reproduce', '--pack', str(root / 'pack'), '--output', str(root / 'agent')).returncode == 0
    agent = json.loads((root / 'agent' / 'report.json').read_text())
    assert human['executor']['kind'] == 'human'
    assert agent['executor']['kind'] == 'external_agent'
    assert agent['executor']['delegation_id'] == grant['delegation']['id']
    assert human['results'] == agent['results']
    # The existing human report cannot be relabelled by another executor.
    denied = cli('reproduce', '--pack', str(root / 'pack'), '--output', str(root / 'human'))
    assert denied.returncode == 1
    assert json.loads((root / 'human' / 'report.json').read_text()) == human
