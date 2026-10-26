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


def test_coverage_points_use_reviewed_checks_and_known_references():
    import json

    coverage = json.loads((GRADING / "coverage.json").read_text())
    rule_ids = {rule["id"] for rule in load_rules(RULES)}
    ids = [p["id"] for p in coverage["points"]]
    assert len(ids) == len(set(ids))
    for point in coverage["points"]:
        assert point["check"] in CHECKS and point["step_id"] in STEPS
        assert point["severity"] in {"high", "medium", "low"}
        assert point["owner"] in {"manager", "business", "tech"}
        assert set(point["zh"]) == set(point["en"]) == {"label", "look", "pointer"}
        if point["check"] == "rule":
            assert point["predicate"]["rule_id"] in rule_ids
    assert {p["step_id"] for p in coverage["points"]} == STEPS


def test_mentor_prompts_are_questions_tied_to_real_triggers():
    import json

    coverage = {p["id"] for p in json.loads((GRADING / "coverage.json").read_text())["points"]}
    rule_ids = {rule["id"] for rule in load_rules(RULES)}
    for prompt in json.loads((GRADING / "mentor.json").read_text())["prompts"]:
        trigger = prompt["trigger"]
        assert trigger.get("rule_id") in rule_ids or trigger.get("coverage_id") in coverage
        assert prompt["colleague"] in {"manager", "business", "tech"}
        assert "？" in prompt["zh"] and "?" in prompt["en"]
