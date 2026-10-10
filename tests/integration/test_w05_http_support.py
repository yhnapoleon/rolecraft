"""Real HTTP harness using the installed runtime and its actual feedback worker."""

import json
import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from career_lab.api.evaluation_runtime import create_feedback_handler
from career_lab.api.vertical_runtime import create_runtime_app, default_installed_scenario
from career_lab.jobs.worker import Worker
from career_lab.runtime.model_adapter import ModelReply
from career_lab.scenarios.v2.module import ScenarioModule


class OverconfidentModel:
    """Controlled external transport only; no real provider or quality claim."""

    revision = "controlled-local/overconfident-v1"
    provider = "controlled-local"
    retries = 0

    def complete(self, messages: list[dict[str, Any]], tools: list[Any]) -> ModelReply:
        payload = json.loads(messages[1]["content"])
        return ModelReply(
            text=json.dumps(
                {
                    "criterion": payload.get("criterion"),
                    "label": "MET",
                    "applicability": "applicable",
                    "explanation": "Controlled overconfident advice",
                    "citation_ids": [],
                }
            )
        )


class WorkSession:
    def __init__(self, app: FastAPI, client: httpx.Client, language: str) -> None:
        self.app = app
        self.client = client
        self.language = language
        response = client.post(
            "/sessions",
            json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
        )
        assert response.status_code == 200, response.text
        created = response.json()
        self.sid: str = created["session_id"]
        self.headers = {"Authorization": "Bearer " + created["token"]}
        self.sequence = 0

    def get(self, path: str = "", *, headers: dict[str, str] | None = None) -> dict[str, Any]:
        response = self.client.get(
            "/sessions/" + self.sid + ("/" + path if path else ""),
            headers=self.headers if headers is None else headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        while isinstance(data.get("result"), dict):
            data = data["result"]
        return data

    def post(self, path: str, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        state = self.get()["state"]
        self.sequence += 1
        response = self.client.post(
            f"/sessions/{self.sid}/{path}",
            headers=self.headers,
            json={
                "schema_version": 2,
                "request_id": "http-request-" + str(self.sequence),
                "operation": operation,
                "expected_version": state["business_seq"],
                "expected_workspace_revision": state["workspace_revision"],
                "payload": payload,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    def product(self, text: str, *, purpose: str = "exploration", **extra: Any) -> dict[str, Any]:
        return self.post(
            "work-products",
            "work_products.create",
            {"kind": "text", "purpose": purpose, "title": "Working note", "content": text, **extra},
        )["result"]["ref"]

    def review(self, product: dict[str, Any], **options: Any) -> dict[str, Any]:
        result = self.post(
            "reviews",
            "reviews.create",
            {"subjects": [product], "purpose": "exploration", "scope": [], **options},
        )
        Worker(self.app.state.jobs, self.app.state.handlers).run_once()
        recovery = self.get("requests/http-request-" + str(self.sequence))
        assert recovery["jobs"][0]["status"] == "completed", recovery
        return self.get("feedback/" + result["result"]["review"]["object_id"])["items"][0]

    def delegate(self, allowed_ids: set[str]) -> dict[str, str]:
        result = self.post(
            "delegations",
            "delegations.create",
            {
                "capabilities": ["read"],
                "allowed_objects": sorted(allowed_ids),
                "expires_at": (datetime.now(UTC) + timedelta(minutes=20)).isoformat(),
                "agent_label": "Evidence reader",
            },
        )
        while isinstance(result.get("result"), dict):
            result = result["result"]
        return {"Authorization": "Bearer " + result["token"]}


def referenced_ids(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = {value["object_id"]} if "object_id" in value else set()
        return found | set().union(*(referenced_ids(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(referenced_ids(item) for item in value))
    return set()


@pytest.fixture(params=["zh", "en"])
def work_session(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[WorkSession]:
    language = request.param[0] if isinstance(request.param, tuple) else str(request.param)
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    monkeypatch.delenv("CAREER_LAB_SCENARIO_CATALOG", raising=False)
    root = default_installed_scenario()
    if language == "en":
        root = root / "locales" / "en"
    handler = None
    if isinstance(request.param, tuple):
        handler = create_feedback_handler(ScenarioModule(root), model=OverconfidentModel())
    app = create_runtime_app(
        "sqlite:///" + str(tmp_path / "http.db"), scenario_root=root, feedback_handler=handler
    )
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", 0))
    except OSError:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()
        sock.close()
        raise
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "HTTP server did not start"
        base_url = "http://127.0.0.1:" + str(sock.getsockname()[1])
        with httpx.Client(base_url=base_url, timeout=90, trust_env=False) as client:
            yield WorkSession(app, client, language)
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        sock.close()
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()
        assert not thread.is_alive(), "HTTP server did not stop"
