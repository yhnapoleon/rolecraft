"""Exercise the real stdio and Streamable HTTP MCP transports: return, replay, revocation."""

import json
import os
import selectors
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from career_lab.mcp.protocol import CAPABILITIES, LEGACY, MODERN, VERSION
from career_lab.mcp.results import RESULT_LIMIT
from scripts.regression.published import ROOT

CLIENT_INFO = {
    "io.modelcontextprotocol/clientInfo": {"name": "rolecraft-regression", "version": "1"}
}


def rpc(
    process: subprocess.Popen[str],
    identifier: int,
    method: str,
    params: dict[str, object],
    expected_error: str | None = None,
) -> dict[str, object]:
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(
        json.dumps({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}) + "\n"
    )
    process.stdin.flush()
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        if not selector.select(15):
            raise TimeoutError("MCP response deadline exceeded")
    value = json.loads(process.stdout.readline())
    assert value["id"] == identifier
    if expected_error is not None:
        assert value["error"]["data"]["code"] == expected_error
        return {"isError": True}
    assert "error" not in value
    return value["result"]


def result_characters(name: str, result: dict[str, object]) -> int:
    """Characters one tool result puts in the Agent's context; over RESULT_LIMIT fails the gate.

    Claude Code moves results over 50,000 characters into a local file the Agent may not open.
    """
    assert result.get("isError") is False, (name, result)
    content = result["content"]
    assert isinstance(content, list)
    structured = json.dumps(result["structuredContent"], ensure_ascii=False, separators=(",", ":"))
    size = max(len(content[0]["text"]), len(structured))
    if size > RESULT_LIMIT:
        raise AssertionError(f"MCP {name} result has {size} characters; limit {RESULT_LIMIT}")
    return size


def exercise(api: str, language: str) -> dict[str, object]:
    with httpx.Client(base_url=api, timeout=15) as client:
        response = client.post(
            "/sessions",
            json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
        )
        response.raise_for_status()
        created = response.json()
        sid = created["session_id"]
        prefix = "/sessions/" + sid
        client.headers["Authorization"] = "Bearer " + created["token"]

        def command(operation: str, payload: dict[str, object], key: str) -> dict[str, object]:
            state = client.get(prefix).json()["state"]
            return {
                "schema_version": 2,
                "request_id": key,
                "operation": operation,
                "payload": payload,
                "expected_version": state["business_seq"],
                "expected_workspace_revision": state["workspace_revision"],
            }

        issued = client.post(
            prefix + "/delegations",
            json=command(
                "delegations.create",
                {
                    "agent_label": "MCP regression",
                    "capabilities": ["read", "act"],
                    "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
                },
                "grant",
            ),
        )
        issued.raise_for_status()
        grant = issued.json()["result"]["result"]
        with tempfile.TemporaryDirectory(prefix="rolecraft-mcp-") as directory:
            config = Path(directory) / "config.json"
            descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as file:
                json.dump({"api_url": api, "session_id": sid, "token": grant["token"]}, file)
            with subprocess.Popen(
                [sys.executable, "-m", "career_lab.mcp", "--config", str(config)],
                cwd=ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ) as process:
                try:
                    rpc(
                        process,
                        1,
                        "initialize",
                        {
                            "protocolVersion": "2025-11-25",
                            "capabilities": {},
                            "clientInfo": {"name": "regression", "version": "1"},
                        },
                    )
                    assert process.stdin is not None
                    process.stdin.write(
                        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
                    )
                    process.stdin.flush()
                    listed = rpc(process, 2, "tools/list", {})
                    assert any(tool["name"] == "work_products.create" for tool in listed["tools"])
                    sizes = {
                        name: result_characters(
                            name,
                            rpc(
                                process,
                                identifier,
                                "tools/call",
                                {"name": name, "arguments": {"session_id": sid}},
                            ),
                        )
                        for identifier, name in ((21, "observation"), (22, "tools"))
                    }
                    arguments = {
                        "name": "work_products.create",
                        "arguments": {
                            "session_id": sid,
                            "command": command(
                                "work_products.create",
                                {
                                    "kind": "text",
                                    "purpose": "exploration",
                                    "title": "MCP evidence note",
                                    "content": "Review this version before adoption.",
                                },
                                "return-once",
                            ),
                        },
                    }
                    first = rpc(process, 3, "tools/call", arguments)
                    repeated = rpc(process, 4, "tools/call", arguments)
                    assert not first.get("isError") and not repeated.get("isError")
                    assert repeated["structuredContent"]["replayed"] is True
                    ref = first["structuredContent"]["result"]["ref"]
                    revoked = client.request(
                        "DELETE",
                        prefix + "/delegations/" + grant["delegation"]["id"],
                        json=command(
                            "delegations.revoke",
                            {"delegation_id": grant["delegation"]["id"]},
                            "revoke",
                        ),
                    )
                    revoked.raise_for_status()
                    denied = rpc(
                        process,
                        5,
                        "tools/call",
                        {"name": "work_items.list", "arguments": {"session_id": sid}},
                        expected_error="credential_revoked_or_invalid",
                    )
                    assert denied["isError"] is True
                    return {
                        "language": language,
                        "status": "passed",
                        "product": ref,
                        "replayed": True,
                        "revoked_read_denied": True,
                        "result_characters": sizes,
                    }
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


