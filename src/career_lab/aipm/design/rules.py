"""Small, closed predicates. Public evidence is supplied by the installed adapter.

No text classifier, generated verdict, business mutation or client capability claim.
The private rule file is server-only; only individual public findings leave here.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from career_lab.contracts.v2 import EvidenceRefV2, ObjectRef, canonical


@dataclass(frozen=True)
class DesignFacts:
    """Trusted, same-window facts resolved by the installer, never by a request body."""

    public_sources: Mapping[str, tuple[EvidenceRefV2, ...]] = field(default_factory=dict)
    # Exact need identity -> authored scope; unknown user needs stay unknown.
    need_scopes: Mapping[str, str] = field(default_factory=dict)
    capabilities: frozenset[tuple[str, str]] = frozenset()
    requested_config: Mapping[str, object] = field(default_factory=dict)
    effective_config: Mapping[str, object] = field(default_factory=dict)
    config_ref: ObjectRef | None = None


PREDICATES = frozenset(
    {"ai_final_approval", "elapsed_as_labor", "tool_unavailable", "config_difference"}
)


def load_rules(path: Path) -> tuple[dict, ...]:
    data = json.loads(path.read_text())
    if data.get("schema_version") != 1:
        raise ValueError("unsupported design grading version")
    rules = data["rules"]
    ids = set()
    for rule in rules:
        required = {
            "id",
            "revision",
            "applies_when",
            "required_public_sources",
            "predicate",
            "severity",
            "zh_feedback",
            "en_feedback",
            "false_positive_examples",
        }
        if not required <= rule.keys() or rule["predicate"] not in PREDICATES:
            raise ValueError("unknown or incomplete design predicate")
        if rule["id"] in ids or rule["severity"] not in {"violation", "improve", "unknown"}:
            raise ValueError("invalid design rule")
        ids.add(rule["id"])
    return tuple(rules)


def need_key(value: object) -> str:
    return value if isinstance(value, str) else canonical(value)


def execution_support(row: dict, facts: DesignFacts) -> str:
    scope = facts.need_scopes.get(need_key(row.get("need_ref")))
    if scope is None:
        return "unknown"
    if (scope, row["target_action"]) in facts.capabilities and not row.get("tool_assumptions"):
        return "supported"
    return "plan_only"


def evaluate_design(
    design: dict, input_ref: ObjectRef, facts: DesignFacts, rules: tuple[dict, ...], language: str
) -> tuple[list[dict], list[dict]]:
    """Return normalized rows and findings; source_refs are copied without rebasing."""
    rows = [
        dict(row, execution_support=execution_support(row, facts)) for row in design.get("rows", [])
    ]
    findings: list[dict] = []

    def emit(rule, location, step, basis, *, finding=None, message=None):
        wording = rule[f"{language}_feedback"]
        findings.append(
            {
                "id": f"{input_ref.object_id}-{input_ref.version}-{rule['id']}-{location}",
                "input_ref": input_ref.model_dump(mode="json"),
                "step_id": step,
                "section_or_row_id": location,
                "rule_revision": rule["revision"],
                "source": "rule",
                "finding": finding or rule["severity"],
                "message": message or wording["message"],
                "basis_refs": [ref.model_dump(mode="json") for ref in basis],
                "checked_scope": wording["checked_scope"],
                "next_action": wording["next_action"],
                "stale": False,
                "affects_formal_score": False,
            }
        )

    for rule in rules:
        required = rule["required_public_sources"]
        basis = tuple(ref for key in required for ref in facts.public_sources.get(key, ()))
        available = all(facts.public_sources.get(key) for key in required)
        predicate = rule["predicate"]
        if predicate in {"ai_final_approval", "tool_unavailable"}:
            for row in rows:
                scope = facts.need_scopes.get(need_key(row.get("need_ref")))
                if scope not in rule["applies_when"]["scopes"]:
                    continue
                if predicate == "ai_final_approval":
                    matches = row["target_action"] == "approve" and row["final_authority"] == "ai"
                else:
                    matches = (
                        row["route"] == "agent_confirmation"
                        and row["execution_support"] != "supported"
                    )
                if matches and available:
                    emit(rule, row["id"], "boundary", basis)
        elif predicate == "elapsed_as_labor" and available:
            for need in design.get("needs", []):
                metric = need.get("metric") or {}
                # Text is never parsed as a formula or a semantic claim.
                if (
                    metric.get("source_field") == "elapsed_minutes"
                    and metric.get("kind") == "labor_time"
                ):
                    emit(rule, need["id"], "need", basis)
        elif predicate == "config_difference" and available:
            if any(
                key in facts.effective_config and value != facts.effective_config[key]
                for key, value in facts.requested_config.items()
            ):
                emit(rule, "solution", "solution", basis)
    for row in rows:
        if not any(item["section_or_row_id"] == row["id"] for item in findings):
            known = facts.need_scopes.get(need_key(row.get("need_ref"))) is not None
            # Passing a finite rule is never a claim of overall correctness.
            findings.append(
                {
                    "id": f"{input_ref.object_id}-{input_ref.version}-scope-{row['id']}",
                    "input_ref": input_ref.model_dump(mode="json"),
                    "step_id": "boundary",
                    "section_or_row_id": row["id"],
                    "source": "rule",
                    "finding": "unknown",
                    "message": (
                        "未发现已核实的权限冲突；方案质量仍待核对。"
                        if known
                        else "这项自由需求没有匹配的核实依据，请补充来源与权限。"
                    )
                    if language == "zh"
                    else (
                        "No verified authority conflict found; the design still needs review."
                        if known
                        else "No verified basis matches this custom need. Add sources and authority."
                    ),
                    "basis_refs": [],
                    "checked_scope": "declared_fields_only",
                    "stale": False,
                    "affects_formal_score": False,
                }
            )
    return rows, findings


def feedback_is_stale(
    input_ref: ObjectRef,
    current_ref: ObjectRef,
    dependencies: tuple[ObjectRef, ...],
    current_heads: Mapping[tuple[str, str], int],
) -> bool:
    return input_ref != current_ref or any(
        current_heads.get((r.kind, r.object_id), r.version) != r.version for r in dependencies
    )
