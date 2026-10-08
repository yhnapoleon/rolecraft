from fastapi.testclient import TestClient
from career_lab.api.app import create_app


def test_approved_alternative_is_reachable_without_actor_spoofing(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'approvals.db'}")
    client = TestClient(app)
    created = client.post("/sessions", json={}).json()
    sid, h = created["session_id"], {"Authorization": "Bearer " + created["token"]}
    plan = {
        "participants": 50,
        "knowledge_domains": ["stable_faq", "policy"],
        "launch_day": 10,
        "update_strategy": "realtime",
        "fallback": "human",
        "work_items": ["realtime_sync", "human_fallback"],
    }

    def action(tool, arguments, key):
        version = app.state.store.get_state(sid).version
        return client.post(
            f"/sessions/{sid}/actions",
            headers=h,
            json={
                "tool": tool,
                "arguments": arguments,
                "request_id": key,
                "expected_version": version,
            },
        )

    assert action("update_pilot", {"plan": plan}, "config").status_code == 200
    early = client.post(
        f"/sessions/{sid}/approvals/resolve",
        headers=h,
        json={"rule_id": "capacity_approved", "request_id": "early", "expected_version": 1},
    )
    assert early.status_code == 422
    for tool, rule in [
        ("request_capacity", "capacity_approved"),
        ("request_resources", "resources_approved"),
    ]:
        assert (
            action(tool, {"reason": "执行50人实时同步试点，申请预算与上线时间"}, tool).status_code
            == 200
        )
        version = app.state.store.get_state(sid).version
        body = {"rule_id": rule, "request_id": rule, "expected_version": version}
        response = client.post(f"/sessions/{sid}/approvals/resolve", headers=h, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["approved"]
        assert (
            client.post(f"/sessions/{sid}/approvals/resolve", headers=h, json=body).json()
            == response.json()
        )
        changed = {**body, "expected_version": version + 1}
        assert (
            client.post(f"/sessions/{sid}/approvals/resolve", headers=h, json=changed).status_code
            == 409
        )
    state = app.state.store.get_state(sid)
    assert state.resources == {"capacity": 60, "dev_days": 6, "deadline_day": 10}
    tested = client.post(
        f"/sessions/{sid}/tests",
        headers=h,
        json={"query": "住宿报销上限是多少？", "config_version": 1, "request_id": "test"},
    )
    assert tested.status_code == 200
    assert not tested.json()["stale"]
    assert "400" in tested.json()["answer"]
