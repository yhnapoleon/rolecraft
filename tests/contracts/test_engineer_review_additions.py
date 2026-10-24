"""Additive engineer-review-v1 fields: structured change claims and hidden comparison counts."""

import json

import pytest
from pydantic import JsonValue, ValidationError

from career_lab.contracts.v2 import AssistantConfig, canonical
from career_lab.contracts.v2.engineer import (
    CHANGE_FIELDS,
    EngineerSubmissionRecord,
    decode_engineer_document,
)
from career_lab.contracts.v2.engineer_examples import engineer_examples


def submission(**changes: JsonValue) -> dict[str, JsonValue]:
    value = engineer_examples()["EngineerSubmissionRecord"].model_dump(mode="json")
    return value | changes


def test_change_claims_roundtrip_and_serialize_only_when_present() -> None:
    claims = [
        {"field": "freshness_guard", "before": "none", "after": "warn", "reason": "Flag stale"},
        {"field": "work_items", "before": [], "after": ["human_fallback"]},
    ]
    record = decode_engineer_document("EngineerSubmission", canonical(submission(changes=claims)))
    assert isinstance(record, EngineerSubmissionRecord)
    assert [c.field for c in record.changes] == ["freshness_guard", "work_items"]
    assert record.changes[0].reason == "Flag stale" and record.changes[1].reason is None
    assert record.changes[1].after == ["human_fallback"]
    dumped = record.model_dump(mode="json")
    assert dumped["changes"][0] == {
        "schema_version": 2,
        "field": "freshness_guard",
        "before": "none",
        "after": "warn",
        "reason": "Flag stale",
    }
    assert decode_engineer_document("EngineerSubmission", record.model_dump_json()) == record
    empty = decode_engineer_document("EngineerSubmission", canonical(submission(changes=[])))
    assert empty.changes == () and "changes" not in empty.model_dump(mode="json")


@pytest.mark.parametrize(
    "field",
    ["id", "session_id", "version", "config_version", "min_score_calibration", "command", "x"],
)
def test_change_claims_reject_identity_calibration_and_unknown_fields(field: str) -> None:
    claims = [{"field": field, "before": 1, "after": 2}]
    with pytest.raises(ValidationError):
        decode_engineer_document("EngineerSubmission", canonical(submission(changes=claims)))


def test_change_claims_reject_duplicate_fields_and_long_reasons() -> None:
    twice = [
        {"field": "min_score", "before": 0.35, "after": 0.4},
        {"field": "min_score", "before": 0.4, "after": 0.5},
    ]
    with pytest.raises(ValidationError, match="duplicate change claim"):
        decode_engineer_document("EngineerSubmission", canonical(submission(changes=twice)))
    long = [{"field": "min_score", "before": 0.35, "after": 0.4, "reason": "x" * 501}]
    with pytest.raises(ValidationError):
        decode_engineer_document("EngineerSubmission", canonical(submission(changes=long)))


def test_change_fields_are_the_learner_editable_assistant_settings() -> None:
    reserved = {"id", "session_id", "version", "config_version", "min_score_calibration"}
    reserved.add("schema_version")  # the V2 envelope, not a setting
    assert set(CHANGE_FIELDS) == set(AssistantConfig.model_fields) - reserved
    assert len(CHANGE_FIELDS) == len(set(CHANGE_FIELDS))


def test_change_claims_strict_file_decode_accepts_json_values() -> None:
    claims = [{"field": "min_score", "before": 0.35, "after": 1, "reason": None}]
    raw = json.dumps(submission(changes=claims))
    record = EngineerSubmissionRecord.model_validate_json(raw, strict=True)
    assert record.changes[0].after == 1


def public_value(**comparison: int) -> dict[str, JsonValue]:
    value = engineer_examples()["EngineerPublicReport"].model_dump(mode="json")
    value["status"] = "incomplete"
    value["hidden"] = {"passed": 3, "failed": 2, "errors": 1}
    if comparison:
        value["hidden_comparison"] = comparison
    return value


def test_public_report_carries_consistent_hidden_comparison_counts() -> None:
    from career_lab.contracts.v2.engineer import EngineerPublicReport

    counts = {"new_failures": 1, "fixed": 2, "still_failing": 1, "unverified": 1}
    report = EngineerPublicReport.model_validate_json(canonical(public_value(**counts)))
    assert report.hidden_comparison is not None
    assert report.hidden_comparison.model_dump(mode="json") == {"schema_version": 2, **counts}
    assert report.model_dump(mode="json")["hidden_comparison"]["new_failures"] == 1
    absent = EngineerPublicReport.model_validate_json(canonical(public_value()))
    assert absent.hidden_comparison is None
    assert "hidden_comparison" not in absent.model_dump(mode="json")


@pytest.mark.parametrize(
    "counts",
    [
        {"new_failures": 2, "fixed": 0, "still_failing": 1, "unverified": 1},
        {"new_failures": 0, "fixed": 4, "still_failing": 0, "unverified": 1},
        {"new_failures": 0, "fixed": 0, "still_failing": 0, "unverified": 0},
        {"new_failures": 1, "fixed": 3, "still_failing": 1, "unverified": 2},
        {"new_failures": -1, "fixed": 0, "still_failing": 0, "unverified": 1},
    ],
    ids=["failures_exceed_failed", "fixed_exceeds_passed", "errors_not_unverified", "sum", "neg"],
)
def test_public_report_rejects_inconsistent_hidden_comparison(counts: dict[str, int]) -> None:
    from career_lab.contracts.v2.engineer import EngineerPublicReport

    with pytest.raises(ValidationError):
        EngineerPublicReport.model_validate_json(canonical(public_value(**counts)))


def private_value(hidden: list[str], comparison: dict[str, int] | None) -> dict[str, JsonValue]:
    """The example report plus hidden rows with the given candidate results."""
    from career_lab.contracts.v2 import digest
    from career_lab.contracts.v2.engineer import EngineerReviewInput

    value = engineer_examples()["EngineerRegressionReport"].model_dump(mode="json")
    template = value["results"][0]
    for index, result in enumerate(hidden):
        row = json.loads(json.dumps(template)) | {
            "probe_id": f"hidden-{index}",
            "visibility": "hidden",
            "result": result,
        }
        if result == "error":
            row.update(actual=None, error_code="engineer_probe_execution_failed")
        value["results"].append(row)
    value["input"]["probe_ids"] = [row["probe_id"] for row in value["results"]]
    value["input_hash"] = digest(EngineerReviewInput.model_validate(value["input"]))
    if "error" in hidden:
        value["status"] = "incomplete"
    if comparison is not None:
        value["hidden_comparison"] = comparison
    return value


def test_private_report_hidden_comparison_is_checked_and_projected_verbatim() -> None:
    from career_lab.contracts.v2.engineer import EngineerRegressionReport, public_engineer_report

    counts = {"new_failures": 1, "fixed": 1, "still_failing": 0, "unverified": 1}
    report = EngineerRegressionReport.model_validate(
        private_value(["fail", "pass", "pass", "error"], counts)
    )
    public = public_engineer_report(report)
    assert public.hidden_comparison == report.hidden_comparison
    raw = public.model_dump_json()
    assert all(f"hidden-{i}" not in raw for i in range(4))
    with pytest.raises(ValidationError):
        EngineerRegressionReport.model_validate(
            private_value(["fail", "pass"], {**counts, "unverified": 0, "still_failing": 1})
        )
