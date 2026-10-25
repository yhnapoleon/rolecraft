"""MCP results fit an Agent's context: both transports, both languages, the widest grant.

Claude Code moves a tool result over 50,000 characters into a local file, so the Agent sees a
path instead of the result. observation and tools stay under 20,000 characters over MCP while
the public routes keep returning the full tool schemas.
"""

import io
import json
import threading
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts import v2 as C
from career_lab.delegations.credentials import Credentials
from career_lab.delegations.http_client import HttpAgentClient
from career_lab.mcp.protocol import CAPABILITIES, MODERN, VERSION, Protocol
from career_lab.mcp.stdio import serve
from career_lab.mcp.streamable_http import INTERNAL_BASE
from scripts.regression.published import write_catalog

LIMIT = 20_000
# Under read+act on the whole workspace these are never callable by an Agent.
CLOSED = {"feedback.create", "reviews.create", "submissions.create", "turns.create"}
CLOSED |= {"work_products.adopt"}


@pytest.fixture(params=["zh", "en"])
def workspace(request, tmp_path, monkeypatch):
    """The learner's widest grant in the UI: read and act, whole workspace."""
    monkeypatch.setenv("CAREER_LAB_SCENARIO_CATALOG", str(write_catalog(tmp_path / "catalog.json")))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    app = create_runtime_app("sqlite:///" + str(tmp_path / "runtime.db"))
    owner = TestClient(app)
    created = owner.post(
        "/sessions",
        json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": request.param},
    )
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    owner.headers["Authorization"] = "Bearer " + created.json()["token"]
    state = owner.get("/sessions/" + sid).json()["state"]
    issued = owner.post(
        f"/sessions/{sid}/delegations",
        json={
            "schema_version": 2,
            "request_id": "grant",
            "operation": "delegations.create",
            "payload": {
                "agent_label": "Size check",
                "capabilities": ["read", "act"],
                "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
            },
            "expected_version": state["business_seq"],
            "expected_workspace_revision": state["workspace_revision"],
        },
    )
    assert issued.status_code == 200, issued.text
    agent = TestClient(app, base_url="http://127.0.0.1")
    try:
        yield {
            "app": app,
            "sid": sid,
            "token": issued.json()["result"]["result"]["token"],
            "agent": agent,
        }
    finally:
        agent.close()
        owner.close()
        app.state.store.close()


def over_http(workspace, name, arguments=None):
    headers = {
        "Authorization": "Bearer " + workspace["token"],
        "MCP-Protocol-Version": MODERN,
        "Mcp-Method": "tools/call",
        "Mcp-Name": name,
    }
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": arguments or {},
            "_meta": {VERSION: MODERN, CAPABILITIES: {}},
        },
    }
    response = workspace["agent"].post(
        f"/sessions/{workspace['sid']}/mcp", json=body, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


def characters(result):
    """What reaches the Agent's context: the text block and the structured copy."""
    assert result["isError"] is False, result
    structured = json.dumps(result["structuredContent"], ensure_ascii=False, separators=(",", ":"))
    return max(len(result["content"][0]["text"]), len(structured))


def public(workspace, path):
    headers = {"Authorization": "Bearer " + workspace["token"]}
    response = workspace["agent"].get(f"/sessions/{workspace['sid']}{path}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_mcp_observation_and_tools_fit_an_agents_context_over_streamable_http(workspace):
    for name in ("observation", "tools"):
        assert characters(over_http(workspace, name)) <= LIMIT, name
    # Reading the brief, the usual first step, keeps observation inside the limit too.
    seen = over_http(workspace, "observation")["structuredContent"]["result"]["as_of"]
    brief = {"session_id": workspace["sid"], "kind": "material", "object_id": "brief", "version": 1}
    command = {
        "schema_version": 2,
        "request_id": "read-brief",
        "operation": "read_material",
        "payload": {"tool": "read_material", "material": brief},
        "expected_version": seen["business_seq"],
        "expected_workspace_revision": seen["workspace_revision"],
    }
    assert over_http(workspace, "read_material", {"command": command})["isError"] is False
    observed = over_http(workspace, "observation")
    assert observed["structuredContent"]["result"]["visible_sources"]
    assert characters(observed) <= LIMIT


class Lines:
    """stdin that sends the next request only after the previous response is written."""

    def __init__(self, requests):
        self.requests = list(requests)
        self.answered = threading.Semaphore(0)
        self.sent = 0

    def readline(self, _limit):
        if self.sent:
            assert self.answered.acquire(timeout=30), "no MCP response"
        if not self.requests:
            return b""
        self.sent += 1
        return json.dumps(self.requests.pop(0)).encode() + b"\n"


class Output(io.StringIO):
    def __init__(self, lines):
        super().__init__()
        self.lines = lines

    def flush(self):
        super().flush()
        self.lines.answered.release()


def test_mcp_observation_and_tools_fit_an_agents_context_over_stdio(workspace):
    backend = HttpAgentClient(
        credentials=Credentials(INTERNAL_BASE, workspace["sid"], workspace["token"]),
        transport=httpx.ASGITransport(app=workspace["app"], raise_app_exceptions=False),
    )
    requests = [
        {
            "jsonrpc": "2.0",
            "id": identifier,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}, "_meta": {VERSION: MODERN, CAPABILITIES: {}}},
        }
        for identifier, name in enumerate(("observation", "tools"), start=1)
    ]
    stdin = Lines(requests)
    stdout = Output(stdin)
    serve(Protocol(backend), stdin, stdout, io.StringIO())
    answers = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [answer["id"] for answer in answers] == [1, 2]
    for answer in answers:
        assert characters(answer["result"]) <= LIMIT


