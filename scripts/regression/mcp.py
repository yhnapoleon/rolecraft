"""Exercise the real stdio MCP transport, idempotent return and revocation."""

import json
import os
import selectors
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from scripts.regression.published import ROOT


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
                    }
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
