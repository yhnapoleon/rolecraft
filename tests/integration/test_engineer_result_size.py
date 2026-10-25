"""Worst-case engineer tool results stay within an Agent's tool result (MCP text <= 20,000).

Every limit is pushed at once: ten handed-over tests with 4,000-character questions run on a
configuration that retrieves twenty passages, twenty 60-character prohibited topics, fifty
trials and fifty drafts that change every editable setting, drafts at their text limit, and
three signed reviews. Each of the five Agent tools is measured on the MCP text it returns.
"""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_engineer_mcp import Agent
from test_engineer_session import (
    ENGINEER_AGENT_ACTIONS,
    Eng,
    build_app,
    make_session,
    sign,
    ticket_path,
)

from career_lab.engineer.candidate import EDITABLE_FIELDS, MAX_TOPIC_LENGTH, MAX_TOPICS
from career_lab.engineer.session import (
    DRAFT_TEXT_LIMIT,
    HANDOVER_LIMIT,
    PAGE_LIMIT,
    UNRESOLVED_LIMIT,
)
from career_lab.scenarios.v2.module import ref_for

LIMIT = 20_000
PUBLIC = ("F01", "F04", "F05", "F12")
QUESTIONS = {
    "zh": [
        "住宿报销上限是多少？",
        "餐费报销的上限？",
        "账号密码忘了怎么重置？",
        "权限申请要填写什么？",
    ],
    "en": [
        "What is the hotel reimbursement limit per night?",
        "What is the meal reimbursement cap?",
        "I forgot my account password. How do I reset it?",
        "What do I need to fill in on an access request?",
    ],
}
FILLER = {
    "zh": "报销 政策 住宿 餐费 请假 密码 权限 ",
    "en": "policy hotel meal leave reset access ",
}


@pytest.fixture(params=["zh", "en"])
def busy(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[tuple[Eng, TestClient]]:
    app = build_app(tmp_path, monkeypatch, request.param)
    try:
        with TestClient(app) as client:
            with TestClient(app, base_url="http://127.0.0.1") as loopback:
                yield make_session(app, client, request.param, tmp_path / "engineer"), loopback
    finally:
        app.state.store.close()


def topics(mark: str) -> list[str]:
    return [
        (f"{mark}{number:02d}-" + "t" * MAX_TOPIC_LENGTH)[:MAX_TOPIC_LENGTH]
        for number in range(MAX_TOPICS)
    ]


def widest_changes(number: int) -> dict[str, Any]:
    """Every editable setting changed, lists at their longest."""
    return {
        "domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal"],
        "scope_filter": False,
        "update_strategy": "manual_policy",
        "fallback": "none",
        "freshness_guard": "warn",
        "work_items": ["scope_filter", "human_fallback", "realtime_sync"],
        "manual_domains": ["stable_faq", "onboarding", "policy_travel", "policy_meal"],
        "prohibited_topics": topics(f"c{number % 10}"),
        "retrieval_limit": 19,
        "chunk_size": 3999,
        "min_score": 0.123456789,
    }


def longest_draft(ticket_id: str, number: int) -> dict[str, Any]:
    changes = widest_changes(number)
    statements = [
        {"field": name, "before": None, "after": None, "reason": "r"} for name in EDITABLE_FIELDS
    ]
    unresolved = [{"description": "u", "probe_ids": list(PUBLIC)} for _ in range(UNRESOLVED_LIMIT)]
    used = len(EDITABLE_FIELDS) * (1 + 8) + UNRESOLVED_LIMIT
    return {
        "ticket_id": ticket_id,
        "changes": changes,
        "explanation": "e" * (DRAFT_TEXT_LIMIT - used),
        "change_statements": statements,
        "claimed_results": dict.fromkeys(PUBLIC, "pass"),
        "unresolved": unresolved,
    }


