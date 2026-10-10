"""Fixture-v2 model-return identity checks. Never import or execute delivery code."""

import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue, field_validator

from career_lab.contracts.v2.core import FileRef, ProtocolError, digest, read_file
from career_lab.contracts.v2.data import RelationInput

from .common import sha
from .handoff_package import HandoffPackage, decode_json
from .handoff_records import LABEL_ORDERS, InputRow, LabelRow, Metadata

RELATION_ORDER = LABEL_ORDERS["relation"]


class CheckpointManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    template: bool
    completed: bool
    model_revision: str
    framework: str
    framework_version: str
    task_type: Literal["relation"]
    label_order: list[str]
    dataset_id: str
    dataset_manifest_sha256: str
    training_partitions: list[str]
    selection_partition: Literal["dev"]
    test_used_for_selection: bool
    evidence_selection_implemented: bool
    evidence_selection_required: bool
    checkpoint_files: dict[str, str]
    load_and_predict_command: str
    training_notes_file: str
    predictions_file: str
    return_protocol: Literal["rolecraft-label-evidence-v2"]
    # Intake supplement: explicit roles; filenames never select a model or adapter.
    artifact_roles: dict[str, list[str]] | None = None


class EvidenceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    candidate_id: str
    candidate_sha256: str


class Prediction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    return_schema_version: int
    record_id: str
    input_hash: str
    model_revision: str
    task_type: Literal["relation"]
    status: Literal["ok", "failed", "abstained"]
    probabilities: list[float] | None
    label: str | None
    evidence_ids: list[str]
    evidence_bindings: list[EvidenceBinding]
    reason: str | None = None

    @field_validator("return_schema_version")
    @classmethod
    def version_two(cls, value: int) -> int:
        if value != 2:
            raise ValueError("return schema version must be 2")
        return value


def _local_bytes(root: Path, name: str) -> bytes:
    # FileRef supplies the same portable path boundary as every other artifact.
    ref = FileRef(path=name, sha256="0" * 64)
    path = root / ref.path
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ProtocolError("handoff_model_file_outside_root")
    return path.read_bytes()


def _checkpoint_files(path: Path, manifest: CheckpointManifest) -> dict[str, bytes]:
    root = path.parent
    if root.is_symlink() or any(item.is_symlink() for item in root.rglob("*")):
        raise ProtocolError("handoff_model_symlink_forbidden")
    files = {path.name: path.read_bytes()}
    for name, expected in manifest.checkpoint_files.items():
        if name == path.name:
            raise ProtocolError("handoff_model_file_set_mismatch")
        files[name] = read_file(root, FileRef(path=name, sha256=expected))
    for name in (manifest.training_notes_file, manifest.predictions_file):
        files[name] = _local_bytes(root, name)
    actual = {item.relative_to(root).as_posix() for item in root.rglob("*") if item.is_file()}
    if actual != files.keys() or not manifest.checkpoint_files:
        raise ProtocolError("handoff_model_file_set_mismatch")
    roles = manifest.artifact_roles
    if roles is None or any(not roles.get(role) for role in ("checkpoint", "config", "tokenizer")):
        raise ProtocolError("handoff_model_artifact_roles_required")
    if any(name not in manifest.checkpoint_files for names in roles.values() for name in names):
        raise ProtocolError("handoff_model_artifact_role_unbound")
    return files


def _check_manifest(manifest: CheckpointManifest, package: HandoffPackage) -> None:
    if (
        manifest.template
        or not manifest.completed
        or manifest.test_used_for_selection
        or not manifest.evidence_selection_implemented
        or not manifest.evidence_selection_required
    ):
        raise ProtocolError("handoff_model_completion_required")
    if manifest.label_order != RELATION_ORDER:
        raise ProtocolError("handoff_model_label_order_mismatch")
    if (manifest.dataset_id, manifest.dataset_manifest_sha256) != (
        package.manifest.dataset_id,
        package.manifest_hash,
    ):
        raise ProtocolError("handoff_model_dataset_mismatch")
    if manifest.training_partitions != ["train"]:
        raise ProtocolError("handoff_model_partition_mismatch")
    if any(
        not getattr(manifest, name).strip()
        for name in (
            "model_revision",
            "framework",
            "framework_version",
            "load_and_predict_command",
            "training_notes_file",
            "predictions_file",
        )
    ):
        raise ProtocolError("handoff_model_field_required")


