"""MCP Streamable HTTP endpoint on the API: same authorization path as stdio, no model calls."""

import importlib.util
import json
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career_lab.contracts import v2 as C
from career_lab.delegations.http_client import HttpAgentClient, RemoteFailure
from career_lab.mcp.protocol import CAPABILITIES, LEGACY, MODERN, VERSION
from career_lab.mcp.streamable_http import HttpLimits, mount_mcp_http

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location(
    "w06_gateway_fixture_streamable_http", ROOT / "tests/integration/test_w06_gateway.py"
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
env = fixture.env
CLIENT_INFO = "io.modelcontextprotocol/clientInfo"


@pytest.fixture
def mcp(env):
    mount_mcp_http(env["app"])
    client = TestClient(env["app"], base_url="http://127.0.0.1")
    yield client
    client.close()


def modern_body(method, params=None, identifier=1):
    meta = {VERSION: MODERN, CAPABILITIES: {}, CLIENT_INFO: {"name": "test", "version": "1"}}
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "method": method,
        "params": {**(params or {}), "_meta": meta},
    }


def modern(mcp, sid, token, method, params=None, *, name=None, headers=None, identifier=1):
    sent = {
        "Authorization": "Bearer " + token,
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MODERN,
        "Mcp-Method": method,
        **({"Mcp-Name": name} if name is not None else {}),
        **(headers or {}),
    }
    return mcp.post(
        f"/sessions/{sid}/mcp", json=modern_body(method, params, identifier), headers=sent
    )


def call(mcp, sid, token, tool, arguments=None, **kw):
    params = {"name": tool, "arguments": arguments or {}}
    return modern(mcp, sid, token, "tools/call", params, name=tool, **kw)


def test_mcp_http_modern_client_discovers_lists_and_reads(env, mcp):
    created, _ = fixture.grant(env, ("read",))
    token, sid = created["token"], env["sid"]
    discovered = modern(mcp, sid, token, "server/discover")
    assert discovered.status_code == 200, discovered.text
    assert discovered.headers["content-type"] == "application/json"
    assert discovered.headers["cache-control"] == "no-store"
    result = discovered.json()["result"]
    assert result["resultType"] == "complete" and result["supportedVersions"] == [MODERN, LEGACY]
    listed = modern(mcp, sid, token, "tools/list").json()["result"]["tools"]
    assert {"observation", "work_items.list"} <= {tool["name"] for tool in listed}
    observed = call(mcp, sid, token, "observation").json()["result"]
    assert observed["isError"] is False
    assert observed["structuredContent"]["result"]["session_id"] == sid
    assert "mcp-session-id" not in {key.lower() for key in discovered.headers}


def legacy(mcp, sid, token, message, *, version=LEGACY):
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json, text/event-stream"}
    if version is not None:
        headers["MCP-Protocol-Version"] = version
    return mcp.post(f"/sessions/{sid}/mcp", json=message, headers=headers)


def test_mcp_http_legacy_client_initializes_and_calls_tools(env, mcp):
    created, _ = fixture.grant(env, ("read",))
    token, sid = created["token"], env["sid"]
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "legacy", "version": "1"},
        },
    }
    started = legacy(mcp, sid, token, initialize, version=None)
    assert started.status_code == 200, started.text
    assert started.json()["result"]["protocolVersion"] == LEGACY
    assert "mcp-session-id" not in {key.lower() for key in started.headers}
    ready = legacy(mcp, sid, token, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert ready.status_code == 202 and ready.content == b""
    listed = legacy(mcp, sid, token, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert "work_items.list" in {tool["name"] for tool in listed.json()["result"]["tools"]}
    called = legacy(
        mcp,
        sid,
        token,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "work_items.list", "arguments": {}},
        },
    ).json()
    assert called["id"] == 3 and called["result"]["isError"] is False


def test_mcp_http_write_grant_returns_work_once_and_read_grant_cannot(env, mcp):
    writer, _ = fixture.grant(env, ("read", "act"))
    command = fixture.command(
        env, "work_products.create", {"kind": "text", "content": "Returned over HTTP MCP"}
    )
    arguments = {"command": command}
    first = call(mcp, env["sid"], writer["token"], "work_products.create", arguments).json()
    assert first["result"]["isError"] is False, first
    product = first["result"]["structuredContent"]
    assert product["executor"]["kind"] == "external_agent" and not product["replayed"]
    again = call(mcp, env["sid"], writer["token"], "work_products.create", arguments).json()
    assert again["result"]["structuredContent"]["replayed"] is True
    reader, _ = fixture.grant(env, ("read",))
    listed = modern(mcp, env["sid"], reader["token"], "tools/list").json()["result"]["tools"]
    assert "work_products.create" not in {tool["name"] for tool in listed}
    refused = call(mcp, env["sid"], reader["token"], "work_products.create", arguments).json()
    assert refused["result"]["isError"] is True
    assert refused["result"]["structuredContent"]["code"] == "capability_forbidden"


