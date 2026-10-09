"""Formal W02 integration: real FastAPI, credentials, SQLite and W01 Mutation."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest

from fastapi.testclient import TestClient
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.contracts.v2 import DelegationGrant, Executor
from tests.support.scenario_packages import installed_root

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def api(tmp_path):
    module = ScenarioModule(installed_root())
    app = create_app(
        "sqlite:///" + str(tmp_path / "formal.db"), extensions=module.install(ExtensionRegistry())
    )
    with TestClient(app) as client:
        response = client.post("/sessions", json={"schema_version": 2, "scenario": "pm_pilot_v2"})
        assert response.status_code == 200
        session = response.json()
        yield (
            app,
            client,
            module,
            session["session_id"],
            {"Authorization": "Bearer " + session["token"]},
        )
    app.state.store.close()


def state(api):
    _, c, _, sid, h = api
    response = c.get(f"/sessions/{sid}", headers=h)
    assert response.status_code == 200
    return response.json()["state"]


def body(api, key, operation, payload):
    s = state(api)
    return {
        "schema_version": 2,
        "request_id": key,
        "operation": operation,
        "payload": payload,
        "expected_version": s["business_seq"],
        "expected_workspace_revision": s["workspace_revision"],
    }


def send(api, path, key, operation, payload, headers=None):
    _, c, _, sid, h = api
    return c.post(
        f"/sessions/{sid}/{path}", headers=headers or h, json=body(api, key, operation, payload)
    )


def config(api, **changes):
    s = state(api)
    raw = api[2].package.baseline(api[3]).model_dump(mode="json")
    return (
        raw
        | changes
        | {"config_version": s["config_version"] + 1, "version": s["config_version"] + 2}
    )


def apply(api, **changes):
    r = send(
        api,
        "actions",
        "apply-" + str(state(api)["config_version"] + 1),
        "apply_config",
        {"tool": "apply_config", "config": config(api, **changes)},
    )
    assert r.status_code == 200, r.text
    return r.json()


def auth_context(api):
    return api[0].state.v2_store.authenticate(api[3], api[4]["Authorization"].split(" ", 1)[1])


def test_c0_real_store_and_same_request_replay(api):
    app, c, _, sid, h = api
    request = body(
        api, "baseline", "tests.create", {"query": "住宿报销上限是多少？", "config_version": 0}
    )
    first = c.post(f"/sessions/{sid}/tests", headers=h, json=request)
    assert first.status_code == 200, first.text
    result = first.json()["result"]["test"]
    assert result["config_ref"]["config_version"] == 0 and result["config_ref"]["version"] == 1
    assert result["execution"]["source_versions"]["policy"] == 1
    assert result["citations"][0]["version"] == 1
    replay = c.post(f"/sessions/{sid}/tests", headers=h, json=request).json()
    assert replay["replayed"] and replay["result"]["test"] == result
    lookup = c.get(f"/sessions/{sid}/requests/baseline", headers=h)
    assert lookup.status_code == 200, lookup.text
    changed = c.post(
        f"/sessions/{sid}/tests",
        headers=h,
        json={**request, "payload": {"query": "另一问题", "config_version": 0}},
    )
    assert changed.status_code == 409


def test_explicit_apply_one_policy_update_private_events_hidden(api):
    app, _, _, sid, _ = api
    first = apply(api)
    assert [e["type"] for e in first["events"]] == ["config_applied", "initial_plan_applied"]
    assert "world_private" not in str(first)
    assert "tech_private" not in str(first)
    second = apply(api)
    assert [e["type"] for e in second["events"]] == ["config_applied"]
    current = app.state.v2_store.view(auth_context(api))
    assert current.private_scenario_state.source_versions["policy"] == 2
    assert current.private_scenario_state.indexed_versions["policy"] == 1


def test_public_basis_reference_and_approval_commit(api):
    app, c, _, sid, h = api
    apply(api, participants=50)
    req = send(
        api,
        "actions",
        "request",
        "request_business",
        {
            "tool": "request_business",
            "terms": {"capacity": 60},
            "reason": "候选用户范围超过现有容量",
            "evidence_refs": [
                {
                    "session_id": sid,
                    "kind": "material",
                    "object_id": "user_groups",
                    "version": 1,
                    "observed_at_seq": 0,
                }
            ],
        },
    )
    assert req.status_code == 200, req.text
    ref = req.json()["result"]["request"]
    pending = app.state.v2_store.view(auth_context(api))
    assert pending.state.resources["capacity"] == 30
    response = send(
        api,
        "approvals/resolve",
        "approve",
        "resolve_approval",
        {"request": ref, "expected_request_revision": 1},
    )
    assert response.status_code == 200, response.text
    decision = response.json()["result"]["decision"]
    assert decision["status"] == "approved" and decision["granted"] == {"capacity": 60}
    assert app.state.v2_store.view(auth_context(api)).state.resources["capacity"] == 60
    assert any(e["type"] == "business_scope_requested" for e in response.json()["events"])


def test_proposed_basis_does_not_apply_or_update_travel_policy(api):
    app, _, _, _, _ = api
    proposed = config(
        api,
        update_strategy="realtime",
        work_items=["realtime_sync", "human_fallback"],
        launch_day=10,
    )
    response = send(
        api,
        "actions",
        "proposal",
        "request_business",
        {
            "tool": "request_business",
            "config": proposed,
            "terms": {"dev_days": 6, "deadline_day": 10},
            "reason": "先确认资源，再决定应用",
        },
    )
    assert response.status_code == 200, response.text
    request = response.json()["result"]["request_data"]
    assert request["basis"]["mode"] == "proposed" and request["basis"]["config_ref"] is None
    current = app.state.v2_store.view(auth_context(api))
    assert current.state.config_version == 0
    assert current.private_scenario_state.source_versions["policy"] == 1
    assert current.private_scenario_state.source_versions["demo"] == 2


def test_unnecessary_and_unguarded_requests_rejected_with_plain_reason(api):
    apply(api, fallback="none", work_items=["scope_filter"], participants=50)
    requested = send(
        api,
        "actions",
        "unguarded",
        "request_business",
        {"tool": "request_business", "terms": {"capacity": 60}, "reason": "需要扩容"},
    )
    assert requested.status_code == 200
    decision = send(
        api,
        "approvals/resolve",
        "resolve",
        "resolve_approval",
        {"request": requested.json()["result"]["request"], "expected_request_revision": 1},
    )
    assert decision.status_code == 200, decision.text
    data = decision.json()["result"]["decision"]
    assert data["status"] == "rejected" and data["reason_code"] == "approval_plan_incomplete"
    assert "人工兜底" in data["reason"]


def test_history_read_and_future_reference_rejected(api):
    _, _, _, sid, _ = api
    future = send(
        api,
        "actions",
        "future",
        "read_material",
        {
            "tool": "read_material",
            "material": {
                "session_id": sid,
                "kind": "material",
                "object_id": "policy",
                "version": 2,
            },
        },
    )
    assert future.status_code == 404
    apply(api)
    historical = send(
        api,
        "actions",
        "historical",
        "read_material",
        {
            "tool": "read_material",
            "material": {
                "session_id": sid,
                "kind": "material",
                "object_id": "policy",
                "version": 1,
            },
        },
    )
    assert historical.status_code == 200, historical.text
    assert "500" in historical.text
    current = send(
        api,
        "actions",
        "current",
        "read_material",
        {
            "tool": "read_material",
            "material": {
                "session_id": sid,
                "kind": "material",
                "object_id": "policy",
                "version": 2,
            },
        },
    )
    assert current.status_code == 200, current.text
    assert "400" in current.text


def test_same_key_concurrency_has_one_real_effect(api):
    app, c, _, sid, h = api
    request = body(
        api, "concurrent", "tests.create", {"query": "会议室预约入口", "config_version": 0}
    )
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(
            pool.map(lambda _: c.post(f"/sessions/{sid}/tests", headers=h, json=request), range(3))
        )
    assert {r.status_code for r in responses} == {200}
    assert len({r.json()["transaction_id"] for r in responses}) == 1
    assert (
        len([x for x in app.state.v2_store.view(auth_context(api)).objects if x.ref.kind == "test"])
        == 1
    )


def test_delegation_scope_and_revocation_are_real(api):
    app, c, _, sid, _ = api
    store = app.state.v2_store
    owner = auth_context(api)
    grant = DelegationGrant(
        id="faq-delegation",
        session_id=sid,
        actor_id="learner",
        executor=Executor(id="qa-delegate", kind="external_agent", delegation_id="faq-delegation"),
        capabilities=("read", "act"),
        allowed_objects=("faq", "pilot"),
        allowed_actions=("tests.create", "refresh_index"),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    token = store.issue_delegation(owner, grant)
    h = {"Authorization": "Bearer " + token}
    tested = send(
        api,
        "tests",
        "delegated",
        "tests.create",
        {"query": "会议室预约", "config_version": 0},
        headers=h,
    )
    assert tested.status_code == 200, tested.text
    assert tested.json()["result"]["test"]["execution"]["executor"]["kind"] == "external_agent"
    denied = send(api, "actions", "scope", "refresh_index", {"tool": "refresh_index"}, headers=h)
    assert denied.status_code == 403
    store.revoke_delegation(owner, grant.id)
    revoked = send(
        api,
        "tests",
        "revoked",
        "tests.create",
        {"query": "会议室预约", "config_version": 0},
        headers=h,
    )
    assert revoked.status_code in {401, 403}


def test_contextual_port_persists_and_replays_activated_policy(api):
    app, c, _, sid, h = api
    apply(api)
    refreshed = send(api, "actions", "refresh", "refresh_index", {"tool": "refresh_index"})
    assert refreshed.status_code == 200, refreshed.text
    request = body(
        api, "new-policy", "tests.create", {"query": "住宿报销上限是多少？", "config_version": 1}
    )
    first = c.post(f"/sessions/{sid}/tests", headers=h, json=request)
    assert first.status_code == 200, first.text
    test = first.json()["result"]["test"]
    assert "400" in test["answer"] and test["citations"][0]["version"] == 2
    assert test["execution"]["indexed_versions"]["policy"] == 2
    before = state(api)
    replay = c.post(f"/sessions/{sid}/tests", headers=h, json=request)
    assert replay.status_code == 200 and replay.json()["replayed"]
    assert replay.json()["result"] == first.json()["result"] and state(api) == before
    lookup = c.get(f"/sessions/{sid}/requests/new-policy", headers=h)
    assert lookup.status_code == 200 and lookup.json()["response"] == first.json()


def test_realtime_effective_config_changes_only_after_real_resource_grant(api):
    requested = {
        "update_strategy": "realtime",
        "work_items": ["realtime_sync", "human_fallback"],
        "launch_day": 10,
    }
    before = apply(api, **requested)
    assert before["result"]["config"]["effective"]["update_strategy"] == "daily"
    req = send(
        api,
        "actions",
        "dev-request",
        "request_business",
        {
            "tool": "request_business",
            "terms": {"dev_days": 6, "deadline_day": 10},
            "reason": "实时同步和人工兜底的实际工作缺口",
        },
    )
    assert req.status_code == 200, req.text
    approved = send(
        api,
        "approvals/resolve",
        "dev-approve",
        "resolve_approval",
        {"request": req.json()["result"]["request"], "expected_request_revision": 1},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"]["decision"]["granted"] == {"dev_days": 6, "deadline_day": 10}
    after = apply(api, **requested)
    assert after["result"]["config"]["effective"]["update_strategy"] == "realtime"
    assert "work_items" not in after["result"]["config"]["differences"]
    tested = send(
        api, "tests", "real-effective", "tests.create", {"query": "会议室预约", "config_version": 2}
    )
    assert tested.status_code == 200, tested.text
    assert tested.json()["result"]["test"]["config"]["effective"]["update_strategy"] == "realtime"
    policy = send(
        api,
        "tests",
        "realtime-policy",
        "tests.create",
        {"query": "住宿报销上限是多少？", "config_version": 2},
    )
    assert policy.status_code == 200, policy.text
    assert "400" in policy.json()["result"]["test"]["answer"]
    assert policy.json()["result"]["test"]["citations"][0]["version"] == 2


def test_material_reference_uses_the_exact_historical_state(api):
    from career_lab.contracts.v2 import ObjectRef, ProtocolError

    store = api[0].state.v2_store
    owner = auth_context(api)
    sid = api[3]
    old = ObjectRef(session_id=sid, kind="material", object_id="policy", version=1)
    future = old.model_copy(update={"version": 2})
    apply(api)
    assert store.resolve_reference(owner, old, storage_revision=0).ref.version == 1
    with pytest.raises(ProtocolError) as denied:
        store.resolve_reference(owner, future, storage_revision=0)
    assert denied.value.status == 404
    assert store.resolve_reference(owner, future).ref.version == 2
