from career_lab.contracts.evaluation import EvidencePackage, GoldAnnotation, JudgeDecision
from career_lab.evals.graders import grade_decision


def test_system_abstention_is_not_correct_insufficient_label():
    item = EvidencePackage(
        item_id="x",
        task_type="relation",
        criterion="x",
        claim="x",
        as_of_seq=0,
        candidate_evidence=(),
        completeness="complete",
    )
    gold = GoldAnnotation(
        item_id="x",
        label="INSUFFICIENT",
        label_tier="G0",
        acceptable_evidence_sets=((),),
        annotation_version="v1",
        missing_requirement="capacity",
    )
    decision = JudgeDecision(
        label="INSUFFICIENT",
        evidence_ids=(),
        reason_code="RULE_ABSTAIN",
        explanation="not supported",
        model_revision="rules",
        abstained=True,
    )
    graded = grade_decision(decision, gold, item)
    assert graded.label_correct is False and graded.joint_correct is False
    assert graded.error_class == "model_abstention"
