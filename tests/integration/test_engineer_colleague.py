"""One role per practice, and the AI colleague who takes the other side (phase 2, step 3):
Daniel in a product manager's practice, Grace in an engineer's. Through the normal routes."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_engineer_session import (
    PUBLIC_PROBES,
    TARGET_QUERY,
    Eng,
    build_app,
    draft,
    make_session,
    sign,
    ticket_path,
)


@pytest.fixture(params=["zh", "en"])
def eng(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[Eng]:
    app = build_app(tmp_path, monkeypatch, request.param)
    try:
        with TestClient(app) as client:
            yield make_session(app, client, request.param, tmp_path / "engineer")
    finally:
        app.state.store.close()


TICKETS = "/engineer/tickets"
CREATE = "engineer.tickets.create"


def role(eng: Eng, value: str, key: str = "role") -> Any:
    return eng.call(TICKETS, CREATE, {"from": "role", "role": value}, key)


def pm_tests(eng: Eng) -> list[str]:
    eng.advance_world()
    made = eng.ok(
        eng.call(
            "/tests",
            "tests.create",
            {"query": TARGET_QUERY[eng.language], "config_version": 1},
            "pm-test",
        )
    )
    return [made["test"]["id"]]


def test_the_role_is_written_once_and_read_back(eng: Eng) -> None:
    assert eng.ok(eng.read(TICKETS))["learner_role"] is None
    assert eng.ok(role(eng, "pm"))["learner_role"] == "pm"
    assert eng.ok(role(eng, "pm", "role-again"))["created"] is False
    refused = role(eng, "engineer", "role-switch")
    assert refused.status_code == 409 and "learner_role_fixed" in refused.text
    assert eng.ok(eng.read(TICKETS))["learner_role"] == "pm"


@pytest.mark.parametrize(
    "body",
    [
        {"from": "role", "role": "pm", "test_ids": ["x"]},
        {"from": "seeded", "test_ids": ["x"]},
        {"from": "decision", "ticket_id": "t", "decision": "apply", "role": "pm"},
        {"from": "role", "role": "manager"},
        {"from": "elsewhere"},
    ],
)
def test_mixed_bodies_are_refused(eng: Eng, body: dict[str, Any]) -> None:
    assert eng.call(TICKETS, CREATE, body, "mixed").status_code == 422


def test_daniel_takes_tickets_only_in_a_product_managers_practice(eng: Eng) -> None:
    ids = pm_tests(eng)
    body = {"from": "tests", "test_ids": ids, "assignee": "colleague"}
    no_role = eng.call(TICKETS, CREATE, body, "no-role")
    assert no_role.status_code == 409 and "assignee_not_allowed" in no_role.text
    eng.ok(role(eng, "engineer"))
    as_engineer = eng.call(TICKETS, CREATE, body, "as-engineer")
    assert as_engineer.status_code == 409


def test_daniel_reproduces_tries_and_signs_by_rule_under_his_own_name(eng: Eng) -> None:
    eng.ok(role(eng, "pm"))
    ids = pm_tests(eng)
    created = eng.ok(
        eng.call(
            TICKETS,
            CREATE,
            {"from": "tests", "test_ids": ids, "assignee": "colleague", "task_id": "task-1"},
            "daniel",
        )
    )
    ticket = created["ticket"]
    handover = ticket["handover"]
    assert ticket["assignee"] == "colleague" and ticket["origin"]["task_id"] == "task-1"
    assert handover["state"] == "reported", handover
    assert handover["actor"] == {
        "role_id": "tech_lead",
        "name": "Daniel",
        "kind": "ai_colleague",
        "orchestration": "rule",
    }
    # The rule says why, in the practice's language, and the report can be read.
    assert handover["rule"]["id"] == "freshness_warn"
    assert handover["rule"]["why"]
    assert handover["tried"][0]["counts"]["failed"] == 0
    # The handed-over question cited an outdated source with no warning; every trial checks by
    # rule whether that failure is gone. Warning clears it; so does handing over to a person.
    cleared = {"failures": ["stale_unwarned"], "questions": 1, "cleared": 1}
    assert handover["rule"]["target"] == cleared
    tried = {t["rule"]: t["target"] for t in handover["tried"]}
    assert tried["freshness_warn"] == cleared
    assert tried["freshness_fallback"] == cleared
    (review,) = ticket["reviews"]
    assert review["signed_by"]["id"] == "colleague-tech-lead"
    assert review["signed_by"]["kind"] == "system"
    assert review["actor"]["name"] == "Daniel"
    assert review["draft_executor"]["kind"] == "system"
    assert ticket["review_budget"] == {"used": 1, "limit": 3}
    read = eng.ok(eng.read("/engineer/reviews/" + handover["review_id"]))["review"]
    assert read["report"]["reviewer"]["kind"] == "system"
    assert {row["probe_id"] for row in read["report"]["public_results"]} == PUBLIC_PROBES
    # The person never signs engineering work in this practice.
    refused = sign(eng, ticket, ticket["latest_draft"]["id"], "pm-sign")
    assert refused.status_code == 409 and "learner_role_cannot_sign" in refused.text


def test_daniels_trials_carry_the_settings_not_in_effect(eng: Eng) -> None:
    """A learner who already requested real-time updates without the person-days: Daniel's
    real-time candidate changes nothing, and his record says real-time is not in effect."""
    eng.ok(role(eng, "pm"))
    eng.advance_world()
    workspace = eng.ok(eng.read("/workbench"))["result"]["timeline"]["workspace"]
    config = workspace["config"]
    base = {
        "schema_version": 2,
        "session_id": config["session_id"],
        "kind": "config",
        "object_id": config["id"],
        "version": config["version"],
        "config_version": config["config_version"],
    }
    eng.ok(
        eng.call(
            "/configuration",
            "configuration.apply",
            {"base": base, "settings": {"update_strategy": "realtime"}},
            "request-realtime",
        )
    )
    made = eng.ok(
        eng.call(
            "/tests",
            "tests.create",
            {"query": TARGET_QUERY[eng.language], "config_version": eng.state()["config_version"]},
            "pm-test-realtime",
        )
    )
    body = {"from": "tests", "test_ids": [made["test"]["id"]], "assignee": "colleague"}
    ticket = eng.ok(eng.call(TICKETS, CREATE, body, "daniel-realtime"))["ticket"]
    tried = {t["rule"]: t for t in ticket["handover"]["tried"]}
    assert tried["realtime_index"]["changes"] == {}
    assert tried["realtime_index"]["effective_differences"] == {
        "update_strategy": "realtime_sync_not_provisioned"
    }
    assert "freshness_guard" not in tried["freshness_warn"]["effective_differences"]
    # Real-time not in effect leaves the stale answer as it was: the target is not cleared.
    assert tried["realtime_index"]["target"]["cleared"] == 0
    assert tried["freshness_warn"]["target"]["cleared"] == 1
    assert ticket["handover"]["rule"]["id"] == "freshness_warn"


def test_the_product_manager_decides_and_apply_is_their_own_configuration_apply(eng: Eng) -> None:
    eng.ok(role(eng, "pm"))
    ids = pm_tests(eng)
    ticket = eng.ok(
        eng.call(
            TICKETS, CREATE, {"from": "tests", "test_ids": ids, "assignee": "colleague"}, "daniel"
        )
    )["ticket"]
    asked = eng.ok(
        eng.call(
            TICKETS,
            CREATE,
            {"from": "decision", "ticket_id": ticket["id"], "decision": "ask", "note": "Why warn?"},
            "ask",
        )
    )
    assert asked["decision"]["decision"] == "ask"
    assert asked["ticket"]["handover"]["state"] == "reported"
    before = eng.state()
    # Recording "apply" without having applied anything is refused: it changes nothing.
    stale = eng.call(
        TICKETS,
        CREATE,
        {"from": "decision", "ticket_id": ticket["id"], "decision": "apply", "config_version": 99},
        "apply-early",
    )
    assert stale.status_code == 409 and "config_version_mismatch" in stale.text
    assert eng.state() == before
    back = eng.ok(
        eng.call(
            TICKETS,
            CREATE,
            {
                "from": "decision",
                "ticket_id": ticket["id"],
                "decision": "return",
                "note": "Not now",
            },
            "return",
        )
    )
    assert back["ticket"]["handover"]["state"] == "returned"
    assert [d["decision"] for d in back["ticket"]["handover"]["decisions"]] == ["ask", "return"]


def engineer_signed(eng: Eng, changes: dict[str, Any], claims: dict[str, str]) -> dict[str, Any]:
    eng.ok(role(eng, "engineer"))
    created = eng.ok(eng.call(TICKETS, CREATE, {"from": "seeded"}, "seed"))["ticket"]
    eng.ok(
        eng.call(
            ticket_path(created, "reproductions"),
            "engineer.reproduce",
            {"ticket_id": created["id"]},
            "r",
        )
    )
    statements = [
        {"field": k, "before": "none", "after": v, "reason": "The index lags the newer notice."}
        for k, v in changes.items()
    ]
    drafted = eng.ok(
        draft(
            eng,
            created,
            "d",
            changes=changes,
            change_statements=statements,
            claimed_results=claims,
            unresolved=[],
        )
    )["draft"]
    eng.ok(sign(eng, created, drafted["id"], "s"))
    return created


def test_grace_applies_a_verified_fix_and_says_so(eng: Eng) -> None:
    ticket = engineer_signed(
        eng, {"freshness_guard": "warn"}, {probe: "pass" for probe in sorted(PUBLIC_PROBES)}
    )
    before = eng.state()
    done = eng.ok(
        eng.call(
            TICKETS,
            CREATE,
            {"from": "decision", "ticket_id": ticket["id"], "decision": "handover"},
            "handover",
        )
    )
    decision = done["decision"]
    assert decision["result"] == "applied", decision
    assert decision["actor"]["name"] == "Grace"
    assert decision["to_version"] == decision["from_version"] + 1
    assert f"v{decision['from_version']}" in decision["reply"]
    assert eng.state()["business_seq"] > before["business_seq"]
    events = eng.ok(eng.read("/timeline"))["result"]["events"]
    applied = [e for e in events if e["data"].get("origin") == "colleague_apply"]
    assert applied and all(e["data"]["actor"]["name"] == "Grace" for e in applied)
    assert all(e["executor"]["id"] == "colleague-supervisor" for e in applied)
    note = applied[0]["data"]["note"]
    assert ("已由 Grace 应用" in note) if eng.language == "zh" else ("Applied by Grace" in note)


def test_grace_returns_a_report_that_does_not_fix_the_target(eng: Eng) -> None:
    ticket = engineer_signed(eng, {}, {})
    before = eng.state()
    done = eng.ok(
        eng.call(
            TICKETS,
            CREATE,
            {"from": "decision", "ticket_id": ticket["id"], "decision": "handover"},
            "handover",
        )
    )
    decision = done["decision"]
    assert decision["result"] == "returned" and "target_not_fixed" in decision["reasons"]
    assert decision["probe_ids"] == ["F01"]
    assert "F01" in decision["reply"]
    assert eng.state()["business_seq"] == before["business_seq"]
    assert done["ticket"]["handover"]["state"] == "returned"


def apply_settings(eng: Eng, settings: dict[str, Any], key: str) -> int:
    """The person's own configuration.apply, from the current configuration."""
    config = eng.ok(eng.read("/timeline"))["result"]["workspace"]["config"]
    base = {
        "schema_version": 2,
        "session_id": eng.sid,
        "kind": "config",
        "object_id": config["id"],
        "version": config["version"],
        "config_version": config["config_version"],
    }
    eng.ok(
        eng.call("/configuration", "configuration.apply", {"base": base, "settings": settings}, key)
    )
    return eng.ok(eng.read("/timeline"))["result"]["workspace"]["config"]["config_version"]


