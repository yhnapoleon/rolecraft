"""Fail-closed validation of the JSON-schema subset used by published tools."""
import math
from career_lab.contracts.v2 import ActionProposal, Observation
from .ports import PortError


def validate_schema(value, schema, root=None, depth=0):
    if depth > 64:
        raise PortError("unsupported_tool_schema")
    root = schema if root is None else root
    if isinstance(schema, bool):
        if not schema:
            raise PortError("invalid_parameters")
        return
    if not isinstance(schema, dict):
        raise PortError("unsupported_tool_schema")
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            raise PortError("unsupported_tool_schema")
        target = root.get("$defs", {}).get(ref[len("#/$defs/"):])
        if target is None:
            raise PortError("unsupported_tool_schema")
        validate_schema(value, target, root, depth+1)
    supported = {"$schema", "$defs", "$ref", "title", "description", "default", "examples",
                 "type", "properties", "required", "additionalProperties", "items", "minItems",
                 "maxItems", "uniqueItems", "enum", "const", "anyOf", "oneOf", "allOf",
                 "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength",
                 "maxLength", "pattern", "format"}
    if set(schema) - supported:
        raise PortError("unsupported_tool_schema")
    for key in ("anyOf", "oneOf"):
        if key in schema:
            passed = 0
            for option in schema[key]:
                try:
                    validate_schema(value, option, root, depth+1)
                    passed += 1
                except PortError as exc:
                    if exc.code == "unsupported_tool_schema":
                        raise
            if not passed or (key == "oneOf" and passed != 1):
                raise PortError("invalid_parameters")
    for option in schema.get("allOf", ()):
        validate_schema(value, option, root, depth+1)
    kind = schema.get("type")
    types = {"object": lambda x: isinstance(x, dict), "array": lambda x: isinstance(x, list),
             "string": lambda x: isinstance(x, str), "boolean": lambda x: isinstance(x, bool),
             "integer": lambda x: type(x) is int, "number": lambda x: type(x) in (int, float) and math.isfinite(x),
             "null": lambda x: x is None}
    if kind:
        allowed = kind if isinstance(kind, list) else [kind]
        if any(t not in types for t in allowed):
            raise PortError("unsupported_tool_schema")
        if not any(types[t](value) for t in allowed):
            raise PortError("invalid_parameters")
    if "enum" in schema and value not in schema["enum"]:
        raise PortError("invalid_parameters")
    if "const" in schema and value != schema["const"]:
        raise PortError("invalid_parameters")
    if isinstance(value, dict):
        if set(schema.get("required", ())) - value.keys():
            raise PortError("invalid_parameters")
        props = schema.get("properties", {})
        for name, item in value.items():
            if name in props:
                validate_schema(item, props[name], root, depth+1)
            elif schema.get("additionalProperties", True) is False:
                raise PortError("invalid_parameters")
            elif isinstance(schema.get("additionalProperties"), dict):
                validate_schema(item, schema["additionalProperties"], root, depth+1)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", math.inf):
            raise PortError("invalid_parameters")
        if schema.get("uniqueItems") and len({repr(x) for x in value}) != len(value):
            raise PortError("invalid_parameters")
        for item in value:
            if "items" in schema:
                validate_schema(item, schema["items"], root, depth+1)
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", math.inf):
            raise PortError("invalid_parameters")
        if "pattern" in schema:
            import re
            if not re.search(schema["pattern"], value):
                raise PortError("invalid_parameters")
        # Formats are annotation-only in JSON Schema; backend validates semantic refs.
    if type(value) in (int, float):
        if ("minimum" in schema and value < schema["minimum"]) or ("maximum" in schema and value > schema["maximum"]):
            raise PortError("invalid_parameters")
        if ("exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]) or ("exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]):
            raise PortError("invalid_parameters")


def validate_action(action: ActionProposal, observation: Observation):
    tool = next((t for t in observation.tools if t.name == action.tool), None)
    if tool is None or not tool.available:
        raise PortError("tool_unavailable")
    validate_schema(action.arguments, tool.parameters)
    return action
