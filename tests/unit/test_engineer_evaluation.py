"""E1-E5 rule conclusions from a trusted review, built through the production report builder."""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pytest

from career_lab.contracts import v2 as C
from career_lab.contracts.v2 import (
    AssistantConfig,
    AuthContext,
    EffectiveConfig,
    FileRef,
    VersionPoint,
    digest,
)
from career_lab.contracts.v2.engineer import (
    EngineerClaimedReport,
    EngineerProbeExpectation,
    EngineerProbeResult,
    EngineerRegressionReport,
    EngineerReviewInput,
    EngineerSubmissionRecord,
)
from career_lab.contracts.v2.engineer_evaluation import (
    CRITERIA,
    LABEL_ORDER,
    RUBRIC_REVISION,
    EngineerRuleEvaluation,
)
from career_lab.contracts.v2.examples import sample_model
from career_lab.engineer.evaluation import evaluate_review
from career_lab.engineer.files import encode, file_ref
from career_lab.engineer.review import build_report
from career_lab.engineer.review_inputs import ReviewContext

BASE = sample_model(AssistantConfig).model_copy(update={"domains": ("policy",)})
POINT = sample_model(VersionPoint)
PACK = FileRef(path="pack.json", sha256="1" * 64)
HIDDEN = "hidden-probe"


@dataclass(frozen=True)
class Review:
    report: EngineerRegressionReport
    record: EngineerSubmissionRecord
    candidate: AssistantConfig
    claimed: EngineerClaimedReport | None

    def evaluate(self) -> EngineerRuleEvaluation:
        return evaluate_review(self.report, self.record, BASE, self.candidate, claimed=self.claimed)


def row(
    probe_id: str, result: str, resolved: EffectiveConfig, *, error: str | None = None
) -> EngineerProbeResult:
    query = "q-" + probe_id
    actual = sample_model(C.TestResultV2).model_copy(
        update={"config": resolved, "query": query, "as_of": POINT}
    )
    return EngineerProbeResult(
        probe_id=probe_id,
        visibility="hidden" if probe_id.startswith(HIDDEN) else "public",
        query=query,
        expected=EngineerProbeExpectation(status="answered"),
        actual=None if result == "error" else actual,
        result=result,
        config_hash=digest(resolved.effective),
        elapsed_seconds=0,
        error_code=(error or "engineer_probe_execution_failed") if result == "error" else None,
    )


def make_review(
    outcomes: dict[str, tuple[str, str]],
    *,
    targets: Sequence[str] = ("F1",),
    settings: dict[str, Any] | None = None,
    changes: Sequence[dict[str, Any]] = (),
    claim: dict[str, str] | None = None,
    unresolved: Sequence[dict[str, Any]] = (),
) -> Review:
    """outcomes: probe ID -> (original result, candidate result); IDs starting 'hidden-' hide."""
    candidate = BASE.model_copy(update=settings or {})
    resolved = EffectiveConfig(requested=candidate, effective=candidate)
    candidate_ref = file_ref("candidate.json", encode(candidate))
    files: dict[str, bytes] = {}
    claim_ref = None
    if claim is not None:
        files["claim.json"] = encode(
            {
                "contract_version": "engineer-review-v1",
                "id": "claimed",
                "pack": PACK,
                "config": candidate_ref,
                "created_at": "2026-10-09T00:00:00Z",
                "results": [{"probe_id": k, "result": v} for k, v in claim.items()],
            }
        )
        claim_ref = file_ref("claim.json", files["claim.json"])
    record = EngineerSubmissionRecord.model_validate(
        {
            "contract_version": "engineer-review-v1",
            "id": "repair",
            "pack": PACK,
            "config": candidate_ref,
            "base_config_hash": hashlib.sha256(encode(BASE)).hexdigest(),
            "regression_report": claim_ref,
            "unresolved": list(unresolved),
            "explanation": "free text",
            "executor": {"id": "learner", "kind": "human"},
            "created_at": "2026-10-09T00:00:00Z",
            "work_language": "en",
            "changes": list(changes),
        }
    )
    files["submission.json"] = encode(record)
    inputs = EngineerReviewInput(
        contract_version="engineer-review-v1",
        pack=PACK,
        baseline_config=file_ref("baseline.json", encode(BASE)),
        config=candidate_ref,
        scenario=PACK,
        probe_suite=PACK,
        reviewer_version=PACK,
        resource_snapshot=PACK,
        submission=file_ref("submission.json", files["submission.json"]),
        probe_ids=tuple(outcomes),
        source_as_of=POINT,
        resolved_config=resolved,
        work_language="en",
        model=None,
    )
    context = ReviewContext(inputs, files, record, None, (), tuple("q-" + t for t in targets))
    report = build_report(
        context,
        sample_model(AuthContext),
        tuple(row(k, v[0], resolved) for k, v in outcomes.items()),
        tuple(row(k, v[1], resolved) for k, v in outcomes.items()),
    )
    claimed = (
        EngineerClaimedReport.model_validate_json(files["claim.json"])
        if claim is not None
        else None
    )
    return Review(report, record, candidate, claimed)


