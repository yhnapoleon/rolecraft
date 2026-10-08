"""Generate UI input types from W01 JSON Schema; stdout only, no schema edits."""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import os

names = [
    "WorkspaceTask",
    "WorkProductVersion",
    "ProductShare",
    "Command",
    "WorkspaceImport",
    "ImportResult",
    "TaskCreate",
    "TaskPatch",
    "TaskBatch",
    "ProductCreate",
    "ProductEdit",
    "ProductAdopt",
    "ShareCreate",
    "ShareUpdate",
    "VersionPoint",
    "WorkspaceProductRead",
    "WorkspaceProductPage",
    "WorkspaceSharePage",
    "WorkspaceImportReceipt",
]


def ts(s):
    if "$ref" in s:
        return s["$ref"].split("/")[-1]
    if "const" in s:
        return json.dumps(s["const"], ensure_ascii=False)
    if "enum" in s:
        return " | ".join(json.dumps(x, ensure_ascii=False) for x in s["enum"])
    for k in ["anyOf", "oneOf"]:
        if k in s:
            return "(" + " | ".join(ts(x) for x in s[k]) + ")"
    t = s.get("type")
    if t == "string":
        return "string"
    if t in ["number", "integer"]:
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "null":
        return "null"
    if t == "array":
        return "(" + ts(s.get("items", {})) + ")[]"
    if t == "object":
        if not s.get("properties"):
            return (
                "Record<string, "
                + (
                    ts(s["additionalProperties"])
                    if isinstance(s.get("additionalProperties"), dict)
                    else "unknown"
                )
                + ">"
            )
        required = s.get("required", [])
        return (
            "{ "
            + "; ".join(
                json.dumps(k) + ("" if k in required else "?") + ": " + ts(v)
                for k, v in s["properties"].items()
            )
            + " }"
        )
    return "unknown"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    models = {}
    for name in names:
        entry = manifest.get("schemas", manifest.get("models", {}))[name]
        raw = (args.manifest.parent / entry["schema"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry.get("schema_sha256", entry.get("sha256"))
        schema = json.loads(raw)
        models.update(schema.pop("$defs", {}))
        models[name] = schema
    lines = [
        "// Generated from W01 manifest SHA256 "
        + hashlib.sha256(args.manifest.read_bytes()).hexdigest()
        + ". Do not edit."
    ]
    lines.extend(
        "export type " + name + " = " + ts(schema) + ";" for name, schema in sorted(models.items())
    )
    output = "\n".join(lines) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=args.output.parent, delete=False) as temp:
            temp.write(output)
            temporary = temp.name
        os.replace(temporary, args.output)
    else:
        print(output, end="")
