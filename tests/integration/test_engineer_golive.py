"""A seeded ticket on a fresh session: the system puts the pilot live first, never the learner.

The engineer card can be opened before the product manager has applied any configuration.
The ticket's failure (an answer that misses the newer policy) only exists once the pilot is
live and the index lags the newer notice, so the server runs the scenario's go-live once as a
system executor, labels it in the timeline and keeps it out of the learner's PM evidence.
"""

import json
from typing import Any

from test_engineer_session import Eng, hidden_queries, make_session, sign, ticket_path, trial
from test_engineer_session import eng as eng

GOLIVE = {"id": "engineer-ticket-golive", "kind": "system"}
NOTE = {
    "zh": "试点配置已上线（系统为工程委托准备起始状态，不是学员的操作）",
    "en": "Pilot configuration went live (set up by the system for the engineering ticket; "
    "not the learner's action)",
}


def events(eng: Eng) -> list[dict[str, Any]]:
    return eng.ok(eng.read("/timeline"))["result"]["events"]


def by(event: dict[str, Any]) -> dict[str, Any]:
    return {key: event["executor"][key] for key in ("id", "kind")}


def test_seeded_ticket_puts_the_pilot_live_as_the_system(eng: Eng) -> None:
    assert events(eng) == []
    ticket = eng.seeded()
    applied = [e for e in events(eng) if by(e) == GOLIVE]
    assert {e["type"] for e in applied} == {"config_applied", "initial_plan_applied"}
    for event in applied:
        assert event["data"]["origin"] == "engineer_ticket_setup"
        assert event["data"]["note"] == NOTE[eng.language]
    assert all(by(e) == GOLIVE for e in events(eng))
    detail = eng.ok(eng.read("/engineer/tickets/" + ticket["id"]))["ticket"]
    (target,) = detail["target_tests"]
    assert target["used_versions"]["policy"] == 1 and target["source_versions"]["policy"] == 2
    assert detail["world_setup"] == {
        "executor": GOLIVE,
        "note": NOTE[eng.language],
        "config_version": 1,
    }
    fixed = eng.ok(trial(eng, ticket, {"freshness_guard": "warn"}, "trial-warn"))["trial"]
    assert fixed["counts"] == {"passed": 4, "failed": 0, "errors": 0, "unchecked": 0, "total": 4}


def test_go_live_runs_once(eng: Eng) -> None:
    first = eng.seeded()
    state = eng.state()
    again = eng.ok(
        eng.call("/engineer/tickets", "engineer.tickets.create", {"from": "seeded"}, "seed-again")
    )["ticket"]
    assert again["id"] == first["id"] and eng.state() == state
    assert len([e for e in events(eng) if e["type"] == "config_applied"]) == 1


def test_no_go_live_after_the_learner_applied(eng: Eng) -> None:
    eng.advance_world()
    before = events(eng)
    ticket = eng.seeded()
    assert events(eng) == before
    assert all(e["executor"]["kind"] == "human" for e in before)
    detail = eng.ok(eng.read("/engineer/tickets/" + ticket["id"]))["ticket"]
    assert detail["world_setup"] is None
    done = eng.ok(
        eng.call(
            ticket_path(ticket, "reproductions"),
            "engineer.reproduce",
            {"ticket_id": ticket["id"]},
            "repro",
        )
    )["reproduction"]
    assert done["status"] == "reproduced"


def pm_work(eng: Eng) -> dict[str, Any]:
    """A PM work product, made before the engineer card is opened."""
    title = "Pilot decision" if eng.language == "en" else "试点决定"
    content = (
        "Defer until the owner and scope are verified. Keep human fallback."
        if eng.language == "en"
        else "负责人和范围核实前暂缓，保留人工兜底。"
    )
    eng.ok(
        eng.call(
            "/work-products",
            "work_products.create",
            {"kind": "text", "purpose": "commitment", "title": title, "content": content},
            "pm-work",
        )
    )
    return next(r for r in json.loads(eng.responses[-1])["objects"] if r["kind"] == "product")


