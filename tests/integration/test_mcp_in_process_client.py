"""The delegated client runs against the app's own public routes without a network hop."""

import importlib.util
from pathlib import Path

import httpx
import pytest

from career_lab.delegations.credentials import Credentials
from career_lab.delegations.http_client import HttpAgentClient, RemoteFailure

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location(
    "w06_gateway_fixture_in_process", ROOT / "tests/integration/test_w06_gateway.py"
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
env = fixture.env


def in_process(app, sid, token):
    return HttpAgentClient(
        credentials=Credentials("http://rolecraft-mcp.invalid", sid, token),
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
    )


def test_in_process_client_reads_and_returns_work_through_the_public_routes(env):
    created, _ = fixture.grant(env, ("read", "act"))
    client = in_process(env["app"], env["sid"], created["token"])
    available = {tool.name for tool in client.tools() if tool.available}
    assert {"work_items.list", "work_products.create"} <= available
    command = fixture.command(
        env, "work_products.create", {"kind": "text", "content": "Returned in process"}
    )
    returned = client.call("work_products.create", {"session_id": env["sid"], "command": command})
    assert returned["executor"]["kind"] == "external_agent"
    assert client.call("work_products.create", {"session_id": env["sid"], "command": command})[
        "replayed"
    ]


def test_in_process_client_keeps_the_public_route_checks(env):
    created, _ = fixture.grant(env, ("read",))
    client = in_process(env["app"], env["sid"], created["token"])
    with pytest.raises(RemoteFailure) as other:
        client.call("work_items.list", {"session_id": "another-session"})
    assert other.value.code == "session_route_mismatch"
    human = in_process(env["app"], env["sid"], env["token"])
    with pytest.raises(RemoteFailure) as refused:
        human.tools()
    assert refused.value.code == "delegation_required"
