"""Integration contract checks for the new frontend, using unchanged backend code.

No provider keys, remote models or production database are used here.
Run from the repository root: uv run pytest apps/web/tests/test_existing_backend.py -q
"""
import pytest
from fastapi.testclient import TestClient

from career_lab.api.app import create_app
from career_lab.jobs.worker import Worker
from career_lab.runtime.model_adapter import LocalModel, ModelReply


@pytest.fixture
def connected(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'web.db'}")
    client = TestClient(app)
    made = client.post("/sessions", json={"scenario": "pm_pilot"}).json()
    prefix = "/sessions/" + made["session_id"]
    headers = {"Authorization": "Bearer " + made["token"]}

    def get(suffix=""):
        response = client.get(prefix + suffix, headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    def post(suffix, body, expected=200):
        response = client.post(prefix + suffix, json=body, headers=headers)
        assert response.status_code == expected, response.text
        return response.json()

    def action(tool, arguments, key):
        return post("/actions", {"tool": tool, "arguments": arguments, "request_id": key, "expected_version": get()["state"]["version"]})

    return app, client, made, get, post, action


def pilot(**overrides):
    return {"participants": 20, "knowledge_domains": ["stable_faq", "policy"], "launch_day": 7,
            "update_strategy": "daily", "fallback": "human", "work_items": ["scope_filter", "human_fallback"]} | overrides


def test_three_role_jobs_access_and_saved_replay(connected):
    app, client, made, get, post, action = connected
    sid = made["session_id"]
    assert client.get("/sessions/" + sid).status_code == 401
    assert "tech_private" not in {m["id"] for m in get("/materials")}
    views = {r: app.state.store.project_view(sid, r) for r in ("supervisor", "tech_lead", "business_lead")}
    assert "tech_private" in {m.id for m in views["tech_lead"].permitted_materials}
    assert "tech_private" not in {m.id for m in views["supervisor"].permitted_materials}
    assert "technical" not in {m.id for m in views["business_lead"].permitted_materials}
    assert "business" not in {m.id for m in views["tech_lead"].permitted_materials}
    for role in views:
        body = {"role_id": role, "text": "请说明你知道的事实与边界。", "request_id": role}
        job = post("/turns", body)["job_id"]
        assert post("/turns", body)["job_id"] == job
        assert get("/jobs/" + job)["status"] == "queued"
        Worker(app.state.jobs, app.state.handlers).run_once()
        result = get("/jobs/" + job)
        assert result["status"] == "completed"
        assert result["result"]["role_id"] == role
        assert result["result"]["model_revision"] == "local-extractive-v1"
    seq = get()["state"]["version"]
    for _ in range(2):
        timeline = get("/timeline")
        assert timeline["mode"] == "saved_replay_no_model_calls"
        assert len(timeline["turns"]) == 3
    assert get()["state"]["version"] == seq
    other = client.post("/sessions", json={}).json()
    cross = client.get("/sessions/" + other["session_id"] + "/jobs/" + job, headers={"Authorization": "Bearer " + other["token"]})
    assert cross.status_code == 404


def test_config_staleness_retest_submission_feedback_and_evidence(connected):
    app, _, _, get, post, action = connected
    action("update_pilot", {"plan": pilot()}, "c1")
    first = post("/tests", {"query": "住宿报销上限是多少？", "config_version": 1, "request_id": "t1"})
    assert first["mode"] == "local-extractive"
    action("read_material", {"material_id": "business"}, "read")
    assert get()["state"]["material_versions"]["policy"] == 2
    stale = post("/tests", {"query": first["query"], "config_version": 1, "request_id": "t2"})
    assert stale["stale"] is True
    assert stale["citations"] == [{"material_id": "policy", "version": 1}]
    action("refresh_index", {}, "index")
    refreshed = post("/tests", {"query": first["query"], "config_version": 1, "request_id": "t3"})
    assert refreshed["stale"] is False
    assert refreshed["citations"] == [{"material_id": "policy", "version": 2}]
    assert refreshed["answer"] != stale["answer"]
    artifact = post("/artifacts", {"content": {"goal": "团队知识查询试点", "owner": "PM", "metrics": "记录有效解答率", "observation_window": "一周", "exit_condition": "严重错误暂停", "rationale": "依据测试与材料决定范围。"}, "request_id": "a1"})
    action("update_pilot", {"plan": pilot(participants=15)}, "c2")
    post("/submissions", {"artifact_id": artifact["id"], "config_version": 2, "request_id": "stale-artifact"}, 409)
    artifact2 = post("/artifacts", {"content": artifact["content"], "request_id": "a2"})
    body = {"artifact_id": artifact2["id"], "config_version": 2, "request_id": "submit"}
    submission = post("/submissions", body)
    assert post("/submissions", body) == submission
    assert get()["state"]["status"] == "submitted"
    post("/actions", {"tool": "resume", "arguments": {}, "expected_version": get()["state"]["version"], "request_id": "no-resume"}, 422)
    job = post("/feedback", {"submission_id": submission["id"]})["job_id"]
    Worker(app.state.jobs, app.state.handlers).run_once()
    report = get("/jobs/" + job)["result"]
    assert report == get("/feedback/" + submission["id"])
    assert report["summary"]["status"] == "pending_review"
    assert any(i["review_required"] for i in report["items"])
    for item in report["items"]:
        for eid in item["evidence_ids"]:
            ev = get("/evidence/" + submission["id"] + "/" + item["criterion_id"] + "/" + eid)
            assert ev["observed_at_seq"] <= submission["as_of_seq"]


def test_pause_resume_and_approval_are_explicit_actions(connected):
    _, _, _, get, post, action = connected
    action("pause", {}, "pause")
    assert get()["state"]["status"] == "paused"
    action("resume", {}, "resume")
    action("update_pilot", {"plan": pilot(participants=50)}, "config")
    action("request_capacity", {"reason": "为50名内部员工验证试点。"}, "request")
    assert get()["state"]["resources"]["capacity"] == 30
    body = {"rule_id": "capacity_approved", "request_id": "approval", "expected_version": get()["state"]["version"]}
    approved = post("/approvals/resolve", body)
    assert approved["authority"] == "scenario-supervisor-policy-v1"
    assert get()["state"]["resources"]["capacity"] == 60
    assert post("/approvals/resolve", body) == approved


def test_failed_role_job_has_bounded_retries_and_a_new_request_can_recover(connected):
    app, _, _, get, post, _ = connected
    class FailingModel:
        revision = "failing-test-only"
        def complete(self, messages, tools):
            raise RuntimeError("controlled test failure")
    app.state.runtime.model = FailingModel()
    job = post("/turns", {"role_id": "supervisor", "text": "失败恢复测试", "request_id": "failure"})["job_id"]
    worker = Worker(app.state.jobs, app.state.handlers)
    for _ in range(3):
        worker.run_once()
    assert get("/jobs/" + job)["status"] == "failed"
    assert get("/jobs/" + job)["attempt"] == 3
    app.state.runtime.model = LocalModel()
    retry = post("/turns", {"role_id": "supervisor", "text": "失败恢复测试", "request_id": "new-attempt"})["job_id"]
    assert retry != job
    worker.run_once()
    assert get("/jobs/" + retry)["status"] == "completed"


def test_existing_runtime_does_not_supply_cross_turn_conversation_memory(connected):
    app, _, _, _, post, _ = connected
    class RecordingModel:
        revision = "recording-test-only"
        def __init__(self):
            self.calls = []
        def complete(self, messages, tools):
            self.calls.append(messages.copy())
            return ModelReply(text="测试替身")
    model = RecordingModel()
    app.state.runtime.model = model
    worker = Worker(app.state.jobs, app.state.handlers)
    for key, text in (("one", "第一轮内容"), ("two", "第二轮内容")):
        post("/turns", {"role_id": "tech_lead", "text": text, "request_id": key})
        worker.run_once()
    assert len(model.calls) == 2
    assert [m["role"] for m in model.calls[1]] == ["system", "user"]
    assert "第一轮内容" not in str(model.calls[1])
