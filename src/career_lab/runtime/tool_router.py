import json

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_materials",
            "description": "List currently visible materials",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_material",
            "description": "Read a currently visible material",
            "parameters": {
                "type": "object",
                "properties": {"material_id": {"type": "string"}},
                "required": ["material_id"],
                "additionalProperties": False,
            },
        },
    },
]


def execute_tool(view, call):
    if call.name == "list_materials" and not call.arguments:
        return {
            "status": "ok",
            "data": [
                {"id": m.id, "version": m.version, "title": m.title}
                for m in view.permitted_materials
            ],
        }
    if call.name == "read_material" and set(call.arguments) == {"material_id"}:
        material = next(
            (m for m in view.permitted_materials if m.id == call.arguments["material_id"]), None
        )
        if material:
            return {
                "status": "ok",
                "data": {"id": material.id, "version": material.version, "text": material.content},
            }
        return {"status": "error", "error_code": "material_unavailable"}
    return {"status": "error", "error_code": "tool_not_allowed"}
