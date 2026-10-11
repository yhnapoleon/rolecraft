"""Decision 5 (2026-10-11): the rule-anchored range uses the installed rubric's frozen weights."""

import json
from fractions import Fraction

import pytest
from pydantic import ValidationError

from career_lab.contracts.v2 import EvaluationBundle, FeedbackItem, FeedbackV2, RuleBound
from career_lab.contracts.v2.evaluation import _RuleScoreCriterion, _RuleScoreRange
from career_lab.rubrics.v4.feedback import score_bounds
from career_lab.rubrics.v4.score_range import (
    frozen_weights,
    installed_rubric,
    rule_score_range,
)
from career_lab.scenarios.v2.release import ROOT

CANDIDATES = ROOT / "scenarios/pm_pilot/v2/candidates"
FINAL_PACKAGE = CANDIDATES / "rubric-final-v1-2.9.6/pm_pilot"
CANDIDATE_PACKAGE = CANDIDATES / "semantic-rules-v1-2.9.6/pm_pilot"
FINAL_SHA256 = "aa0de4302ca42368a262dc516fd3d8dab83286dd10dff7350c35b0c3772321cd"


def installed(package):
    bundle = EvaluationBundle.model_validate_json(
        (package / "runtime/evaluation.json").read_bytes()
    )
    return installed_rubric(package, bundle)


FINAL, FINAL_SHA = installed(FINAL_PACKAGE)
CRITERIA = [row["id"] for row in FINAL["criteria"]]
# Exact per-criterion weights the installed file implies (10/25/20/20/15/10 split evenly).
WEIGHT = {
    "R1.target": Fraction(5),
    "R1.metrics": Fraction(5),
    "R2.support": Fraction(25, 3),
    "R2.unknowns": Fraction(25, 3),
    "R2.failure_analysis": Fraction(25, 3),
    "R3.capacity": Fraction(10),
    "R3.resources": Fraction(10),
    "R4.functional_tests": Fraction(10),
    "R4.staleness_test": Fraction(10),
    "R5.impact": Fraction(15, 2),
    "R5.adjustment": Fraction(15, 2),
    "R6.consistency": Fraction(10, 3),
    "R6.operations": Fraction(10, 3),
    "R6.alternatives": Fraction(10, 3),
}


def anchored(criterion, label):
    return FeedbackItem(
        criterion=criterion,
        label=label,
        applicability="applicable",
        source="verified_rule",
        explanation="rule",
        citations=(),
        rule_bound=RuleBound(lower=label, upper=label),
    )


def bounded(criterion, lower, upper):
    return FeedbackItem(
        criterion=criterion,
        label=lower,
        applicability="applicable",
        source="verified_rule",
        explanation="rule",
        citations=(),
        rule_bound=RuleBound(lower=lower, upper=upper),
    )


def pending(criterion, applicability="applicable"):
    return FeedbackItem(
        criterion=criterion,
        label="INSUFFICIENT",
        applicability=applicability,
        source="pending",
        explanation="pending",
        citations=(),
    )


def not_applicable(criterion):
    return FeedbackItem(
        criterion=criterion,
        label="NOT_APPLICABLE",
        applicability="not_applicable",
        source="verified_rule",
        explanation="n/a",
        citations=(),
    )


def close(value, expected):
    return value == pytest.approx(float(expected), abs=1e-9)


def test_weights_are_read_from_the_installed_rubric_file():
    assert FINAL_SHA == FINAL_SHA256
    assert FINAL["dimension_weights"] == {
        "R1": 10,
        "R2": 25,
        "R3": 20,
        "R4": 20,
        "R5": 15,
        "R6": 10,
    }
    assert frozen_weights(FINAL) == WEIGHT
    # Changing the file's weights changes the range: nothing is hard-coded.
    changed = json.loads(json.dumps(FINAL))
    changed["dimension_weights"] = {"R1": 25, "R2": 10, "R3": 20, "R4": 20, "R5": 15, "R6": 10}
    items = [anchored(c, "MET") if c.startswith("R1.") else pending(c) for c in CRITERIA]
    first = rule_score_range(items, FINAL, FINAL_SHA)
    second = rule_score_range(items, changed, FINAL_SHA)
    assert first is not None and second is not None
    assert close(first.lower, 10) and close(second.lower, 25)


