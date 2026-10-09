"""Same live installation drives HTTP, MCP and function-tool discovery."""

from dataclasses import replace
from pathlib import Path

from test_w14_vertical_runtime import connect

from career_lab.contracts.v2 import ToolSchema
from career_lab.delegations.openai_tools import function_name, function_tools
from career_lab.mcp.protocol import CAPABILITIES, MODERN, VERSION, Protocol


def test_tool_01_unready_registration_is_unavailable_in_every_catalogue(tmp_path: Path) -> None:
    app, client, sid, headers, _ = connect(tmp_path)
    try:
        operation = app.state.extensions.operations["tests.create"]
        app.state.extensions.operations["tests.create"] = replace(
            operation,
            ready=False,
            unavailable_code="assistant_not_installed",
        )

        class HttpCatalogue:
            def tools(self) -> tuple[ToolSchema, ...]:
                response = client.get("/sessions/" + sid + "/tools", headers=headers)
                assert response.status_code == 200, response.text
                return tuple(
                    ToolSchema.model_validate(row)
                    for row in response.json()["result"]["result"]["tools"]
                )

        backend = HttpCatalogue()
        tools = backend.tools()
        target = next(tool for tool in tools if tool.name == "tests.create")
        assert target.available is False
        assert target.unavailable_code == "assistant_not_installed"
        mcp = Protocol(backend).handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {"_meta": {VERSION: MODERN, CAPABILITIES: {}}},
            }
        )["tools"]
        functions = function_tools(tools)
        assert "tests.create" not in {tool["name"] for tool in mcp}
        assert function_name("tests.create") not in {tool["name"] for tool in functions}
        assert {function_name(tool["name"]) for tool in mcp} == {tool["name"] for tool in functions}
        for tool in tools:
            if tool.available:
                assert (
                    next(row for row in mcp if row["name"] == tool.name)["inputSchema"]
                    == tool.parameters
                )
                assert (
                    next(row for row in functions if row["name"] == function_name(tool.name))[
                        "parameters"
                    ]
                    == tool.parameters
                )
        app.state.extensions.operations["tests.create"] = operation
        assert next(tool for tool in backend.tools() if tool.name == "tests.create").available
    finally:
        app.state.store.close()
