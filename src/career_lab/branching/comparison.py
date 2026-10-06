"""Paired descriptive comparisons, preserving every regression and unknown."""
from dataclasses import dataclass
import math

from career_lab.contracts.v2 import BranchManifest, FileRef, Lineage, ProtocolError


@dataclass(frozen=True)
class EvaluatedRun:
    run: FileRef
    session_id: str
    lineage: Lineage
    split: str
    evaluation: FileRef
    runtime: FileRef
    seed: int
    metrics: dict[str, float | None]
    completed: bool | None
    model_calls: int | None
    cost: float | None


def compare_runs(parent: EvaluatedRun, child: EvaluatedRun, branch: BranchManifest, *, directions):
    if (parent.lineage.session_id != parent.session_id or not parent.lineage.run_id
            or parent.lineage.run_id not in branch.lineage.source_record_ids):
        raise ProtocolError("comparison_parent_lineage_mismatch")
    if parent.run != branch.parent_run:
        raise ProtocolError("comparison_parent_mismatch")
    if parent.evaluation != child.evaluation or child.evaluation != branch.evaluation:
        raise ProtocolError("comparison_evaluation_mismatch", status=409)
    if (child.lineage.branch_id != branch.id or child.lineage != branch.lineage
            or child.session_id == parent.session_id or child.session_id != branch.lineage.session_id):
        raise ProtocolError("comparison_child_identity_mismatch")
    if (parent.lineage.structure_id != child.lineage.structure_id
            or parent.lineage.component_id != child.lineage.component_id
            or parent.split != child.split or child.split != branch.split):
        raise ProtocolError("comparison_lineage_or_split_mismatch")
    if child.runtime != branch.runtime:
        raise ProtocolError("continuation_runtime_mismatch")
    reasons = []
    if parent.runtime != child.runtime:
        reasons.append("continuation_runtime_differs")
    if parent.seed != child.seed:
        reasons.append("seed_differs")
    rows = []
    for name in sorted(parent.metrics.keys() | child.metrics.keys()):
        a, b = parent.metrics.get(name), child.metrics.get(name)
        for value in (a, b):
            if value is not None and (type(value) not in {int, float} or not math.isfinite(value)):
                raise ProtocolError("comparison_nonfinite_metric")
        if directions.get(name) not in {"higher", "lower"}:
            raise ProtocolError("metric_direction_required")
        delta = b - a if a is not None and b is not None else None
        assessment = "unknown" if delta is None else "unchanged"
        if delta:
            assessment = "improved" if (delta > 0) == (directions[name] == "higher") else "regressed"
        rows.append({"metric": name, "parent": a, "child": b, "delta": delta, "direction": directions[name],
                     "assessment": assessment})
    return {"branch_id": branch.id, "grouping_unit": "parent_run",
            "parent_run": parent.run.model_dump(mode="json"), "structure_id": parent.lineage.structure_id,
            "scope": "simulated_intervention_not_human_causal_evidence",
            "comparison": "descriptive_only" if reasons else "matched_simulation_comparison",
            "confounds": reasons, "metrics": rows, "parent_completed": parent.completed,
            "child_completed": child.completed, "parent_model_calls": parent.model_calls,
            "child_model_calls": child.model_calls, "parent_cost": parent.cost, "child_cost": child.cost,
            "intervention": branch.intervention.model_dump(mode="json"),
            "evaluation": branch.evaluation.model_dump(mode="json"),
            "human_learning_effect": "not_measured"}