def conclusion(review: Review, criterion: str) -> Any:
    return review.evaluate().conclusion(criterion)


def test_labels_and_criteria_come_from_the_final_engineer_rubric() -> None:
    from career_lab.rubrics.v4.final_rubric import load_final_definition

    definition = load_final_definition("engineer")
    assert RUBRIC_REVISION == definition["revision"]
    assert LABEL_ORDER == tuple(definition["label_order"])
    assert CRITERIA == tuple(row["id"] for row in definition["criteria"])
    modes = {row["id"]: row["evaluation_mode"] for row in definition["criteria"]}
    evaluation = make_review({"F1": ("fail", "pass")}).evaluate()
    assert [c.criterion for c in evaluation.criteria] == list(CRITERIA)
    for item in evaluation.criteria:
        assert item.basis == modes[item.criterion]
    assert evaluation.rubric_revision == RUBRIC_REVISION
    assert evaluation.affects_score is False


@pytest.mark.parametrize(
    "outcomes,targets,label,reason,probes",
    [
        ({"F1": ("fail", "pass"), "F2": ("pass", "pass")}, ("F1",), "MET", "targets_repaired", 1),
        (
            {"F1": ("fail", "pass"), "F2": ("fail", "fail")},
            ("F1", "F2"),
            "PARTIAL",
            "targets_partially_repaired",
            1,
        ),
        ({"F1": ("fail", "fail")}, ("F1",), "NOT_MET", "targets_not_repaired", 1),
        ({"F1": ("fail", "error")}, ("F1",), "INSUFFICIENT", "target_verification_incomplete", 1),
        ({"F1": ("pass", "pass")}, ("F1",), "INSUFFICIENT", "target_baseline_not_failing", 1),
        (
            {"F1": ("fail", "pass")},
            ("F1", "missing"),
            "INSUFFICIENT",
            "target_without_trusted_probe",
            0,
        ),
        ({"F1": ("fail", "pass")}, (), "NOT_APPLICABLE", "no_targets", 0),
    ],
    ids=["met", "partial", "not_met", "error", "baseline_passing", "no_probe", "no_targets"],
)
def test_e1_target_fixed(
    outcomes: dict[str, tuple[str, str]],
    targets: tuple[str, ...],
    label: str,
    reason: str,
    probes: int,
) -> None:
    result = conclusion(make_review(outcomes, targets=targets), "E1.target_fixed")
    assert result.label == label and result.basis == "rule" and result.status == "concluded"
    assert reason in result.reason_codes
    assert len(result.probe_ids) == probes


def test_e1_hidden_target_is_counted_without_its_id() -> None:
    review = make_review(
        {"F1": ("fail", "pass"), HIDDEN + "-1": ("fail", "fail")}, targets=("F1", HIDDEN + "-1")
    )
    result = conclusion(review, "E1.target_fixed")
    assert result.label == "PARTIAL"
    assert result.probe_ids == () and result.hidden_probes == 1
    assert HIDDEN not in review.evaluate().model_dump_json()


def test_e2_hidden_new_failure_is_not_met_despite_target_repair() -> None:
    review = make_review({"F1": ("fail", "pass"), HIDDEN + "-1": ("pass", "fail")})
    result = conclusion(review, "E2.no_regressions")
    assert result.label == "NOT_MET" and "new_failures_found" in result.reason_codes
    assert result.probe_ids == () and result.hidden_probes == 1
    assert conclusion(review, "E1.target_fixed").label == "MET"
    assert HIDDEN not in review.evaluate().model_dump_json()


