"""Read immutable final definitions and the policies a final-rubric installation binds.

Installing them into a scenario package is a separate, explicit formal rebind.
"""

import argparse
import hashlib
import json
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Literal

from pydantic import JsonValue, TypeAdapter

from career_lab.contracts.v2 import FeedbackV2, digest
from career_lab.evidence.v2.ports import CriterionPolicy
from career_lab.rubrics.evaluation_identity import FINAL_DEFINITIONS, FINAL_EVALUATION_VERSION

DEFINITIONS = FINAL_DEFINITIONS
FILES = {
    "aipm": "rubric-v2-final-20261009.json",
    "engineer": "engineer-rubric-v1-final-20261009.json",
}
FINAL_RUBRIC_REVISION = "rubric-v2-final-20261009"
JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


def load_final_definition(role: Literal["aipm", "engineer"] = "aipm") -> dict[str, JsonValue]:
    """Verify the frozen artifact before returning its annotation definition."""
    return _load_artifact(role)[0]


def _load_artifact(role: Literal["aipm", "engineer"]) -> tuple[dict[str, JsonValue], str]:
    if role not in FILES:
        raise ValueError("Unknown rubric role")
    manifest = json.loads((DEFINITIONS / "manifest-final-20261009.json").read_text())
    raw = (DEFINITIONS / FILES[role]).read_bytes()
    expected = manifest["files"][FILES[role]]
    if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
        raise ValueError("Final rubric identity mismatch")
    value = JSON_OBJECT.validate_json(raw)
    if (
        value.get("status") != "final"
        or value.get("role") != role
        or value.get("revision") != expected["revision"]
    ):
        raise ValueError("Final rubric status or role mismatch")
    return value, expected["sha256"]


def final_definition_bytes() -> bytes:
    """The approved AIPM definition file, byte for byte, after its manifest identity check."""
    _load_artifact("aipm")
    return (DEFINITIONS / FILES["aipm"]).read_bytes()


def final_policies(*, work_language: str = "zh") -> tuple[CriterionPolicy, ...]:
    """Fourteen policies carrying the final five-label conditions as their description.

    Installation checks them against the candidate rule flags in
    rubric_v2.installed_final_policies, which imports this module.
    """
    if work_language not in {"zh", "en"}:
        raise ValueError("fixed language required")
    definition = load_final_definition("aipm")
    return tuple(
        CriterionPolicy(
            row[work_language]["id"],
            row[work_language]["description"],
            row[work_language]["mechanism"],
            tuple(row[work_language]["purposes"]),
            row[work_language]["launch_only"],
        )
        for row in definition["criteria"]
    )


def criterion_weights(definition: dict[str, JsonValue]) -> dict[str, "Fraction"]:
    """Allocate the original dimension weights over the fixed, complete criterion set."""
    dimensions = definition["dimension_weights"]
    criteria = definition["criteria"]
    if not isinstance(dimensions, dict) or not isinstance(criteria, list):
        raise ValueError("Invalid rubric weight definition")
    if any(type(value) is not int or value <= 0 for value in dimensions.values()):
        raise ValueError("Dimension weights must be positive integers")
    entries: list[tuple[str, str]] = []
    for row in criteria:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError("Invalid criterion identity")
        dimension = row.get("dimension")
        if not isinstance(dimension, str) or dimension not in dimensions:
            raise ValueError("Invalid criterion dimension")
        entries.append((row["id"], dimension))
    if len(entries) != len({identifier for identifier, _ in entries}):
        raise ValueError("Duplicate rubric criterion")
    counts = Counter(dimension for _, dimension in entries)
    if set(counts) != set(dimensions):
        raise ValueError("Every declared dimension must have canonical criteria")
    weights = {
        identifier: Fraction(dimensions[dimension], counts[dimension])
        for identifier, dimension in entries
    }
    if sum(weights.values(), Fraction()) != 100:
        raise ValueError("The original coverage denominator must remain 100")
    return weights