def test_mcp_tool_lists_name_what_the_agent_can_call_and_public_routes_keep_full_schemas(
    workspace,
):
    listed_tools = public(workspace, "/tools")["result"]["result"]["tools"]
    observation = public(workspace, "/observation")["result"]
    assert all("parameters" in tool for tool in listed_tools)
    assert observation["tools"] == listed_tools

    # The MCP observation is the public one without its optional tool catalogue.
    mcp_observation = over_http(workspace, "observation")["structuredContent"]["result"]
    assert "tools" not in mcp_observation
    assert mcp_observation == {key: value for key, value in observation.items() if key != "tools"}
    assert C.Observation.model_validate(mcp_observation).session_id == workspace["sid"]
    mcp_tools = over_http(workspace, "tools")["structuredContent"]["result"]["result"]["tools"]
    names = {tool["name"] for tool in mcp_tools}
    assert names == {tool["name"] for tool in listed_tools} - CLOSED
    assert {"name", "capability", "available", "unavailable_code"} == set(mcp_tools[0])
    revision = next(tool for tool in mcp_tools if tool["name"] == "begin_revision")
    assert revision["available"] is False
    assert revision["unavailable_code"] == "session_not_submitted"
    # Everything the Agent may call now is exactly what tools/list advertises.
    headers = {
        "Authorization": "Bearer " + workspace["token"],
        "MCP-Protocol-Version": MODERN,
        "Mcp-Method": "tools/list",
    }
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {"_meta": {VERSION: MODERN, CAPABILITIES: {}}},
    }
    advertised = (
        workspace["agent"]
        .post(f"/sessions/{workspace['sid']}/mcp", json=body, headers=headers)
        .json()["result"]["tools"]
    )
    assert {tool["name"] for tool in mcp_tools if tool["available"]} == {
        tool["name"] for tool in advertised
    }


def test_mcp_materials_list_returns_the_requested_page(workspace):
    everything = over_http(workspace, "materials.list")["structuredContent"]["result"]["result"]
    assert len(everything["materials"]) > 3 and everything["next_cursor"] is None
    first = over_http(workspace, "materials.list", {"query": {"limit": 3}})
    page = first["structuredContent"]["result"]["result"]
    assert page["materials"] == everything["materials"][:3] and page["next_cursor"] == 3
    rest = over_http(workspace, "materials.list", {"query": {"cursor": 3, "limit": 100}})
    page = rest["structuredContent"]["result"]["result"]
    assert page["materials"] == everything["materials"][3:] and page["next_cursor"] is None