def grant_until(env, expires_at):
    body = C.DelegationInput(capabilities=("read",), expires_at=expires_at, agent_label="short")
    issued = env["client"].post(
        f"/sessions/{env['sid']}/delegations",
        json=fixture.command(env, "delegations.create", body.model_dump(mode="json")),
    )
    assert issued.status_code == 200, issued.text
    return issued.json()["result"]["result"]


def refusal(response, status, code):
    assert response.status_code == status, response.text
    body = response.json()
    assert "id" not in body and body["error"]["data"]["code"] == code
    return body["error"]


def test_mcp_http_rejects_revoked_and_expired_authorizations(env, mcp):
    created, _ = fixture.grant(env, ("read",))
    assert modern(mcp, env["sid"], created["token"], "tools/list").status_code == 200
    delegation = created["delegation"]["id"]
    revoke = fixture.command(env, "delegations.revoke", {"delegation_id": delegation})
    revoked = env["client"].request(
        "DELETE", f"/sessions/{env['sid']}/delegations/{delegation}", json=revoke
    )
    assert revoked.status_code == 200, revoked.text
    denied = modern(mcp, env["sid"], created["token"], "tools/list")
    assert refusal(denied, 401, "credential_revoked_or_invalid")["code"] == 1003
    assert denied.headers["www-authenticate"] == 'Bearer realm="rolecraft", error="invalid_token"'
    soon = datetime.now(UTC) + timedelta(seconds=2)
    short = grant_until(env, soon)
    assert modern(mcp, env["sid"], short["token"], "tools/list").status_code == 200
    while datetime.now(UTC) <= soon:
        time.sleep(0.1)
    refusal(modern(mcp, env["sid"], short["token"], "tools/list"), 401, "credential_expired")


def second_session(env):
    created = (
        env["client"]
        .post("/sessions", json={"schema_version": 2, "scenario": "controlled-w06"})
        .json()
    )
    return created["session_id"]


def test_mcp_http_keeps_each_authorization_inside_its_own_session(env, mcp):
    created, _ = fixture.grant(env, ("read",))
    token, sid = created["token"], env["sid"]
    other = second_session(env)
    refusal(modern(mcp, other, token, "tools/list"), 401, "token_invalid")
    explicit = call(mcp, sid, token, "work_items.list", {"session_id": other}).json()["result"]
    assert explicit["isError"] and explicit["structuredContent"]["code"] == "session_route_mismatch"