def coverage_report(report: FeedbackV2) -> dict[str, JsonValue]:
    """Describe existing rule bounds; never infer labels, regrade work or enable scoring."""
    if report.read_projection is not None:
        raise ValueError("A partial feedback projection is not a saved original")
    definition, definition_sha = _load_artifact("aipm")
    weights = criterion_weights(definition)
    rules = {item.criterion: item for item in report.rule_items or ()}
    items = {item.criterion: item for item in report.items}
    if (
        set(rules) != set(weights)
        or set(items) != set(weights)
        or len(report.rule_items or ()) != len(rules)
        or len(report.items) != len(items)
    ):
        raise ValueError("Coverage requires all canonical criterion and rule results exactly once")
    groups: dict[str, list[str]] = {
        "rule_calibrated": [],
        "model_advice": [],
        "pending": [],
        "not_applicable": [],
    }
    intervals: dict[str, JsonValue] = {}
    order = {"NOT_MET": 0, "PARTIAL": 1, "MET": 2}
    for identifier, rule in rules.items():
        final = items[identifier]
        bound = rule.rule_bound
        if rule.applicability == "undetermined":
            group = "pending"
            intervals[identifier] = None
        elif rule.label == "NOT_APPLICABLE":
            if rule.applicability != "not_applicable" or final.applicability != "not_applicable":
                raise ValueError("Inconsistent not-applicable result")
            group = "not_applicable"
            intervals[identifier] = None
        else:
            intervals[identifier] = (
                {"lower": bound.lower, "upper": bound.upper, "source": "verified_rule"}
                if rule.source == "verified_rule" and bound is not None
                else {"lower": "NOT_MET", "upper": "MET", "source": "unresolved"}
            )
            if final.source == "model_advice" and final.label in order and bound is not None:
                if not order[bound.lower] <= order[final.label] <= order[bound.upper]:
                    raise ValueError("Model advice cannot override a verified rule bound")
            if (
                rule.source == "verified_rule"
                and rule.applicability == "applicable"
                and bound is not None
                and bound.lower == bound.upper == rule.label
            ):
                group = "rule_calibrated"
            elif (
                final.source == "model_advice"
                and final.applicability == "applicable"
                and final.label in order
            ):
                group = "model_advice"
            else:
                group = "pending"
        groups[group].append(identifier)
    totals = {
        name: sum((weights[identifier] for identifier in identifiers), Fraction())
        for name, identifiers in groups.items()
    }
    installed = (
        report.provenance is not None
        and report.provenance.evaluation_version == FINAL_EVALUATION_VERSION
    )
    return {
        "weight_definition_revision": definition["revision"],
        "weight_definition_sha256": definition_sha,
        "definition_installed": installed,
        "source_provenance": report.provenance.model_dump(mode="json")
        if report.provenance
        else None,
        "source_feedback_id": report.id,
        "source_feedback_sha256": digest(report),
        "source_evaluation": report.evaluation.model_dump(mode="json"),
        "scope": (
            "final-definition weights applied to feedback produced under the installed "
            "final definition"
            if installed
            else "final-definition weights applied to existing feedback; "
            "that feedback was not produced under the final definition"
        ),
        "denominator": 100,
        "criterion_weight_fractions": {name: str(weight) for name, weight in weights.items()},
        **{name + "_weight": float(weight) for name, weight in totals.items()},
        "criterion_groups": groups,
        "reference": 45,
        "difference_from_45": float(totals["rule_calibrated"] - 45),
        "reference_is_gate": False,
        "runtime_count_coverage": report.verified_coverage,
        "status": "unscorable" if len(groups["not_applicable"]) == len(weights) else "reported",
        "single_total_score": None,
        "score_intervals": intervals,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feedback", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; keep prior measurements and choose a new path")
    try:
        raw = args.feedback.read_bytes()
        payload = json.loads(raw)
        report = FeedbackV2.model_validate(payload.get("report", payload))
        result = coverage_report(report)
    except (OSError, ValueError, AttributeError):
        parser.error("A complete saved feedback record and valid final definition are required")
    result["source_file_sha256"] = hashlib.sha256(raw).hexdigest()
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("Rule-calibrated coverage:", result["rule_calibrated_weight"], "/ 100")


if __name__ == "__main__":
    main()