def reported(eng: Eng) -> dict[str, Any]:
    eng.ok(role(eng, "pm"))
    ids = pm_tests(eng)
    return eng.ok(
        eng.call(
            TICKETS, CREATE, {"from": "tests", "test_ids": ids, "assignee": "colleague"}, "daniel"
        )
    )["ticket"]


def record_apply(eng: Eng, ticket: dict[str, Any], version: int, key: str) -> Any:
    return eng.call(
        TICKETS,
        CREATE,
        {
            "from": "decision",
            "ticket_id": ticket["id"],
            "decision": "apply",
            "config_version": version,
        },
        key,
    )


def test_apply_is_recorded_only_when_the_configuration_carries_the_reports_change(
    eng: Eng,
) -> None:
    ticket = reported(eng)
    change = ticket["handover"]["rule"]["changes"]
    # Something else applied: the record would claim a change that is not there.
    other = apply_settings(
        eng, {"fallback": "human", "work_items": ["scope_filter", "human_fallback"]}, "other"
    )
    refused = record_apply(eng, ticket, other, "apply-other")
    assert refused.status_code == 409 and "config_not_from_report" in refused.text
    # The report's change applied by the person: recorded as applied, with no other changes.
    version = apply_settings(eng, {k: v["after"] for k, v in change.items()}, "report")
    done = eng.ok(record_apply(eng, ticket, version, "apply-report"))
    assert done["decision"]["result"] == "applied" and done["decision"]["other_changes"] == {}
    assert done["ticket"]["handover"]["state"] == "applied"


