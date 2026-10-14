"""Saved vs used configuration and approval decision cards over the normal HTTP routes."""

import json
from typing import Any

from test_w05_http_support import WorkSession
from test_w05_http_support import work_session as work_session

from career_lab.contracts import v2 as C
from career_lab.evidence.v2.ports import DEFAULT_POLICIES
from career_lab.evidence.v2.store_reader import StoreEvidenceReader
from career_lab.scenarios.v2.evidence_ports.store import create_store_fact_adapter

CEILINGS = {
    "zh": "可审批上限：容量60人，开发资源6人日，期限第10天。",
    "en": "Approval ceilings: capacity 60 people, 6 developer-days, and deadline day 10.",
}


def workspace(session: WorkSession) -> dict[str, Any]:
    return session.get("timeline")["workspace"]


def save(session: WorkSession, **settings: Any) -> None:
    config = workspace(session)["config"]
    base = C.ObjectRef(
        session_id=session.sid,
        kind="config",
        object_id=config["id"],
        version=config["version"],
        config_version=config["config_version"],
    ).model_dump(mode="json")
    session.post("configuration", "configuration.apply", {"base": base, "settings": settings})


def request(session: WorkSession, terms: dict[str, int]) -> dict[str, Any]:
    reason = "按方案申请开发资源" if session.language == "zh" else "Resources for the plan"
    payload = {"tool": "request_business", "terms": terms, "reason": reason}
    return session.post("actions", "request_business", payload)["result"]["request"]


def resolve(session: WorkSession, ref: dict[str, Any]) -> dict[str, Any]:
    payload = {"request": ref, "expected_request_revision": ref["version"]}
    return session.post("approvals/resolve", "resolve_approval", payload)["result"]


def learner(session: WorkSession) -> C.AuthContext:
    token = session.headers["Authorization"].split(" ", 1)[1]
    return session.app.state.v2_store.authenticate(session.sid, token)


def test_counteroffer_and_acceptance_keep_the_terms_they_were_judged_on(
    work_session: WorkSession,
) -> None:
    session = work_session
    save(session, update_strategy="realtime", work_items=["human_fallback", "realtime_sync"])
    offered = resolve(session, request(session, {"dev_days": 7}))
    decision = offered["decision"]
    assert (decision["status"], decision["countered"]) == ("countered", {"dev_days": 6})
    (term,) = decision["assessment"]["terms"]
    assert (term["requested"], term["limit"], term["needed"], term["issues"]) == (
        7,
        6,
        6,
        ["over_limit"],
    )
    assert decision["assessment"]["clauses"][0]["quote"] == CEILINGS[session.language]
    accepted = session.post(
        "actions",
        "accept_counteroffer",
        {"tool": "accept_counteroffer", "request": offered["request"], "terms": {"dev_days": 6}},
    )["result"]["decision"]
    (term,) = accepted["assessment"]["terms"]
    assert (accepted["status"], term["requested"], term["issues"]) == ("accepted", 6, [])
    assert workspace(session)["resources"]["dev_days"] == 6


def test_evaluators_read_decisions_without_the_display_assessment(
    work_session: WorkSession,
) -> None:
    session = work_session
    save(session, update_strategy="realtime", work_items=["human_fallback", "realtime_sync"])
    decided = resolve(session, request(session, {"dev_days": 6}))
    assert decided["decision"]["assessment"]["terms"]
    auth = learner(session)
    store = session.app.state.v2_store
    adapter = create_store_fact_adapter(
        store, session.app.state.scenario_v2, session.app.state.gateway.registry
    )
    plain = StoreEvidenceReader(store, auth, policies=DEFAULT_POLICIES)
    row = next(
        r for r in session.get("timeline")["objects"] if r["ref"]["kind"] == "business_decision"
    )
    ref = C.ObjectRef.model_validate(row["ref"])
    expected = C.canonical({k: v for k, v in row["content"].items() if k != "assessment"})
    assert adapter.source_reader(auth, ref, plain.captured_at).text == expected
    assert plain.read(auth, ref, plain.captured_at).text == expected
    assert "assessment" not in json.loads(expected)


def test_workspace_reports_the_configuration_the_next_test_uses(
    work_session: WorkSession,
) -> None:
    session = work_session
    planned = ["scope_filter", "human_fallback", "realtime_sync"]
    save(session, update_strategy="realtime", work_items=planned)
    current = workspace(session)
    used = current["effective_config"]
    assert used["requested"] == current["config"]
    assert used["effective"]["update_strategy"] == "daily"
    assert used["differences"] == {
        "update_strategy": "realtime_sync_not_provisioned",
        "work_items": "requested_work_exceeds_approved_budget",
    }
    question = (
        "住宿报销上限是多少？"
        if session.language == "zh"
        else "What is the hotel reimbursement limit per night?"
    )
    version = current["config"]["config_version"]
    test = session.post("tests", "tests.create", {"query": question, "config_version": version})
    assert test["result"]["test"]["config"] == used


def test_approved_resources_change_what_tests_use_without_saving_again(
    work_session: WorkSession,
) -> None:
    session = work_session
    save(session, update_strategy="realtime", work_items=["human_fallback", "realtime_sync"])
    assert workspace(session)["effective_config"]["effective"]["update_strategy"] == "daily"
    resolve(session, request(session, {"dev_days": 6}))
    used = workspace(session)["effective_config"]
    assert used["differences"] == {}
    assert used["effective"]["update_strategy"] == "realtime"


def test_object_scoped_agent_reads_no_workspace(work_session: WorkSession) -> None:
    session = work_session
    agent = session.delegate({"brief"})
    assert "workspace" not in session.get("timeline", headers=agent)
