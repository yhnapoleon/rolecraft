"""Only the explicitly approved optional provenance envelope may differ from v2."""

from copy import deepcopy

from pydantic import JsonValue

from .core import ProtocolError

PROVENANCE_DEFINITIONS = ("CodeIdentity", "FeedbackProvenance", "SupportModelIdentity")


def without_provenance(schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    result = deepcopy(schema)

    def visit(node: object) -> None:
        if isinstance(node, dict):
            if node.get("title") == "FeedbackV2" and "properties" in node:
                if "provenance" in node.get("required", []):
                    raise ProtocolError("provenance_must_remain_optional", status=409)
                node["properties"].pop("provenance", None)
            for name in ("$defs", "schemas"):
                if name in node:
                    # Definitions referenced only from the provenance envelope.
                    for definition in PROVENANCE_DEFINITIONS:
                        node[name].pop(definition, None)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(result)
    return result
