"""Final definition and diagnostic coverage; installed evaluator remains unchanged."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_w05_http_support import WorkSession
from test_w05_http_support import work_session as work_session

from career_lab.contracts import v2 as C
from career_lab.contracts.v2.projection import project_feedback_content
from career_lab.jobs.worker import Worker
from career_lab.rubrics.v4 import final_rubric
from career_lab.rubrics.v4.final_rubric import load_final_definition

CANONICAL = (
    "R1.target",
    "R1.metrics",
    "R2.support",
    "R2.unknowns",
    "R2.failure_analysis",
    "R3.capacity",
    "R3.resources",
    "R4.functional_tests",
    "R4.staleness_test",
    "R5.impact",
    "R5.adjustment",
    "R6.consistency",
    "R6.operations",
    "R6.alternatives",
)
LABELS = {"MET", "PARTIAL", "NOT_MET", "INSUFFICIENT", "NOT_APPLICABLE"}


def test_final_rubric_has_fourteen_specific_bilingual_five_state_definitions() -> None:
    definition = load_final_definition("aipm")
    assert definition["revision"] == "rubric-v2-final-20261009"
    assert definition["status"] == "final"
    assert tuple(row["id"] for row in definition["criteria"]) == CANONICAL
    assert definition["dimension_weights"] == {
        "R1": 10,
        "R2": 25,
        "R3": 20,
        "R4": 20,
        "R5": 15,
        "R6": 10,
    }
    for row in definition["criteria"]:
        for language in ("zh", "en"):
            conditions = row["label_conditions"][language]
            assert set(conditions) == LABELS
            for label, condition in conditions.items():
                assert (
                    condition.strip() and label + ": " + condition in row[language]["description"]
                )
            assert "MET须有完整支持；PARTIAL须有具体缺口" not in row[language]["description"]
            assert (
                "MET requires full support, PARTIAL a specific gap"
                not in row[language]["description"]
            )
    launch_duties = {
        "R3.capacity",
        "R3.resources",
        "R4.functional_tests",
        "R4.staleness_test",
        "R5.adjustment",
    }
    for row in definition["criteria"]:
        if row["id"] in launch_duties:
            assert row["zh"]["purposes"] == row["en"]["purposes"] == ["commitment", "result"]
    assert definition["publication"]["installed"] is False
    assert definition["score_policy"]["single_total_score"] is False
    assert definition["coverage_policy"]["denominator"] == 100
    assert definition["coverage_policy"]["reference_is_gate"] is False


def test_final_aliases_only_target_canonical_ids_and_engineer_has_five_items() -> None:
    definition = load_final_definition("aipm")
    assert set(definition["legacy_aliases"].values()) <= set(CANONICAL)
    engineer = load_final_definition("engineer")
    assert engineer["revision"] == "engineer-rubric-v1-final-20261009"
    assert len(engineer["criteria"]) == 5
    assert [row["rule_calibratable"] for row in engineer["criteria"]] == [
        True,
        True,
        True,
        True,
        False,
    ]
    assert engineer["score_policy"]["weights"] is None
    for row in engineer["criteria"]:
        for language in ("zh", "en"):
            assert set(row["label_conditions"][language]) == LABELS


@pytest.mark.parametrize("investigated", [False, True], ids=["no-investigation", "investigated"])
def test_no_go_preserves_applicable_duties_and_reports_coverage(
    work_session: WorkSession, investigated: bool, tmp_path: Path
) -> None:
    session = work_session
    if investigated:
        for material in ("brief", "technical"):
            session.post(
                "actions",
                "read_material",
                {
                    "tool": "read_material",
                    "material": {
                        "session_id": session.sid,
                        "kind": "material",
                        "object_id": material,
                        "version": 1,
                    },
                },
            )
        session.post(
            "tests",
            "tests.create",
            {
                "query": "住宿报销上限是多少？"
                if session.language == "zh"
                else "What is the hotel reimbursement limit per night?",
                "config_version": 0,
            },
        )
    text = (
        (
            "调查后建议不开展；保留停止依据、替代方案与后续复议。"
            if investigated
            else "目前决定不开展，依据仍待核实。"
        )
        if session.language == "zh"
        else (
            "After investigation, do not proceed; retain the basis, alternatives and follow-up."
            if investigated
            else "Do not proceed for now; the rationale remains unverified."
        )
    )
    product = session.product(text, purpose="commitment")
    config = session.get("timeline")["workspace"]["config"]
    ref = C.ObjectRef(
        session_id=session.sid,
        kind="config",
        object_id=config["id"],
        version=config["version"],
        config_version=config["config_version"],
    ).model_dump(mode="json")
    submitted = session.post(
        "submissions",
        "submissions.create",
        {"decision": "no_go", "products": [product], "config": ref},
    )
    assert Worker(session.app.state.jobs, session.app.state.handlers).run_once()
    recovered = session.get("requests/http-request-" + str(session.sequence))
    assert recovered["jobs"][0]["status"] == "completed", recovered
    report = C.FeedbackV2.model_validate(
        session.get("feedback/" + submitted["result"]["submission"]["object_id"])["items"][0]
    )
    assert len(report.items) == 14
    assert any(item.applicability == "applicable" for item in report.items)
    assert not all(item.label == "NOT_MET" for item in report.items)
    summary = final_rubric.coverage_report(report)
    assert summary["denominator"] == 100 and summary["single_total_score"] is None
    assert summary["weight_definition_revision"] == "rubric-v2-final-20261009"
    assert summary["weight_definition_sha256"]
    assert summary["definition_installed"] is False
    assert summary["source_provenance"]["evaluation_version"] == "feedback-rubric-v2-c2.1"
    projected, partial = project_feedback_content(
        report.model_dump(mode="json"), lambda ref: ref["kind"] != "material", limited_scope=True
    )
    assert partial is True
    with pytest.raises(ValueError, match="partial"):
        final_rubric.coverage_report(C.FeedbackV2.model_validate(projected))
    assert summary["rule_calibrated_weight"] == 0
    assert summary["not_applicable_weight"] < 100
    counts = report.verified_facts[0].activity_totals
    assert counts["test_run"].verified_records == int(investigated)
    assert counts["material_read"].verified_records == (2 if investigated else 0)
    if os.environ.get("RUBRIC_FINAL_EVIDENCE"):
        output = Path(os.environ["RUBRIC_FINAL_EVIDENCE"])
        output.mkdir(parents=True, exist_ok=True)
        name = session.language + ("-investigated" if investigated else "-no-investigation")
        (output / (name + ".json")).write_text(
            json.dumps(
                {"report": report.model_dump(mode="json"), "coverage": summary},
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )


def test_coverage_cli_retains_full_denominator_with_controlled_na_results(tmp_path: Path) -> None:
    # A controlled wire report checks arithmetic only, not scenario or model quality.
    at = C.VersionPoint(business_seq=0, workspace_revision=0, storage_revision=0)
    items = tuple(
        C.FeedbackItem(
            criterion=identifier,
            label="NOT_APPLICABLE",
            applicability="not_applicable",
            source="verified_rule",
            explanation="Controlled applicability input",
            citations=(),
        )
        for identifier in CANONICAL
    )
    report = C.FeedbackV2(
        id="controlled-coverage",
        session_id="controlled-session",
        subject=C.ObjectRef(
            session_id="controlled-session", kind="review", object_id="controlled-review", version=1
        ),
        evaluation=C.FileRef(path="controlled-evaluation.json", sha256="0" * 64),
        as_of=at,
        items=items,
        rule_items=items,
        business_response="Controlled coverage input",
        next_options=(),
        verified_coverage=0,
        model_coverage=0,
    )
    for kind, current in (
        ("all-na", report),
        (
            "one-rule",
            report.model_copy(
                update={
                    "items": tuple(
                        item.model_copy(
                            update={
                                "label": "MET",
                                "applicability": "applicable",
                                "rule_bound": C.RuleBound(lower="MET", upper="MET"),
                            }
                        )
                        if item.criterion == "R3.capacity"
                        else item
                        for item in items
                    ),
                    "rule_items": tuple(
                        item.model_copy(
                            update={
                                "label": "MET",
                                "applicability": "applicable",
                                "rule_bound": C.RuleBound(lower="MET", upper="MET"),
                            }
                        )
                        if item.criterion == "R3.capacity"
                        else item
                        for item in items
                    ),
                }
            ),
        ),
    ):
        source = tmp_path / (kind + ".json")
        output = tmp_path / (kind + "-coverage.json")
        source.write_text(json.dumps(current.model_dump(mode="json")))
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "career_lab.rubrics.v4.final_rubric",
                "--feedback",
                str(source),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        summary = json.loads(output.read_text())
        assert summary["denominator"] == 100 and summary["single_total_score"] is None
        if kind == "all-na":
            assert summary["status"] == "unscorable"
            assert (
                summary["rule_calibrated_weight"] == 0 and summary["not_applicable_weight"] == 100
            )
        else:
            assert summary["rule_calibrated_weight"] == 10
            assert summary["not_applicable_weight"] == 90
        assert summary["reference_is_gate"] is False


def test_undetermined_applicability_has_no_score_interval() -> None:
    items = tuple(
        C.FeedbackItem(
            criterion=identifier,
            label="INSUFFICIENT",
            applicability="undetermined",
            source="pending",
            explanation="Purpose unknown",
            citations=(),
        )
        for identifier in CANONICAL
    )
    report = C.FeedbackV2(
        id="controlled-unknown",
        session_id="controlled-session",
        subject=C.ObjectRef(
            session_id="controlled-session", kind="review", object_id="unknown-purpose", version=1
        ),
        evaluation=C.FileRef(path="controlled-evaluation.json", sha256="0" * 64),
        as_of=C.VersionPoint(business_seq=0, workspace_revision=0, storage_revision=0),
        items=items,
        rule_items=items,
        business_response="Purpose unknown",
        next_options=(),
        verified_coverage=0,
        model_coverage=0,
    )
    result = final_rubric.coverage_report(report)
    assert result["pending_weight"] == 100 and result["rule_calibrated_weight"] == 0
    assert all(value is None for value in result["score_intervals"].values())
