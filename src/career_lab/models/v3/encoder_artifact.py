"""Hash-verified local encoder returns, independent of optional inference libraries.

Weights are streamed into a registry-owned copy. Producer commands are descriptive
metadata only; registration never imports or executes producer Python code.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from career_lab.contracts.v2.core import FileRef, ProtocolError, read_file
from career_lab.models.v3.core import LABELS

RETURN_PROTOCOL = "rolecraft-label-evidence-v2"


def checked_path(root: Path, name: str) -> Path:
    FileRef(path=name, sha256="0" * 64)
    path = root / name
    if any(part.is_symlink() for part in (path, *path.parents) if part != root.parent):
        raise ProtocolError("checkpoint_symlink_not_allowed", status=403)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ProtocolError("file_outside_root", status=403)
    if not path.is_file():
        raise ProtocolError("file_missing", status=503)
    return path


def verify_file(root: Path, ref: FileRef, destination: BinaryIO | None = None) -> None:
    """Stream large safetensors; no NumPy archive limits or whole-file allocation."""
    hasher = hashlib.sha256()
    with checked_path(root, ref.path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            hasher.update(chunk)
            if destination is not None:
                destination.write(chunk)
    if hasher.hexdigest() != ref.sha256:
        raise ProtocolError("file_hash_mismatch", status=409)


def file_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise ProtocolError("checkpoint_files_required")
    result = {}
    for name, checksum in value.items():
        ref = FileRef(path=name, sha256=checksum)
        if ref.path != Path(ref.path).as_posix():
            raise ProtocolError("checkpoint_path_not_canonical")
        result[ref.path] = ref.sha256
    return result


def verify_encoder_files(root: Path, files: object, manifest_path: str) -> dict[str, str]:
    """Shared local-only member policy for registration and actual HF loading."""
    if (
        not isinstance(files, dict)
        or "config.json" not in files
        or not any(name.endswith(".safetensors") for name in files)
    ):
        raise ProtocolError("local_checkpoint_files_incomplete")
    files = file_map(files)
    for name, checksum in files.items():
        if Path(name).suffix not in {".json", ".safetensors", ".model", ".txt", ".md"}:
            raise ProtocolError("checkpoint_file_type_not_allowed")
        verify_file(root, FileRef(path=name, sha256=checksum))
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).as_posix() != manifest_path
    }
    if actual != set(files):
        raise ProtocolError("local_checkpoint_member_set_mismatch")
    return files


def read_json(root: Path, name: str, files: dict[str, str]) -> dict[str, Any]:
    if name not in files:
        raise ProtocolError("checkpoint_files_incomplete")
    value = json.loads(read_file(root, FileRef(path=name, sha256=files[name])))
    if not isinstance(value, dict):
        raise ProtocolError("checkpoint_metadata_invalid")
    return value


@dataclass(frozen=True)
class EncoderArtifact:
    model_revision: str
    source_revision: str
    files: dict[str, str]


def validate_return_identity(manifest: dict[str, Any]) -> None:
    if manifest.get("return_protocol") != RETURN_PROTOCOL:
        raise ProtocolError("model_return_protocol_invalid")
    if manifest.get("task_type") != "relation" or manifest.get("label_order") != list(
        LABELS["relation"]
    ):
        raise ProtocolError("model_return_task_or_labels_invalid")
    if (
        manifest.get("template") is not False
        or manifest.get("completed") is not True
        or manifest.get("evidence_selection_implemented") is not True
        or manifest.get("evidence_selection_required") is not True
    ):
        raise ProtocolError("model_return_incomplete")
    if (
        manifest.get("training_partitions") != ["train"]
        or manifest.get("selection_partition") != "dev"
        or manifest.get("test_used_for_selection") is not False
    ):
        raise ProtocolError("model_return_selection_contaminated")
    for field in (
        "model_revision",
        "framework",
        "framework_version",
        "dataset_id",
        "load_and_predict_command",
        "training_notes_file",
        "predictions_file",
    ):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise ProtocolError("model_return_identity_incomplete")
    if not re.fullmatch(r"[0-9a-f]{64}", str(manifest.get("dataset_manifest_sha256", ""))):
        raise ProtocolError("model_return_dataset_identity_invalid")


def validate_training_identity(config: dict[str, Any]) -> None:
    report = config.get("training_report")
    if not isinstance(report, dict):
        raise ProtocolError("checkpoint_training_identity_mismatch")
    after = report.get("after_weights")
    source = config.get("source_revision")
    if (
        report.get("source_revision") != source
        or report.get("fit_split") != "train"
        or not isinstance(after, str)
        or re.fullmatch(r"[0-9a-f]{64}", after) is None
        or config.get("model_revision") != f"hf-finetuned:{source}:{after}"
    ):
        raise ProtocolError("checkpoint_training_identity_mismatch")


def inspect_encoder(root: Path, manifest_ref: FileRef, *, scope: str) -> EncoderArtifact:
    root = root.resolve()
    manifest = json.loads(read_file(root, manifest_ref))
    validate_return_identity(manifest)
    if "fixture" in manifest["dataset_id"].lower() and scope != "synthetic_fixture":
        raise ProtocolError("fixture_cannot_be_registered_as_external")
    files = file_map(manifest.get("checkpoint_files"))
    if manifest_ref.path in files:
        raise ProtocolError("checkpoint_manifest_self_reference")
    config = read_json(root, "checkpoint.json", files)
    members = file_map(config.get("files"))
    if "heads.npz" not in members or "encoder/local-files.json" not in members:
        raise ProtocolError("checkpoint_files_incomplete")
    if any(files.get(name) != checksum for name, checksum in members.items()):
        raise ProtocolError("checkpoint_manifest_disagreement")
    local = read_json(root, "encoder/local-files.json", members)
    local_files = file_map(local.get("files"))
    validate_training_identity(config)
    if (
        local.get("protocol") != "w08-hf-local-files-v1"
        or local.get("weights_stage") != "supervised_finetuned"
        or not re.fullmatch(r"[0-9a-f]{40}", str(config.get("source_revision", "")))
        or config["source_revision"] != local.get("source_revision")
    ):
        raise ProtocolError("local_checkpoint_revision_or_stage_invalid")
    if (
        config.get("task_type") != "relation"
        or config.get("model_revision") != manifest["model_revision"]
    ):
        raise ProtocolError("checkpoint_model_identity_mismatch")
    if not any(
        "tokenizer" in name or name in {"vocab.txt", "sentencepiece.bpe.model"}
        for name in local_files
    ):
        raise ProtocolError("checkpoint_tokenizer_missing")
    if any(members.get("encoder/" + name) != checksum for name, checksum in local_files.items()):
        raise ProtocolError("checkpoint_manifest_disagreement")
    expected_members = {
        "heads.npz",
        "encoder/local-files.json",
        *("encoder/" + name for name in local_files),
    }
    if set(members) != expected_members or not expected_members | {"checkpoint.json"} <= set(files):
        raise ProtocolError("checkpoint_member_set_mismatch")
    verify_encoder_files(root / "encoder", local_files, "local-files.json")
    verified = {"encoder/" + name for name in local_files}
    for name, checksum in files.items():
        if name not in verified:
            verify_file(root, FileRef(path=name, sha256=checksum))
    return EncoderArtifact(
        manifest["model_revision"],
        config["source_revision"],
        files | {manifest_ref.path: manifest_ref.sha256},
    )
