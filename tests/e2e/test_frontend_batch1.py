from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from career_lab.api.app import create_app
from career_lab.jobs.repository import jobs
from career_lab.jobs.worker import Worker
from career_lab.runtime.model_adapter import ModelReply, ScriptedModel
from career_lab.storage.sessions import digest


PLAN = {"participants": 20, "knowledge_domains": ["stable_faq"], "launch_day": 7,
        "update_strategy": "daily", "fallback": "human", "work_items": ["scope_filter", "human_fallback"]}


@pytest.fixture
def api(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'batch1.db'}")
    client = TestClient(app)
    created = client.post("/sessions", json={}).json()
    sid = created["session_id"]
    client.headers["Authorization"] = "Bearer " + created["token"]
    return app, client, sid, created


def post(client, sid, path, body):
    response = client.post(f"/sessions/{sid}/{path}", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def configure(client, sid):
    return post(client, sid, "actions", {"tool": "update_pilot", "arguments": {"plan": PLAN},
                                        "request_id": "config", "expected_version": 0})


def assert_utc(value):
    assert value.endswith("Z")
    assert datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo == timezone.utc


def test_lists_restore_post_responses_timestamps_and_replays(api):
    app, client, sid, _ = api
    configure(client, sid)
    tests = [post(client, sid, "tests", {"query": "会议室如何申请？", "config_version": 1, "request_id": f"test-{i}"}) for i in range(2)]
    artifacts = [post(client, sid, "artifacts", {"content": {"goal": f"目标{i}"}, "request_id": f"draft-{i}"}) for i in range(2)]
    submission_body = {"artifact_id": artifacts[-1]["id"], "config_version": 1, "request_id": "submit"}
    submissions = [post(client, sid, "submissions", submission_body)]
    before = app.state.store.get_state(sid)
    # Replay all three kinds after submission: the original timestamp must survive.
    assert post(client, sid, "tests", {"query": "会议室如何申请？", "config_version": 1, "request_id": "test-0"}) == tests[0]
    assert post(client, sid, "artifacts", {"content": {"goal": "目标0"}, "request_id": "draft-0"}) == artifacts[0]
    assert post(client, sid, "submissions", submission_body) == submissions[0]
    restarted = TestClient(create_app(str(app.state.store.db.engine.url)))
    restarted.headers.update(client.headers)
    for path, expected in (("tests", tests), ("artifacts", artifacts), ("submissions", submissions)):
        assert restarted.get(f"/sessions/{sid}/{path}").json() == expected
        for record in expected:
            assert_utc(record["created_at"])
            assert isinstance(record["as_of_seq"], int)
            saved = app.state.store.get_object(sid, record["id"])
            assert "created_at" not in saved
        assert client.get(f"/sessions/{sid}/{path}", headers={"Authorization": "Bearer wrong"}).status_code == 401
    timeline = restarted.get(f"/sessions/{sid}/timeline").json()
    for event in timeline["events"]:
        assert_utc(event["created_at"])
    assert app.state.store.get_state(sid) == before


def test_job_kind_role_question_and_times(api):
    app, client, sid, _ = api
    question = "  当前资源是多少？\n请说明依据。  "
    body = {"role_id": "tech_lead", "text": question, "request_id": "turn"}
    jid = post(client, sid, "turns", body)["job_id"]
    endpoint = f"/sessions/{sid}/jobs/{jid}"
    queued = client.get(endpoint).json()
    assert (queued["kind"], queued["role_id"], queued["status"]) == ("turn", "tech_lead", "queued")
    assert_utc(queued["queued_at"])
    assert queued["started_at"] is queued["finished_at"] is None
    assert post(client, sid, "turns", body)["job_id"] == jid
    assert client.get(endpoint).json() == queued
    Worker(app.state.jobs, app.state.handlers).run_once()
    completed = client.get(endpoint).json()
    assert completed["status"] == "completed"
    assert completed["queued_at"] == queued["queued_at"]
    assert_utc(completed["started_at"])
    assert_utc(completed["finished_at"])
    turn = client.get(f"/sessions/{sid}/timeline").json()["turns"][0]
    assert turn["question"] == question
    assert_utc(turn["created_at"])
    assert "created_at" not in completed["result"]
    other = client.post("/sessions", json={}).json()
    assert client.get(f"/sessions/{other['session_id']}/jobs/{jid}", headers={"Authorization": "Bearer " + other["token"]}).status_code == 404


@pytest.mark.parametrize("status,role,code", [("active", "invalid", "unknown_role"), ("paused", "tech_lead", "session_paused"), ("submitted", "tech_lead", "session_submitted")])
def test_turn_validation_does_not_enqueue(api, status, role, code):
    app, client, sid, _ = api
    if status == "paused":
        post(client, sid, "actions", {"tool": "pause", "arguments": {}, "request_id": "pause", "expected_version": 0})
    elif status == "submitted":
        configure(client, sid)
        artifact = post(client, sid, "artifacts", {"content": {"goal": "test"}, "request_id": "draft"})
        post(client, sid, "submissions", {"artifact_id": artifact["id"], "config_version": 1, "request_id": "submit"})
    response = client.post(f"/sessions/{sid}/turns", json={"role_id": role, "text": "问题", "request_id": "turn"})
    assert response.status_code == 422
    assert response.json()["code"] == code
    with app.state.store.db.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(jobs)).scalar_one() == 0


