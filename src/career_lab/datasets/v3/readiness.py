"""Mechanical training readiness; independent of research or semantic validity."""


def input_problem(record):
    if (
        record.family in {"relation", "criterion"}
        and record.model_input.evidence.completeness != "complete"
    ):
        return "input_" + record.model_input.evidence.completeness
    if record.family == "trajectory" and not record.model_input.logs_complete:
        return "incomplete_logs"
    return None


def readiness(records, annotations, *, fixture):
    rows = list(records)
    labels = {a.record_id: a for a in annotations}
    blockers = []
    for r in rows:
        reason = input_problem(r)
        if reason:
            blockers.append({"record_id": r.record_id, "reason": reason})
        if labels[r.record_id].status != "accepted":
            blockers.append({"record_id": r.record_id, "reason": "annotation_not_accepted"})
    required = {
        "relation": {"SUPPORTED", "CONTRADICTED", "INSUFFICIENT"},
        "criterion": {"MET", "PARTIAL", "NOT_MET", "INSUFFICIENT", "NOT_APPLICABLE"},
    }
    train = [r for r in rows if r.split == "train" and r.family in required]
    if not train:
        blockers.append({"record_id": rows[0].record_id, "reason": "training_partition_required"})
    for family, wanted in required.items():
        subset = [r for r in train if r.family == family]
        if (
            subset
            and {labels[r.record_id].final.label for r in subset if labels[r.record_id].final}
            != wanted
        ):
            blockers.append(
                {
                    "record_id": subset[0].record_id,
                    "reason": "training_class_coverage_missing:" + family,
                }
            )
    return {
        "policy": "complete-accepted-training-v1",
        "status": "diagnostic" if blockers else "ready",
        "scope": "fixture" if fixture else "development",
        "blockers": blockers,
        "research_approved": False,
    }
