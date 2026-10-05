import pytest
from fastapi.testclient import TestClient

from career_lab.api.app import create_app
from career_lab.api.feedback import feedback_id, generate_feedback
from career_lab.evidence.assembler import EvidenceAssembler
from career_lab.jobs.worker import Worker
from career_lab.rubrics import checks, feedback


def submission_fixture(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'rubric-batch1.db'}")
    client = TestClient(app)
    created = client.post("/sessions", json={}).json()
    sid = created["session_id"]
    headers = {"Authorization": "Bearer " + created["token"]}
    plan = {"participants": 20, "knowledge_domains": ["stable_faq"], "launch_day": 7,
            "update_strategy": "daily", "fallback": "human", "work_items": ["scope_filter", "human_fallback"]}
    configured = client.post(f"/sessions/{sid}/actions", headers=headers, json={
        "tool": "update_pilot", "arguments": {"plan": plan}, "request_id": "config", "expected_version": 0,
    })
    assert configured.status_code == 200, configured.text
    artifact = client.post(f"/sessions/{sid}/artifacts", headers=headers,
                           json={"content": {"goal": "减少重复咨询"}, "request_id": "artifact"})
    assert artifact.status_code == 200, artifact.text
    submission = client.post(f"/sessions/{sid}/submissions", headers=headers, json={
        "artifact_id": artifact.json()["id"], "config_version": 1, "request_id": "submission",
    })
    assert submission.status_code == 200, submission.text
    return app, client, sid, headers, submission.json()


def feedback_job(app, client, sid, headers, submission, attempts=1):
    requested = client.post(f"/sessions/{sid}/feedback", headers=headers,
                            json={"submission_id": submission["id"]})
    assert requested.status_code == 200, requested.text
    worker = Worker(app.state.jobs, app.state.handlers)
    for _ in range(attempts):
        assert worker.run_once()
    result = client.get(f"/sessions/{sid}/jobs/{requested.json()['job_id']}", headers=headers)
    assert result.status_code == 200, result.text
    return result.json()


@pytest.mark.parametrize("overflow", [False, True])
def test_real_evidence_completeness_reaches_saved_feedback_and_job_api(tmp_path, monkeypatch, overflow):
    app, client, sid, headers, submission = submission_fixture(tmp_path)
    if overflow:
        # Exercise the assembler's real size check and no-truncation behavior.
        monkeypatch.setattr(feedback, "EvidenceAssembler", lambda store: EvidenceAssembler(store, token_budget=10))
        item = EvidenceAssembler(app.state.store, token_budget=10).assemble_item(submission["id"], "R3.resources", "oracle")
        assert item.completeness == "overflow"
        assert item.context is None and item.candidate_evidence == () and item.source_map == {}
    state_before = app.state.store.get_state(sid)
    result = feedback_job(app, client, sid, headers, submission)
    assert result["status"] == "completed", result
    report = result["result"]
    assert report["model_revision"] == submission["model_revision"] == "rules-v3"
    assert report["overflow"] is overflow
    assert all(item["completeness"] == ("overflow" if overflow else "complete") for item in report["items"])
    if overflow:
        assert all(item["reason"] == "证据超过长度上限，本项未评。" for item in report["items"])
        assert all(item["label"] == "INSUFFICIENT" and item["review_required"] for item in report["items"])
        assert report["summary"]["coverage"] == 0
        assert report["summary"]["lower"] == 0 and report["summary"]["upper"] == 1
    saved = client.get(f"/sessions/{sid}/feedback/{submission['id']}", headers=headers)
    assert saved.status_code == 200 and saved.json() == report
    assert app.state.store.get_state(sid) == state_before


def test_unreviewed_rules_v2_submission_fails_instead_of_using_current_rules(tmp_path, monkeypatch):
    with monkeypatch.context() as historical:
        historical.setattr(checks, "RULES_REVISION", "rules-v2")
        app, client, sid, headers, submission = submission_fixture(tmp_path)
    assert submission["model_revision"] == "rules-v2"
    with pytest.raises(ValueError, match="historical rules engine unavailable"):
        generate_feedback(app.state.store, sid, submission["id"])
    job = feedback_job(app, client, sid, headers, submission, attempts=3)
    assert job["status"] == "failed" and job["result"] is None
    assert app.state.store.list_objects(sid, "feedback") == []


def test_saved_rules_v2_feedback_remains_readable_and_is_not_regenerated(tmp_path, monkeypatch):
    with monkeypatch.context() as historical:
        historical.setattr(checks, "RULES_REVISION", "rules-v2")
        historical.setattr(feedback, "RULES_REVISION", "rules-v2")
        app, client, sid, headers, submission = submission_fixture(tmp_path)
        report = feedback.build_feedback(app.state.store, sid, submission["id"])
    # A pre-batch report lacks the new additive completeness fields.
    report.pop("overflow")
    for item in report["items"]:
        item.pop("completeness")
    app.state.store.save_derived(sid, feedback_id(app.state.store, sid, submission["id"]), "feedback", report)
    saved = client.get(f"/sessions/{sid}/feedback/{submission['id']}", headers=headers)
    assert saved.status_code == 200 and saved.json() == report
    assert generate_feedback(app.state.store, sid, submission["id"]) == report
    job = feedback_job(app, client, sid, headers, submission)
    assert job["status"] == "completed" and job["result"] == report
