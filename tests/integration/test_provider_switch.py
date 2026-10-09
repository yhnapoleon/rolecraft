"""Configuration-only runtime checks against a loopback OpenAI-compatible server.

The assistant, colleagues and Judge share the formally configured provider.
Controlled replies demonstrate wiring and recovery, never semantic quality.
"""

import json
import secrets
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from career_lab.api.vertical_runtime import create_runtime_app, default_installed_scenario
from career_lab.jobs.worker import Worker
from career_lab.scenarios.v2.localization import locale_root


@dataclass
class Provider:
    language: str
    calls: list[dict] = field(default_factory=list)
    failure: str | None = None

    def reply(self, payload: dict) -> str:
        self.calls.append(payload)
        messages = payload["messages"]
        system = messages[0]["content"]
        if system.startswith("assistant-generation-v1"):
            data = json.loads(messages[1]["content"])
            return json.dumps(
                {
                    "answer": data["candidates"][0]["text"],
                    "citation_ids": [data["candidates"][0]["id"]],
                }
            )
        if "citation_ids" in system:
            data = json.loads(messages[1]["content"])
            return json.dumps(
                {
                    "criterion": data["criterion"],
                    "label": "INSUFFICIENT",
                    "applicability": data["applicability"],
                    "citation_ids": [],
                    "explanation": "机制验证：仍需补充比较依据。"
                    if self.language == "zh"
                    else "Mechanism verification: additional comparison evidence is needed.",
                }
            )
        return (
            "机制验证：你想先核对哪项试点条件？"
            if self.language == "zh"
            else ("Mechanism verification: which pilot condition would you like to verify first?")
        )


