"""Re-audit immutable exports before transferring input files to a responsible party."""

import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from career_lab.contracts.v2 import FileRef, ProtocolError, digest, read_file

from .common import check_payload, read_json
from .export import INPUT, ExportResult, aggregate_exports
from .quality import audit_records
from .release import load_export
from .temporal import CONTEXT_KEY


def load_live_export(root: Path) -> ExportResult:
    manifest = read_json(root / "dataset-manifest.json")
    files = manifest["files"]
    for name, identity in files.items():
        raw = read_file(root, FileRef(path=name, sha256=identity["sha256"]))
        if len(raw) != identity["size"]:
            raise ProtocolError("export_file_size_mismatch")
    result = load_export(root / "audit/export")
    expected = {row.record_id: row for row in result.records}
    seen: set[str] = set()
    for path in sorted((root / "data").glob("*.inputs.jsonl")):
        if str(path.relative_to(root)) not in files:
            raise ProtocolError("export_unmanifested_input")
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if set(row) != {"record_id", "input_hash", "model_input"}:
                raise ProtocolError("export_input_fields_invalid")
            check_payload(row["model_input"])
            model = INPUT.validate_python(row["model_input"])
            if model.task_type in {"relation", "criterion"} and (
                set(model.evidence.rule_context) - {CONTEXT_KEY}
            ):
                raise ProtocolError("export_input_context_forbidden")
            rid = row["record_id"]
            if rid in seen or rid not in expected:
                raise ProtocolError("export_record_set_mismatch")
            original = expected[rid]
            if row["input_hash"] != digest(model) or model != original.model_input:
                raise ProtocolError("export_input_identity_mismatch")
            if path.name != original.split + ".inputs.jsonl":
                raise ProtocolError("export_split_mismatch")
            seen.add(rid)
    if seen != set(expected):
        raise ProtocolError("export_record_set_mismatch")
    sources = read_json(root / "audit/source-index.json")
    for row in result.records:
        for ref in row.provenance.actual_sources:
            if sources.get(ref.path, {}).get("sha256") != ref.sha256:
                raise ProtocolError("export_source_index_mismatch")
            text = read_file(root, ref).decode("utf-8")
            entry = sources[ref.path]
            if (
                entry["language"] != row.language
                or entry["ref"]["session_id"] != row.lineage.session_id
            ):
                raise ProtocolError("export_source_identity_mismatch")
            if entry["span_start"] != 0 or entry["span_end"] != len(text):
                raise ProtocolError("export_source_span_mismatch")
    if manifest["training_ready"] is not False or manifest["records"] != len(result.records):
        raise ProtocolError("export_status_mismatch")
    return result


def audit_exports(paths: Iterable[Path]) -> dict[str, object]:
    paths = list(paths)
    results = [
        load_live_export(path) if (path / "dataset-manifest.json").exists() else load_export(path)
        for path in paths
    ]
    combined = aggregate_exports(results)
    report = audit_records(combined.records, annotations=combined.annotations)
    anchors: Counter[str] = Counter()
    for path in paths:
        source_index = path / "audit/source-index.json"
        if (path / "dataset-manifest.json").exists():
            anchors.update(value["language"] for value in read_json(source_index).values())
    return {
        **report,
        "training_ready": False,
        "scope": "export_mechanism",
        "source_set_digest": combined.source_set_digest,
        "source_anchors": dict(anchors),
    }
