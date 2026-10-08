from career_lab.contracts.evaluation import ItemGrade, JudgeDecision


def grade_decision(decision, gold, item):
    if gold.item_id != item.item_id or gold.task_type != item.task_type:
        raise ValueError("gold/input identity mismatch")
    try:
        if isinstance(decision, str):
            decision = JudgeDecision.model_validate_json(decision)
        else:
            decision = JudgeDecision.model_validate(decision)
        if decision.task_type != item.task_type:
            raise ValueError("task type mismatch")
    except (ValueError, TypeError):
        return ItemGrade(
            item_id=item.item_id,
            schema_valid=False,
            label_correct=False,
            evidence_score=0,
            joint_correct=False,
            error_class="model_format_error",
        )
    selected = set(decision.evidence_ids)
    if decision.abstained:
        return ItemGrade(
            item_id=item.item_id,
            schema_valid=True,
            label_correct=False,
            evidence_score=0,
            joint_correct=False,
            error_class="model_abstention",
        )
    correct = decision.label == gold.label
    if selected - {e.id for e in item.candidate_evidence}:
        return ItemGrade(
            item_id=item.item_id,
            schema_valid=True,
            label_correct=correct,
            evidence_score=0,
            joint_correct=False,
            error_class="invalid_reference",
        )
    if not gold.evidence_evaluable:
        return ItemGrade(
            item_id=item.item_id,
            schema_valid=True,
            label_correct=correct,
            evidence_score=None,
            joint_correct=None,
            error_class=None if correct else "wrong_label",
        )
    scores = [
        2 * len(selected & set(s)) / (len(selected) + len(s)) if selected or s else 1.0
        for s in gold.acceptable_evidence_sets
    ]
    evidence_score = max(scores, default=0.0)
    joint = correct and evidence_score == 1
    error = None if joint else ("wrong_label" if not correct else "insufficient_or_extra_evidence")
    return ItemGrade(
        item_id=item.item_id,
        schema_valid=True,
        label_correct=correct,
        evidence_score=evidence_score,
        joint_correct=joint,
        error_class=error,
    )