@pytest.mark.parametrize(
    "outcomes,label,reason,public",
    [
        ({"F1": ("fail", "pass"), "F2": ("pass", "pass")}, "MET", "no_new_failures", ()),
        (
            {"F1": ("fail", "pass"), "F2": ("pass", "fail")},
            "NOT_MET",
            "new_failures_found",
            ("F2",),
        ),
        (
            {"F1": ("fail", "pass"), "F2": ("pass", "error")},
            "INSUFFICIENT",
            "regression_coverage_incomplete",
            ("F2",),
        ),
        (
            {"F1": ("pass", "fail"), "F2": ("error", "pass")},
            "NOT_MET",
            "new_failures_found",
            ("F1",),
        ),
    ],
    ids=["met", "public_failure", "error", "failure_beats_error"],
)
def test_e2_no_regressions(
    outcomes: dict[str, tuple[str, str]], label: str, reason: str, public: tuple[str, ...]
) -> None:
    result = conclusion(make_review(outcomes), "E2.no_regressions")
    assert result.label == label and reason in result.reason_codes
    assert result.probe_ids == public


FRESH = {"field": "freshness_guard", "before": "none", "after": "warn"}


@pytest.mark.parametrize(
    "settings,changes,label,reason,checks",
    [
        (
            {"freshness_guard": "warn"},
            [FRESH],
            "MET",
            "changes_match_diff",
            {"freshness_guard": "matched"},
        ),
        (
            {"freshness_guard": "warn", "retrieval_limit": 5},
            [FRESH],
            "PARTIAL",
            "changes_omitted",
            {"freshness_guard": "matched", "retrieval_limit": "omitted"},
        ),
        (
            {"freshness_guard": "warn"},
            [FRESH | {"before": "fallback"}],
            "NOT_MET",
            "change_claims_contradicted",
            {"freshness_guard": "before_mismatch"},
        ),
        (
            {"freshness_guard": "warn"},
            [FRESH | {"after": "fallback"}],
            "NOT_MET",
            "change_claims_contradicted",
            {"freshness_guard": "after_mismatch"},
        ),
        (
            {},
            [FRESH],
            "NOT_MET",
            "change_claims_contradicted",
            {"freshness_guard": "change_not_made"},
        ),
        (
            {"freshness_guard": "warn"},
            [FRESH | {"after": "none"}],
            "NOT_MET",
            "change_claims_contradicted",
            {"freshness_guard": "change_denied"},
        ),
        ({"freshness_guard": "warn"}, [], "INSUFFICIENT", "change_claims_not_provided", {}),
        (
            {},
            [{"field": "min_score", "before": 0.35, "after": 0.35}],
            "MET",
            "changes_match_diff",
            {"min_score": "matched"},
        ),
        (
            {"scope_filter": False},
            [{"field": "scope_filter", "before": 1, "after": 0}],
            "NOT_MET",
            "change_claims_contradicted",
            {"scope_filter": "values_mismatch"},
        ),
    ],
    ids=[
        "met",
        "omitted",
        "wrong_before",
        "wrong_after",
        "claimed_not_made",
        "claimed_unchanged",
        "free_text_only",
        "unchanged_claim_zero_diff",
        "json_types_strict",
    ],
)
def test_e3_change_consistency(
    settings: dict[str, Any],
    changes: list[dict[str, Any]],
    label: str,
    reason: str,
    checks: dict[str, str],
) -> None:
    result = conclusion(
        make_review({"F1": ("fail", "pass")}, settings=settings, changes=changes),
        "E3.change_consistency",
    )
    assert result.label == label and reason in result.reason_codes
    assert {c.field: c.status for c in result.field_checks} == checks


def test_e3_compares_values_numerically_and_lists_in_order() -> None:
    settings = {"min_score": 1.0, "work_items": ("human_fallback", "scope_filter")}
    changes = [
        {"field": "min_score", "before": 0.35, "after": 1},
        {"field": "work_items", "before": [], "after": ["human_fallback", "scope_filter"]},
    ]
    review = make_review({"F1": ("fail", "pass")}, settings=settings, changes=changes)
    assert conclusion(review, "E3.change_consistency").label == "MET"
    reordered = [changes[0], changes[1] | {"after": ["scope_filter", "human_fallback"]}]
    review = make_review({"F1": ("fail", "pass")}, settings=settings, changes=reordered)
    assert conclusion(review, "E3.change_consistency").label == "NOT_MET"


