"""Sessions keep the rubric they were created with when the installation moves to the final one."""

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career_lab.api.vertical_runtime import create_runtime_app, default_installed_scenario
from career_lab.jobs.worker import Worker

ROOT = Path(__file__).resolve().parents[2]
# The installation that preceded the final rubric; kept as history and as the archive source.
PREVIOUS = ROOT / "scenarios/pm_pilot/v2/candidates/semantic-rules-v1-2.9.6/pm_pilot"


class Session:
    def __init__(self, app, client, created, language):
        self.app, self.client, self.language = app, client, language
        self.sid = created["session_id"]
        self.headers = {"Authorization": "Bearer " + created["token"]}
        self.binding = created["binding"]

    def get(self, path):
        return self.client.get(f"/sessions/{self.sid}/{path}", headers=self.headers)

    def post(self, path, key, operation, payload):
        state = self.get("").json()["state"]
        return self.client.post(
            f"/sessions/{self.sid}/{path}",
            headers=self.headers,
            json={
                "schema_version": 2,
                "request_id": key,
                "expected_version": state["business_seq"],
                "expected_workspace_revision": state["workspace_revision"],
                "operation": operation,
                "payload": payload,
            },
        )

    def submit_and_read_feedback(self):
        made = self.post(
            "work-products",
            "work",
            "work_products.create",
            {
                "kind": "text",
                "purpose": "commitment",
                "title": "Pilot decision" if self.language == "en" else "试点决定",
                "content": "Defer until the scope is verified."
                if self.language == "en"
                else "范围核实前暂缓。",
            },
        )
        assert made.status_code == 200, made.text
        product = next(ref for ref in made.json()["objects"] if ref["kind"] == "product")
        submitted = self.post(
            "submissions",
            "submit",
            "submissions.create",
            {"decision": "defer_with_conditions", "products": [product]},
        )
        assert submitted.status_code == 200, submitted.text
        assert Worker(self.app.state.jobs, self.app.state.handlers).run_once()
        subject = submitted.json()["result"]["submission"]["object_id"]
        return subject, self.get("feedback/" + subject).json()


def start(app, language):
    client = TestClient(app)
    created = client.post(
        "/sessions",
        json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
    )
    assert created.status_code == 200, created.text
    return Session(app, client, created.json(), language)


def evaluation_sha(root: Path) -> str:
    return hashlib.sha256((root / "runtime/evaluation.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_existing_session_keeps_candidate_rubric_and_new_session_uses_final(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    monkeypatch.delenv("CAREER_LAB_SCENARIO_CATALOG", raising=False)
    monkeypatch.delenv("CAREER_LAB_SCENARIO_V2", raising=False)
    previous = PREVIOUS if language == "zh" else PREVIOUS / "locales/en"
    current = default_installed_scenario()
    current = current if language == "zh" else current / "locales/en"
    database = "sqlite:///" + str(tmp_path / "shared.db")

    before = create_runtime_app(database, scenario_root=previous)
    try:
        old = start(before, language)
        subject, old_feedback = old.submit_and_read_feedback()
    finally:
        before.state.store.close()
        before.state.v2_store.db.engine.dispose()
    report = old_feedback["result"]["result"]["items"][0]
    assert report["provenance"]["evaluation_version"] == "feedback-rubric-v2-c2.1"
    assert report["evaluation"]["sha256"] == evaluation_sha(previous)

    after = create_runtime_app(database, scenario_root=current)
    try:
        old.app, old.client = after, TestClient(after)
        assert old.get("feedback/" + subject).json() == old_feedback
        context = old.get("workbench").json()["result"]["result"]
        assert (
            context["read_only"]
            and context["session"]["scenarioHash"] == (old.binding["scenarioHash"])
        )
        denied = old.post(
            "work-products",
            "after-switch",
            "work_products.create",
            {"kind": "text", "title": "x", "content": "blocked"},
        )
        assert denied.status_code == 409 and denied.json()["code"] == "scenario_read_only"
        assert old.get("feedback/" + subject).json() == old_feedback

        new = start(after, language)
        assert new.binding["scenarioHash"] != old.binding["scenarioHash"]
        _, new_feedback = new.submit_and_read_feedback()
        fresh = new_feedback["result"]["result"]["items"][0]
        assert fresh["provenance"]["evaluation_version"] == "feedback-rubric-v2-final.1"
        assert fresh["evaluation"]["sha256"] == evaluation_sha(current)
        assert json.loads((current / "runtime/evaluation.json").read_bytes())["rubric"][
            "sha256"
        ] == ("aa0de4302ca42368a262dc516fd3d8dab83286dd10dff7350c35b0c3772321cd")
    finally:
        after.state.store.close()
        after.state.v2_store.db.engine.dispose()
