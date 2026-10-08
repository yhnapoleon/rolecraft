"""Normalized-classifier fusion and advisory rule reconciliation; never world writes."""

import numpy as np
from career_lab.contracts.v2.core import ProtocolError
from .core import LABELS, probabilities, prediction, abstention, checked_input


def blend(left, right, alpha, item, revision="unregistered-fusion", threshold=0.5):
    if item.task_type != "relation":
        raise ProtocolError("relation_fusion_only")
    if not np.isfinite(alpha) or not 0 <= alpha <= 1:
        raise ProtocolError("invalid_blend_weight")
    if alpha in (0.0, 1.0):
        from dataclasses import replace

        selected = left if alpha == 0 else right
        selected.validate(item)
        if selected.status != "ok":
            return replace(selected, model_revision=revision)
        ev = dict(selected.evidence_probabilities)
        if ev.keys() != {c.id for c in item.evidence.candidate_evidence}:
            raise ProtocolError("fusion_evidence_identity_mismatch")
        return prediction(
            item,
            revision,
            selected.probabilities,
            [ev[c.id] for c in item.evidence.candidate_evidence],
            threshold,
        )
    left.validate(item)
    right.validate(item)
    if left.status != "ok" or right.status != "ok":
        return abstention(item, revision, "fusion_component_unavailable")
    a = np.array(probabilities(left.probabilities, "relation"))
    b = np.array(probabilities(right.probabilities, "relation"))
    ea = dict(left.evidence_probabilities)
    eb = dict(right.evidence_probabilities)
    expected = {c.id for c in item.evidence.candidate_evidence}
    if ea.keys() != expected or eb.keys() != expected:
        raise ProtocolError("fusion_evidence_identity_mismatch")
    return prediction(
        item,
        revision,
        (1 - alpha) * a + alpha * b,
        [(1 - alpha) * ea[c.id] + alpha * eb[c.id] for c in item.evidence.candidate_evidence],
        threshold,
    )


class FusionCandidate:
    kind = "probability_fusion"

    def __init__(self, left, right, alpha, threshold=0.5):
        if (
            not isinstance(alpha, (int, float))
            or not np.isfinite(alpha)
            or not 0 <= alpha <= 1
            or not isinstance(threshold, (int, float))
            or not np.isfinite(threshold)
            or not 0 <= threshold <= 1
        ):
            raise ProtocolError("fusion_parameters_invalid")
        self.left, self.right, self.alpha, self.threshold = left, right, alpha, threshold
        self.task_type = "relation"
        self.revision = f"fusion:{left.revision}:{right.revision}:{alpha}"

    def predict(self, item):
        if self.alpha == 0:
            p = self.left.predict(item)
            return blend(p, p, 0, item, self.revision, self.threshold)
        if self.alpha == 1:
            p = self.right.predict(item)
            return blend(p, p, 1, item, self.revision, self.threshold)
        return blend(
            self.left.predict(item),
            self.right.predict(item),
            self.alpha,
            item,
            self.revision,
            self.threshold,
        )


def select_alpha(dev, left, right, policy=None):
    from career_lab.models.v3.core import training_examples
    from career_lab.experiments.v3.training.metrics import grade, summarize
    from career_lab.experiments.v3.training.selection import SelectionPolicy, choose_dev, rank_key

    policy = (policy or SelectionPolicy()).validate()
    rows = training_examples(dev, "relation", split="dev", require_all_classes=False)
    inputs = [(r, left.predict(r.item), right.predict(r.item)) for r in rows]
    grid = []
    # Stable tie order prefers threshold 0.5, then nearest alternatives; the
    # complete ordering is part of the predeclared selection policy/result.
    thresholds = sorted(policy.evidence_thresholds, key=lambda x: (abs(x - 0.5), x))
    for alpha in policy.alpha_grid:
        for threshold in thresholds:
            metrics = summarize(
                [grade(r, blend(a, b, alpha, r.item, threshold=threshold)) for r, a, b in inputs],
                "relation",
            )
            grid.append(
                {
                    "id": f"alpha={alpha};threshold={threshold}",
                    "alpha": alpha,
                    "threshold": threshold,
                    "metrics": metrics,
                    "cost": 1 if alpha in (0.0, 1.0) else 2,
                }
            )
    decision = choose_dev(grid, policy)
    winner = next((x for x in grid if x["id"] == decision["selected"]), None)
    endpoint = max(
        (x["metrics"]["joint_correctness"] or 0 for x in grid if x["alpha"] in (0.0, 1.0)),
        default=0,
    )
    return {
        "selection_split": "dev",
        "alpha": winner["alpha"] if winner else None,
        "evidence_threshold": winner["threshold"] if winner else None,
        "selection_status": decision["status"],
        "policy": decision["policy"],
        "grid": grid,
        "fusion_gain_observed": bool(
            winner
            and winner["alpha"] not in (0.0, 1.0)
            and winner["metrics"]["joint_correctness"] > endpoint
        ),
        "endpoint_selected": bool(winner and winner["alpha"] in (0.0, 1.0)),
        "dev_input_hashes": [r.annotation.input_hash for r in rows],
    }


def reconcile_advice(item, model_prediction):
    item = checked_input(item)
    model_prediction.validate(item)
    if item.task_type != "criterion":
        raise ProtocolError("criterion_reconciliation_only")
    package = item.evidence
    out = model_prediction.as_dict()
    out.update(rule_context_unchanged=True, rule_conflict=False, source="model_advice")
    if model_prediction.status != "ok":
        return out
    label = model_prediction.label
    if package.applicability != "applicable":
        out.update(
            status="abstained",
            label=None,
            reason_code="applicability_not_established",
            source="pending",
        )
    elif label in {"INSUFFICIENT", "NOT_APPLICABLE"}:
        out.update(source="pending")  # Neither label is placed on a MET/NOT_MET score scale.
    elif package.rule_bound:
        ordered = ("NOT_MET", "PARTIAL", "MET")
        bound = package.rule_bound
        if not ordered.index(bound.lower) <= ordered.index(label) <= ordered.index(bound.upper):
            out.update(
                status="abstained",
                label=None,
                reason_code="verified_rule_conflict",
                rule_conflict=True,
                source="pending",
            )
    return out
