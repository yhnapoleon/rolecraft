"""MCP copies of tool results stay small for an Agent's context; public routes do not change."""

import json

from career_lab.contracts import v2 as C
from career_lab.mcp.protocol import CAPABILITIES, MODERN, VERSION, Protocol

SESSION = "bound-session"
PARAMETERS = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"session_id": {"type": "string"}, "query": {"type": "object"}},
    "required": ["session_id"],
    "additionalProperties": False,
    "$defs": {"Large": {"description": "x" * 4000}},
}


def schema(name, capability="read", code=None):
    return C.ToolSchema(
        name=name,
        capability=capability,
        parameters=PARAMETERS,
        parameters_hash=C.digest(PARAMETERS),
        available=code is None,
        unavailable_code=code,
    )


CATALOGUE = (
    schema("materials.list"),
    schema("observation"),
    schema("tools"),
    schema("work_items.create", "act"),
    schema("begin_revision", "act", "session_not_submitted"),
    schema("feedback.create", "act", "private_worker_unavailable"),
    schema("reviews.create", "act", "atomic_job_limit_unavailable"),
    schema("submissions.create", "submit", "capability_forbidden"),
    schema("work_items.batch", "act", "action_forbidden"),
    schema("work_products.adopt", "act", "human_adoption_required"),
)


class Backend:
    """Returns what the public routes return, bound to one session like the real clients."""

    session_id = SESSION

    def __init__(self, materials=None, next_cursor=None):
        self.materials = materials or []
        self.next_cursor = next_cursor

    def tools(self):
        return CATALOGUE

    def call(self, name, arguments):
        tools = [t.model_dump(mode="json") for t in CATALOGUE]
        if name == "observation":
            return {
                "schema_version": 2,
                "result": {"session_id": SESSION, "catalog": [{"id": "brief"}], "tools": tools},
            }
        if name == "tools":
            return {
                "schema_version": 2,
                "result": {"schema_version": 2, "result": {"tools": tools}},
            }
        if name == "materials.list":
            page = {
                "materials": self.materials,
                "requested_as_of_seq": 3,
                "next_cursor": self.next_cursor,
                "catalog_is_not_acquired_knowledge": True,
            }
            return {"schema_version": 2, "result": {"schema_version": 2, "result": page}}
        return {"ok": True}


def call(backend, name, arguments=None):
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": arguments or {},
            "_meta": {VERSION: MODERN, CAPABILITIES: {}},
        },
    }
    result = Protocol(backend).handle(request)
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    return result["structuredContent"]


def test_mcp_observation_leaves_the_tool_catalogue_to_tools_list():
    observed = call(Backend(), "observation")
    # Still a valid public Observation: tools is optional and defaults to none.
    assert observed == {
        "schema_version": 2,
        "result": {"session_id": SESSION, "catalog": [{"id": "brief"}]},
    }


def test_mcp_tools_result_names_each_callable_tool_and_its_availability():
    listed = call(Backend(), "tools")
    assert listed["schema_version"] == 2 and listed["result"]["schema_version"] == 2
    assert listed["result"]["result"]["tools"] == [
        {
            "name": "begin_revision",
            "capability": "act",
            "available": False,
            "unavailable_code": "session_not_submitted",
        },
        {
            "name": "materials.list",
            "capability": "read",
            "available": True,
            "unavailable_code": None,
        },
        {"name": "observation", "capability": "read", "available": True, "unavailable_code": None},
        {"name": "tools", "capability": "read", "available": True, "unavailable_code": None},
        {
            "name": "work_items.create",
            "capability": "act",
            "available": True,
            "unavailable_code": None,
        },
    ]


MATERIALS = [{"id": name, "version": 1} for name in ("a", "b", "c", "d", "e")]


def test_mcp_materials_list_honours_limit_and_cursor():
    def page(query=None):
        arguments = {"query": query} if query is not None else {}
        return call(Backend(MATERIALS), "materials.list", arguments)["result"]["result"]

    assert page()["materials"] == MATERIALS and page()["next_cursor"] is None
    first = page({"limit": 2})
    assert [m["id"] for m in first["materials"]] == ["a", "b"] and first["next_cursor"] == 2
    last = page({"cursor": 4, "limit": 2})
    assert [m["id"] for m in last["materials"]] == ["e"] and last["next_cursor"] is None
    assert last["requested_as_of_seq"] == 3 and last["catalog_is_not_acquired_knowledge"]


def test_mcp_materials_list_refuses_a_limit_outside_the_published_range():
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "materials.list",
            "arguments": {"query": {"limit": 0}},
            "_meta": {VERSION: MODERN, CAPABILITIES: {}},
        },
    }
    result = Protocol(Backend(MATERIALS)).handle(request)
    assert result["isError"] is True
    assert result["content"][0]["text"] == "tool_arguments_invalid"


def test_mcp_materials_list_never_answers_past_the_routes_first_page_with_a_short_page():
    backend = Backend(MATERIALS, next_cursor=5)
    inside = call(backend, "materials.list", {"query": {"cursor": 2, "limit": 3}})
    assert [m["id"] for m in inside["result"]["result"]["materials"]] == ["c", "d", "e"]
    assert inside["result"]["result"]["next_cursor"] == 5
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "materials.list",
            "arguments": {"query": {"cursor": 4, "limit": 3}},
            "_meta": {VERSION: MODERN, CAPABILITIES: {}},
        },
    }
    beyond = Protocol(backend).handle(request)
    assert beyond["isError"] is True
    assert beyond["structuredContent"]["code"] == "materials_page_unavailable"


def test_mcp_materials_list_passes_another_registrations_page_through():
    class Other(Backend):
        def call(self, name, arguments):
            return {"schema_version": 2, "result": {"schema_version": 2, "result": {"items": [1]}}}

    listed = call(Other(), "materials.list", {"query": {"limit": 1}})
    assert listed["result"]["result"] == {"items": [1]}