def rule_check(eng: Eng, product: dict[str, Any], key: str) -> dict[str, Any]:
    """The PM evaluation evidence: the rule items and verified facts a submission would get."""
    config = eng.ok(eng.read("/timeline"))["result"]["workspace"]["config"]
    state = eng.state()
    response = eng.client.post(
        "/sessions/" + eng.sid + "/submission-rule-check",
        headers=eng.headers,
        json={
            "schema_version": 2,
            "request_id": key,
            "operation": "submissions.rule_check",
            "payload": {
                "decision": "launch",
                "products": [product],
                "config": {
                    "session_id": eng.sid,
                    "kind": "config",
                    "object_id": config["id"],
                    "version": config["version"],
                    "config_version": config["config_version"],
                },
            },
            "expected_version": state["business_seq"],
            "expected_workspace_revision": state["workspace_revision"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


def evaluated(check: dict[str, Any]) -> tuple[Any, Any]:
    items = [
        (item["criterion"], item["label"], item["applicability"], item["source"])
        for item in check["rule_items"]
    ]
    return items, check["facts"]


def test_go_live_is_not_learner_pm_work(eng: Eng) -> None:
    """The system's go-live earns or costs the learner nothing a go-live by them would not.

    Its settings equal the baseline, so it is no configuration adjustment, and it adds no test
    run. The PM's rule items and verified facts equal those after the learner applies the same
    settings in person; the go-live only makes the newer policy a world fact.
    """
    product = pm_work(eng)
    eng.seeded()
    by_system = rule_check(eng, product, "check-system")
    assert by_system["facts"]["adjustment_actions"] == 0
    assert by_system["facts"]["test_runs"] == []
    assert by_system["facts"]["policy_version"] == 2
    person = make_session(eng.app, eng.client, eng.language, eng.root)
    other = pm_work(person)
    person.advance_world()
    assert evaluated(by_system) == evaluated(rule_check(person, other, "check-person"))


def criteria(review: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["criterion"][:2]: item for item in review["evaluation"]["criteria"]}


def test_demo_from_the_engineer_card_on_a_fresh_session(eng: Eng) -> None:
    """The demo: an over-broad fix is caught by a hidden probe; the root-cause fix passes all.

    Nobody applied a configuration first. Engineer work never touches the PM's tests or
    evaluation evidence; the only PM-visible record is the system's labelled go-live.
    """
    product = pm_work(eng)
    ticket = eng.seeded()

    def pm_view() -> list[Any]:
        return [
            eng.state(),
            eng.ok(eng.read("/tests")),
            eng.read("/timeline").json(),
            evaluated(rule_check(eng, product, "pm-check")),
        ]

    before = pm_view()
    tried = eng.ok(trial(eng, ticket, {"freshness_guard": "warn"}, "trial-warn"))["trial"]
    assert tried["counts"]["passed"] == 4 and tried["counts"]["total"] == 4
    baseline = eng.ok(eng.read("/engineer/tickets/" + ticket["id"]))["ticket"]["baseline_config"]
    warning = {
        "field": "freshness_guard",
        "before": "none",
        "after": "warn",
        "reason": "The index lags the newer notice.",
    }
    claims = {probe: "pass" for probe in ("F01", "F04", "F05", "F12")}
    root_cause = eng.ok(
        eng.call(
            ticket_path(ticket, "drafts"),
            "engineer.submissions.draft",
            {
                "ticket_id": ticket["id"],
                "changes": {"freshness_guard": "warn"},
                "explanation": "Warn when the indexed policy is older than the source.",
                "change_statements": [warning],
                "claimed_results": claims,
            },
            "draft-root",
        )
    )["draft"]
    fixed = eng.ok(sign(eng, ticket, root_cause["id"], "sign-root"))["review"]
    found = criteria(fixed)
    assert (found["E1"]["label"], found["E2"]["label"]) == ("MET", "MET")
    assert fixed["report"]["hidden_comparison"]["fixed"] == 2
    assert fixed["report"]["hidden_comparison"]["new_failures"] == 0
    overreach = eng.ok(
        eng.call(
            ticket_path(ticket, "drafts"),
            "engineer.submissions.draft",
            {
                "ticket_id": ticket["id"],
                "changes": {"freshness_guard": "warn", "min_score": 0.2},
                "explanation": "Warn on lag and lower the threshold to find the newer notice.",
                "change_statements": [
                    warning,
                    {
                        "field": "min_score",
                        "before": baseline["min_score"],
                        "after": 0.2,
                        "reason": "Find the newer notice.",
                    },
                ],
                "claimed_results": claims,
            },
            "draft-overreach",
        )
    )["draft"]
    caught = eng.ok(sign(eng, ticket, overreach["id"], "sign-overreach"))["review"]
    found = criteria(caught)
    assert found["E2"]["label"] == "NOT_MET"
    assert caught["report"]["hidden_comparison"]["new_failures"] == 1
    assert found["E2"]["hidden_probes"] == 1 and found["E2"]["probe_ids"] == []
    assert all(row["result"] == "pass" for row in caught["report"]["public_results"])
    assert pm_view() == before
    text = "\n".join(eng.responses)
    assert not any(query in text for query in hidden_queries(eng))
    assert str(eng.root) not in text and "private-reviews" not in text
