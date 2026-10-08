"""Task-specific independent graders, explicit denominators and clustered comparisons."""

from collections import Counter, defaultdict
import numpy as np

from career_lab.contracts.v2.core import ProtocolError
from career_lab.models.v3.core import LABELS, Prediction
from career_lab.models.v3.temporal import legal_evidence_ids


def set_scores(selected, acceptable):
    selected = set(selected)
    scores = []
    for target in acceptable:
        target = set(target)
        if not selected and not target:
            scores.append((1.0, 1.0, 1.0))
            continue
        intersection = len(selected & target)
        precision = intersection / len(selected) if selected else 0.0
        recall = intersection / len(target) if target else 0.0
        f1 = 2 * intersection / (len(selected) + len(target)) if selected or target else 0.0
        scores.append((f1, precision, recall))
    return max(scores, default=(0.0, 0.0, 0.0))


def grade(example, prediction):
    example.validate()
    gold = example.annotation.final
    item = example.item
    base = {
        "record_id": example.record_id,
        "input_hash": example.annotation.input_hash,
        "task_type": item.task_type,
        "structure_id": example.structure_id,
        "component_id": example.component_id,
        "label_tier": example.annotation.label_tier,
        "language": example.language,
        "bucket": example.bucket,
        "gold": gold.label,
        "predicted": None,
        "status": "failed",
        "format_valid": False,
        "label_correct": False,
        "evidence_f1": 0.0,
        "evidence_precision": 0.0,
        "evidence_recall": 0.0,
        "joint_correct": False,
        "error_code": None,
    }
    if not gold.evidence_evaluable:
        base.update(
            evidence_f1=None, evidence_precision=None, evidence_recall=None, joint_correct=None
        )
    try:
        prediction.validate(item)
    except (ValueError, TypeError, AttributeError) as exc:
        code = getattr(exc, "code", "invalid_prediction")
        if code == "prediction_invalid_reference":
            return base | {
                "format_valid": True,
                "status": "invalid_reference",
                "predicted": prediction.label,
                "label_correct": prediction.label == gold.label,
                "error_code": code,
            }
        return base | {"error_code": code}
    base.update(format_valid=True, status=prediction.status, predicted=prediction.label)
    if prediction.status != "ok":
        return base | {"error_code": prediction.reason_code}
    correct = prediction.label == gold.label
    base["label_correct"] = correct
    if set(prediction.evidence_ids) - legal_evidence_ids(item):
        return base | {"status": "invalid_reference", "error_code": "invalid_evidence_time"}
    if not gold.evidence_evaluable:
        return base | {
            "evidence_f1": None,
            "evidence_precision": None,
            "evidence_recall": None,
            "joint_correct": None,
            "error_code": None if correct else "wrong_label",
        }
    f1, precision, recall = set_scores(prediction.evidence_ids, gold.acceptable_evidence_sets)
    joint = correct and f1 == 1.0
    return base | {
        "evidence_f1": f1,
        "evidence_precision": precision,
        "evidence_recall": recall,
        "joint_correct": joint,
        "error_code": None
        if joint
        else "wrong_label"
        if not correct
        else "incomplete_or_extra_evidence",
    }


