"""Physically separated operator export artifacts; no training-readiness promotion."""

from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from career_lab.contracts.v2 import ProtocolError

from .common import immutable_directory, json_bytes, sha, write_new
from .release import save_export

if TYPE_CHECKING:
    from career_lab.api.dataset_export import LiveCapture


def _files(root: Path) -> dict[str, Path]:
    paths = list(root.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ProtocolError("export_output_symlink", status=409)
    return {str(path.relative_to(root)): path for path in paths if path.is_file()}


def save_capture(target: Path, capture: "LiveCapture") -> dict[str, object]:
    if target.exists():
        if target.is_symlink():
            raise ProtocolError("export_output_conflict", status=409)
        with TemporaryDirectory(prefix=".export-check-", dir=target.parent) as temporary:
            stage = Path(temporary)
            manifest = _write_capture(stage, capture)
            expected, existing = _files(stage), _files(target)
            if expected.keys() != existing.keys() or any(
                expected[name].read_bytes() != existing[name].read_bytes() for name in expected
            ):
                raise ProtocolError("export_output_conflict", status=409)
            return manifest
    with immutable_directory(target) as root:
        return _write_capture(root, capture)


def _write_capture(root: Path, capture: "LiveCapture") -> dict[str, object]:
    result = capture.result
    save_export(root / "audit/export", result)
    for path, raw in capture.sources.items():
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    write_new(root / "audit/authorization.json", capture.authorization)
    write_new(root / "audit/source-map.json", result.source_maps)
    write_new(
        root / "audit/source-index.json",
        {name: entry.model_dump(mode="json") for name, entry in capture.source_index.items()},
    )
    families = Counter(row.family for row in result.records)
    metadata = []
    for split in sorted({row.split for row in result.records}):
        records = [row for row in result.records if row.split == split]
        labels = {row.record_id: row for row in result.annotations}
        path = root / "data"
        path.mkdir(exist_ok=True)
        (path / (split + ".inputs.jsonl")).write_bytes(
            b"".join(
                json_bytes(
                    {
                        "record_id": row.record_id,
                        "input_hash": row.input_hash,
                        "model_input": row.model_input.model_dump(mode="json"),
                    }
                )
                for row in records
            )
        )
        (path / (split + ".labels.jsonl")).write_bytes(
            b"".join(json_bytes(labels[row.record_id]) for row in records)
        )
        metadata.extend(
            row.model_dump(mode="json", exclude={"model_input", "label_ref"}) for row in records
        )
    (root / "audit/metadata.jsonl").write_bytes(b"".join(json_bytes(row) for row in metadata))
    manifest = {
        "schema_version": 1,
        "status": "UNANNOTATED_RUNTIME_EXPORT",
        "origin": result.origin,
        "records": len(result.records),
        "snapshot_hash": capture.snapshot_hash,
        "authorization_id": capture.authorization["id"],
        "training_ready": False,
        "readiness": {"status": "blocked", "reasons": ["responsible_party_data_required"]},
        "families": {
            family: {
                "records": families[family],
                **({"empty_reason": capture.empty_reasons[family]} if not families[family] else {}),
            }
            for family in ("relation", "criterion", "trajectory", "acquisition")
        },
        "languages": dict(Counter(row.language for row in result.records)),
        "quarantined": list(result.quarantined),
        "execution_failures": list(capture.execution_failures),
    }
    files = {
        str(path.relative_to(root)): {
            "sha256": sha(path.read_bytes()),
            "size": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    manifest["files"] = files
    write_new(root / "dataset-manifest.json", manifest)
    return manifest
