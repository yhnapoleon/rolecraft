from pathlib import Path

import pytest

from career_lab.aipm.design.rules import DesignFacts, evaluate_design, feedback_is_stale, load_rules
from career_lab.contracts.v2 import EvidenceRefV2, ObjectRef

RULES = (
    Path(__file__).resolve().parents[3]
    / "scenarios/pm_pilot/aipm-phase1/private/grading/design.json"
)
REF = ObjectRef(session_id="s", kind="aipm_design", object_id="design", version=1)
SOURCE = EvidenceRefV2(
    session_id="s",
    kind="material",
    object_id="scope",
    version=1,
    observed_at_seq=2,
    quote="The assistant cannot approve expenses.",
)
FACTS = DesignFacts(
    public_sources={
        "assistant_authority": (SOURCE,),
        "elapsed_definition": (SOURCE,),
        "configuration_dependencies": (SOURCE,),
    },
    need_scopes={"expenses": "expense", "access": "access"},
    capabilities=frozenset({("expense", "explain")}),
)


def row(**changes):
    return dict(
        id="r1",
        revision=1,
        need_ref="expenses",
        user_request="解释报销审批流程 / explain expense approvals",
        source_refs=[],
        target_action="explain",
        route="retrieval_generation",
        rationale="",
        final_authority="named_human_role",
        tool_assumptions=[],
        unresolved=[],
        execution_support="supported",
        **changes,
    )


def assess(changes=None, facts=FACTS, language="zh"):
    value = row()
    value.update(changes or {})
    return evaluate_design({"rows": [value]}, REF, facts, load_rules(RULES), language)


@pytest.mark.parametrize("language", ["zh", "en"])
def test_final_ai_approval_is_violation_with_exact_public_basis(language):
    _, findings = assess({"target_action": "approve", "final_authority": "ai"}, language=language)
    assert findings[0]["finding"] == "violation"
    assert findings[0]["basis_refs"] == [SOURCE.model_dump(mode="json")]
    assert findings[0]["input_ref"] == REF.model_dump(mode="json")
    assert findings[0]["affects_formal_score"] is False


@pytest.mark.parametrize(
    "action,route,authority",
    [
        ("explain", "retrieval_generation", "ai"),
        ("prepare_draft", "agent_confirmation", "named_human_role"),
        ("approve", "human", "named_human_role"),
    ],
)
def test_process_explanation_draft_and_human_approval_are_not_violations(action, route, authority):
    _, findings = assess({"target_action": action, "route": route, "final_authority": authority})
    assert all(f["finding"] != "violation" for f in findings)


def test_unknown_free_need_or_absent_public_evidence_never_gets_a_violation():
    for facts, changes in [(DesignFacts(), {}), (FACTS, {"need_ref": "free"})]:
        _, findings = assess(
            {"target_action": "approve", "final_authority": "ai", **changes}, facts
        )
        assert all(f["finding"] == "unknown" for f in findings)


def test_client_supported_claim_cannot_enable_uninstalled_tool():
    rows, findings = assess(
        {
            "target_action": "prepare_draft",
            "route": "agent_confirmation",
            "tool_assumptions": ["submit_expense"],
        }
    )
    assert rows[0]["execution_support"] == "plan_only"
    assert findings[0]["finding"] == "improve"


def test_elapsed_as_labor_requires_structured_claim_not_words():
    rules = load_rules(RULES)
    for kind, expected in [("labor_time", 1), ("elapsed_time", 0), ("other", 0)]:
        _, findings = evaluate_design(
            {
                "needs": [
                    {
                        "id": "n",
                        "metric": {
                            "kind": kind,
                            "source_field": "elapsed_minutes",
                            "formula_description": "labor_saved_minutes",
                        },
                    }
                ]
            },
            REF,
            FACTS,
            rules,
            "en",
        )
        assert len(findings) == expected


def test_configuration_difference_preserves_requested_and_effective_values():
    facts = DesignFacts(
        public_sources=FACTS.public_sources,
        requested_config={"sync": "realtime"},
        effective_config={"sync": "daily"},
    )
    _, findings = evaluate_design({}, REF, facts, load_rules(RULES), "en")
    assert findings[0]["finding"] == "improve"
    assert facts.requested_config["sync"] == "realtime"


def test_feedback_staleness_is_version_scoped():
    assert not feedback_is_stale(REF, REF, (SOURCE,), {("material", "scope"): 1})
    assert feedback_is_stale(REF, REF, (SOURCE,), {("material", "scope"): 2})
    assert feedback_is_stale(REF, REF.model_copy(update={"version": 2}), (), {})


def test_unreviewed_predicate_is_rejected(tmp_path):
    import json

    data = json.loads(RULES.read_text())
    data["rules"][0]["predicate"] = "eval"
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_rules(path)
