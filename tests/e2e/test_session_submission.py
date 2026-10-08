from fastapi.testclient import TestClient

from career_lab.api.app import create_app


def test_api_session_to_submission_and_restart(tmp_path):
    url = f"sqlite:///{tmp_path / 'api.db'}"
    client = TestClient(create_app(url))
    created = client.post("/sessions", json={}).json()
    sid = created["session_id"]
    headers = {"Authorization": "Bearer " + created["token"]}
    assert client.get(f"/sessions/{sid}").status_code == 401
    plan = {
        "participants": 20,
        "knowledge_domains": ["stable_faq"],
        "launch_day": 7,
        "update_strategy": "daily",
        "fallback": "human",
        "work_items": ["scope_filter", "human_fallback"],
    }
    response = client.post(
        f"/sessions/{sid}/actions",
        headers=headers,
        json={
            "tool": "update_pilot",
            "arguments": {"plan": plan},
            "request_id": "config",
            "expected_version": 0,
        },
    )
    assert response.status_code == 200, response.text
    assert (
        client.post(
            f"/sessions/{sid}/actions",
            headers=headers,
            json={
                "tool": "approve_request",
                "arguments": {},
                "request_id": "hack",
                "expected_version": 1,
            },
        ).status_code
        == 422
    )
    tested = client.post(
        f"/sessions/{sid}/tests",
        headers=headers,
        json={"query": "如何申请会议室？", "config_version": 1, "request_id": "test"},
    )
    assert tested.status_code == 200, tested.text
    assert tested.json()["citations"]
    artifact = client.post(
        f"/sessions/{sid}/artifacts",
        headers=headers,
        json={
            "request_id": "draft",
            "content": {
                "goal": "减少咨询",
                "owner": "PM",
                "metrics": "有效解答率80%",
                "observation_window": "7天",
                "exit_condition": "出现严重错误即关闭",
                "rationale": "稳定FAQ先行",
            },
        },
    )
    assert artifact.status_code == 200, artifact.text
    submitted = client.post(
        f"/sessions/{sid}/submissions",
        headers=headers,
        json={"artifact_id": artifact.json()["id"], "config_version": 1, "request_id": "submit"},
    )
    assert submitted.status_code == 200, submitted.text
    assert (
        client.post(
            f"/sessions/{sid}/submissions",
            headers=headers,
            json={
                "artifact_id": artifact.json()["id"],
                "config_version": 1,
                "request_id": "submit",
            },
        ).json()
        == submitted.json()
    )
    restarted = TestClient(create_app(url))
    assert (
        restarted.get(f"/sessions/{sid}", headers=headers).json()["state"]["status"] == "submitted"
    )
    assert "tech_private" not in restarted.get(f"/sessions/{sid}/materials", headers=headers).text