def test_mcp_http_accepts_only_a_delegated_agent_token(env, mcp):
    refusal(modern(mcp, env["sid"], env["token"], "tools/list"), 401, "delegation_required")
    missing = mcp.post(f"/sessions/{env['sid']}/mcp", json=modern_body("tools/list"))
    assert refusal(missing, 401, "token_required")["code"] == 1003
    assert missing.headers["www-authenticate"] == 'Bearer realm="rolecraft"'
    basic = mcp.post(
        f"/sessions/{env['sid']}/mcp",
        json=modern_body("tools/list"),
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    refusal(basic, 401, "token_required")


@pytest.mark.parametrize(
    "origin", ["http://127.0.0.1", "null", "http://localhost:5173", "https://evil.example"]
)
def test_mcp_http_refuses_any_browser_origin(env, mcp, origin):
    created, _ = fixture.grant(env, ("read",))
    refused = modern(mcp, env["sid"], created["token"], "tools/list", headers={"Origin": origin})
    assert refused.status_code == 403
    assert refused.json() == {
        "jsonrpc": "2.0",
        "error": {"code": 1005, "message": "Browser-origin requests are not accepted"},
    }
    assert not any(key.lower().startswith("access-control-") for key in refused.headers)


def test_mcp_http_serves_loopback_hosts_and_post_only(env, mcp):
    created, _ = fixture.grant(env, ("read",))
    for host in ("127.0.0.1:20020", "localhost", "[::1]:8000"):
        served = modern(mcp, env["sid"], created["token"], "ping", headers={"Host": host})
        assert served.status_code == 200, (host, served.text)
    rebound = modern(
        mcp, env["sid"], created["token"], "ping", headers={"Host": "evil.example:20020"}
    )
    assert rebound.status_code == 403 and rebound.json()["error"]["code"] == 1005
    for method in ("GET", "DELETE", "OPTIONS"):
        other = mcp.request(
            method,
            f"/sessions/{env['sid']}/mcp",
            headers={"Authorization": "Bearer " + created["token"]},
        )
        assert other.status_code == 405 and other.headers["allow"] == "POST"
        assert not any(key.lower().startswith("access-control-") for key in other.headers)


def post(mcp, sid, token, body, headers):
    return mcp.post(
        f"/sessions/{sid}/mcp", json=body, headers={"Authorization": "Bearer " + token, **headers}
    )


def rpc_code(response, status):
    assert response.status_code == status, response.text
    return response.json()["error"]["code"]


def test_mcp_http_checks_mirrored_headers_against_the_body(env, mcp):
    created, _ = fixture.grant(env, ("read",))
    token, sid = created["token"], env["sid"]
    listing = modern_body("tools/list")
    full = {"MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/list"}
    assert rpc_code(post(mcp, sid, token, listing, {"Mcp-Method": "tools/list"}), 400) == -32020
    stale = {**full, "MCP-Protocol-Version": LEGACY}
    assert rpc_code(post(mcp, sid, token, listing, stale), 400) == -32020
    assert rpc_code(post(mcp, sid, token, listing, {"MCP-Protocol-Version": MODERN}), 400) == -32020
    wrong = {**full, "Mcp-Method": "tools/call"}
    assert rpc_code(post(mcp, sid, token, listing, wrong), 400) == -32020
    calling = modern_body("tools/call", {"name": "work_items.list", "arguments": {}})
    named = {"MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/call"}
    assert rpc_code(post(mcp, sid, token, calling, named), 400) == -32020
    other = {**named, "Mcp-Name": "materials.list"}
    assert rpc_code(post(mcp, sid, token, calling, other), 400) == -32020
    encoded = {**named, "Mcp-Name": "=?base64?" + "d29ya19pdGVtcy5saXN0" + "?="}
    assert post(mcp, sid, token, calling, encoded).json()["result"]["isError"] is False


def test_mcp_http_reports_version_method_and_metadata_errors_with_http_status(env, mcp):
    created, _ = fixture.grant(env, ("read",))
    token, sid = created["token"], env["sid"]
    future = modern_body("ping")
    future["params"]["_meta"][VERSION] = "2099-01-01"
    headers = {"MCP-Protocol-Version": "2099-01-01", "Mcp-Method": "ping"}
    unsupported = post(mcp, sid, token, future, headers)
    assert rpc_code(unsupported, 400) == -32022
    assert unsupported.json()["error"]["data"] == {
        "supported": [MODERN, LEGACY],
        "requested": "2099-01-01",
    }
    unknown = modern(mcp, sid, token, "unknown/method")
    assert rpc_code(unknown, 404) == -32601 and unknown.json()["id"] == 1
    bare = modern_body("tools/list")
    del bare["params"]["_meta"][CAPABILITIES]
    headers = {"MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/list"}
    assert rpc_code(post(mcp, sid, token, bare, headers), 400) == -32602


def test_mcp_http_rejects_malformed_transport_input(env, mcp):
    created, _ = fixture.grant(env, ("read",))
    token, sid = created["token"], env["sid"]
    url = f"/sessions/{sid}/mcp"
    auth = {"Authorization": "Bearer " + token}
    listing = modern_body("tools/list")
    full = {**auth, "MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/list"}
    batch = mcp.post(url, json=[listing], headers=full)
    assert rpc_code(batch, 400) == -32600
    answer = mcp.post(url, json={"jsonrpc": "2.0", "id": 9, "result": {}}, headers=full)
    assert rpc_code(answer, 400) == -32600
    assert rpc_code(mcp.post(url + "?token=" + token, json=listing, headers=full), 400) == -32600
    garbled = mcp.post(
        url, content=b"{not json", headers={**full, "Content-Type": "application/json"}
    )
    assert rpc_code(garbled, 400) == -32700
    text = mcp.post(url, content=b"{}", headers={**full, "Content-Type": "text/plain"})
    assert text.status_code == 415
    html = mcp.post(url, json=listing, headers={**full, "Accept": "text/html"})
    assert html.status_code == 406
    assert mcp.post(url, json=listing, headers={**full, "Accept": "*/*"}).status_code == 200
    huge = {**listing, "params": {**listing["params"], "pad": "x" * 1_048_577}}
    assert mcp.post(url, json=huge, headers=full).status_code == 413
    plain = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    unversioned = mcp.post(url, json=plain, headers=auth)
    assert rpc_code(unversioned, 400) == -32600
    assert unversioned.json()["error"]["data"] == {"supported": [MODERN, LEGACY]}


def failing_tools(error):
    def tools(self):
        raise error

    return tools


def test_mcp_http_maps_backend_failures_without_leaking_details(env, mcp, monkeypatch):
    created, _ = fixture.grant(env, ("read",))
    token, sid = created["token"], env["sid"]
    monkeypatch.setattr(
        HttpAgentClient, "tools", failing_tools(RemoteFailure("credential_revoked_or_invalid", 403))
    )
    refusal(modern(mcp, sid, token, "tools/list"), 401, "credential_revoked_or_invalid")
    monkeypatch.setattr(
        HttpAgentClient, "tools", failing_tools(RemoteFailure("response_unconfirmed"))
    )
    unconfirmed = modern(mcp, sid, token, "tools/list")
    assert unconfirmed.status_code == 200
    assert unconfirmed.json()["error"] == {
        "code": 1001,
        "message": "RoleCraft service unavailable",
        "data": {"code": "response_unconfirmed"},
    }
    monkeypatch.setattr(HttpAgentClient, "tools", failing_tools(RuntimeError("detail " + token)))
    broken = modern(mcp, sid, token, "tools/list")
    assert broken.status_code == 500
    assert broken.json() == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32603, "message": "Internal error"},
    }


