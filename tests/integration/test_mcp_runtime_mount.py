"""The standard runtime app serves MCP over HTTP; the endpoint stays out of the contract."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.mcp.protocol import CAPABILITIES, MODERN, VERSION


def test_mcp_http_is_mounted_on_the_runtime_app_and_kept_out_of_the_contract(tmp_path):
    app = create_runtime_app("sqlite:///" + str(tmp_path / "runtime.db"))
    owner = TestClient(app)
    agent = TestClient(app, base_url="http://127.0.0.1")
    try:
        created = owner.post("/sessions", json={"schema_version": 2, "scenario": "pm_pilot_v2"})
        assert created.status_code == 200, created.text
        sid = created.json()["session_id"]
        owner.headers["Authorization"] = "Bearer " + created.json()["token"]
        state = owner.get("/sessions/" + sid).json()["state"]
        expires = (datetime.now(UTC) + timedelta(minutes=15)).isoformat()
        issued = owner.post(
            f"/sessions/{sid}/delegations",
            json={
                "schema_version": 2,
                "request_id": "grant",
                "operation": "delegations.create",
                "payload": {
                    "agent_label": "Runtime agent",
                    "capabilities": ["read", "act"],
                    "expires_at": expires,
                },
                "expected_version": state["business_seq"],
                "expected_workspace_revision": state["workspace_revision"],
            },
        )
        assert issued.status_code == 200, issued.text
        token = issued.json()["result"]["result"]["token"]
        other = owner.post(
            "/sessions", json={"schema_version": 2, "scenario": "pm_pilot_v2"}
        ).json()["session_id"]

        def send(method, params=None, name=None):
            meta = {VERSION: MODERN, CAPABILITIES: {}}
            headers = {
                "Authorization": "Bearer " + token,
                "MCP-Protocol-Version": MODERN,
                "Mcp-Method": method,
                **({"Mcp-Name": name} if name else {}),
            }
            body = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": {**(params or {}), "_meta": meta},
            }
            return agent.post(f"/sessions/{sid}/mcp", json=body, headers=headers)

        listed = send("tools/list")
        assert listed.status_code == 200, listed.text
        names = {tool["name"] for tool in listed.json()["result"]["tools"]}
        assert {"materials.list", "objects.read", "work_products.create"} <= names
        materials = send(
            "tools/call", {"name": "materials.list", "arguments": {}}, "materials.list"
        )
        assert materials.json()["result"]["isError"] is False
        foreign = {"session_id": other, "kind": "material", "object_id": "brief", "version": 1}
        read = send(
            "tools/call",
            {"name": "objects.read", "arguments": {"query": {"ref": foreign}}},
            "objects.read",
        ).json()["result"]
        assert read["isError"] and read["structuredContent"]["code"] == "session_route_mismatch"
        assert "/sessions/{session_id}/mcp" not in app.openapi()["paths"]
    finally:
        owner.close()
        agent.close()
        app.state.store.close()
