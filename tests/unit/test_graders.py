from career_lab.contracts.evaluation import EvidencePackage, GoldAnnotation, JudgeDecision
from career_lab.evals.graders import grade_decision


def inputs():
    item = EvidencePackage(
        item_id="x",
        task_type="relation",
        criterion="r",
        claim="c",
        as_of_seq=0,
        completeness="complete",
        candidate_evidence=[{"id": f"e{i}", "version": 1, "text": "fact"} for i in (1, 2, 3)],
    )
    gold = GoldAnnotation(
        item_id="x",
        label="SUPPORTED",
        label_tier="G0",
        acceptable_evidence_sets=[["e1", "e2"], ["e3"]],
        annotation_version="v1",
    )
    return item, gold


def test_invalid_incomplete_and_alternative_evidence():
    item, gold = inputs()

    def decision(ids):
        return JudgeDecision(
            label="SUPPORTED",
            evidence_ids=ids,
            reason_code="ok",
            explanation="ok",
            model_revision="test",
        )

    assert grade_decision(decision(["e99"]), gold, item).error_class == "invalid_reference"
    assert not grade_decision(decision(["e1"]), gold, item).joint_correct
    assert grade_decision(decision(["e3"]), gold, item).joint_correct
    assert grade_decision("bad json", gold, item).error_class == "model_format_error"
