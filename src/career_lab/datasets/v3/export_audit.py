"""Re-audit immutable exports before transferring input files to a responsible party."""

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pydantic import JsonValue

from career_lab.contracts.v2 import FileRef, ProtocolError, VersionPoint, digest, read_file
from career_lab.research.authorization import within

from .common import check_payload, read_json
from .export import INPUT, ExportResult, aggregate_exports
from .projection import SOURCE_KINDS, SourceIndexEntry
from .quality import audit_records
from .release import load_export
from .temporal import CONTEXT_KEY


@dataclass(frozen=True)
class AuditedExport:
    result: ExportResult
    sources: dict[str, SourceIndexEntry]


def _json_in_root(root: Path, name: str) -> dict[str, JsonValue]:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ProtocolError("export_file_outside_root")
    value = read_json(path)
    if not isinstance(value, dict):
        raise ProtocolError("export_metadata_object_required")
    return value


def _checked_manifest(root: Path) -> tuple[dict[str, JsonValue], dict[str, FileRef]]:
    manifest = _json_in_root(root, "dataset-manifest.json")
    files = manifest["files"]
    required = {
        "audit/source-index.json",
        "audit/source-map.json",
        "audit/metadata.jsonl",
        "audit/authorization.json",
        "audit/export/manifest.json",
        "audit/export/export.json",
    }
    if not isinstance(files, dict) or not required <= files.keys():
        raise ProtocolError("export_required_file_missing")
    references = {}
    for name, identity in files.items():
        if not isinstance(identity, dict) or type(identity.get("size")) is not int:
            raise ProtocolError("export_manifest_invalid")
        ref = FileRef(path=name, sha256=identity["sha256"])
        raw = read_file(root, ref)
        if len(raw) != identity["size"]:
            raise ProtocolError("export_file_size_mismatch")
        references[name] = ref
    envelope = _json_in_root(root, "audit/export/manifest.json")
    inner = FileRef.model_validate(envelope["export"])
    if inner.path != "export.json" or inner.sha256 != references["audit/export/export.json"].sha256:
        raise ProtocolError("export_envelope_mismatch")
    return manifest, references


def _check_inputs(root: Path, result: ExportResult, files: dict[str, FileRef]) -> None:
    expected = {row.record_id: row for row in result.records}
    required_labels = {"data/" + row.split + ".labels.jsonl" for row in result.records}
    if not required_labels <= files.keys():
        raise ProtocolError("export_required_file_missing")
    seen: set[str] = set()
    for path in sorted((root / "data").glob("*.inputs.jsonl")):
        name = str(path.relative_to(root))
        if name not in files:
            raise ProtocolError("export_unmanifested_input")
        for line in read_file(root, files[name]).decode("utf-8").splitlines():
            row = json.loads(line)
            if set(row) != {"record_id", "input_hash", "model_input"}:
                raise ProtocolError("export_input_fields_invalid")
            check_payload(row["model_input"])
            model = INPUT.validate_python(row["model_input"])
            if model.task_type in {"relation", "criterion"}:
                if set(model.evidence.rule_context) - {CONTEXT_KEY}:
                    raise ProtocolError("export_input_context_forbidden")
                refs = (
                    *model.evidence.subjects,
                    *(candidate.ref for candidate in model.evidence.candidate_evidence),
                )
                if any(ref.kind not in SOURCE_KINDS for ref in refs):
                    raise ProtocolError("export_source_kind_forbidden")
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


def _check_sources(
    root: Path, result: ExportResult, files: dict[str, FileRef]
) -> dict[str, SourceIndexEntry]:
    values = _json_in_root(root, "audit/source-index.json")
    sources = {name: SourceIndexEntry.model_validate(value) for name, value in values.items()}
    windows = {
        entry["session_id"]: VersionPoint.model_validate(entry["capture_point"])
        for entry in result.source_snapshots
    }
    for name, entry in sources.items():
        if (
            not name.startswith("audit/sources/")
            or name not in files
            or files[name].sha256 != entry.sha256
        ):
            raise ProtocolError("export_source_index_mismatch")
        at = windows.get(entry.ref.session_id)
        if at is None or not within(entry.available_at, at):
            raise ProtocolError("export_source_identity_mismatch")
        if entry.span_end != len(read_file(root, files[name]).decode("utf-8")):
            raise ProtocolError("export_source_span_mismatch")
    for row in result.records:
        for ref in row.provenance.actual_sources:
            entry = sources.get(ref.path)
            if entry is None or entry.sha256 != ref.sha256:
                raise ProtocolError("export_source_index_mismatch")
            if entry.language != row.language or entry.ref.session_id != row.lineage.session_id:
                raise ProtocolError("export_source_identity_mismatch")
    return sources


def load_live_export(root: Path) -> AuditedExport:
    manifest, files = _checked_manifest(root)
    result = load_export(root / "audit/export")
    _check_inputs(root, result, files)
    sources = _check_sources(root, result, files)
    if manifest["training_ready"] is not False or manifest["records"] != len(result.records):
        raise ProtocolError("export_status_mismatch")
    return AuditedExport(result, sources)


def audit_exports(paths: Iterable[Path]) -> dict[str, object]:
    results = []
    anchors: Counter[str] = Counter()
    for path in paths:
        if (path / "dataset-manifest.json").exists():
            verified = load_live_export(path)
            results.append(verified.result)
            anchors.update(entry.language for entry in verified.sources.values())
        else:
            _json_in_root(path, "manifest.json")
            results.append(load_export(path))
    combined = aggregate_exports(results)
    report = audit_records(combined.records, annotations=combined.annotations)
    return {
        **report,
        "training_ready": False,
        "scope": "export_mechanism",
        "source_set_digest": combined.source_set_digest,
        "source_anchors": dict(anchors),
    }
