"""A delegated Agent works an engineer ticket over MCP Streamable HTTP; only the person signs."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_engineer_session import (
    ENGINEER_AGENT_ACTIONS,
    PUBLIC_PROBES,
    Eng,
    build_app,
    draft,
    hidden_queries,
    make_session,
    sign,
    trial,
)

from career_lab.mcp.protocol import CAPABILITIES, MODERN, VERSION

# The MCP result limit the delegated client is held to (an Agent's tool result).
RESULT_LIMIT = 20_000
PERSON_ONLY = {"engineer.tickets.create", "engineer.submissions.sign"}


class Agent:
    def __init__(self, eng: Eng, client: TestClient, token: str):
        self.eng, self.client, self.token = eng, client, token
        self.texts: list[str] = []

    def rpc(self, method: str, params: dict[str, Any] | None = None, name: str | None = None):
        headers = {
            "Authorization": "Bearer " + self.token,
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": MODERN,
            "Mcp-Method": method,
            **({"Mcp-Name": name} if name else {}),
        }
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": {**(params or {}), "_meta": {VERSION: MODERN, CAPABILITIES: {}}},
        }
        response = self.client.post(f"/sessions/{self.eng.sid}/mcp", json=body, headers=headers)
        assert response.status_code == 200, response.text
        self.texts.append(response.text)
        return response.json()

    def tools(self) -> set[str]:
        return {tool["name"] for tool in self.rpc("tools/list")["result"]["tools"]}

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.rpc("tools/call", {"name": name, "arguments": arguments}, name)["result"]
        assert result["isError"] is False, result
        (content,) = result["content"]
        if name.startswith("engineer."):
            assert len(content["text"]) <= RESULT_LIMIT, (name, len(content["text"]))
        return result["structuredContent"]

    def read(self, name: str, **query: Any) -> dict[str, Any]:
        return self.call(name, {"query": query})["result"]

    def act(self, name: str, request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        state = self.eng.state()
        command = {
            "schema_version": 2,
            "request_id": request_id,
            "operation": name,
            "payload": payload,
            "expected_version": state["business_seq"],
            "expected_workspace_revision": state["workspace_revision"],
        }
        return self.call(name, {"command": command})["result"]


@pytest.fixture(params=["zh", "en"])
def eng(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[tuple[Eng, TestClient]]:
    app = build_app(tmp_path, monkeypatch, request.param)
    try:
        with TestClient(app) as client:
            # The MCP endpoint answers loopback hosts only.
            with TestClient(app, base_url="http://127.0.0.1") as loopback:
                yield make_session(app, client, request.param, tmp_path / "engineer"), loopback
    finally:
        app.state.store.close()


def statement() -> dict[str, Any]:
    return {
        "field": "freshness_guard",
        "before": "none",
        "after": "warn",
        "reason": "The index lags the newer notice.",
    }


def work_the_ticket(agent: Agent, ticket_id: str) -> dict[str, Any]:
    """Read the ticket, reproduce, try a candidate and draft it, all as the Agent."""
    listed = agent.read("engineer.tickets.read")["tickets"]
    assert [row["id"] for row in listed] == [ticket_id]
    detail = agent.read("engineer.tickets.read", ticket_id=ticket_id)["ticket"]
    assert detail["baseline_config"]["freshness_guard"] == "none"
    assert {probe["id"] for probe in detail["public_probes"]} == PUBLIC_PROBES
    reproduced = agent.act("engineer.reproduce", "agent-repro", {"ticket_id": ticket_id})
    assert reproduced["reproduction"]["executor"]["kind"] == "external_agent"
    tried = agent.act(
        "engineer.trial",
        "agent-trial",
        {"ticket_id": ticket_id, "changes": {"freshness_guard": "warn"}},
    )["trial"]
    assert tried["counts"]["passed"] == 4 and tried["executor"]["kind"] == "external_agent"
    made = agent.act(
        "engineer.submissions.draft",
        "agent-draft",
        {
            "ticket_id": ticket_id,
            "changes": {"freshness_guard": "warn"},
            "explanation": "Warn when the indexed policy is older than the source.",
            "change_statements": [statement()],
            "claimed_results": {probe: "pass" for probe in sorted(PUBLIC_PROBES)},
        },
    )["draft"]
    assert made["executor"]["kind"] == "external_agent"
    assert made["config_hash"] == tried["config_hash"]
    return made


def test_agent_works_the_ticket_over_mcp_and_the_person_signs(
    eng: tuple[Eng, TestClient],
) -> None:
    person, loopback = eng
    person.advance_world()
    ticket = person.seeded()
    # An MCP client starts from the observation; the tool index comes from the `tools` tool
    # (over MCP the observation carries no tool catalogue), so the grant allows both.
    token = person.grant(
        "mcp-engineer", ["read", "act"], [*ENGINEER_AGENT_ACTIONS, "observation", "tools"]
    )
    agent = Agent(person, loopback, token)
    assert agent.tools() == {*ENGINEER_AGENT_ACTIONS, "observation", "tools", "requests.read"}
    catalogue = agent.call("tools", {})["result"]["result"]["tools"]
    engineer = {tool["name"]: tool for tool in catalogue if tool["name"].startswith("engineer.")}
    assert set(engineer) == set(ENGINEER_AGENT_ACTIONS)
    assert all(
        tool["available"] and tool["unavailable_code"] is None for tool in engineer.values()
    ), engineer
    made = work_the_ticket(agent, ticket["id"])
    # Signing stays with the person: no tool, and the route refuses the Agent's token.
    refused = sign(person, ticket, made["id"], "agent-sign", token=token)
    assert refused.status_code == 403 and refused.json()["code"] == "capability_forbidden"
    unknown = agent.rpc(
        "tools/call",
        {
            "name": "engineer.submissions.sign",
            "arguments": {"command": {"operation": "engineer.submissions.sign"}},
        },
        "engineer.submissions.sign",
    )
    assert unknown["error"]["code"] == -32602
    signed = person.ok(sign(person, ticket, made["id"], "person-sign"))
    assert signed["signoff"]["signed_by"]["kind"] == "human"
    review_id = signed["review"]["review_id"]
    reviews = agent.read("engineer.reviews.read")["reviews"]
    assert [row["review_id"] for row in reviews] == [review_id]
    review = agent.read("engineer.reviews.read", review_id=review_id)["review"]
    # The Agent's root-cause fix: no new hidden failure, the target's two hidden kin fixed.
    assert review["report"]["hidden_comparison"]["new_failures"] == 0
    assert review["report"]["hidden_comparison"]["fixed"] == 2
    labels = {item["criterion"][:2]: item["label"] for item in review["evaluation"]["criteria"]}
    assert labels == {"E1": "MET", "E2": "MET", "E3": "MET", "E4": "MET", "E5": None}
    assert review["evaluation"] == signed["review"]["evaluation"]
    text = "\n".join(agent.texts)
    assert token not in text and person.token not in text
    assert str(person.root) not in text and "private-reviews" not in text
    assert not any(query in text for query in hidden_queries(person))


def test_a_broad_grant_still_has_no_person_only_tool(eng: tuple[Eng, TestClient]) -> None:
    person, loopback = eng
    person.advance_world()
    ticket = person.seeded()
    token = person.grant("broad-engineer", ["read", "act", "submit"], None)
    agent = Agent(person, loopback, token)
    names = agent.tools()
    assert set(ENGINEER_AGENT_ACTIONS) <= names
    assert not names & PERSON_ONLY
    made = work_the_ticket(agent, ticket["id"])
    refused = sign(person, ticket, made["id"], "broad-sign", token=token)
    assert refused.status_code == 403
    assert refused.json()["code"] == "engineer_signoff_requires_human"
    detail = agent.read("engineer.tickets.read", ticket_id=ticket["id"])["ticket"]
    assert detail["review_budget"] == {"used": 0, "limit": 3}
    assert [row["id"] for row in detail["drafts"]] == [made["id"]]


def test_a_busy_ticket_detail_stays_within_the_result_limit(eng: tuple[Eng, TestClient]) -> None:
    """The detail lists the latest experiments and drafts; budgets count all of them."""
    person, loopback = eng
    person.advance_world()
    ticket = person.seeded()
    trials = [
        person.ok(trial(person, ticket, {"freshness_guard": "warn"}, f"t{number}"))["trial"]["id"]
        for number in range(1, 23)
    ]
    explanation = "Warn when the indexed policy is older than the source notice. " * 6
    drafts = [
        person.ok(draft(person, ticket, f"d{number}", explanation=f"{number}. {explanation}"))[
            "draft"
        ]["id"]
        for number in range(12)
    ]
    token = person.grant("busy-engineer", ["read"], [*ENGINEER_AGENT_ACTIONS, "observation"])
    detail = Agent(person, loopback, token).read("engineer.tickets.read", ticket_id=ticket["id"])[
        "ticket"
    ]
    assert [row["id"] for row in detail["trials"]] == trials[-10:]
    assert [row["id"] for row in detail["drafts"]] == drafts[-10:]
    assert detail["latest_draft"]["id"] == drafts[-1]
    assert detail["experiment_budget"] == {"used": 22, "limit": 50}
    assert detail["draft_budget"] == {"used": 12, "limit": 50}