@dataclass
class RuntimeSession:
    app: FastAPI
    client: TestClient
    session: dict
    provider: Provider
    key: str = field(repr=False)
    directory: Path

    def get(self, path: str) -> httpx.Response:
        return self.client.get(
            "/sessions/" + self.session["session_id"] + path,
            headers={"Authorization": "Bearer " + self.session["token"]},
        )

    def send(self, path: str, key: str, operation: str, payload: dict) -> dict:
        state = self.get("").json()["state"]
        response = self.client.post(
            "/sessions/" + self.session["session_id"] + path,
            headers={"Authorization": "Bearer " + self.session["token"]},
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

    def run(self) -> None:
        assert Worker(self.app.state.jobs, self.app.state.handlers).run_once()


@pytest.fixture(params=["zh", "en"])
def runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[RuntimeSession]:
    language, configured_provider = (
        request.param if isinstance(request.param, tuple) else (request.param, "openai")
    )
    provider = Provider(language)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            assert self.path == "/chat/completions"
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            content = provider.reply(payload)
            status = 503 if provider.failure == "http" else 200
            body = (
                b"{broken"
                if provider.failure == "json"
                else json.dumps(
                    {
                        "choices": [{"message": {"content": content}}],
                        "usage": {"prompt_tokens": 40, "completion_tokens": 16},
                    }
                ).encode()
            )
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    key = "sk-" + secrets.token_hex(24)
    key_file = tmp_path / "provider.key"
    key_file.write_text(key)
    monkeypatch.setenv("CAREER_LAB_KEY_FILE", str(key_file))
    monkeypatch.setenv("CAREER_LAB_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("CAREER_LAB_MODEL", "controlled-mechanism")
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    monkeypatch.delenv("CAREER_LAB_SCENARIO_CATALOG", raising=False)
    app = create_runtime_app(
        "sqlite:///" + str(tmp_path / "runtime.db"),
        provider=configured_provider,
        scenario_root=locale_root(default_installed_scenario(), language),
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                "/sessions",
                json={
                    "schema_version": 2,
                    "scenario": "pm_pilot_v2",
                    "work_language": language,
                },
            )
            assert response.status_code == 200, response.text
            yield RuntimeSession(app, client, response.json(), provider, key, tmp_path)
    finally:
        app.state.store.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_configured_runtime_colleague_and_judge_reach_provider(runtime: RuntimeSession, caplog):
    language = runtime.provider.language
    runtime.send(
        "/turns",
        "colleague",
        "turns.create",
        {
            "role_id": "supervisor",
            "text": "请说明试点条件。" if language == "zh" else "What are the pilot conditions?",
        },
    )
    runtime.run()
    assert len(runtime.provider.calls) == 1
    role = runtime.get("/requests/colleague").json()
    assert role["status"] == "completed", role
    assert runtime.get("/requests/colleague").json() == role
    assert len(runtime.provider.calls) == 1
    product = runtime.send(
        "/work-products",
        "work",
        "work_products.create",
        {
            "kind": "text",
            "purpose": "comparison",
            "content": "需要比较候选方案，并记录未知条件。"
            if language == "zh"
            else "Compare the candidate approaches and record unknown conditions.",
        },
    )
    ref = next(item for item in product["objects"] if item["kind"] == "product")
    runtime.send(
        "/reviews",
        "review",
        "reviews.create",
        {
            "subjects": [ref],
            "purpose": "comparison",
            "scope": ["R6.alternatives"],
        },
    )
    runtime.run()
    review = runtime.get("/requests/review").json()
    assert review["status"] == "completed", review
    assert len(runtime.provider.calls) == 2
    assert runtime.get("/requests/review").json() == review
    assert not Worker(runtime.app.state.jobs, runtime.app.state.handlers).run_once()
    assert len(runtime.provider.calls) == 2
    assert all(call["model"] == "controlled-mechanism" for call in runtime.provider.calls)
    assert runtime.key not in json.dumps([role, review, runtime.provider.calls])
    assert runtime.key not in caplog.text
    for file in runtime.directory.iterdir():
        if file.name.startswith("runtime.db"):
            assert runtime.key.encode() not in file.read_bytes()


def test_formal_factory_retains_missing_assistant_provider_status(runtime: RuntimeSession):
    """Retain the historical test ID while verifying the now-connected factory."""
    assert_assistant_generation(runtime, "openai")


@pytest.mark.parametrize("runtime", [("zh", "deepseek"), ("en", "deepseek")], indirect=True)
def test_deepseek_runtime_assistant_uses_same_configuration_path(runtime: RuntimeSession):
    assert_assistant_generation(runtime, "deepseek")


def assert_assistant_generation(runtime: RuntimeSession, expected_provider: str) -> None:
    config = runtime.get("/workbench").json()["result"]["result"]["timeline"]["workspace"]["config"]
    base = {
        "session_id": runtime.session["session_id"],
        "kind": "config",
        "object_id": config["id"],
        "version": config["version"],
        "config_version": config["config_version"],
    }
    runtime.send(
        "/configuration",
        "llm-mode",
        "configuration.apply",
        {
            "base": base,
            "settings": {"generator": "llm"},
        },
    )
    result = runtime.send(
        "/tests",
        "assistant",
        "tests.create",
        {
            "query": "住宿报销上限是多少？"
            if runtime.provider.language == "zh"
            else "What is the hotel reimbursement limit?",
            "config_version": 1,
        },
    )
    assert result["result"]["status"] == "queued"
    assert runtime.provider.calls == []
    runtime.run()
    saved = runtime.get("/requests/assistant").json()
    assert saved["status"] == "completed", saved
    result = saved["jobs"][0]["effect"]["result"]
    assert result["test"]["status"] == "answered"
    assert result["generation"]["mode"] == "llm"
    assert result["generation"]["work_language"] == runtime.provider.language
    assert result["generation"]["provider"] == expected_provider
    assert result["test"]["citations"][0]["version"] == 1
    assert len(runtime.provider.calls) == 1
    assert runtime.get("/requests/assistant").json() == saved
    assert len(runtime.provider.calls) == 1
    assert runtime.key not in json.dumps([saved, runtime.provider.calls])


@pytest.mark.parametrize("failure", ["http", "json"])
def test_failed_configured_role_never_retries(runtime: RuntimeSession, failure: str):
    runtime.provider.failure = failure
    runtime.send(
        "/turns",
        "failed-role",
        "turns.create",
        {
            "role_id": "supervisor",
            "text": "请说明试点条件。"
            if runtime.provider.language == "zh"
            else "What are the pilot conditions?",
        },
    )
    runtime.run()
    saved = runtime.get("/requests/failed-role").json()
    assert saved["status"] == "failed", saved
    assert len(runtime.provider.calls) == 1
    assert not Worker(runtime.app.state.jobs, runtime.app.state.handlers).run_once()
    assert runtime.get("/requests/failed-role").json() == saved
    assert len(runtime.provider.calls) == 1


@pytest.mark.parametrize("failure", ["http", "json"])
def test_failed_configured_judge_retains_work_without_retry(runtime: RuntimeSession, failure: str):
    runtime.provider.failure = failure
    language = runtime.provider.language
    product = runtime.send(
        "/work-products",
        "work",
        "work_products.create",
        {
            "kind": "text",
            "purpose": "comparison",
            "content": "比较缩小范围与延后试点两种方案。"
            if language == "zh"
            else "Compare reducing the scope with delaying the pilot.",
        },
    )
    ref = next(item for item in product["objects"] if item["kind"] == "product")
    runtime.send(
        "/reviews",
        "failed-judge",
        "reviews.create",
        {
            "subjects": [ref],
            "purpose": "comparison",
            "scope": ["R6.alternatives"],
        },
    )
    runtime.run()
    saved = runtime.get("/requests/failed-judge").json()
    assert saved["status"] == "completed", saved
    assert len(runtime.provider.calls) == 1
    feedback = saved["jobs"][0]["effect"]["result"]["feedbacks"][0]
    result = runtime.get("/feedback-records/" + feedback["object_id"]).json()["result"]["result"][
        "feedback"
    ]
    assert result["model_coverage"] == 0
    assert result["items"][0]["label"] == "INSUFFICIENT"
    assert not Worker(runtime.app.state.jobs, runtime.app.state.handlers).run_once()
    assert runtime.get("/requests/failed-judge").json() == saved
    assert len(runtime.provider.calls) == 1
    assert runtime.key not in json.dumps([saved, result, runtime.provider.calls])
