import pytest

from career_lab.contracts.evaluation import EvidencePackage, RuleContext
from career_lab.rubrics.checks import run_rule_checks


def item(participants=30, capacity=30, logs_complete=True, completeness="complete"):
    return EvidencePackage(item_id="x", task_type="criterion", criterion="R3.capacity", claim="check", as_of_seq=0,
        candidate_evidence=[], completeness=completeness, context=RuleContext(capacity=capacity, dev_days=3, deadline_day=7,
        plan={"participants": participants, "knowledge_domains": ["stable_faq"], "launch_day": 7, "update_strategy": "daily", "fallback": "human", "work_items": ["scope_filter", "human_fallback"]},
        deliverable={}, tests=[], work_costs={"scope_filter": 1, "human_fallback": 1}, approvals=[], policy_updated=False, logs_complete=logs_complete))


@pytest.mark.parametrize("n,cap,expected", [(20,30,"MET"),(30,30,"MET"),(50,60,"MET"),(31,30,"NOT_MET"),(50,30,"NOT_MET"),(61,60,"NOT_MET")])
def test_approved_capacity_and_bad_paths(n, cap, expected):
    assert run_rule_checks(item(n, cap))[0].label == expected


def test_missing_logs_and_overflow_are_not_zero():
    assert run_rule_checks(item(logs_complete=False))[0].label == "INSUFFICIENT"
    assert run_rule_checks(item(completeness="overflow"))[0].label == "INSUFFICIENT"


def test_no_policy_change_has_no_staleness_observation_window():
    evidence = item().model_copy(update={"criterion": "R4.staleness_test"})
    context = evidence.context.model_copy(update={"plan": evidence.context.plan.model_copy(update={"knowledge_domains": ("stable_faq", "policy")})})
    assert run_rule_checks(evidence.model_copy(update={"context": context}))[0].label == "NOT_APPLICABLE"
