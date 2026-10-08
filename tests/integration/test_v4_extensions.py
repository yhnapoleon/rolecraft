"""Real local API/worker coverage for the integration-owned optional-practice seam."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.api import v4_extensions as extension
from career_lab.jobs.worker import Worker
from career_lab.contracts.v2 import digest
from career_lab.storage.v2_tables import v2_sessions

ROOT = Path(__file__).resolve().parents[2]

class Case(dict):
    def __repr__(self):
        return '<practice fixture; credentials redacted>'


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    target = tmp_path_factory.mktemp("extension-catalog") / "prepared"
    subprocess.run([sys.executable, str(ROOT / "docs/integration/prepare_scenarios.py"), "--output", str(target)],
                   cwd=ROOT, check=True, capture_output=True)
    return target / "catalog.json"

@pytest.fixture()
def practice(tmp_path, monkeypatch, prepared):
    monkeypatch.setenv("CAREER_LAB_SCENARIO_CATALOG", str(prepared))
    monkeypatch.delenv("CAREER_LAB_SCENARIO_ARCHIVE", raising=False)
    url = "sqlite:///" + str(tmp_path / "extensions.db")
    app = create_runtime_app(url, provider="local")
    client = TestClient(app, raise_server_exceptions=False)
    created = client.post("/sessions", json={"schema_version":2,"scenario":"pm_pilot_v2","work_language":"zh"}).json()
    sid = created["session_id"]
    headers = {"Authorization":"Bearer " + created["token"]}
    def send(path, key, operation, payload):
        state = client.get("/sessions/" + sid, headers=headers).json()["state"]
        return client.post("/sessions/" + sid + "/" + path, headers=headers, json={"schema_version":2,
            "request_id":key,"operation":operation,"payload":payload,"expected_version":state["business_seq"],
            "expected_workspace_revision":state["workspace_revision"]})
    made = send("work-products", "draft", "work_products.create", {"kind":"text","purpose":"commitment","content":"先核实需求与验收条件，暂缓开放。"})
    assert made.status_code == 200
    product = next(ref for ref in made.json()["objects"] if ref["kind"] == "product")
    submitted = send("submissions", "submit", "submissions.create", {"decision":"defer_with_conditions","products":[product]})
    assert submitted.status_code == 200 and Worker(app.state.jobs, app.state.handlers).run_once()
    sub = submitted.json()["result"]["submission"]["object_id"]
    endpoint = "/sessions/" + sid + "/practice"
    shown = client.get(endpoint, params={"submission_id":sub}, headers=headers)
    assert shown.status_code == 200 and len(shown.json()["result"]["catalog"]) == 2
    yield Case(app=app, client=client, sid=sid, headers=headers, send=send, shown=shown.json()["result"], endpoint=endpoint, url=url)
    client.close(); app.state.store.close(); app.state.v2_store.db.engine.dispose()


def choose(p, *, key="choice", choice="choose_other", option="pm_pilot_urgent-zh", shown=None, headers=None):
    return p["client"].post(p["endpoint"] + "/choices", headers=headers or p["headers"], json={
        "request_id":key,"shown":shown or p["shown"],"choice":choice,"option_id":option})


def test_choice_restart_recovery_keeps_one_session_and_original_feedback(practice):
    p = practice; first = choose(p); assert first.status_code == 200
    original = p["shown"]["source_feedback_hash"]
    restarted = create_runtime_app(p["url"], provider="local")
    with TestClient(restarted) as client:
        replay = client.post(p["endpoint"]+"/choices", headers=p["headers"], json={"request_id":"choice",
            "shown":p["shown"],"choice":"choose_other","option_id":"pm_pilot_urgent-zh"})
        assert replay.status_code == 200
        same_session = replay.json()["result"]["session"] == first.json()["result"]["session"]
        assert same_session
        assert replay.json()["result"]["duplicate"] is True
        assert replay.json()["result"]["plan"]["help_source"] == "self_selected"
        current = client.get('/sessions/'+p['sid']+'/feedback-records/'+p['shown']['source_feedback']['object_id'], headers=p['headers'])
        assert digest(current.json()['result']['result']['feedback']) == original
        plan = replay.json()['result']['plan']
        assert plan['creates_session'] is True
        assert plan['new_session_id'] == replay.json()['result']['session']['session_id']
        # Compare the source hash carried by the immutable plan, not a new score.
        assert replay.json()["result"]["plan"]["source_feedback_hash"] == original
    restarted.state.store.close(); restarted.state.v2_store.db.engine.dispose()
    assert choose(p, option="pm_pilot_capacity15-zh").status_code == 409
    with p["app"].state.v2_store.db.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(v2_sessions)).scalar_one() == 2


def test_choice_failure_after_creation_retries_without_duplicate_session(practice, monkeypatch):
    p=practice; original=extension.insert; fault=[True]
    def fail_once(table):
        if table is extension.practice_links and fault[0]:
            fault[0]=False
            raise RuntimeError("controlled link write failure")
        return original(table)
    monkeypatch.setattr(extension,"insert",fail_once)
    assert choose(p).status_code == 500
    with p["app"].state.v2_store.db.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(v2_sessions)).scalar_one() == 2
    recovered=choose(p); assert recovered.status_code == 200
    assert recovered.json()["result"]["session"]["session_id"] == choose(p).json()["result"]["session"]["session_id"]
    with p["app"].state.v2_store.db.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(v2_sessions)).scalar_one() == 2
        assert connection.execute(select(func.count()).select_from(extension.practice_links)).scalar_one() == 1


def test_other_language_cannot_be_forged_in_shown_feedback(practice):
    p=practice; forged={**p["shown"],"work_language":"en"}
    result=choose(p,shown=forged,option="pm_pilot_urgent-en")
    assert result.status_code == 409
    assert result.json()["code"] == "practice_language_mismatch"
    with p["app"].state.v2_store.db.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(v2_sessions)).scalar_one() == 1


@pytest.mark.parametrize("body", [[],{}, {"request_id":"bad","choice":"choose_other","option_id":"pm_pilot_urgent-zh","shown":{"source_feedback":{}}}])
def test_malformed_choice_is_rejected_without_server_error(practice,body):
    p=practice
    result=p["client"].post(p["endpoint"]+"/choices",headers=p["headers"],json=body)
    assert result.status_code == 422


def test_only_owner_can_list_grants_or_choose_and_lists_never_return_credentials(practice):
    p=practice
    issued=p["send"]("delegations","grant","delegations.create",{"agent_label":"Test helper",
        "expires_at":(datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat(),"capabilities":["read","act"]})
    assert issued.status_code == 200
    grant=issued.json()["result"]["result"];agent={"Authorization":"Bearer "+grant["token"]}
    url="/sessions/"+p["sid"]+"/delegations"
    visible=p["client"].get(url,headers=p["headers"])
    assert visible.status_code == 200
    assert grant["token"] not in visible.text and "token_hash" not in visible.text
    assert visible.json()["result"]["result"]["items"][0]["effective_status"] == "active"
    assert p["client"].get(url,headers=agent).status_code == 403
    assert choose(p,headers=agent).status_code == 403
    assert p["client"].get(url).status_code == 401
    foreign=p["client"].post("/sessions",json={"schema_version":2,"scenario":"pm_pilot_v2"}).json()
    assert p["client"].get(url,headers={"Authorization":"Bearer "+foreign["token"]}).status_code in (401,403)


def test_decline_does_not_create_or_rewrite_a_practice(practice):
    p=practice
    result=choose(p,choice="decline",option=None)
    assert result.status_code == 200 and result.json()["result"]["session"] is None
    again=choose(p,choice="decline",option=None)
    assert again.status_code == 200 and again.json()["result"]["duplicate"] is True
    with p["app"].state.v2_store.db.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(v2_sessions)).scalar_one() == 1