def test_state_projection_preserves_policy_pending_strings_and_stored_state(api):
    app, client, sid, created = api
    responses = [created["state"], client.get(f"/sessions/{sid}").json()["state"]]
    configure(client, sid)
    action = post(client, sid, "actions", {"tool": "request_capacity", "arguments": {"reason": "测试"}, "request_id": "request", "expected_version": 1})
    responses += [action["state"], *action["snapshots"]]
    assert action["state"]["pending_requests"] == ["capacity_approved"]
    # Third action fires the existing policy rule; every returned snapshot is projected.
    action = post(client, sid, "actions", {"tool": "read_material", "arguments": {"material_id": "policy"}, "request_id": "read", "expected_version": action["state"]["version"]})
    responses += [action["state"], *action["snapshots"]]
    assert len(action["snapshots"]) == 2
    for state in responses:
        for field in ("material_versions", "indexed_versions"):
            assert "tech_private" not in state[field]
            assert "policy" in state[field]
        assert isinstance(state["pending_requests"], list)
        assert all(isinstance(value, str) for value in state["pending_requests"])
    stored = app.state.store.get_state(sid)
    assert "tech_private" in stored.material_versions
    assert stored.action_count == 3
    assert stored.version == 4


def test_feedback_retry_recovers_failed_job_and_keeps_other_states(api):
    app, client, sid, _ = api
    configure(client, sid)
    artifact = post(client, sid, "artifacts", {"content": {"goal": "test"}, "request_id": "draft"})
    submission = post(client, sid, "submissions", {"artifact_id": artifact["id"], "config_version": 1, "request_id": "submit"})
    body = {"submission_id": submission["id"]}
    jid = post(client, sid, "feedback", body)["job_id"]
    endpoint = f"/sessions/{sid}/jobs/{jid}"
    queued = client.get(endpoint).json()
    assert (queued["kind"], queued["role_id"]) == ("feedback", None)
    post(client, sid, "feedback", {**body, "retry": True})
    assert client.get(endpoint).json() == queued
    worker = Worker(app.state.jobs, {"feedback": lambda _: (_ for _ in ()).throw(RuntimeError("controlled failure"))})
    for _ in range(3):
        assert worker.run_once()
    failed = client.get(endpoint).json()
    assert failed["status"] == "failed" and failed["attempt"] == 3
    assert_utc(failed["finished_at"])
    post(client, sid, "feedback", body)
    assert client.get(endpoint).json() == failed
    assert post(client, sid, "feedback", {**body, "retry": True})["job_id"] == jid
    retried = client.get(endpoint).json()
    assert retried["status"] == "queued" and retried["attempt"] == 0
    assert retried["error"] is retried["started_at"] is retried["finished_at"] is None
    assert Worker(app.state.jobs, app.state.handlers).run_once()
    completed = client.get(endpoint).json()
    assert completed["status"] == "completed", completed
    post(client, sid, "feedback", {**body, "retry": True})
    assert client.get(endpoint).json() == completed


def test_turn_context_roundtrip_fingerprint_and_prompt_isolation(api):
    app, client, sid, _ = api
    model = ScriptedModel([ModelReply(text="same"), ModelReply(text="same")])
    app.state.runtime.model = model
    context = {"task_id": "事项 / 自由编号", "work_id": "work 1", "attachments": [{"type": "work", "id": "draft-1", "version": 2}, {"type": "test", "id": "test-1"}]}
    body = {"role_id": "tech_lead", "text": "资源？", "request_id": "context", **context}
    jid = post(client, sid, "turns", body)["job_id"]
    assert post(client, sid, "turns", body)["job_id"] == jid
    worker = Worker(app.state.jobs, app.state.handlers)
    assert worker.run_once()
    turn = client.get(f"/sessions/{sid}/timeline").json()["turns"][0]
    assert turn["context"] == context
    for change in ({"task_id": "other"}, {"work_id": "other"}, {"attachments": []}):
        response = client.post(f"/sessions/{sid}/turns", json={**body, **change})
        assert response.status_code == 422
        assert response.json()["error"] == "job key conflict"
        assert response.json()["code"] == "request_id_reused"
    other = client.post("/sessions", json={}).json()
    old_client = TestClient(app)
    old_client.headers["Authorization"] = "Bearer " + other["token"]
    legacy_body = {"role_id": "tech_lead", "text": "资源？", "request_id": "legacy"}
    legacy_job = post(old_client, other["session_id"], "turns", legacy_body)["job_id"]
    assert app.state.jobs.get(legacy_job)["payload"] == {"session_id": other["session_id"], **legacy_body}
    assert worker.run_once()
    saved = app.state.store.get_object(other["session_id"], digest([other["session_id"], "turn", "legacy"]), "turn")
    assert saved["request_hash"] == digest({"session": other["session_id"], "role": "tech_lead", "text": "资源？"})
    assert "context" not in saved["result"]
    assert model.calls[0] == model.calls[1]


@pytest.mark.parametrize("extra", [{"task_id": "x" * 201}, {"work_id": "x" * 201},
                                 {"attachments": [{"type": "test", "id": "t"}] * 11},
                                 {"attachments": [{"type": "other", "id": "x"}]}])
def test_invalid_turn_context_rejected_before_enqueue(api, extra):
    app, client, sid, _ = api
    response = client.post(f"/sessions/{sid}/turns", json={"role_id": "tech_lead", "text": "问题", "request_id": "turn", **extra})
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert app.state.jobs.claim_job("worker") is None
