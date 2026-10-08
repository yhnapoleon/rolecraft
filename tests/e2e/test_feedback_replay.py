from fastapi.testclient import TestClient

from career_lab.api.app import create_app
from career_lab.jobs.worker import Worker


def test_feedback_job_replay_and_evidence_links(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'feedback.db'}")
    client = TestClient(app)
    created = client.post("/sessions", json={}).json()
    sid = created["session_id"]
    h = {"Authorization": "Bearer " + created["token"]}
    plan = {
        "participants": 31,
        "knowledge_domains": ["stable_faq"],
        "launch_day": 7,
        "update_strategy": "daily",
        "fallback": "human",
        "work_items": ["scope_filter", "human_fallback"],
    }
    client.post(
        f"/sessions/{sid}/actions",
        headers=h,
        json={
            "tool": "update_pilot",
            "arguments": {"plan": plan},
            "request_id": "config",
            "expected_version": 0,
        },
    )
    artifact = client.post(
        f"/sessions/{sid}/artifacts",
        headers=h,
        json={"request_id": "a", "content": {"goal": "减少咨询"}},
    ).json()
    sub = client.post(
        f"/sessions/{sid}/submissions",
        headers=h,
        json={"artifact_id": artifact["id"], "config_version": 1, "request_id": "s"},
    ).json()
    requested = client.post(
        f"/sessions/{sid}/feedback", headers=h, json={"submission_id": sub["id"]}
    )
    assert requested.status_code == 200, requested.text
    worker = Worker(app.state.jobs, app.state.handlers)
    worker.run_once()
    result = client.get(f"/sessions/{sid}/jobs/{requested.json()['job_id']}", headers=h).json()
    assert result["status"] == "completed", result
    report = result["result"]
    assert (
        next(i for i in report["items"] if i["criterion_id"] == "R3.capacity")["label"] == "NOT_MET"
    )
    events_before = len(app.state.store.events(sid))
    for _ in range(2):
        assert client.get(f"/sessions/{sid}/timeline", headers=h).status_code == 200
        assert client.get(f"/sessions/{sid}/feedback/{sub['id']}", headers=h).json() == report
    assert len(app.state.store.events(sid)) == events_before
    eid = next(iter(report["sources"]["R3.capacity"]))
    evidence = client.get(f"/sessions/{sid}/evidence/{sub['id']}/R3.capacity/{eid}", headers=h)
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["observed_at_seq"] <= sub["as_of_seq"]
