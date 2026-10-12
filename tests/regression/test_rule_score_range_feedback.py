"""Decision 5 (2026-10-11): final-rubric feedback records its rule-anchored range; c2 none."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts.v2 import EvaluationBundle, FeedbackV2
from career_lab.contracts.v2.projection import project_feedback_content
from career_lab.rubrics.v4.score_range import installed_rubric, rule_score_range

from .conftest import PublishedSession
from .test_rubric_final_rebind import FINAL_SHA256, FINAL_SOURCE, LANGUAGE_ROOTS, SOURCE

FINAL_ROOTS = {"zh": FINAL_SOURCE, "en": FINAL_SOURCE / "locales/en"}


def launch_feedback(root: Path, directory: Path, language: str) -> dict[str, object]:
    """Launch with the current configuration, as the v4 submit control sends it."""
    app = create_runtime_app(
        "sqlite:///" + str(directory / "session.db"), provider="local", scenario_root=root
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                "/sessions",
                json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
            )
            assert response.status_code == 200, response.text
            created = response.json()
            session = PublishedSession(
                app,
                client,
                created["session_id"],
                {"Authorization": "Bearer " + created["token"]},
                language,
            )
            work = session.work()
            config = session.get("timeline").json()["result"]["result"]["workspace"]["config"]
            saved = session.send(
                "submissions",
                "submit",
                "submissions.create",
                {
                    "decision": "launch",
                    "products": [work],
                    "config": {
                        "session_id": session.session_id,
                        "kind": "config",
                        "object_id": config["id"],
                        "version": config["version"],
                        "config_version": config["config_version"],
                    },
                },
            )
            session.run_job()
            subject = saved["result"]["submission"]["object_id"]
            return session.get("feedback/" + subject).json()["result"]["result"]["items"][0]
    finally:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_final_rubric_feedback_records_the_rule_anchored_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    root = FINAL_ROOTS[language]
    feedback = launch_feedback(root, tmp_path, language)
    report = FeedbackV2.model_validate(feedback)
    found = report.score_range
    assert found is not None
    assert found.rubric_revision == "rubric-v2-final-20261009"
    assert found.rubric_sha256 == FINAL_SHA256
    # Mixed outcomes: capacity and resources met, no tests run, change items not applicable.
    statuses = {row.criterion: row.status for row in found.criteria}
    assert statuses["R3.capacity"] == statuses["R3.resources"] == "anchored"
    assert statuses["R4.functional_tests"] == "anchored"
    assert {statuses[c] for c in ("R4.staleness_test", "R5.impact", "R5.adjustment")} == {
        "not_applicable"
    }
    assert statuses["R2.support"] == "pending"
    assert (found.lower, found.upper, found.denominator) == pytest.approx((20, 65, 75))
    # The stored range is exactly the one computed from the installed file and the rule results.
    bundle = EvaluationBundle.model_validate_json((root / "runtime/evaluation.json").read_bytes())
    definition, sha = installed_rubric(root, bundle)
    assert report.rule_items is not None
    assert rule_score_range(report.rule_items, definition, sha) == found
    # A range with its denominator, never a single total.
    assert set(feedback["score_range"]) == {
        "schema_version",
        "rubric_revision",
        "rubric_sha256",
        "denominator",
        "lower",
        "upper",
        "criteria",
    }


@pytest.mark.parametrize("language", ["zh", "en"])
def test_candidate_two_feedback_has_no_range_and_keeps_its_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    feedback = launch_feedback(SOURCE / LANGUAGE_ROOTS[language], tmp_path, language)
    assert feedback["provenance"]["evaluation_version"] == "feedback-rubric-v2-c2.1"
    assert "score_range" not in feedback
    assert FeedbackV2.model_validate(feedback).model_dump(mode="json") == feedback


def test_partial_projection_withholds_a_range_it_can_no_longer_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    feedback = launch_feedback(FINAL_ROOTS["zh"], tmp_path, "zh")
    cited = {
        (ref["kind"], ref["object_id"])
        for item in feedback["rule_items"]
        if item["criterion"] == "R3.capacity"
        for ref in item["citations"]
    }
    assert cited
    full, changed = project_feedback_content(feedback, lambda ref: True)
    assert not changed and full["score_range"] == feedback["score_range"]
    projected, changed = project_feedback_content(
        feedback, lambda ref: (ref["kind"], ref["object_id"]) not in cited
    )
    assert changed and projected["read_projection"] == "partial"
    assert "score_range" not in projected
    FeedbackV2.model_validate(projected)
