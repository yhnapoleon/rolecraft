"""MCP protocol view of one authorized session: session_id defaults to the bound session."""

import pytest

from career_lab.contracts import v2 as C
from career_lab.mcp.protocol import CAPABILITIES, LEGACY, MODERN, VERSION, Protocol, RpcFailure

SESSION = "bound-session"


def schema(content: dict[str, object], required: list[str]) -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"session_id": {"type": "string", "minLength": 1}, **content},
        "required": required,
        "additionalProperties": False,
        "$defs": {},
    }


READ = schema({"query": {"type": "object"}}, ["session_id"])
WRITE = schema({"command": {"type": "object"}}, ["session_id", "command"])


def tool(name: str, capability: str, parameters: dict[str, object]) -> C.ToolSchema:
    return C.ToolSchema(
        name=name,
        capability=capability,
        parameters=parameters,
        parameters_hash=C.digest(parameters),
        available=True,
    )


class BoundBackend:
    """A backend bound to one authorized session, like the stdio and HTTP clients."""

    session_id = SESSION

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def tools(self) -> tuple[C.ToolSchema, ...]:
        return (
            tool("work_items.list", "read", READ),
            tool("work_products.create", "act", WRITE),
        )

    def call(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, arguments))
        return {"ok": True}


def modern(method: str, params: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 7,
        "method": method,
        "params": {**(params or {}), "_meta": {VERSION: MODERN, CAPABILITIES: {}}},
    }


def test_mcp_tools_list_advertises_session_id_as_optional_for_a_bound_session() -> None:
    listed = Protocol(BoundBackend()).handle(modern("tools/list"))["tools"]
    read, write = (
        next(t for t in listed if t["name"] == n)
        for n in ("work_items.list", "work_products.create")
    )
    assert "required" not in read["inputSchema"]
    assert write["inputSchema"]["required"] == ["command"]
    for advertised in (read, write):
        session = advertised["inputSchema"]["properties"]["session_id"]
        assert session["type"] == "string" and session["minLength"] == 1
        assert "defaults to" in session["description"]
    # The backend's own schema is a frozen contract value and stays untouched.
    assert (
        READ["required"] == ["session_id"] and "description" not in READ["properties"]["session_id"]
    )


def test_mcp_tools_call_fills_the_bound_session_when_omitted() -> None:
    backend = BoundBackend()
    result = Protocol(backend).handle(
        modern("tools/call", {"name": "work_items.list", "arguments": {"query": {"limit": 5}}})
    )
    assert result["isError"] is False
    assert backend.calls == [("work_items.list", {"query": {"limit": 5}, "session_id": SESSION})]


def test_mcp_tools_call_passes_an_explicit_session_to_the_backend_check() -> None:
    backend = BoundBackend()
    Protocol(backend).handle(
        modern("tools/call", {"name": "work_items.list", "arguments": {"session_id": "other"}})
    )
    # The backend's existing check rejects a session other than its own; it must see the value.
    assert backend.calls == [("work_items.list", {"session_id": "other"})]


def initialize() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "client", "version": "1"},
        },
    }


def test_mcp_instructions_state_the_session_default_in_both_eras() -> None:
    discovered = Protocol(BoundBackend()).handle(modern("server/discover"))["instructions"]
    handshake = Protocol(BoundBackend()).handle(initialize())["instructions"]
    assert discovered == handshake
    assert "session_id is optional" in discovered
    assert "requests.read" in discovered and "request_id" in discovered


def test_mcp_negotiated_legacy_serves_requests_without_a_handshake() -> None:
    plain = {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}}
    with pytest.raises(RpcFailure) as refused:
        Protocol(BoundBackend()).handle(plain)
    assert refused.value.code == -32602
    listed = Protocol(BoundBackend(), negotiated=LEGACY).handle(plain)
    assert [t["name"] for t in listed["tools"]] == ["work_items.list", "work_products.create"]
    assert "resultType" not in listed
    with pytest.raises(ValueError):
        Protocol(BoundBackend(), negotiated="2025-06-18")


def test_mcp_unsupported_version_names_both_supported_eras_and_the_request() -> None:
    request = modern("ping")
    request["params"]["_meta"][VERSION] = "2099-01-01"
    with pytest.raises(RpcFailure) as refused:
        Protocol(BoundBackend()).handle(request)
    assert refused.value.code == -32022
    assert refused.value.data == {"supported": [MODERN, LEGACY], "requested": "2099-01-01"}