def test_mixed_outcomes_tighten_only_where_rules_are_verified():
    items = [
        anchored("R1.target", "MET"),
        bounded("R1.metrics", "NOT_MET", "PARTIAL"),
        pending("R2.support"),
        anchored("R2.unknowns", "NOT_MET"),
        not_applicable("R2.failure_analysis"),
        anchored("R3.capacity", "MET"),
        anchored("R3.resources", "PARTIAL"),
        pending("R4.functional_tests"),
        not_applicable("R4.staleness_test"),
        not_applicable("R5.impact"),
        pending("R5.adjustment", "undetermined"),
        bounded("R6.consistency", "PARTIAL", "MET"),
        pending("R6.operations"),
        anchored("R6.alternatives", "NOT_MET"),
    ]
    found = rule_score_range(items, FINAL, FINAL_SHA)
    assert found is not None
    lower = WEIGHT["R1.target"] + WEIGHT["R3.capacity"] + WEIGHT["R3.resources"] / 2
    lower += WEIGHT["R6.consistency"] / 2
    pending_weight = (
        WEIGHT["R2.support"]
        + WEIGHT["R4.functional_tests"]
        + WEIGHT["R5.adjustment"]
        + WEIGHT["R6.operations"]
    )
    upper = (
        WEIGHT["R1.target"]
        + WEIGHT["R1.metrics"] / 2
        + WEIGHT["R3.capacity"]
        + WEIGHT["R3.resources"] / 2
        + WEIGHT["R6.consistency"]
        + pending_weight
    )
    denominator = 100 - WEIGHT["R2.failure_analysis"] - WEIGHT["R4.staleness_test"]
    denominator -= WEIGHT["R5.impact"]
    assert close(found.lower, lower) and close(found.upper, upper)
    assert close(found.denominator, denominator)
    assert found.rubric_revision == "rubric-v2-final-20261009"
    assert found.rubric_sha256 == FINAL_SHA256
    rows = {row.criterion: row for row in found.criteria}
    assert [row.criterion for row in found.criteria] == CRITERIA
    assert {name: row.status for name, row in rows.items()} == {
        "R1.target": "anchored",
        "R1.metrics": "bounded",
        "R2.support": "pending",
        "R2.unknowns": "anchored",
        "R2.failure_analysis": "not_applicable",
        "R3.capacity": "anchored",
        "R3.resources": "anchored",
        "R4.functional_tests": "pending",
        "R4.staleness_test": "not_applicable",
        "R5.impact": "not_applicable",
        "R5.adjustment": "undetermined",
        "R6.consistency": "bounded",
        "R6.operations": "pending",
        "R6.alternatives": "anchored",
    }
    assert close(rows["R1.metrics"].lower, 0) and close(rows["R1.metrics"].upper, 2.5)
    assert close(rows["R3.resources"].lower, 5) and close(rows["R3.resources"].upper, 5)
    # Pending, undetermined and not-applicable criteria carry a weight, never points.
    for name in ("R2.support", "R5.adjustment", "R2.failure_analysis"):
        assert rows[name].lower is None and rows[name].upper is None
        assert close(rows[name].weight, WEIGHT[name])


def test_all_met_is_a_narrow_range():
    found = rule_score_range([anchored(c, "MET") for c in CRITERIA], FINAL, FINAL_SHA)
    assert found is not None
    assert close(found.lower, 100) and close(found.upper, 100) and close(found.denominator, 100)


def test_all_pending_spans_the_full_width():
    found = rule_score_range([pending(c) for c in CRITERIA], FINAL, FINAL_SHA)
    assert found is not None
    assert close(found.lower, 0) and close(found.upper, 100) and close(found.denominator, 100)
    undetermined = rule_score_range(
        [pending(c, "undetermined") for c in CRITERIA], FINAL, FINAL_SHA
    )
    assert undetermined is not None
    assert close(undetermined.lower, 0) and close(undetermined.upper, 100)
    assert {row.status for row in undetermined.criteria} == {"undetermined"}


def test_not_applicable_leaves_the_denominator_without_rescaling():
    excluded = {"R4.functional_tests", "R4.staleness_test", "R5.impact", "R5.adjustment"}
    items = [not_applicable(c) if c in excluded else pending(c) for c in CRITERIA]
    found = rule_score_range(items, FINAL, FINAL_SHA)
    assert found is not None
    assert close(found.denominator, 65)
    assert close(found.lower, 0) and close(found.upper, 65)
    met = [not_applicable(c) if c in excluded else anchored(c, "MET") for c in CRITERIA]
    full = rule_score_range(met, FINAL, FINAL_SHA)
    assert full is not None and close(full.lower, 65) and close(full.upper, 65)


