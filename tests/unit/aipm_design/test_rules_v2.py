"""audience_scope and approval_authority: structured choices only, never free text."""

from pathlib import Path

import pytest

from career_lab.aipm.design.rules import DesignFacts, evaluate_design, load_rules
from career_lab.contracts.v2 import EvidenceRefV2, ObjectRef

RULES = (
    Path(__file__).resolve().parents[3]
    / "scenarios/pm_pilot/aipm-phase1/private/grading/design.json"
)
REF = ObjectRef(session_id="s", kind="aipm_design", object_id="design", version=1)


def source(material):
    return EvidenceRefV2(
        session_id="s", kind="material", object_id=material, version=1, observed_at_seq=0
    )


FACTS = DesignFacts(
    public_sources={"pilot_users": (source("brief"),), "approval_rules": (source("approvals"),)},
    need_scopes={"expenses": "expense"},
)


def findings(design, facts=FACTS, language="zh"):
    return evaluate_design(design, REF, facts, load_rules(RULES), language)[1]


def violations(design, **kw):
    return [f for f in findings(design, **kw) if f["finding"] == "violation"]


def business(audience):
    return {"business": {"audience": audience, "offering_explanation": "", "task_goal": ""}}


def approver(who, relationships=("approver",)):
    return {
        "stakeholders": [
            {
                "id": "approver-choice",
                "name_or_role": who,
                "relationships": list(relationships),
                "responsibility": "",
                "fact_or_hypothesis": "unknown",
            }
        ]
    }


@pytest.mark.parametrize("language", ["zh", "en"])
def test_external_audience_conflicts_with_the_brief(language):
    [hit] = violations(business("external"), language=language)
    assert (hit["step_id"], hit["section_or_row_id"]) == ("business", "business")
    assert hit["basis_refs"] == [source("brief").model_dump(mode="json")]
    assert hit["affects_formal_score"] is False


@pytest.mark.parametrize("audience", ["internal", "both", "unknown"])
def test_other_audiences_are_never_flagged(audience):
    assert violations(business(audience)) == []


@pytest.mark.parametrize("who", ["chen", "daniel", "xu_qing"])
def test_choosing_a_person_without_authority_is_flagged(who):
    [hit] = violations(approver(who))
    assert (hit["step_id"], hit["section_or_row_id"]) == ("stakeholders", "approver-choice")


@pytest.mark.parametrize(
    "design",
    [
        approver("grace"),
        approver("unknown"),
        approver("chen", relationships=("user",)),
        approver("Chen 的意见"),
        approver("Chen's view"),
        # A triage row that explains who approves is a different input and never triggers.
        {
            "rows": [
                {
                    "id": "r",
                    "revision": 1,
                    "need_ref": "expenses",
                    "user_request": "解释谁负责审批报销",
                    "target_action": "explain",
                    "route": "retrieval_generation",
                    "rationale": "",
                    "final_authority": "named_human_role",
                }
            ]
        },
    ],
)
def test_false_positive_examples_never_trigger(design):
    assert violations(design) == []


def test_missing_public_evidence_keeps_both_rules_silent():
    empty = DesignFacts()
    assert violations({**business("external"), **approver("chen")}, facts=empty) == []


def test_feedback_points_to_sources_without_naming_the_answer():
    for rule in load_rules(RULES):
        if rule["id"] in {"audience_scope", "approval_authority"}:
            text = " ".join(rule["zh_feedback"].values()) + " ".join(rule["en_feedback"].values())
            assert "Grace" not in text and "内部员工" not in text and "internal staff" not in text
            fields = {k for e in rule["false_positive_examples"] for k in e} - {"expected"}
            assert fields, rule["id"]


GRADING = RULES.parent
CHECKS = {"choice", "citation", "rule", "rubric_rule", "sentence", "model", "self"}
STEPS = {"business", "stakeholders", "need", "boundary", "solution", "assurance", "decision"}


def test_coverage_items_use_reviewed_checks_and_known_references():
    import json

    coverage = json.loads((GRADING / "coverage.json").read_text())
    rule_ids = {rule["id"] for rule in load_rules(RULES)}
    ids = [item["id"] for item in coverage["items"]]
    assert len(ids) == len(set(ids))
    for item in coverage["items"]:
        assert item["check"] in CHECKS and item["step_id"] in STEPS
        assert item["severity"] in {"high", "medium", "low"}
        assert item["owner"] in {"manager", "business", "tech"}
        assert set(item["label"]) == set(item["look_again"]) == {"zh", "en"}
        predicate = item["predicate"]
        if item["check"] == "rule":
            assert predicate["rule"] in rule_ids
        if item["check"] == "choice":
            assert predicate["field"] and predicate["conflicts_with"] == []
        if item["check"] == "rubric_rule":
            assert predicate["criterion"].startswith("R")
    assert {item["step_id"] for item in coverage["items"]} == STEPS


def test_mentor_prompts_are_questions_tied_to_real_triggers():
    import json

    coverage = {
        i["id"]: i["step_id"] for i in json.loads((GRADING / "coverage.json").read_text())["items"]
    }
    rule_ids = {rule["id"] for rule in load_rules(RULES)}
    for prompt in json.loads((GRADING / "mentor.json").read_text())["prompts"]:
        assert set(prompt.get("when_rule", [])) <= rule_ids
        for cid, marks in prompt.get("when_coverage", {}).items():
            assert coverage[cid] == prompt["step_id"]
            assert set(marks) <= {"wrong", "missing", "to_check"}
        assert prompt.get("when_rule") or prompt.get("when_coverage")
        assert prompt["colleague"] in {"manager", "business", "tech"}
        assert "？" in prompt["question"]["zh"] and "?" in prompt["question"]["en"]
