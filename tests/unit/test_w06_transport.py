"""Transport boundaries: no credentials in stdout/errors, bounded cancellation."""

import argparse, io, json, os, threading, time
from pathlib import Path
import pytest
from career_lab.contracts import v2 as C
from career_lab.delegations.credentials import load_credentials, redact
from career_lab.delegations.http_client import HttpAgentClient, RemoteFailure, safe_id
from career_lab.delegations.public_output import validate_public_output
from career_lab.mcp.protocol import Protocol, RpcFailure, MODERN, VERSION, CAPABILITIES
from career_lab.mcp.stdio import serve
from career_lab.mcp.__main__ import register_cli

SECRET = "fake-secret-for-tests"


@pytest.mark.parametrize(
    "change",
    [
        {"api_url": "http://example.com"},
        {"api_url": "https://user:password@example.com"},
        {"api_url": "https://example.com?token=x"},
        {"session_id": "../other"},
        {"token": "x\ry"},
    ],
)
def test_w06_credentials_reject_unsafe_settings(tmp_path, change):
    p = tmp_path / "config"
    p.write_text(
        json.dumps(
            {"api_url": "http://127.0.0.1:8000", "session_id": "sid", "token": SECRET} | change
        )
    )
    p.chmod(0o600)
    with pytest.raises(ValueError):
        load_credentials(p)


def test_w06_credentials_require_private_file_and_no_symlink(tmp_path):
    p = tmp_path / "config"
    p.write_text(
        json.dumps({"api_url": "http://127.0.0.1:8000", "session_id": "sid", "token": SECRET})
    )
    p.chmod(0o644)
    with pytest.raises(ValueError):
        load_credentials(p)
    p.chmod(0o600)
    assert SECRET not in repr(load_credentials(p))
    link = tmp_path / "link"
    link.symlink_to(p)
    with pytest.raises(OSError):
        load_credentials(link)
    assert SECRET not in json.dumps(redact({"token": SECRET, "body": "quoted " + SECRET}, SECRET))


@pytest.mark.parametrize("value", ["..", ".", "a/b", "a%2fb", "a\\b", "a\nb"])
def test_w06_route_ids_cannot_escape_fixed_path(value):
    with pytest.raises(RemoteFailure):
        safe_id(value)


class Backend:
    def tools(self):
        return ()


def modern(method, params=None):
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {**(params or {}), "_meta": {VERSION: MODERN, CAPABILITIES: {}}},
    }


@pytest.mark.parametrize(
    "message,code",
    [
        (modern("shell"), -32601),
        ({"jsonrpc": "2.0", "id": 1, "method": "ping"}, -32602),
        ({"jsonrpc": "2.0", "id": None, "method": "ping"}, -32600),
        (modern("tools/list", {"cursor": "-1"}), -32602),
        (modern("tools/list", {"cursor": "5"}), -32602),
    ],
)
def test_w06_stable_protocol_errors(message, code):
    with pytest.raises(RpcFailure) as exc:
        Protocol(Backend()).handle(message)
    assert exc.value.code == code


def test_w06_unsupported_version_and_cli_hook():
    protocol = Protocol(Backend())
    r = modern("ping")
    r["params"]["_meta"][VERSION] = "1900-01-01"
    with pytest.raises(RpcFailure) as exc:
        protocol.handle(r)
    assert exc.value.code == -32022
    parser = argparse.ArgumentParser()
    register_cli(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["mcp", "--config", "private.json"])
    assert callable(args.w06_handler)


def test_w06_invalid_json_stdout_is_protocol_only():
    output = io.StringIO()
    errors = io.StringIO()
    serve(Protocol(Backend()), io.BytesIO(b"garbage fake-secret-for-tests\n"), output, errors)
    result = json.loads(output.getvalue())
    assert result["error"]["code"] == -32700 and SECRET not in output.getvalue() + errors.getvalue()


def test_w06_cancellation_suppresses_response_and_eof_closes():
    entered = threading.Event()
    release = threading.Event()

    class Slow:
        def handle(self, request):
            entered.set()
            release.wait(2)
            return {"done": True}

    class Stream:
        def __init__(self):
            self.n = 0

        def readline(self, limit):
            self.n += 1
            if self.n == 1:
                return json.dumps(modern("ping")).encode() + b"\n"
            if self.n == 2:
                assert entered.wait(1)
                return b'{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":1}}\n'
            release.set()
            return b""

    output = io.StringIO()
    serve(Slow(), Stream(), output, io.StringIO())
    assert output.getvalue() == ""


def test_w06_wait_request_bounded_and_same_business_key():
    class Pending(HttpAgentClient):
        def __init__(self):
            self.calls = []

        def call(self, name, args, deadline=None):
            self.calls.append((name, args))
            return {"status": "pending", "jobs": [{"job_id": "real-public-id", "status": "queued"}]}

    client = Pending()
    start = time.monotonic()
    last = client.wait_request("sid", "same-key", seconds=0.08, interval=0.02)
    assert 0.07 <= time.monotonic() - start < 0.5 and last["jobs"][0]["job_id"] == "real-public-id"
    assert len(client.calls) >= 2 and all(
        c[1]["query"]["request_id"] == "same-key" for c in client.calls
    )


@pytest.mark.parametrize(
    "value",
    [
        {"kind": "role_context", "object_id": "private"},
        {"session_id": "s", "role_id": "r", "text": "x", "generation_audit": {"secret": SECRET}},
        {"session_id": "s", "role_id": "r", "prompt_messages": [SECRET]},
    ],
)
def test_w06_final_role_projection_rejects_untyped_private_carriers(value):
    with pytest.raises(RemoteFailure) as exc:
        validate_public_output({"nested": [value]})
    assert exc.value.code == "public_projection_unavailable" and SECRET not in str(exc.value)


@pytest.mark.parametrize("language,expected", [("zh", "读取"), ("en", "Read")])
def test_w06_localized_tool_explanation_preserves_source(language, expected):
    from career_lab.delegations.localization import tool_description, source_text
    from types import SimpleNamespace

    assert expected in tool_description(language, "read")
    source = SimpleNamespace(text="实际授权的原句 / Exact authorized original.")
    assert source_text(source) == source.text
    with pytest.raises(ValueError):
        tool_description("auto", "read")
