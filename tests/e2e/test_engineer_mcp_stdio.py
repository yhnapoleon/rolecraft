"""A delegated Agent works an engineer ticket through the stdio MCP server; the person signs.

Real TCP runtime app and an independently launched stdio server; no model calls.
"""

import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient

from career_lab.mcp.protocol import CAPABILITIES, MODERN, VERSION

sys.path.insert(0, str(Path(__file__).parents[1] / "integration"))
from test_engineer_session import (  # noqa: E402
    ENGINEER_AGENT_ACTIONS,
    PUBLIC_PROBES,
    Eng,
    build_app,
    make_session,
    sign,
)

RESULT_LIMIT = 50_000


class Pipe:
    def __init__(self, config: Path):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "career_lab.mcp", "--config", str(config)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
        )
        self.lines: queue.Queue[str] = queue.Queue()
        self.transcript: list[str] = []
        self.number = 0

        def reader() -> None:
            assert self.proc.stdout is not None
            for line in self.proc.stdout:
                self.lines.put(line)

        self.thread = threading.Thread(target=reader, daemon=True)
        self.thread.start()

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.number += 1
        message = {
            "jsonrpc": "2.0",
            "id": self.number,
            "method": method,
            "params": {**(params or {}), "_meta": {VERSION: MODERN, CAPABILITIES: {}}},
        }
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()
        raw = self.lines.get(timeout=30)
        self.transcript.append(raw)
        value = json.loads(raw)
        assert value["id"] == self.number
        return value

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})["result"]
        assert result["isError"] is False, result
        assert len(result["content"][0]["text"]) < RESULT_LIMIT, name
        return result["structuredContent"]["result"]

    def close(self) -> str:
        assert self.proc.stdin is not None and self.proc.stderr is not None
        self.proc.stdin.close()
        assert self.proc.wait(timeout=10) == 0
        self.thread.join(1)
        stderr = self.proc.stderr.read()
        assert not stderr, stderr
        return "".join(self.transcript)


@pytest.fixture(params=["zh", "en"])
def live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[tuple[Eng, str]]:
    app = build_app(tmp_path, monkeypatch, request.param)
    client = TestClient(app)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(32)
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="critical", access_log=False, lifespan="off")
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    try:
        yield (
            make_session(app, client, request.param, tmp_path / "engineer"),
            f"http://127.0.0.1:{sock.getsockname()[1]}",
        )
    finally:
        server.should_exit = True
        thread.join(5)
        client.close()
        app.state.store.close()
        sock.close()


def agent_config(person: Eng, api_url: str, token: str) -> Path:
    config = person.root.parent / "delegate.json"
    config.write_text(json.dumps({"api_url": api_url, "session_id": person.sid, "token": token}))
    config.chmod(0o600)
    return config


def command(person: Eng, name: str, request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    state = person.state()
    return {
        "command": {
            "schema_version": 2,
            "request_id": request_id,
            "operation": name,
            "payload": payload,
            "expected_version": state["business_seq"],
            "expected_workspace_revision": state["workspace_revision"],
        }
    }


def test_agent_works_the_ticket_over_stdio_and_the_person_signs(live: tuple[Eng, str]) -> None:
    person, api_url = live
    person.advance_world()
    ticket = person.seeded()
    token = person.grant("stdio-engineer", ["read", "act", "submit"], None)
    pipe = Pipe(agent_config(person, api_url, token))
    try:
        names = {tool["name"] for tool in pipe.rpc("tools/list")["result"]["tools"]}
        assert set(ENGINEER_AGENT_ACTIONS) <= names
        assert not names & {"engineer.tickets.create", "engineer.submissions.sign"}
        detail = pipe.call("engineer.tickets.read", {"query": {"ticket_id": ticket["id"]}})
        assert {probe["id"] for probe in detail["ticket"]["public_probes"]} == PUBLIC_PROBES
        tried = pipe.call(
            "engineer.trial",
            command(
                person,
                "engineer.trial",
                "stdio-trial",
                {"ticket_id": ticket["id"], "changes": {"freshness_guard": "warn"}},
            ),
        )["trial"]
        assert tried["counts"]["passed"] == 4 and tried["executor"]["kind"] == "external_agent"
        made = pipe.call(
            "engineer.submissions.draft",
            command(
                person,
                "engineer.submissions.draft",
                "stdio-draft",
                {
                    "ticket_id": ticket["id"],
                    "changes": {"freshness_guard": "warn"},
                    "explanation": "Warn when the indexed policy is older than the source.",
                    "change_statements": [
                        {
                            "field": "freshness_guard",
                            "before": "none",
                            "after": "warn",
                            "reason": "The index lags the newer notice.",
                        }
                    ],
                    "claimed_results": {probe: "pass" for probe in sorted(PUBLIC_PROBES)},
                },
            ),
        )["draft"]
        assert made["executor"]["kind"] == "external_agent"
        unknown = pipe.rpc(
            "tools/call",
            {"name": "engineer.submissions.sign", "arguments": {}},
        )
        assert unknown["error"]["code"] == -32602
        refused = sign(person, ticket, made["id"], "agent-sign", token=token)
        assert refused.status_code == 403
        assert refused.json()["code"] == "engineer_signoff_requires_human"
        signed = person.ok(sign(person, ticket, made["id"], "person-sign"))["review"]
        review = pipe.call("engineer.reviews.read", {"query": {"review_id": signed["review_id"]}})
        labels = {
            item["criterion"][:2]: item["label"]
            for item in review["review"]["evaluation"]["criteria"]
        }
        # The root-cause fix: no new hidden failure, the target's two hidden kin fixed.
        assert labels == {"E1": "MET", "E2": "MET", "E3": "MET", "E4": "MET", "E5": None}
        assert review["review"]["report"]["hidden_comparison"]["new_failures"] == 0
        assert review["review"]["report"]["hidden_comparison"]["fixed"] == 2
    finally:
        transcript = pipe.close()
    assert token not in transcript and person.token not in transcript
    assert str(person.root) not in transcript and "private-reviews" not in transcript
