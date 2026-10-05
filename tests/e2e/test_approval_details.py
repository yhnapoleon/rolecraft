from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from career_lab.api.app import create_app
from career_lab.storage.sessions import digest


PLAN = {"participants": 50, "knowledge_domains": ["stable_faq"], "launch_day": 7,
        "update_strategy": "daily", "fallback": "human", "work_items": ["scope_filter", "human_fallback"]}


@pytest.fixture
def approval_api(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'approvals-details.db'}")
    with TestClient(app) as client:
        created = client.post("/sessions", json={}).json()
        sid = created["session_id"]
        headers = {"Authorization": "Bearer " + created["token"]}
        yield app, client, sid, headers
    app.state.store.close()


def action(api, tool, arguments, request_id):
    app, client, sid, headers = api
    response = client.post(f"/sessions/{sid}/actions", headers=headers, json={
        "tool": tool, "arguments": arguments, "request_id": request_id,
        "expected_version": app.state.store.get_state(sid).version})
    assert response.status_code == 200, response.text
    return response.json()


def request_body(api, rule="capacity_approved", request_id="resolve"):
    return {"rule_id": rule, "request_id": request_id, "expected_version": api[0].state.store.get_state(api[2]).version}


def resolve(api, body):
    _, client, sid, headers = api
    return client.post(f"/sessions/{sid}/approvals/resolve", headers=headers, json=body)


def test_denial_is_saved_once_without_world_change_and_replays_after_changes(approval_api):
    app, client, sid, headers = approval_api
    action(approval_api, "update_pilot", {"plan": {**PLAN, "fallback": "none", "work_items": ["scope_filter"]}}, "config")
    action(approval_api, "request_capacity", {"reason": "Need 50 participants"}, "request")
    before = app.state.store.get_state(sid)
    body = request_body(approval_api)
    denied = resolve(approval_api, body)
    assert denied.status_code == 422
    assert denied.json()["error"] == "requested plan lacks necessary work or human fallback"
    assert denied.json()["code"] == "approval_plan_incomplete"
    assert denied.json()["details"]["missing"] == {
        "work_items": ["human_fallback"], "human_fallback": True, "minimum_participants": False}
    assert app.state.store.get_state(sid) == before
    timeline = client.get(f"/sessions/{sid}/timeline", headers=headers).json()
    record = timeline["approval_denials"][0]
    assert record["created_at"].endswith("Z")
    assert resolve(approval_api, body).json() == denied.json()
    assert len(app.state.store.list_objects(sid, "approval_denied")) == 1
    raw = app.state.store.get_object(sid, record["id"], "approval_denied")
    assert set(raw) == {"rule_id", "request_id", "code", "details"}
    action(approval_api, "update_pilot", {"plan": PLAN}, "fixed-config")
    assert resolve(approval_api, body).json() == denied.json()
    assert client.get(f"/sessions/{sid}/timeline", headers=headers).json()["approval_denials"][0] == record
    reused = resolve(approval_api, {**body, "expected_version": app.state.store.get_state(sid).version})
    assert reused.status_code == 409
    assert reused.json() == {"error": "approval request ID reused with different content", "code": "request_id_reused"}
    assert resolve(approval_api, request_body(approval_api, request_id="fixed-approval")).json()["state"]["resources"]["capacity"] == 60


@pytest.mark.parametrize("setup,code,message", [
    ("no_pending", "approval_no_pending_request", "supervisor approval requires a pending scenario request"),
    ("no_config", "approval_needs_config", "configure the requested pilot before supervisor review"),
    ("unnecessary", "approval_not_needed_or_over_limit", "request is unnecessary or exceeds the scenario approval limits"),
    ("over_limit", "approval_not_needed_or_over_limit", "request is unnecessary or exceeds the scenario approval limits"),
    ("below_minimum", "approval_plan_incomplete", "requested plan lacks necessary work or human fallback"),
])
def test_approval_denial_codes_and_original_messages(approval_api, setup, code, message):
    app, _, sid, _ = approval_api
    if setup not in {"no_pending", "no_config"}:
        count = {"unnecessary": 20, "over_limit": 70, "below_minimum": 0}[setup]
        action(approval_api, "update_pilot", {"plan": {**PLAN, "participants": count}}, "config")
    if setup != "no_pending":
        action(approval_api, "request_capacity", {"reason": "Need more capacity"}, "request")
    before = app.state.store.get_state(sid)
    response = resolve(approval_api, request_body(approval_api))
    assert response.status_code == 422
    assert response.json()["code"] == code
    assert response.json()["error"] == message
    assert app.state.store.get_state(sid) == before
    if setup in {"unnecessary", "over_limit"}:
        assert response.json()["details"] == {"requested": {"capacity": count}, "current": {"capacity": 30}, "limit": {"capacity": 60}}
    if setup == "below_minimum":
        assert response.json()["details"]["missing"]["minimum_participants"] is True