def summarize(rows, task_type):
    labels = LABELS[task_type]
    rows = list(rows)
    if any(r["task_type"] != task_type for r in rows):
        raise ProtocolError("mixed_metric_tasks")
    total = len(rows)
    legal = [r for r in rows if r["format_valid"] and r["status"] == "ok"]
    matrix = {g: {p: 0 for p in (*labels, "NO_PREDICTION")} for g in labels}
    for row in rows:
        if row["gold"] not in labels:
            raise ProtocolError("metric_gold_namespace")
        matrix[row["gold"]][
            row["predicted"] if row["predicted"] in labels else "NO_PREDICTION"
        ] += 1
    per_class = {}
    for label in labels:
        tp = matrix[label][label]
        support = sum(matrix[label].values())
        predicted = sum(matrix[g][label] for g in labels)
        per_class[label] = {
            "support": support,
            "precision": tp / predicted if predicted else None,
            "recall": tp / support if support else None,
            "f1": 2 * tp / (support + predicted) if support + predicted else 0.0,
        }
    pos, neg = ("SUPPORTED", "CONTRADICTED") if task_type == "relation" else ("MET", "NOT_MET")

    def rate(g, p):
        targets = {p} if isinstance(p, str) else set(p)
        denominator = sum(r["gold"] == g for r in rows)
        return {
            "numerator": sum(r["gold"] == g and r["predicted"] in targets for r in rows),
            "denominator": denominator,
            "rate": sum(r["gold"] == g and r["predicted"] in targets for r in rows) / denominator
            if denominator
            else None,
        }

    joint = [r for r in rows if r["joint_correct"] is not None]
    evidence = [r for r in rows if r["evidence_f1"] is not None]
    return {
        "count": total,
        "fixed_labels": list(labels),
        "confusion": matrix,
        "per_class": per_class,
        "macro_f1": sum(v["f1"] for v in per_class.values()) / len(labels) if total else None,
        "accuracy": sum(r["label_correct"] for r in rows) / total if total else None,
        "legal_output_count": len(legal),
        "legal_output_accuracy": sum(r["label_correct"] for r in legal) / len(legal)
        if legal
        else None,
        "coverage": len(legal) / total if total else None,
        "format_failures": sum(not r["format_valid"] for r in rows),
        "abstentions": sum(r["status"] == "abstained" for r in rows),
        "invalid_references": sum(r["status"] == "invalid_reference" for r in rows),
        "infrastructure_failures": sum(
            r["status"] == "failed"
            and r["format_valid"]
            and r.get("failure_kind", "infrastructure") == "infrastructure"
            for r in rows
        ),
        "metric_version": "w08-evidence-metrics-v2",
        "false_deduction": rate(pos, {neg, "INSUFFICIENT"})
        if task_type == "relation"
        else rate(pos, neg),
        "supported_contradicted": rate("SUPPORTED", "CONTRADICTED")
        if task_type == "relation"
        else None,
        "supported_insufficient": rate("SUPPORTED", "INSUFFICIENT")
        if task_type == "relation"
        else None,
        "false_pass": rate(neg, pos),
        "insufficient_false_pass": rate("INSUFFICIENT", pos),
        "applicability_errors": sum(
            (r["gold"] == "NOT_APPLICABLE") != (r["predicted"] == "NOT_APPLICABLE") for r in legal
        )
        if task_type == "criterion"
        else None,
        "joint_denominator": len(joint),
        "joint_correctness": sum(bool(r["joint_correct"]) for r in joint) / len(joint)
        if joint
        else None,
        "evidence_denominator": len(evidence),
        "mean_evidence_f1": sum(r["evidence_f1"] for r in evidence) / len(evidence)
        if evidence
        else None,
        "errors": dict(Counter(r["error_code"] for r in rows if r["error_code"])),
    }


def sliced(rows, task):
    rows = list(rows)
    return {
        field: {
            str(value): summarize([r for r in rows if r[field] == value], task)
            for value in sorted({r[field] for r in rows})
        }
        for field in ("label_tier", "language", "bucket", "structure_id")
    }


def paired_cluster_delta(left, right, *, seed=5002, resamples=200, metric="joint_correct"):
    if metric not in {"joint_correct", "label_correct"}:
        raise ProtocolError("paired_metric_unsupported")
    a = {r["record_id"]: r for r in left}
    b = {r["record_id"]: r for r in right}
    if len(a) != len(left) or len(b) != len(right) or a.keys() != b.keys():
        raise ProtocolError("paired_identity_mismatch")
    if any(
        a[k]["input_hash"] != b[k]["input_hash"] or a[k]["component_id"] != b[k]["component_id"]
        for k in a
    ):
        raise ProtocolError("paired_input_mismatch")
    groups = defaultdict(list)
    excluded = []
    for k in a:
        if (a[k][metric] is None) != (b[k][metric] is None):
            raise ProtocolError("paired_metric_eligibility_mismatch")
        if a[k][metric] is None:
            excluded.append(k)
            continue
        groups[a[k]["component_id"]].append(int(b[k][metric]) - int(a[k][metric]))
    base = {"metric": metric, "requested_pairs": len(a), "excluded_record_ids": excluded}
    if not groups:
        return base | {"pairs": 0, "groups": 0, "delta": None, "interval": None}
    rng = np.random.default_rng(seed)
    keys = list(groups)
    samples = []
    for _ in range(resamples):
        vals = [v for i in rng.integers(0, len(keys), len(keys)) for v in groups[keys[i]]]
        samples.append(float(np.mean(vals)))
    return base | {
        "pairs": len(a) - len(excluded),
        "groups": len(groups),
        "delta": float(np.mean([x for vals in groups.values() for x in vals])),
        "interval": [float(x) for x in np.quantile(samples, [0.025, 0.975])],
        "warning": "descriptive small-sample interval; not evidence of stable improvement"
        if len(groups) < 10
        else None,
    }
