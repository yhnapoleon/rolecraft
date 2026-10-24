"""The person's record of their own Agent over MCP: connections, tool calls, connection state."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from career_lab.contracts import v2 as C

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location(
    "mcp_http_fixture_agent_activity", ROOT / "tests/integration/test_mcp_streamable_http.py"
)
http = importlib.util.module_from_spec(spec)
spec.loader.exec_module(http)
fixture = http.fixture
mcp = http.mcp


@pytest.fixture
def env(env_base):
    if not getattr(env_base["app"].state, "v4_extensions", False):
        from career_lab.api.v4_extensions import mount_v4_extensions

        mount_v4_extensions(env_base["app"])
        env_base["app"].state.v4_extensions = True
    return env_base


env_base = http.env


def activity(env, after=0, token=None):
    headers = {"Authorization": "Bearer " + token} if token else None
    response = env["client"].get(
        f"/sessions/{env['sid']}/agent-activity", params={"after": after}, headers=headers
    )
    return response


def page(env, after=0):
    response = activity(env, after)
    assert response.status_code == 200, response.text
    return C.AgentActivityResponse.model_validate(response.json()).result.result


def grant_for(env, hours):
    body = C.DelegationInput(
        capabilities=("read",),
        expires_at=datetime.now(UTC) + timedelta(hours=hours),
        agent_label="My agent",
    )
    return env["client"].post(
        f"/sessions/{env['sid']}/delegations",
        json=fixture.command(env, "delegations.create", body.model_dump(mode="json")),
    )


def test_agent_access_lasts_a_whole_practice_day(env):
    assert grant_for(env, 23 + 55 / 60).status_code == 200
    refused = grant_for(env, 25)
    assert refused.status_code == 422 or refused.status_code == 400, refused.text
    assert "delegation_expiry_invalid" in refused.text


def test_agent_activity_records_connection_calls_and_refusals(env, mcp):
    assert page(env).connection.state == "none"
    writer, _ = fixture.grant(env, ("read", "act"))
    sid, token = env["sid"], writer["token"]
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "claude-code", "version": "2.1.0"},
        },
    }
    assert http.legacy(mcp, sid, token, initialize, version=None).status_code == 200
    listed = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    assert http.legacy(mcp, sid, token, listed).status_code == 200
    first = page(env)
    assert [row.kind for row in first.items] == ["connected"]
    assert first.items[0].client == C.AgentClient(name="claude-code", version="2.1.0")
    assert first.connection.state == "connected" and first.connection.client == "claude-code"
    cursor = first.next_cursor

    command = fixture.command(env, "work_products.create", {"kind": "text", "content": "Plan"})
    created = http.call(mcp, sid, token, "work_products.create", {"command": command}).json()
    assert created["result"]["isError"] is False, created
    reader, _ = fixture.grant(env, ("read",))
    refused = http.call(mcp, sid, reader["token"], "work_products.create", {"command": command})
    assert refused.json()["result"]["isError"] is True

    later = page(env, cursor).items
    # The modern test client names itself "test", and the reader is another delegation.
    assert [(r.kind, r.client.name) for r in later if r.kind == "connected"] == [
        ("connected", "test"),
        ("connected", "test"),
    ]
    rows = [r for r in later if r.kind == "tool_call"]
    assert [(r.tool, r.capability, r.status) for r in rows] == [
        ("work_products.create", "act", "ok"),
        ("work_products.create", "act", "error"),
    ]
    product = next(o for o in rows[0].objects if o.kind == "product")
    assert product.version == 1 and product.id
    assert rows[1].error_code == "capability_forbidden" and rows[1].objects == ()
    assert rows[0].delegation_id == writer["delegation"]["id"]
    assert rows[1].delegation_id == reader["delegation"]["id"]
    # The Agent's own token never reads the person's record.
    assert activity(env, token=token).status_code == 403
    # Revoking every grant that was seen leaves the agent unable to reach the workspace.
    for grant in (writer, reader):
        delegation = grant["delegation"]["id"]
        revoked = env["client"].request(
            "DELETE",
            f"/sessions/{sid}/delegations/{delegation}",
            json=fixture.command(env, "delegations.revoke", {"delegation_id": delegation}),
        )
        assert revoked.status_code == 200, revoked.text
    assert page(env).connection.state == "idle"
    assert page(env, later[-1].seq).items == ()


def test_agent_activity_stores_no_body_or_token(env, mcp):
    writer, _ = fixture.grant(env, ("read", "act"))
    secret = "Confidential draft body"
    command = fixture.command(env, "work_products.create", {"kind": "text", "content": secret})
    http.call(mcp, env["sid"], writer["token"], "work_products.create", {"command": command})
    raw = activity(env).text
    assert secret not in raw and writer["token"] not in raw


@pytest.mark.parametrize(
    ("name", "arguments", "structured", "expected"),
    [
        (
            "materials.list",
            {"query": {}},
            {"result": {"result": {"materials": [{"id": "m1", "version": 2, "title": "Policy"}]}}},
            ([{"kind": "material", "id": "m1", "version": 2, "title": "Policy"}], 1),
        ),
        (
            "objects.read",
            {"query": {"ref": {"kind": "material", "object_id": "m1", "version": 2}}},
            {"ref": {}, "content": {"title": "Policy", "fragments": []}},
            ([{"kind": "material", "id": "m1", "version": 2, "title": "Policy"}], None),
        ),
        (
            "engineer.tickets.read",
            {"query": {"ticket_id": "t1"}},
            {"result": {"ticket": {"id": "t1", "title": "Hotel-limit answers need a look"}}},
            (
                [
                    {
                        "kind": "ticket",
                        "id": "t1",
                        "version": None,
                        "title": "Hotel-limit answers need a look",
                    }
                ],
                None,
            ),
        ),
        (
            "engineer.trial",
            {"command": {"payload": {"ticket_id": "t1"}}},
            {"result": {"trial": {"id": "x7", "ticket_id": "t1"}}},
            (
                [
                    {"kind": "experiment", "id": "x7", "version": None, "title": None},
                    {"kind": "ticket", "id": "t1", "version": None, "title": None},
                ],
                None,
            ),
        ),
    ],
)
def test_agent_activity_names_the_objects_a_call_touched(name, arguments, structured, expected):
    from career_lab.delegations.activity import touched

    assert touched(name, arguments, structured) == (expected[0], expected[1])