def test_unsupported_approval_rule_has_stable_code(approval_api, monkeypatch):
    app, _, sid, _ = approval_api
    action(approval_api, "update_pilot", {"plan": PLAN}, "config")
    action(approval_api, "request_capacity", {"reason": "Need more capacity"}, "request")
    spec = app.state.store.get_spec(sid)
    rules = tuple(rule.model_copy(update={"trigger": rule.trigger.model_copy(update={"request_tool": "unsupported"})})
                  if rule.id == "capacity_approved" else rule for rule in spec.event_rules)
    # Exercise a supported contract shape without changing the scenario bundle.
    monkeypatch.setattr(app.state.store, "get_spec", lambda _: spec.model_copy(update={"event_rules": rules}))
    response = resolve(approval_api, request_body(approval_api))
    assert response.status_code == 422
    assert response.json() == {"error": "unsupported supervisor approval rule", "code": "approval_unsupported_rule", "details": {}}


def test_success_replay_preserves_approval_snapshot_and_visibility(approval_api):
    app, _, sid, _ = approval_api
    action(approval_api, "update_pilot", {"plan": PLAN}, "config")
    action(approval_api, "request_capacity", {"reason": "Need more capacity"}, "request")
    body = request_body(approval_api)
    approved = resolve(approval_api, body)
    assert approved.status_code == 200, approved.text
    result = approved.json()
    assert result["state"]["resources"]["capacity"] == 60
    assert "tech_private" not in result["state"]["material_versions"]
    assert "tech_private" not in result["state"]["indexed_versions"]
    assert result["created_at"].endswith("Z")
    action(approval_api, "read_material", {"material_id": "brief"}, "later")
    assert app.state.store.get_state(sid).version > result["state"]["version"]
    assert resolve(approval_api, body).json() == result


@pytest.mark.parametrize("approved", [False, True])
def test_concurrent_identical_approvals_have_one_result(approval_api, approved):
    app, _, sid, _ = approval_api
    action(approval_api, "update_pilot", {"plan": {**PLAN, "fallback": "human" if approved else "none"}}, "config")
    action(approval_api, "request_capacity", {"reason": "Need more capacity"}, "request")
    body = request_body(approval_api)
    before = app.state.store.get_state(sid)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: resolve(approval_api, body), range(4)))
    assert {response.status_code for response in responses} == ({200} if approved else {422})
    assert all(response.json() == responses[0].json() for response in responses)
    kind = "approval_decision" if approved else "approval_denied"
    assert len(app.state.store.list_objects(sid, kind)) == 1
    after = app.state.store.get_state(sid)
    assert after.action_count == before.action_count + (1 if approved else 0)
    if not approved:
        assert after.version == before.version


def test_denial_refuses_stale_snapshot_during_save(approval_api, monkeypatch):
    app, _, sid, _ = approval_api
    save = app.state.store.save_derived
    body = request_body(approval_api)

    def concurrent_save(*args, **kwargs):
        action(approval_api, "read_material", {"material_id": "brief"}, "concurrent")
        return save(*args, **kwargs)

    monkeypatch.setattr(app.state.store, "save_derived", concurrent_save)
    response = resolve(approval_api, body)
    assert response.status_code == 409
    assert response.json()["code"] == "version_conflict"
    assert app.state.store.list_objects(sid, "approval_denied") == []


def test_denied_request_id_cannot_be_used_for_a_different_approval(approval_api):
    app, _, sid, _ = approval_api
    body = request_body(approval_api)
    assert resolve(approval_api, body).status_code == 422
    response = resolve(approval_api, {**body, "rule_id": "resources_approved"})
    assert response.status_code == 409
    assert response.json()["code"] == "request_id_reused"
    assert app.state.store.get_object_metadata(sid, digest([sid, "approval", "resolve"]))["request_hash"] == digest(body)


def test_resource_denial_reports_requested_current_and_limit(approval_api):
    action(approval_api, "update_pilot", {"plan": {**PLAN, "launch_day": 11}}, "config")
    action(approval_api, "request_resources", {"reason": "Need later launch"}, "request")
    response = resolve(approval_api, request_body(approval_api, rule="resources_approved"))
    assert response.status_code == 422
    assert response.json()["code"] == "approval_not_needed_or_over_limit"
    assert response.json()["details"] == {
        "requested": {"dev_days": 2, "deadline_day": 11},
        "current": {"dev_days": 3, "deadline_day": 7},
        "limit": {"dev_days": 6, "deadline_day": 10},
    }


def test_concurrent_different_requests_share_one_approval_id(approval_api):
    app, _, sid, _ = approval_api
    action(approval_api, "update_pilot", {"plan": PLAN}, "config")
    action(approval_api, "request_capacity", {"reason": "Need 50 participants"}, "capacity")
    action(approval_api, "request_resources", {"reason": "Ask for resources"}, "resources")
    bodies = [request_body(approval_api, rule=rule) for rule in ("capacity_approved", "resources_approved")]
    before = app.state.store.get_state(sid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda body: resolve(approval_api, body), bodies))
    codes = [response.status_code for response in responses]
    assert codes in ([200, 409], [409, 422])
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json() == {"error": "approval request ID reused with different content", "code": "request_id_reused"}
    records = app.state.store.list_objects(sid, "approval_decision") + app.state.store.list_objects(sid, "approval_denied")
    assert len(records) == 1
    after = app.state.store.get_state(sid)
    assert after.action_count == before.action_count + (1 if 200 in codes else 0)