def test_apply_with_further_changes_lists_them(eng: Eng) -> None:
    ticket = reported(eng)
    change = {k: v["after"] for k, v in ticket["handover"]["rule"]["changes"].items()}
    version = apply_settings(eng, {**change, "min_score": 0.25}, "report-plus")
    config = eng.ok(eng.read("/timeline"))["result"]["workspace"]["config"]
    assert config["min_score"] == 0.25
    done = eng.ok(record_apply(eng, ticket, version, "apply"))
    assert done["decision"]["result"] == "applied_with_changes", str(done["decision"])
    assert set(done["decision"]["other_changes"]) == {"min_score"}
    assert done["ticket"]["handover"]["state"] == "applied_with_changes"


def behavior_rows(eng: Eng) -> list[dict[str, Any]]:
    body = eng.read("/behavior").json()
    result = body.get("result", body)
    result = result.get("result", result)
    return result.get("sequence", [])


def test_colleagues_never_appear_as_the_learner(eng: Eng) -> None:
    eng.ok(role(eng, "pm"))
    ids = pm_tests(eng)
    timeline = eng.ok(eng.read("/timeline"))["result"]["events"]
    behavior = behavior_rows(eng)
    activity = eng.ok(eng.read("/agent-activity"))["result"]["items"]
    eng.ok(
        eng.call(
            TICKETS, CREATE, {"from": "tests", "test_ids": ids, "assignee": "colleague"}, "daniel"
        )
    )
    # Daniel's reproduce, trials, draft and sign-off write no business event, no behaviour row
    # and no agent activity: nothing of his run can be read as the learner's work.
    assert eng.ok(eng.read("/timeline"))["result"]["events"] == timeline
    assert behavior_rows(eng) == behavior
    assert eng.ok(eng.read("/agent-activity"))["result"]["items"] == activity == []


def test_graces_apply_is_hers_in_events_and_behaviour(eng: Eng) -> None:
    ticket = engineer_signed(
        eng, {"freshness_guard": "warn"}, {probe: "pass" for probe in sorted(PUBLIC_PROBES)}
    )
    before = {e["seq"] for e in eng.ok(eng.read("/timeline"))["result"]["events"]}
    eng.ok(
        eng.call(
            TICKETS,
            CREATE,
            {"from": "decision", "ticket_id": ticket["id"], "decision": "handover"},
            "handover",
        )
    )
    events = eng.ok(eng.read("/timeline"))["result"]["events"]
    new = [e for e in events if e["seq"] not in before]
    assert new and all(e["executor"]["kind"] == "system" for e in new)
    assert all(e["executor"]["id"] == "colleague-supervisor" for e in new)
    rows = {row["seq"]: row for row in behavior_rows(eng)}
    for event in new:
        if event["seq"] in rows:
            assert rows[event["seq"]]["executor"] == "system"