def test_nothing_applicable_has_no_range():
    found = rule_score_range([not_applicable(c) for c in CRITERIA], FINAL, FINAL_SHA)
    assert found is not None
    assert found.denominator == 0 and found.lower is None and found.upper is None


def test_candidate_two_rubric_has_no_range():
    candidate, sha = installed(CANDIDATE_PACKAGE)
    assert (
        candidate["dimension_weights"] == "original_weights_pending_confirmation_no_aggregate_score"
    )
    assert frozen_weights(candidate) is None
    assert rule_score_range([anchored(c, "MET") for c in CRITERIA], candidate, sha) is None


def test_model_advice_never_narrows_the_range():
    # The range reads only rule results: a pending rule stays full width whatever advice says.
    rules = [pending(c) for c in CRITERIA]
    advised = FeedbackItem(
        criterion="R2.support",
        label="MET",
        applicability="applicable",
        source="model_advice",
        explanation="advice",
        citations=(),
    )
    found = rule_score_range(rules, FINAL, FINAL_SHA)
    assert found is not None and close(found.lower, 0) and close(found.upper, 100)
    with_advice = [advised if item.criterion == "R2.support" else item for item in rules]
    again = rule_score_range(with_advice, FINAL, FINAL_SHA)
    assert again is not None and close(again.lower, 0) and close(again.upper, 100)
    assert {row.criterion: row.status for row in again.criteria}["R2.support"] == "pending"


def test_rule_results_must_match_the_installed_criteria():
    # A scoped review evaluates only some criteria: no range over the whole rubric.
    assert rule_score_range([pending(c) for c in CRITERIA[:-1]], FINAL, FINAL_SHA) is None
    assert rule_score_range([anchored("R6.alternatives", "MET")], FINAL, FINAL_SHA) is None
    with pytest.raises(ValueError, match="every canonical rule result"):
        rule_score_range([pending(c) for c in [*CRITERIA, CRITERIA[0]]], FINAL, FINAL_SHA)
    with pytest.raises(ValueError, match="every canonical rule result"):
        rule_score_range([pending(c) for c in [*CRITERIA, "R6.comparison"]], FINAL, FINAL_SHA)


def test_contract_rejects_single_totals_and_points_on_non_rule_criteria():
    found = rule_score_range([pending(c) for c in CRITERIA], FINAL, FINAL_SHA)
    assert found is not None
    data = found.model_dump(mode="json")
    with pytest.raises(ValidationError):
        _RuleScoreCriterion(criterion="R2.support", weight=8.5, status="pending", lower=0, upper=8)
    with pytest.raises(ValidationError):
        _RuleScoreCriterion(criterion="R1.target", weight=5, status="anchored", lower=0, upper=5)
    with pytest.raises(ValidationError):
        _RuleScoreRange.model_validate({**data, "lower": 10})
    with pytest.raises(ValidationError):
        _RuleScoreRange.model_validate({**data, "upper": None})
    with pytest.raises(ValidationError):
        _RuleScoreRange.model_validate({**data, "denominator": 90})
    with pytest.raises(ValidationError):
        _RuleScoreRange.model_validate({**data, "total": 50})


def test_diagnostic_bounds_share_the_rule_interval():
    report = score_bounds([anchored("R1.target", "PARTIAL"), pending("R2.support")])
    assert report["criteria"]["R1.target"] == {"lower": 0.5, "upper": 0.5}
    assert report["criteria"]["R2.support"] == {"lower": 0.0, "upper": 1.0}
    # The engine's diagnostics stay unaggregated; the weighted range is attached on write.
    assert report["aggregation"] == "not_aggregated_without_frozen_weights"


def test_feedback_without_a_range_keeps_its_bytes():
    example = ROOT / "docs/contracts/expansion-v3/examples/FeedbackV2.json"
    raw = json.loads(example.read_text())
    report = FeedbackV2.model_validate(raw)
    assert report.score_range is None
    assert "score_range" not in report.model_dump(mode="json")
    assert json.loads(report.model_dump_json()) == raw
