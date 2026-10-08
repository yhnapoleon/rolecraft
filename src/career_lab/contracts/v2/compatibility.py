"""Only the explicitly approved optional provenance envelope may differ from v2."""

from copy import deepcopy


def without_provenance(schema: dict) -> dict:
    result = deepcopy(schema)

    def visit(node: object) -> None:
        if isinstance(node, dict):
            if node.get("title") == "FeedbackV2" and "properties" in node:
                assert "provenance" not in node.get("required", [])
                node["properties"].pop("provenance", None)
            for name in ("$defs", "schemas"):
                if name in node:
                    node[name].pop("CodeIdentity", None)
                    node[name].pop("FeedbackProvenance", None)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(result)
    return result
