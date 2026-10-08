from pathlib import Path

import pytest

from career_lab.contracts.scenario import PilotPlan
from career_lab.scenarios.loader import load_scenario
from career_lab.scenarios.solutions import check_solution

SCENARIO = Path(__file__).resolve().parents[2] / "scenarios/pm_pilot/v1/scenario.yaml"


def stable_plan(**changes):
    values = dict(
        participants=30,
        knowledge_domains=["stable_faq"],
        launch_day=7,
        update_strategy="daily",
        fallback="human",
        work_items=["scope_filter", "human_fallback"],
    )
    return PilotPlan(**(values | changes))


def test_two_valid_solution_paths():
    spec = load_scenario(SCENARIO)
    assert check_solution(spec, stable_plan()) == []
    delayed = stable_plan(
        participants=50,
        knowledge_domains=["stable_faq", "policy"],
        launch_day=10,
        update_strategy="realtime",
        work_items=["realtime_sync", "human_fallback"],
    )
    assert (
        check_solution(
            spec, delayed, approved_event_ids=("capacity_approved", "resources_approved")
        )
        == []
    )
    assert {i.code for i in check_solution(spec, delayed)} >= {
        "capacity_exceeded",
        "budget_exceeded",
        "deadline_exceeded",
    }


def test_refusing_everything_is_not_success():
    spec = load_scenario(SCENARIO)
    assert "no_pilot" in {
        i.code for i in check_solution(spec, stable_plan(participants=0, knowledge_domains=[]))
    }


@pytest.mark.parametrize("participants,valid", [(29, True), (30, True), (31, False)])
def test_capacity_boundary(participants, valid):
    issues = check_solution(load_scenario(SCENARIO), stable_plan(participants=participants))
    assert (not issues) is valid


def test_dynamic_policy_requires_realtime_or_restricted_fallback():
    spec = load_scenario(SCENARIO)
    plan = stable_plan(knowledge_domains=["stable_faq", "policy"])
    assert "stale_policy_risk" in {i.code for i in check_solution(spec, plan)}
    assert check_solution(spec, plan.model_copy(update={"update_strategy": "manual_policy"})) == []


def test_unknown_approval_does_not_grant_resources():
    with pytest.raises(ValueError, match="approval"):
        check_solution(load_scenario(SCENARIO), stable_plan(), approved_event_ids=("invented",))


def test_realtime_claim_without_work_is_rejected():
    issues = check_solution(load_scenario(SCENARIO), stable_plan(update_strategy="realtime"))
    assert "missing_work_item" in {i.code for i in issues}


def test_unrecognized_domain_and_work_cannot_be_ignored():
    issues = check_solution(
        load_scenario(SCENARIO),
        stable_plan(knowledge_domains=["unknown"], work_items=["free_magic"]),
    )
    assert {i.code for i in issues} >= {"unknown_domain", "unknown_work_item"}