def _prediction_identity(
    prediction: Prediction, row: InputRow, label: LabelRow, revision: str
) -> None:
    if (
        not isinstance(row.model_input, RelationInput)
        or prediction.task_type != row.model_input.task_type
    ):
        raise ProtocolError("handoff_prediction_task_mismatch")
    if prediction.input_hash != row.input_hash or prediction.model_revision != revision:
        raise ProtocolError("handoff_prediction_identity_mismatch")
    candidates = {item.id: item for item in row.model_input.evidence.candidate_evidence}
    ids = prediction.evidence_ids
    if len(set(ids)) != len(ids) or set(ids) - candidates.keys():
        raise ProtocolError("handoff_prediction_evidence_mismatch")
    bindings = {item.candidate_id: item.candidate_sha256 for item in prediction.evidence_bindings}
    if len(bindings) != len(prediction.evidence_bindings) or bindings.keys() != set(ids):
        raise ProtocolError("handoff_prediction_evidence_mismatch")
    if any(bindings[cid] != row.candidate_hash(cid) for cid in ids):
        raise ProtocolError("handoff_prediction_candidate_hash_mismatch")
    if (not ids or prediction.status != "ok") and not (prediction.reason or "").strip():
        raise ProtocolError("handoff_prediction_reason_required")
    if prediction.status != "ok":
        if prediction.probabilities is not None or prediction.label is not None or ids or bindings:
            raise ProtocolError("handoff_failed_prediction_has_label")
        return
    probabilities = prediction.probabilities
    if (
        probabilities is None
        or len(probabilities) != 3
        or any(not math.isfinite(value) or not 0 <= value <= 1 for value in probabilities)
        or abs(sum(probabilities) - 1) > 1e-6
    ):
        raise ProtocolError("handoff_prediction_probabilities_invalid")
    winner = max(range(3), key=lambda index: probabilities[index])
    if prediction.label != RELATION_ORDER[winner]:
        raise ProtocolError("handoff_prediction_argmax_mismatch")
    if not ids and prediction.label != "INSUFFICIENT" and label.evidence_evaluable:
        raise ProtocolError("handoff_prediction_evidence_required")


def validate_model_return(
    package: HandoffPackage,
    path: Path,
    split: str,
    inputs: dict[str, InputRow],
    labels: dict[str, LabelRow],
    metadata: dict[str, Metadata],
) -> dict[str, JsonValue]:
    if path.is_symlink():
        raise ProtocolError("handoff_model_symlink_forbidden")
    manifest = CheckpointManifest.model_validate(decode_json(path.read_bytes()))
    _check_manifest(manifest, package)
    files = _checkpoint_files(path, manifest)
    expected = {rid for rid in inputs if metadata[rid].split == split}
    if not expected:
        raise ProtocolError("handoff_prediction_partition_empty")
    results, seen = [], set()
    for raw in files[manifest.predictions_file].splitlines():
        if not raw.strip():
            continue
        prediction = Prediction.model_validate(decode_json(raw))
        rid = prediction.record_id
        if rid not in expected or rid in seen:
            raise ProtocolError("handoff_prediction_record_set_mismatch")
        seen.add(rid)
        try:
            _prediction_identity(prediction, inputs[rid], labels[rid], manifest.model_revision)
            result = {
                "record_id": rid,
                "status": "accept" if prediction.status == "ok" else "pending",
                "reasons": [] if prediction.status == "ok" else ["prediction_" + prediction.status],
            }
        except ProtocolError as error:
            result = {"record_id": rid, "status": "quarantine", "reasons": [error.code]}
        results.append(result)
    if seen != expected:
        raise ProtocolError("handoff_prediction_record_set_mismatch")
    return {
        "format_valid": all(row["status"] == "accept" for row in results),
        "model_revision": manifest.model_revision,
        "return_sha256": digest({name: sha(raw) for name, raw in sorted(files.items())}),
        "artifact_files": {name: sha(raw) for name, raw in files.items()},
        "records": results,
        "split": split,
        "model_loaded": False,
        "training_verified": False,
        "quality_verified": False,
    }
