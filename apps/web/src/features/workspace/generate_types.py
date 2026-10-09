"""Generate frontend wire types from the frozen schema manifest without changing it."""

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import TypeAlias

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]

WORKSPACE_MODELS = [
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
HOST_MODELS = WORKSPACE_MODELS + [
    "ActionInput",
    "ApprovalInput",
    "AssistantConfig",
    "BeginRevisionInput",
    "FeedbackInput",
    "FeedbackResponseCreate",
    "FeedbackResponseRecord",
    "FeedbackV2",
    "DelegationInput",
    "DelegationRevoke",
    "DelegationListResult",
    "DelegationSummary",
    "DelegationGrant",
    "BusinessRequest",
    "BusinessDecision",
    "DisclosedFragment",
    "TurnInput",
    "SubmitInput",
    "ReviewInput",
    "ReviewRequest",
    "SubmissionV2",
    "TestRequestV2",
    "TestResultV2",
    "PublicState",
    "PublicTransactionResult",
    "RequestResult",
    "ObjectRead",
    "Observation",
    "ToolSchema",
    "MaterialMetadata",
    "PublicEvent",
    "ObjectRef",
    "EvidenceRefV2",
    "PublicDisclosureRecord",
]
Schema = dict[str, JsonValue]


def object_schema(value: JsonValue) -> Schema:
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON schema object")
    return value


def ts(schema: Schema) -> str:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        return reference.split("/")[-1]
    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=False)
    values = schema.get("enum")
    if isinstance(values, list):
        return " | ".join(json.dumps(value, ensure_ascii=False) for value in values)
    for key in ("anyOf", "oneOf"):
        branches = schema.get(key)
        if isinstance(branches, list):
            return "(" + " | ".join(ts(object_schema(value)) for value in branches) + ")"
    kind = schema.get("type")
    if kind == "string" or kind == "boolean" or kind == "null":
        return kind
    if kind == "number" or kind == "integer":
        return "number"
    if kind == "array":
        return "(" + ts(object_schema(schema.get("items", {}))) + ")[]"
    if kind == "object":
        properties = schema.get("properties")
        if not properties:
            additional = schema.get("additionalProperties")
            value = ts(additional) if isinstance(additional, dict) else "unknown"
            return "Record<string, " + value + ">"
        required = schema.get("required", [])
        if not isinstance(required, list):
            raise ValueError("Expected required field names")
        fields = [
            json.dumps(key) + ("" if key in required else "?") + ": " + ts(object_schema(value))
            for key, value in object_schema(properties).items()
        ]
        return "{ " + "; ".join(fields) + " }"
    return "unknown"


def compatible_schema(name: str, frozen: Schema) -> Schema:
    if name != "FeedbackV2":
        return frozen
    from career_lab.contracts.v2.compatibility import without_provenance
    from career_lab.contracts.v2.evaluation import FeedbackV2

    current = FeedbackV2.model_json_schema()
    if without_provenance(current) != frozen:
        raise ValueError("Feedback schema changed beyond the approved provenance extension")
    return current


def generate(manifest_path: Path, names: list[str]) -> str:
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    models: dict[str, Schema] = {}
    for name in names:
        entry = manifest.get("schemas", manifest.get("models", {}))[name]
        raw = (manifest_path.parent / entry["schema"]).read_bytes()
        expected = entry.get("schema_sha256", entry.get("sha256"))
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"Frozen schema changed: {name}")
        schema = compatible_schema(name, object_schema(json.loads(raw)))
        definitions = object_schema(schema.pop("$defs", {}))
        models.update({key: object_schema(value) for key, value in definitions.items()})
        models[name] = schema
    identity = hashlib.sha256(manifest_bytes).hexdigest()
    lines = [f"// Generated from frozen manifest SHA256 {identity}. Do not edit."]
    if "FeedbackV2" in names:
        lines.append("// Includes the approved optional FeedbackV2 provenance extension.")
    lines.extend(
        "export type " + name + " = " + ts(schema) + ";" for name, schema in sorted(models.items())
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--models", nargs="+")
    parser.add_argument("--host", action="store_true", help="Generate all public host DTOs")
    args = parser.parse_args()
    names = args.models or (HOST_MODELS if args.host else WORKSPACE_MODELS)
    output = generate(args.manifest, names)
    if args.output is None:
        print(output, end="")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=args.output.parent, delete=False) as temporary:
        temporary.write(output)
        name = temporary.name
    os.replace(name, args.output)


if __name__ == "__main__":
    main()