@pytest.mark.parametrize(
    "outcomes,claim,label,reason,public",
    [
        (
            {"F1": ("fail", "pass"), "F2": ("pass", "fail")},
            {"F1": "pass", "F2": "fail"},
            "MET",
            "claim_reproduced",
            ("F1", "F2"),
        ),
        (
            {"F1": ("fail", "pass"), "F2": ("pass", "fail")},
            {"F1": "pass"},
            "PARTIAL",
            "claim_scope_partial",
            ("F2",),
        ),
        (
            {"F1": ("fail", "pass"), "F2": ("pass", "pass")},
            {"F1": "fail", "F2": "pass"},
            "NOT_MET",
            "claim_contradicts_rerun",
            ("F1",),
        ),
        (
            {"F1": ("fail", "pass")},
            {"F1": "pass", "F9": "pass"},
            "NOT_MET",
            "claim_outside_public_suite",
            (),
        ),
        ({"F1": ("fail", "pass")}, None, "INSUFFICIENT", "claim_not_provided", ()),
        (
            {"F1": ("fail", "pass"), "F2": ("pass", "error")},
            {"F1": "pass", "F2": "pass"},
            "INSUFFICIENT",
            "verification_incomplete",
            ("F2",),
        ),
    ],
    ids=["met", "partial_scope", "contradicted", "unknown_probe", "not_provided", "error"],
)
def test_e4_reproducibility(
    outcomes: dict[str, tuple[str, str]],
    claim: dict[str, str] | None,
    label: str,
    reason: str,
    public: tuple[str, ...],
) -> None:
    result = conclusion(make_review(outcomes, claim=claim), "E4.reproducibility")
    assert result.label == label and reason in result.reason_codes
    assert result.probe_ids == public


def test_e4_hidden_claim_is_not_echoed() -> None:
    review = make_review(
        {"F1": ("fail", "pass"), HIDDEN + "-1": ("pass", "pass")},
        claim={"F1": "pass", HIDDEN + "-1": "pass"},
    )
    result = conclusion(review, "E4.reproducibility")
    assert result.label == "NOT_MET" and "claim_outside_public_suite" in result.reason_codes
    assert HIDDEN not in review.evaluate().model_dump_json()


def test_e5_waits_for_model_with_rule_precheck_of_unexplained_failures() -> None:
    review = make_review(
        {
            "F1": ("fail", "pass"),
            "F2": ("fail", "fail"),
            "F3": ("pass", "fail"),
            "F4": ("pass", "error"),
            HIDDEN + "-1": ("pass", "fail"),
            HIDDEN + "-2": ("fail", "fail"),
        },
        unresolved=[
            {"id": "open-1", "description": "F3 needs a policy owner", "probe_ids": ["F3"]}
        ],
    )
    result = conclusion(review, "E5.remaining_explanation")
    assert result.status == "waiting_model" and result.label is None
    assert result.basis == "semantic_advice" and result.reason_codes == ("waiting_model",)
    assert result.precheck is not None and result.precheck.basis == "rule"
    assert result.precheck.unexplained_probe_ids == ("F2",)
    assert result.precheck.unexplained_hidden == 2
    assert HIDDEN not in review.evaluate().model_dump_json()


def test_inputs_must_be_the_reviewed_submission_and_configurations() -> None:
    review = make_review({"F1": ("fail", "pass")}, settings={"freshness_guard": "warn"})
    with pytest.raises(ValueError, match="candidate"):
        evaluate_review(review.report, review.record, BASE, BASE, claimed=None)
    other = BASE.model_copy(update={"retrieval_limit": 4})
    with pytest.raises(ValueError, match="baseline"):
        evaluate_review(review.report, review.record, other, review.candidate, claimed=None)
    changed = review.record.model_copy(update={"explanation": "different"})
    with pytest.raises(ValueError, match="submission"):
        evaluate_review(review.report, changed, BASE, review.candidate, claimed=None)
    claimed = make_review({"F1": ("fail", "pass")}, claim={"F1": "pass"})
    with pytest.raises(ValueError, match="claimed report"):
        evaluate_review(claimed.report, claimed.record, BASE, claimed.candidate, claimed=None)


def test_output_contract_rejects_mislabelled_conclusions() -> None:
    from pydantic import ValidationError

    value = make_review({"F1": ("fail", "pass")}).evaluate().model_dump(mode="json")
    broken = [dict(value, criteria=value["criteria"][:4])]
    e2_partial = [dict(c) for c in value["criteria"]]
    e2_partial[1]["label"] = "PARTIAL"
    broken.append(dict(value, criteria=e2_partial))
    e5_label = [dict(c) for c in value["criteria"]]
    e5_label[4]["label"] = "MET"
    broken.append(dict(value, criteria=e5_label))
    e1_unlabelled = [dict(c) for c in value["criteria"]]
    e1_unlabelled[0]["label"] = None
    broken.append(dict(value, criteria=e1_unlabelled))
    for item in broken:
        with pytest.raises(ValidationError):
            EngineerRuleEvaluation.model_validate(item)
    assert EngineerRuleEvaluation.model_validate(value).model_dump(mode="json") == value