class McpHttp:
    """What an agent's own Streamable HTTP client sends: no RoleCraft code on its side."""

    def __init__(self, endpoint: str, token: str) -> None:
        self.endpoint = endpoint
        self.sequence = 0
        self.client = httpx.Client(
            timeout=15,
            trust_env=False,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/json, text/event-stream",
            },
        )

    def __enter__(self) -> "McpHttp":
        return self

    def __exit__(self, *_: object) -> None:
        self.client.close()

    def post_modern(self, method: str, params: dict[str, object] | None = None) -> httpx.Response:
        self.sequence += 1
        headers = {"MCP-Protocol-Version": MODERN, "Mcp-Method": method}
        if method == "tools/call" and params is not None:
            headers["Mcp-Name"] = str(params["name"])
        meta = {VERSION: MODERN, CAPABILITIES: {}, **CLIENT_INFO}
        body = {
            "jsonrpc": "2.0",
            "id": self.sequence,
            "method": method,
            "params": {**(params or {}), "_meta": meta},
        }
        return self.client.post(self.endpoint, json=body, headers=headers)

    def modern(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        response = self.post_modern(method, params)
        response.raise_for_status()
        value = response.json()
        assert "error" not in value, value
        return value["result"]

    def call_result(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        """The whole tool result, as the Agent's context receives it."""
        return self.modern("tools/call", {"name": name, "arguments": arguments})

    def call(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        result = self.call_result(name, arguments)
        assert result["isError"] is False, result
        return result["structuredContent"]

    def legacy_handshake(self) -> str:
        """2025-11-25: initialize, then send the negotiated version on every request."""
        self.sequence += 1
        started = self.client.post(
            self.endpoint,
            json={
                "jsonrpc": "2.0",
                "id": self.sequence,
                "method": "initialize",
                "params": {
                    "protocolVersion": LEGACY,
                    "capabilities": {},
                    "clientInfo": {"name": "rolecraft-regression", "version": "1"},
                },
            },
        )
        started.raise_for_status()
        negotiated = {"MCP-Protocol-Version": started.json()["result"]["protocolVersion"]}
        ready = self.client.post(
            self.endpoint,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=negotiated,
        )
        assert ready.status_code == 202
        self.sequence += 1
        listed = self.client.post(
            self.endpoint,
            json={"jsonrpc": "2.0", "id": self.sequence, "method": "tools/list"},
            headers=negotiated,
        )
        listed.raise_for_status()
        assert listed.json()["result"]["tools"]
        return negotiated["MCP-Protocol-Version"]


def exercise_http(
    api: str, mcp_base: str, language: str, on_token: Callable[[str], None] | None = None
) -> dict[str, object]:
    """Return, replay and revoke over Streamable HTTP; mcp_base may be the web /api proxy.

    on_token lets a caller check logs for the secret; results never carry it.
    """
    with httpx.Client(base_url=api, timeout=15, trust_env=False) as owner:
        response = owner.post(
            "/sessions",
            json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
        )
        response.raise_for_status()
        created = response.json()
        prefix = "/sessions/" + created["session_id"]
        owner.headers["Authorization"] = "Bearer " + created["token"]

        def command(operation: str, payload: dict[str, object], key: str) -> dict[str, object]:
            state = owner.get(prefix).json()["state"]
            return {
                "schema_version": 2,
                "request_id": key,
                "operation": operation,
                "payload": payload,
                "expected_version": state["business_seq"],
                "expected_workspace_revision": state["workspace_revision"],
            }

        issued = owner.post(
            prefix + "/delegations",
            json=command(
                "delegations.create",
                {
                    "agent_label": "MCP HTTP regression",
                    "capabilities": ["read", "act"],
                    "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
                },
                "grant",
            ),
        )
        issued.raise_for_status()
        grant = issued.json()["result"]["result"]
        if on_token is not None:
            on_token(grant["token"])
        with McpHttp(mcp_base.rstrip("/") + prefix + "/mcp", grant["token"]) as agent:
            assert MODERN in agent.modern("server/discover")["supportedVersions"]
            listed = {tool["name"]: tool for tool in agent.modern("tools/list")["tools"]}
            schema = listed["work_products.create"]["inputSchema"]
            assert "session_id" not in schema.get("required", [])
            sizes = {
                name: result_characters(name, agent.call_result(name, {}))
                for name in ("observation", "tools")
            }
            seen = agent.call("observation", {})["result"]["as_of"]
            returned = {
                "schema_version": 2,
                "request_id": "return-once-http",
                "operation": "work_products.create",
                "payload": {
                    "kind": "text",
                    "purpose": "exploration",
                    "title": "MCP HTTP evidence note",
                    "content": "Review this version before adoption.",
                },
                "expected_version": seen["business_seq"],
                "expected_workspace_revision": seen["workspace_revision"],
            }
            first = agent.call("work_products.create", {"command": returned})
            repeated = agent.call("work_products.create", {"command": returned})
            assert first["replayed"] is False and repeated["replayed"] is True
            assert agent.legacy_handshake() == LEGACY
            revoked = owner.request(
                "DELETE",
                prefix + "/delegations/" + grant["delegation"]["id"],
                json=command(
                    "delegations.revoke", {"delegation_id": grant["delegation"]["id"]}, "revoke"
                ),
            )
            revoked.raise_for_status()
            denied = agent.post_modern("tools/list")
            assert denied.status_code == 401
            assert denied.json()["error"]["data"]["code"] == "credential_revoked_or_invalid"
    return {
        "language": language,
        "transport": "streamable_http",
        "status": "passed",
        "product": first["result"]["ref"],
        "replayed": True,
        "legacy_handshake": True,
        "revoked_status": 401,
        "result_characters": sizes,
    }
