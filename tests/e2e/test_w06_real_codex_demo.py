"""Offline protocol-control checks, explicitly NOT a real Agent demonstration."""

import json
from pathlib import Path
import queue
from types import SimpleNamespace
import time
import pytest

from examples.byo_agent_client import real_codex_demo as m


@pytest.fixture
def demo(tmp_path, monkeypatch):
    d = object.__new__(m.CodexAgentDemo)
    d.config_path = tmp_path / "delegate.json"
    d.directory = tmp_path
    d.agent_cwd = tmp_path / "empty-agent"
    d.credentials = SimpleNamespace(
        session_id="session1", token="SECRET_TOKEN", api_url="http://127.0.0.1:9"
    )
    d.report = {
        "status": "preparing",
        "model_turn_started": False,
        "demo_accepted": False,
        "human_handback": "pending",
    }
    d.sent = []
    d.events = []
    d.completed_turns = {}
    d.sequence = 0
    d.thread_id = d.turn_id = None
    d.messages = queue.Queue()
    d.wire = []
    d.send = d.wire.append
    monkeypatch.setattr(
        m,
        "HttpAgentClient",
        lambda *_: SimpleNamespace(
            observation=lambda *_: SimpleNamespace(visible_sources=["public"], tools=[])
        ),
    )
    d.binding = {
        "protocol": 2,
        "sessionId": "session1",
        "workLanguage": "en",
        "scenarioHash": "a" * 64,
    }
    monkeypatch.setattr(m, "session_binding", lambda *_: dict(d.binding))
    return d


def config():
    return {
        "model_provider": m.PROVIDER,
        "web_search": "disabled",
        "model_providers": {m.PROVIDER: {"request_max_retries": 0, "stream_max_retries": 0}},
        "features": {key: False for key in m.DISABLED_FEATURES},
        "mcp_servers": {
            "rolecraft": {
                "enabled_tools": list(m.DEMO_TOOLS),
                "tools": {name: {"approval_mode": "approve"} for name in m.AUTHORIZED_WRITES},
            }
        },
    }


@pytest.mark.parametrize("account", [None, {"type": "apiKey"}, {"type": "amazonBedrock"}])
def test_preflight_refuses_non_subscription_before_any_turn(demo, account):
    def rpc(method, params, **kw):
        demo.sent.append(method)
        return {"account": account} if method == "account/read" else {}

    demo.rpc = rpc
    with pytest.raises(m.DemoFailure, match="existing_chatgpt_subscription_required"):
        demo.preflight()
    assert demo.sent == ["initialize", "account/read"]
    assert not demo.report["model_turn_started"]


def test_preflight_is_no_turn_redacted_and_requires_zero_retry(demo):
    settings = config()

    def rpc(method, params, **kw):
        demo.sent.append(method)
        if method == "account/read":
            return {"account": {"type": "chatgpt", "email": "PRIVATE_EMAIL", "planType": "pro"}}
        if method == "config/read":
            return {"config": settings}
        return {}

    demo.rpc = rpc
    demo.preflight()
    assert demo.sent == ["initialize", "account/read", "config/read"]
    assert "PRIVATE_EMAIL" not in (demo.directory / "codex-agent-trace.json").read_text()
    settings["model_providers"][m.PROVIDER]["request_max_retries"] = 1
    with pytest.raises(m.DemoFailure, match="effective_demo_configuration_mismatch"):
        demo.preflight()
    assert "turn/start" not in demo.sent


@pytest.mark.parametrize("language", ["zh", "en"])
def test_model_turn_mcp_events_do_not_claim_human_or_product_acceptance(demo, language):
    demo.report["status"] = "preflight_complete"
    demo.binding["workLanguage"] = language

    def rpc(method, params, **kw):
        demo.sent.append(method)
        if method == "thread/start":
            return {
                "thread": {"id": "thread1"},
                "model": "recorded-model",
                "modelProvider": m.PROVIDER,
                "sandbox": {"type": "readOnly"},
            }
        assert method == "turn/start"
        assert (
            language == "zh"
            and "Chinese" in params["input"][0]["text"]
            or language == "en"
            and "English" in params["input"][0]["text"]
        )
        demo.events.append(
            {
                "method": "item/completed",
                "params": {
                    "threadId": "thread1",
                    "item": {
                        "type": "mcpToolCall",
                        "server": "rolecraft",
                        "tool": "work_products.create",
                        "arguments": {"command": {"request_id": "original-business-key"}},
                        "result": {"public": "SECRET_TOKEN"},
                    },
                },
            }
        )
        demo.completed_turns["turn1"] = {"id": "turn1", "status": "completed"}
        return {"turn": {"id": "turn1"}}

    demo.rpc = rpc
    result = demo.run_turn("Prepare a source-backed work product.", language=language)
    assert result["status"] == "agent_turn_completed_pending_product_verification"
    assert result["human_handback"] == "pending" and result["demo_accepted"] is False
    assert result["work_language_verified"] is True
    assert result["business_request_ids"] == ["original-business-key"]
    assert "SECRET_TOKEN" not in (demo.directory / "codex-agent-trace.json").read_text()
    assert demo.sent == ["thread/start", "turn/start"]
    with pytest.raises(m.DemoFailure, match="fresh_preflight_required"):
        demo.run_turn("again", language=language)


