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


@pytest.mark.parametrize(
    "field,kind,expected",
    [
        ("duration_minutes", "labor_time", 1),
        (" Duration_Minutes ", "labor_time", 1),
        ("SD-120.duration_minutes", "labor_time", 1),
        ("elapsed_minutes", "labor_time", 1),
        ("duration_minutes", "elapsed_time", 0),
        ("duration_minutes", "other", 0),
        ("handling_minutes", "labor_time", 0),
        ("", "labor_time", 0),
    ],
)
def test_elapsed_field_from_the_field_dictionary_as_labor_is_flagged(field, kind, expected):
    metric = {"kind": kind, "source_field": field}
    _, findings = evaluate_design(
        {"needs": [{"id": "n", "metric": metric}]}, REF, FACTS, load_rules(RULES), "zh"
    )
    assert len(findings) == expected


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
                            "source_field": "duration_minutes",
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


@pytest.mark.parametrize(
    "request_text,action,authority,violation",
    [
        ("报销最终批准交给 AI", "approve", "ai", True),
        ("Let the AI give final expense approval", "approve", "ai", True),
        ("解释怎样申请报销", "explain", "ai", False),
        ("报销审批交给 AI", "explain", "named_human_role", False),
        ("解释怎样申请报销", "approve", "named_human_role", False),
    ],
)
def test_structured_choice_decides_and_request_words_never_do(
    request_text, action, authority, violation
):
    _, findings = assess(
        {"user_request": request_text, "target_action": action, "final_authority": authority}
    )
    assert any(f["finding"] == "violation" for f in findings) is violation


def test_private_rule_false_positive_examples_hold():
    rules = {rule["id"]: rule for rule in load_rules(RULES)}
    for rule_id in ("authority", "tool_capability"):
        for example in rules[rule_id]["false_positive_examples"]:
            fields = {k: v for k, v in example.items() if k != "expected"}
            route = "agent_confirmation" if rule_id == "tool_capability" else "retrieval_generation"
            rows, findings = assess({"route": route, **fields})
            assert all(f["finding"] != "violation" for f in findings), example
            if example["expected"] == "plan_only_not_violation":
                assert rows[0]["execution_support"] == "plan_only"


def test_shared_fixture_boundary_cases():
    shared = Path(__file__).resolve().parents[2] / "fixtures/aipm-phase1/shared.json"
    import json

    cases = {c["id"]: c for c in json.loads(shared.read_text())["cases"]}
    expected = {
        "approval-by-ai": ("approve", "agent_confirmation", "violation"),
        "explain-policy": ("explain", "retrieval_generation", "not_a_violation"),
        "draft-with-confirmation": ("prepare_draft", "agent_confirmation", "plan_only"),
    }
    for case_id, (action, route, outcome) in expected.items():
        case = cases[case_id]
        assert (case["target_action"], case["expected"]) == (action, outcome)
        rows, findings = assess(
            {"target_action": action, "route": route, "final_authority": case["final_authority"]}
        )
        assert any(f["finding"] == "violation" for f in findings) is (outcome == "violation")
        if outcome == "plan_only":
            assert rows[0]["execution_support"] == "plan_only"
