"""Test-only loopback OpenAI-compatible services and one bilingual session driver.

The services answer with fixed mechanism replies so each slot's wiring is observable;
they demonstrate configuration and request shape, never semantic quality.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from career_lab.api.vertical_runtime import create_runtime_app, default_installed_scenario
from career_lab.jobs.worker import Worker
from career_lab.scenarios.v2.localization import locale_root

# Content-derived ids (e-<sha256>, object hashes) and generated UUIDs differ per session.
_GENERATED = re.compile(
    rb"\b[a-z]+-[0-9a-f]{24,64}\b"
    rb"|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
    rb"|\b[0-9a-f]{32,64}\b"
)


def normalized_body(raw: bytes, session_id: str) -> bytes:
    """Request bytes with per-session identifiers numbered in order of first appearance."""
    seen: dict[bytes, bytes] = {}

    def number(match: re.Match[bytes]) -> bytes:
        return seen.setdefault(match.group(0), b"<id%d>" % len(seen))

    return _GENERATED.sub(number, raw.replace(session_id.encode(), b"<session>"))


def body_digests(calls: list[Call], session_id: str) -> list[str]:
    return [hashlib.sha256(normalized_body(call.body, session_id)).hexdigest() for call in calls]


def request_kind(payload: dict) -> str:
    """Which product call a chat request is, from its fixed system prompt or payload."""
    system = payload["messages"][0]["content"]
    if system.startswith("assistant-generation-v2"):
        return "assistant"
    if system.startswith("Review the actual reply"):
        return "role_review"
    body = payload["messages"][1]["content"] if len(payload["messages"]) > 1 else ""
    try:
        data = json.loads(body)
    except ValueError:
        return "role"
    if isinstance(data, dict) and "proposed_label" in data and "cited_ids" in data:
        return "support"
    if "citation_ids" in system:
        return "judge"
    return "role"


def reply(payload: dict, language: str, *, insufficient: bool = False) -> str:
    """``insufficient`` makes the Judge cite nothing, so no support check is ever sent."""
    kind = request_kind(payload)
    messages = payload["messages"]
    if kind == "assistant":
        data = json.loads(messages[1]["content"])
        return json.dumps(
            {
                "answerable": True,
                "answer": data["candidates"][0]["text"],
                "citation_ids": [data["candidates"][0]["id"]],
            }
        )
    if kind == "role_review":
        return json.dumps(
            {
                "request_kinds": ["business_judgment"],
                "facts_answered": True,
                "citations_supported": True,
                "within_knowledge": True,
                "preserves_stance": True,
                "no_complete_solution": True,
                "no_resource_approval": True,
                "one_main_question": True,
                "conditions_preserved": True,
                "language_match": True,
                "decision": "supported",
            }
        )
    if kind == "support":
        return json.dumps(
            {"relation": "INSUFFICIENT", "reason": "Mechanism check only.", "spans": []}
        )
    if kind == "judge":
        data = json.loads(messages[1]["content"])
        candidates = [c["id"] for c in data.get("candidate_evidence", [])]
        bound = data.get("rule_bound") or {}
        label = bound.get("upper") or "PARTIAL"
        if insufficient:
            candidates = []
        return json.dumps(
            {
                "criterion": data["criterion"],
                "label": label if candidates else "INSUFFICIENT",
                "applicability": data["applicability"],
                "citation_ids": candidates[:1],
                "explanation": "机制验证：仅检查接线。"
                if language == "zh"
                else "Mechanism verification: wiring only.",
            }
        )
    return (
        "机制验证：你想先核对哪项试点条件？"
        if language == "zh"
        else "Mechanism verification: which pilot condition would you like to verify first?"
    )


@dataclass
class Call:
    kind: str
    model: str
    max_tokens: int
    authorization: str | None
    body: bytes


@dataclass
class LoopbackProvider:
    """One scripted service; ``failure`` set to ``"http"`` answers 503 to every request."""

    language: str
    calls: list[Call] = field(default_factory=list)
    failure: str | None = None
    insufficient: bool = False
    server: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        assert self.server is not None
        return f"http://127.0.0.1:{self.server.server_port}"

    def kinds(self) -> list[str]:
        return [call.kind for call in self.calls]


@contextmanager
def loopback(language: str) -> Iterator[LoopbackProvider]:
    provider = LoopbackProvider(language)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            payload = json.loads(raw)
            provider.calls.append(
                Call(
                    request_kind(payload),
                    payload["model"],
                    payload["max_tokens"],
                    self.headers.get("Authorization"),
                    raw,
                )
            )
            if self.path != "/chat/completions" or provider.failure == "http":
                body = b'{"error": "scripted failure"}'
                self.send_response(503)
            else:
                content = reply(payload, provider.language, insufficient=provider.insufficient)
                body = json.dumps(
                    {
                        "choices": [{"message": {"content": content}}],
                        "usage": {"prompt_tokens": 40, "completion_tokens": 16},
                    }
                ).encode()
                self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    provider.server = server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield provider
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@dataclass
class Session:
    app: FastAPI
    client: TestClient
    session_id: str
    token: str
    language: str

    def get(self, path: str) -> httpx.Response:
        return self.client.get(
            "/sessions/" + self.session_id + path,
            headers={"Authorization": "Bearer " + self.token},
        )

    def send(self, path: str, key: str, operation: str, payload: dict) -> dict:
        state = self.get("").json()["state"]
        response = self.client.post(
            "/sessions/" + self.session_id + path,
            headers={"Authorization": "Bearer " + self.token},
            json={
                "schema_version": 2,
                "request_id": key,
                "operation": operation,
                "payload": payload,
                "expected_version": state["business_seq"],
                "expected_workspace_revision": state["workspace_revision"],
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    def run(self) -> bool:
        return Worker(self.app.state.jobs, self.app.state.handlers).run_once()


@contextmanager
def runtime_session(database: Path, language: str, provider: str) -> Iterator[Session]:
    app = create_runtime_app(
        "sqlite:///" + str(database),
        provider=provider,
        scenario_root=locale_root(default_installed_scenario(), language),
    )
    try:
        with TestClient(app) as client:
            made = client.post(
                "/sessions",
                json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
            )
            assert made.status_code == 200, made.text
            body = made.json()
            yield Session(app, client, body["session_id"], body["token"], language)
    finally:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()


def colleague_turn(session: Session) -> dict:
    zh = session.language == "zh"
    session.send(
        "/turns",
        "colleague",
        "turns.create",
        {
            "role_id": "supervisor",
            "text": "请说明试点条件。" if zh else "What are the pilot conditions?",
        },
    )
    session.run()
    return session.get("/requests/colleague").json()


def assistant_generation(session: Session) -> dict:
    config = session.get("/workbench").json()["result"]["result"]["timeline"]["workspace"]["config"]
    base = {
        "session_id": session.session_id,
        "kind": "config",
        "object_id": config["id"],
        "version": config["version"],
        "config_version": config["config_version"],
    }
    session.send(
        "/configuration",
        "llm-mode",
        "configuration.apply",
        {"base": base, "settings": {"generator": "llm"}},
    )
    session.send(
        "/tests",
        "assistant",
        "tests.create",
        {
            "query": "住宿报销上限是多少？"
            if session.language == "zh"
            else "What is the hotel reimbursement limit?",
            "config_version": config["config_version"] + 1,
        },
    )
    session.run()
    return session.get("/requests/assistant").json()


def feedback_review(session: Session) -> dict:
    zh = session.language == "zh"
    product = session.send(
        "/work-products",
        "work",
        "work_products.create",
        {
            "kind": "text",
            "purpose": "commitment",
            "content": "负责人和范围核实前暂缓，保留人工兜底。比较两个候选方案。"
            if zh
            else "Defer until the owner and scope are verified. Keep human fallback. "
            "Compare the two candidate approaches.",
        },
    )
    ref = next(item for item in product["objects"] if item["kind"] == "product")
    transaction = session.send(
        "/reviews",
        "review",
        "reviews.create",
        {"subjects": [ref], "purpose": "commitment", "scope": [], "decision": "launch_narrow"},
    )
    session.run()
    feedback = session.get("/feedback/" + transaction["result"]["review"]["object_id"])
    assert feedback.status_code == 200, feedback.text
    return feedback.json()["result"]["result"]["items"][0]
