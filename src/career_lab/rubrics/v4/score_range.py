"""Weighted range of the rule-anchored rubric part (2026-10-11 decision 5).

The learner sees a range, never a single total, and model advice is never scored.
Weights come only from the rubric file installed with the evaluation; a candidate rubric
without frozen weights gets no range. A verified rule bound fixes its criterion's share;
every other applicable criterion (pending verification, model advice, undetermined
applicability) spans its full weight. Not-applicable criteria leave the denominator, and
the denominator is reported as it is rather than rescaled to 100.
"""

from collections.abc import Iterable, Mapping
from fractions import Fraction
from pathlib import Path

from pydantic import JsonValue, TypeAdapter

from career_lab.contracts.v2.core import read_file
from career_lab.contracts.v2.evaluation import FeedbackItem, _RuleScoreCriterion, _RuleScoreRange
from career_lab.contracts.v2.research import EvaluationBundle

from .final_rubric import criterion_weights

# Share of a criterion's weight that each rule label fixes.
LABEL_SHARE = {"NOT_MET": Fraction(0), "PARTIAL": Fraction(1, 2), "MET": Fraction(1)}
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


def rule_interval(item: FeedbackItem) -> tuple[Fraction, Fraction] | None:
    """The share interval a verified rule bound fixes for one applicable criterion."""
    if (
        item.applicability != "applicable"
        or item.source != "verified_rule"
        or item.rule_bound is None
    ):
        return None
    return LABEL_SHARE[item.rule_bound.lower], LABEL_SHARE[item.rule_bound.upper]


def installed_rubric(root: Path, bundle: EvaluationBundle) -> tuple[dict[str, JsonValue], str]:
    """The rubric file installed with this evaluation, checked against its recorded hash."""
    return _JSON_OBJECT.validate_json(read_file(root, bundle.rubric)), bundle.rubric.sha256


def frozen_weights(definition: Mapping[str, JsonValue]) -> dict[str, Fraction] | None:
    """Per-criterion weights of a final rubric; a candidate rubric has none to aggregate."""
    if definition.get("status") != "final" or not isinstance(
        definition.get("dimension_weights"), dict
    ):
        return None
    return criterion_weights(dict(definition))


def rule_score_range(
    rule_items: Iterable[FeedbackItem],
    definition: Mapping[str, JsonValue],
    rubric_sha256: str,
) -> _RuleScoreRange | None:
    """Aggregate recorded rule results with the installed weights; None without frozen ones."""
    weights = frozen_weights(definition)
    if weights is None:
        return None
    rows = list(rule_items)
    results = {item.criterion: item for item in rows}
    if len(results) != len(rows) or set(results) != set(weights):
        raise ValueError("A score range needs every canonical rule result exactly once")
    criteria = []
    denominator = lower = upper = Fraction(0)
    for criterion, weight in weights.items():
        item = results[criterion]
        if (item.label == "NOT_APPLICABLE") != (item.applicability == "not_applicable"):
            raise ValueError("Inconsistent not-applicable rule result")
        if item.applicability == "not_applicable":
            criteria.append(
                _RuleScoreCriterion(
                    criterion=criterion, weight=float(weight), status="not_applicable"
                )
            )
            continue
        denominator += weight
        interval = rule_interval(item)
        if interval is None:
            # Pending verification and model advice widen the range; they never score.
            upper += weight
            criteria.append(
                _RuleScoreCriterion(
                    criterion=criterion,
                    weight=float(weight),
                    status="undetermined" if item.applicability == "undetermined" else "pending",
                )
            )
            continue
        low, high = weight * interval[0], weight * interval[1]
        lower, upper = lower + low, upper + high
        criteria.append(
            _RuleScoreCriterion(
                criterion=criterion,
                weight=float(weight),
                status="anchored" if low == high else "bounded",
                lower=float(low),
                upper=float(high),
            )
        )
    revision = definition.get("revision")
    if not isinstance(revision, str):
        raise ValueError("Installed rubric revision missing")
    return _RuleScoreRange(
        rubric_revision=revision,
        rubric_sha256=rubric_sha256,
        denominator=float(denominator),
        lower=float(lower) if denominator else None,
        upper=float(upper) if denominator else None,
        criteria=tuple(criteria),
    )