def test_mcp_http_logs_safe_codes_and_never_the_token(env, mcp, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    created, _ = fixture.grant(env, ("read", "act"))
    token, sid = created["token"], env["sid"]
    wrong = "f" * 64
    replies = [
        modern(mcp, sid, token, "tools/list"),
        call(mcp, sid, token, "work_items.list"),
        modern(mcp, sid, wrong, "tools/list"),
        modern(mcp, sid, token, "tools/list", headers={"Origin": "https://evil.example"}),
        modern(mcp, sid, token, "unknown/method"),
    ]
    monkeypatch.setattr(HttpAgentClient, "tools", failing_tools(RuntimeError("detail " + token)))
    replies.append(modern(mcp, sid, token, "tools/list"))
    for reply in replies:
        assert token not in reply.text and token not in str(reply.headers.raw)
        assert wrong not in reply.text
    assert token not in caplog.text and wrong not in caplog.text
    lines = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "career_lab.http"
    ]
    codes = {line["code"] for line in lines if line["route"] == "/sessions/{session_id}/mcp"}
    assert {
        "mcp_unauthorized",
        "mcp_browser_refused",
        "mcp_method_not_found",
        "mcp_internal_error",
    } <= codes


def test_mcp_http_limits_the_rate_of_each_authorization(env):
    mount_mcp_http(env["app"], limits=HttpLimits(burst=2, per_second=0.5))
    agent = TestClient(env["app"], base_url="http://127.0.0.1")
    first, _ = fixture.grant(env, ("read",))
    second, _ = fixture.grant(env, ("read",))
    sid = env["sid"]
    assert [modern(agent, sid, first["token"], "ping").status_code for _ in range(2)] == [200, 200]
    limited = modern(agent, sid, first["token"], "ping")
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) >= 1
    assert limited.json()["error"]["code"] == 1004
    assert modern(agent, sid, second["token"], "ping").status_code == 200
    agent.close()


def test_mcp_http_bounds_requests_in_progress(env, monkeypatch):
    mount_mcp_http(env["app"], limits=HttpLimits(in_flight=1))
    created, _ = fixture.grant(env, ("read",))
    entered, release = threading.Event(), threading.Event()
    tools = HttpAgentClient.tools

    def held(self):
        entered.set()
        release.wait(5)
        return tools(self)

    monkeypatch.setattr(HttpAgentClient, "tools", held)
    results = {}
    with TestClient(env["app"], base_url="http://127.0.0.1") as agent:

        def first():
            results["first"] = modern(agent, env["sid"], created["token"], "tools/list")

        worker = threading.Thread(target=first)
        worker.start()
        assert entered.wait(5)
        second = modern(agent, env["sid"], created["token"], "tools/list")
        release.set()
        worker.join(5)
    assert second.status_code == 429 and second.headers["retry-after"] == "1"
    assert second.json()["error"]["code"] == 1002
    assert results["first"].status_code == 200