def text_of(agent: Agent, name: str, arguments: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    result = agent.rpc("tools/call", {"name": name, "arguments": arguments}, name)["result"]
    assert result["isError"] is False, result
    (content,) = result["content"]
    return len(content["text"]), result["structuredContent"]["result"]


def command(eng: Eng, name: str, key: str, payload: dict[str, Any]) -> dict[str, Any]:
    state = eng.state()
    return {
        "command": {
            "schema_version": 2,
            "request_id": key,
            "operation": name,
            "payload": payload,
            "expected_version": state["business_seq"],
            "expected_workspace_revision": state["workspace_revision"],
        }
    }


def test_worst_case_results_stay_within_the_limit(busy: tuple[Eng, TestClient]) -> None:
    eng, loopback = busy
    module = eng.app.state.scenario_v2
    applied = eng.call(
        "/configuration",
        "configuration.apply",
        {
            "base": ref_for("config", module.package.baseline(eng.sid)).model_dump(mode="json"),
            "settings": {
                "retrieval_limit": 20,
                "chunk_size": 4000,
                "min_score": 0.0,
                "prohibited_topics": topics("b"),
            },
        },
        "widest-config",
    )
    assert applied.status_code == 200, applied.text
    tests = []
    for number in range(HANDOVER_LIMIT + 1):
        question = QUESTIONS[eng.language][number % 4] + " " + FILLER[eng.language] * 200
        made = eng.ok(
            eng.call(
                "/tests",
                "tests.create",
                {"query": question[:3990] + str(number), "config_version": 1},
                f"pm-{number}",
            )
        )
        tests.append(made["test"]["id"])
    too_many = eng.call(
        "/engineer/tickets", "engineer.tickets.create", {"from": "tests", "test_ids": tests}, "big"
    )
    assert too_many.status_code == 422, too_many.text
    assert too_many.json()["code"] == "engineer_test_selection_too_large"
    ticket = eng.ok(
        eng.call(
            "/engineer/tickets",
            "engineer.tickets.create",
            {"from": "tests", "test_ids": tests[:HANDOVER_LIMIT]},
            "ticket",
        )
    )["ticket"]
    token = eng.grant("busy-agent", ["read", "act"], [*ENGINEER_AGENT_ACTIONS, "observation"])
    agent = Agent(eng, loopback, token)
    sizes = {}
    sizes["reproduce"], _ = text_of(
        agent,
        "engineer.reproduce",
        command(eng, "engineer.reproduce", "repro", {"ticket_id": ticket["id"]}),
    )
    # The reproduction above and these trials fill the experiment budget (50).
    for number in range(49):
        size, _ = text_of(
            agent,
            "engineer.trial",
            command(
                eng,
                "engineer.trial",
                f"trial-{number}",
                {"ticket_id": ticket["id"], "changes": widest_changes(number)},
            ),
        )
        sizes["trial"] = max(sizes.get("trial", 0), size)
    drafts = []
    for number in range(50):
        size, made = text_of(
            agent,
            "engineer.submissions.draft",
            command(
                eng,
                "engineer.submissions.draft",
                f"draft-{number}",
                longest_draft(ticket["id"], number),
            ),
        )
        sizes["draft"] = max(sizes.get("draft", 0), size)
        drafts.append(made["draft"]["id"])
    reviews = []
    for number, draft_id in enumerate(drafts[-3:]):
        signed = eng.ok(sign(eng, ticket, draft_id, f"sign-{number}"))
        reviews.append(signed["review"]["review_id"])
    sizes["detail"], detail = text_of(
        agent, "engineer.tickets.read", {"query": {"ticket_id": ticket["id"]}}
    )
    for review_id in reviews:
        size, _ = text_of(agent, "engineer.reviews.read", {"query": {"review_id": review_id}})
        sizes["review"] = max(sizes.get("review", 0), size)
    eng.seeded()  # a page may mix both ticket sources; the seeded title is the longer one
    for name, key in (("engineer.reviews.read", "reviews"), ("engineer.tickets.read", "tickets")):
        size, listed = text_of(agent, name, {"query": {}})
        rows = listed[key]
        # Summaries have a fixed shape: pad the page to its limit with the largest one.
        largest = max(len(json.dumps(r, ensure_ascii=False, separators=(",", ":"))) for r in rows)
        sizes[key + "_page"] = size + (PAGE_LIMIT - len(rows)) * (largest + 1)
    assert max(sizes.values()) <= LIMIT, sizes
    ticket_view = detail["ticket"]
    # The person signing can read the latest draft in full; older ones are summarized.
    assert ticket_view["latest_draft"]["id"] == drafts[-1]
    assert (
        ticket_view["latest_draft"]["explanation"] == longest_draft(ticket["id"], 49)["explanation"]
    )
    assert ticket_view["drafts"][-1]["id"] == drafts[-1]
    assert ticket_view["experiment_budget"] == {"used": 50, "limit": 50}
    assert ticket_view["draft_budget"] == {"used": 50, "limit": 50}
    assert len(ticket_view["target_tests"]) == HANDOVER_LIMIT
    assert [row["review_id"] for row in ticket_view["reviews"]] == reviews


def test_draft_text_has_one_limit(busy: tuple[Eng, TestClient]) -> None:
    eng, _ = busy
    ticket = eng.seeded()
    payload = longest_draft(ticket["id"], 0)
    payload["changes"] = {"freshness_guard": "warn"}
    payload["explanation"] += "x"
    refused = eng.call(ticket_path(ticket, "drafts"), "engineer.submissions.draft", payload, "long")
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "engineer_draft_text_too_long"
    payload["explanation"] = payload["explanation"][:-1]
    assert (
        eng.ok(
            eng.call(ticket_path(ticket, "drafts"), "engineer.submissions.draft", payload, "fits")
        )["draft"]["explanation"]
        == payload["explanation"]
    )


def test_a_baseline_beyond_the_editable_limits_opens_no_ticket(
    busy: tuple[Eng, TestClient],
) -> None:
    """Its every trial would be refused, and its settings would not fit the ticket view."""
    eng, _ = busy
    module = eng.app.state.scenario_v2
    applied = eng.call(
        "/configuration",
        "configuration.apply",
        {
            "base": ref_for("config", module.package.baseline(eng.sid)).model_dump(mode="json"),
            "settings": {"prohibited_topics": [f"topic {n}" for n in range(MAX_TOPICS + 1)]},
        },
        "many-topics",
    )
    assert applied.status_code == 200, applied.text
    refused = eng.call("/engineer/tickets", "engineer.tickets.create", {"from": "seeded"}, "s")
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "engineer_baseline_unsupported"
    assert eng.ok(eng.read("/engineer/tickets"))["tickets"] == []