@pytest.mark.parametrize("status", ["completed", "failed", "interrupted"])
def test_missing_mcp_or_failed_turn_never_becomes_demo_success(demo, status):
    demo.report["status"] = "preflight_complete"

    def rpc(method, params, **kw):
        demo.sent.append(method)
        if method == "thread/start":
            return {
                "thread": {"id": "thread1"},
                "modelProvider": m.PROVIDER,
                "sandbox": {"type": "readOnly"},
            }
        demo.completed_turns["turn1"] = {"id": "turn1", "status": status}
        return {"turn": {"id": "turn1"}}

    demo.rpc = rpc
    with pytest.raises(m.DemoFailure):
        demo.run_turn("A real task", language="en")
    assert demo.report["status"] == "incomplete" and not demo.report["demo_accepted"]
    assert demo.sent.count("turn/start") == 1


def test_early_turn_notification_and_unexpected_retry_are_recorded(demo):
    demo.thread_id = "thread1"
    demo.messages.put(
        {"method": "turn/started", "params": {"threadId": "thread1", "turn": {"id": "turn1"}}}
    )
    demo.receive(time.monotonic() + 1)
    assert demo.turn_id == "turn1" and demo.report["model_turn_started"]
    demo.messages.put({"method": "error", "params": {"threadId": "thread1", "willRetry": True}})
    with pytest.raises(m.DemoFailure, match="unexpected_model_retry"):
        demo.receive(time.monotonic() + 1)
    assert demo.events[-1]["method"] == "error"


def test_unexpected_server_approval_is_not_auto_accepted(demo):
    demo.messages.put({"id": 99, "method": "item/permissions/requestApproval", "params": {}})
    with pytest.raises(m.DemoFailure, match="operator_review_required"):
        demo.receive(time.monotonic() + 1)
    assert demo.wire[0]["id"] == 99 and "error" in demo.wire[0]
    assert demo.report["pending_request_method"] == "item/permissions/requestApproval"


def test_language_mismatch_stops_before_thread_or_model(demo):
    demo.report["status"] = "preflight_complete"
    with pytest.raises(m.DemoFailure, match="work_language_mismatch"):
        demo.run_turn("调查当前来源", language="zh")
    assert not demo.sent and not demo.report["model_turn_started"]


@pytest.mark.parametrize("fault", ["missing_write_permission", "extra_tool"])
def test_preflight_rejects_incomplete_or_expanded_tool_permission(demo, fault):
    settings = config()
    if fault == "missing_write_permission":
        settings["mcp_servers"]["rolecraft"]["tools"].pop("tests.create")
    else:
        settings["mcp_servers"]["rolecraft"]["enabled_tools"].append("submissions.create")

    def rpc(method, params, **kw):
        demo.sent.append(method)
        if method == "account/read":
            return {"account": {"type": "chatgpt", "planType": "pro"}}
        if method == "config/read":
            return {"config": settings}
        return {}

    demo.rpc = rpc
    with pytest.raises(m.DemoFailure, match="explicit_demo_tool_authorization_missing"):
        demo.preflight()
    assert "turn/start" not in demo.sent


@pytest.mark.parametrize(
    "status,binding,error",
    [
        (403, None, "authorized_session_binding_unavailable"),
        (
            200,
            {"protocol": 2, "sessionId": "another", "workLanguage": "en", "scenarioHash": "a" * 64},
            "session_binding_invalid",
        ),
        (
            200,
            {"protocol": 2, "sessionId": "session1", "workLanguage": "en"},
            "session_binding_invalid",
        ),
        (
            200,
            {
                "protocol": 2,
                "sessionId": "session1",
                "workLanguage": "fr",
                "scenarioHash": "a" * 64,
            },
            "session_binding_invalid",
        ),
    ],
)
def test_live_binding_rejects_unavailable_or_mixed_context(
    tmp_path, monkeypatch, status, binding, error
):
    class Client:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kw):
            assert url == "http://127.0.0.1:9/sessions/session1/workbench"
            return SimpleNamespace(
                status_code=status,
                json=lambda: {"schema_version": 2, "result": {"result": {"session": binding}}},
            )

    monkeypatch.setattr(m.httpx, "Client", Client)
    credentials = SimpleNamespace(
        api_url="http://127.0.0.1:9", session_id="session1", token="SECRET"
    )
    with pytest.raises(m.DemoFailure, match=error):
        m.session_binding(credentials)


def test_child_override_preserves_literal_dots_in_tool_names(tmp_path):
    import tomllib

    settings = m.overrides(tmp_path / "delegate.json", tmp_path)
    value = tomllib.loads(next(s for s in settings if s.startswith("mcp_servers=")))
    server = value["mcp_servers"]["rolecraft"]
    assert set(server["tools"]) == set(m.AUTHORIZED_WRITES)
    assert server["tools"]["tests.create"]["approval_mode"] == "approve"
    assert "submissions.create" not in server["enabled_tools"]
