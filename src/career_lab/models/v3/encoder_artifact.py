"""Hash-verified local encoder returns, independent of optional inference libraries.

Weights are streamed into a registry-owned copy. Producer commands are descriptive
metadata only; registration never imports or executes producer Python code.

Two checkpoint layouts load: the fixture v2 era layout (no ``checkpoint_schema_version``)
and v3 (``docs/data/return-v3/encoder-return.md``). Everything a return declares is
checked here without torch: identity, inference settings, head arrays and architecture.
"""

import hashlib
import io
import json
import math
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np

from career_lab.contracts.v2.core import FileRef, ProtocolError, digest, read_file
from career_lab.models.v3.core import LABELS

RETURN_PROTOCOL = "rolecraft-label-evidence-v2"
ARTIFACT_KIND = "huggingface_encoder"
ARTIFACT_PROTOCOL = "rolecraft-encoder-return-v3"
LABEL_TIERS = ("G0", "G1", "G2", "G2v")
WEIGHTS_STAGES = ("supervised_finetuned", "pretrained_untrained_heads")
TRAINED, UNTRAINED = WEIGHTS_STAGES
VARIANTS = ("pack", "pair", "pair_aggregate")
LEGACY_VARIANTS = ("pack", "pair")
# pair_aggregate judges each (claim, candidate) pair in this fixed order.
PAIR_LABELS = ("SUPPORTS", "CONTRADICTS", "UNRELATED")
# The fixture v2 era layout fixed the evidence threshold at 0.5.
LEGACY_EVIDENCE_THRESHOLD = 0.5
V3_ONLY_FIELDS = ("pooling", "evidence_threshold", "pair_label_order")
# Inputs of the v3 model_revision: weights plus every setting that changes predictions.
REVISION_FIELDS = (
    "after_weights",
    "evidence_threshold",
    "max_tokens",
    "pooling",
    "source_revision",
    "task_type",
    "variant",
    "weights_stage",
)
# Tokenizers without a real limit report a huge sentinel instead of a length.
_UNBOUNDED_TOKENIZER = 10**9


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


def model_revision_v3(fields: dict[str, Any]) -> str:
    """``hf-encoder-v3:`` + SHA-256 of the canonical JSON of ``REVISION_FIELDS``."""
    return "hf-encoder-v3:" + digest({name: fields[name] for name in REVISION_FIELDS})


def head_shapes(variant: str, hidden: int) -> dict[str, tuple[int, ...]]:
    """The head arrays ``heads.npz`` must hold for ``variant`` over a ``hidden``-wide encoder."""
    if variant == "pair_aggregate":
        return {"pair.weight": (len(PAIR_LABELS), hidden), "pair.bias": (len(PAIR_LABELS),)}
    labels = len(LABELS["relation"])
    return {
        "relation.weight": (labels, hidden),
        "relation.bias": (labels,),
        "selector.weight": (1, 2 * hidden),
        "selector.bias": (1,),
    }


@dataclass(frozen=True)
class EncoderSettings:
    """How a checkpoint turns encoder states into a prediction."""

    schema: int
    variant: str
    pooling: str
    evidence_threshold: float
    max_tokens: int
    seed: int


@dataclass(frozen=True)
class EncoderArtifact:
    model_revision: str
    source_revision: str
    files: dict[str, str]
    weights_stage: str
    # The training data release the outer manifest names (dataset_id, sha256, label tiers).
    dataset: dict[str, Any]
    settings: EncoderSettings


def _check_task(manifest: dict[str, Any]) -> None:
    if manifest.get("return_protocol") != RETURN_PROTOCOL:
        raise ProtocolError("model_return_protocol_invalid")
    if manifest.get("task_type") != "relation" or manifest.get("label_order") != list(
        LABELS["relation"]
    ):
        raise ProtocolError("model_return_task_or_labels_invalid")


def _check_identity(manifest: dict[str, Any]) -> None:
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


def validate_return_identity(manifest: dict[str, Any]) -> None:
    """Outer manifest policy (fixture v2 template) shared by every return kind.

    A completed, trained delivery only: template off, completion and evidence selection
    declared, train-only fitting and dev-only selection, identity fields present. Any
    other ``weights_stage`` is refused here; artifact kinds are each protocol's concern.
    """
    _check_task(manifest)
    if manifest.get("weights_stage", TRAINED) != TRAINED:
        raise ProtocolError("model_return_weights_stage_invalid")
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
    _check_identity(manifest)


def validate_encoder_return_identity(manifest: dict[str, Any], *, scope: str) -> str:
    """Encoder returns: the shared policy, or for a synthetic registration the honest
    declaration of pretrained weights with untrained heads. Returns the weights stage."""
    stage = manifest.get("weights_stage", TRAINED)
    if stage != UNTRAINED:
        validate_return_identity(manifest)
        return TRAINED
    _check_task(manifest)
    if scope != "synthetic_fixture":
        raise ProtocolError("untrained_heads_require_synthetic_scope", status=403)
    if (
        manifest.get("template") is not False
        or manifest.get("completed") is not False
        or manifest.get("evidence_selection_implemented") is not True
        or manifest.get("evidence_selection_required") is not True
        or manifest.get("training_partitions") != []
        or manifest.get("selection_partition") is not None
        or manifest.get("test_used_for_selection") is not False
    ):
        raise ProtocolError("untrained_heads_declaration_invalid")
    _check_identity(manifest)
    return UNTRAINED


def is_encoder_return(manifest: object) -> bool:
    """A fixture v2 style return manifest that names no other artifact kind.

    Returns without ``artifact_kind`` predate v3 and are encoder returns; linear, fusion
    and any other kind belong to their own registration protocol.
    """
    return (
        isinstance(manifest, dict)
        and "return_protocol" in manifest
        and manifest.get("artifact_kind", ARTIFACT_KIND) == ARTIFACT_KIND
        and manifest.get("artifact_protocol", ARTIFACT_PROTOCOL) == ARTIFACT_PROTOCOL
    )


def dataset_identity(manifest: dict[str, Any]) -> dict[str, Any]:
    tiers = manifest.get("label_tiers", [])
    if (
        not isinstance(tiers, list)
        or len(set(tiers)) != len(tiers)
        or any(tier not in LABEL_TIERS for tier in tiers)
    ):
        raise ProtocolError("model_return_dataset_identity_invalid")
    return {
        "dataset_id": manifest["dataset_id"],
        "dataset_manifest_sha256": manifest["dataset_manifest_sha256"],
        "label_tiers": sorted(tiers, key=LABEL_TIERS.index),
    }


def checkpoint_settings(config: dict[str, Any]) -> EncoderSettings:
    """Inference settings of either layout; v3 states them, the legacy layout implies them."""
    schema = config.get("checkpoint_schema_version")
    if schema is None:
        if any(field in config for field in V3_ONLY_FIELDS):
            raise ProtocolError("checkpoint_schema_version_required")
        if config.get("variant") not in LEGACY_VARIANTS:
            raise ProtocolError("encoder_architecture_unsupported")
        threshold, pooling = LEGACY_EVIDENCE_THRESHOLD, "mean"
    elif schema == 3:
        if config.get("variant") not in VARIANTS or config.get("pooling") != "mean":
            raise ProtocolError("encoder_architecture_unsupported")
        if config["variant"] == "pair_aggregate" and config.get("pair_label_order") != list(
            PAIR_LABELS
        ):
            raise ProtocolError("model_return_task_or_labels_invalid")
        threshold, pooling = config.get("evidence_threshold"), "mean"
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, int | float)
            or not math.isfinite(threshold)
            or not 0 < threshold < 1
        ):
            raise ProtocolError("checkpoint_inference_settings_invalid")
    else:
        raise ProtocolError("checkpoint_schema_version_unsupported")
    max_tokens, seed = config.get("max_tokens"), config.get("seed")
    if type(max_tokens) is not int or max_tokens < 4 or type(seed) is not int:
        raise ProtocolError("checkpoint_inference_settings_invalid")
    return EncoderSettings(
        2 if schema is None else 3, config["variant"], pooling, float(threshold), max_tokens, seed
    )


def validate_training_identity(
    config: dict[str, Any], settings: EncoderSettings, weights_stage: str
) -> None:
    report = config.get("training_report")
    if not isinstance(report, dict):
        raise ProtocolError("checkpoint_training_identity_mismatch")
    after = report.get("after_weights")
    source = config.get("source_revision")
    if weights_stage == UNTRAINED:
        trained_as_declared = report.get("training_kind") == "none" and "fit_split" not in report
    else:
        trained_as_declared = report.get("fit_split") == "train" and (
            report.get("training_kind") != "none"
            if settings.schema == 2
            else isinstance(report.get("training_kind"), str)
            and report["training_kind"] not in {"", "none"}
        )
    if (
        report.get("source_revision") != source
        or not trained_as_declared
        or not isinstance(after, str)
        or re.fullmatch(r"[0-9a-f]{64}", after) is None
    ):
        raise ProtocolError("checkpoint_training_identity_mismatch")
    expected = (
        f"hf-finetuned:{source}:{after}"
        if settings.schema == 2
        else model_revision_v3(
            {
                "after_weights": after,
                "evidence_threshold": settings.evidence_threshold,
                "max_tokens": settings.max_tokens,
                "pooling": settings.pooling,
                "source_revision": source,
                "task_type": config.get("task_type"),
                "variant": settings.variant,
                "weights_stage": weights_stage,
            }
        )
    )
    if config.get("model_revision") != expected:
        raise ProtocolError("checkpoint_training_identity_mismatch")


def encoder_width(encoder_config: dict[str, Any]) -> int:
    """Hidden size of a standard local Transformers encoder; remote code is unsupported."""
    hidden = encoder_config.get("hidden_size")
    if (
        type(hidden) is not int
        or hidden < 1
        or not isinstance(encoder_config.get("model_type"), str)
        or "auto_map" in encoder_config
    ):
        raise ProtocolError("encoder_architecture_unsupported")
    return hidden


def check_capacity(
    settings: EncoderSettings, encoder_config: dict[str, Any], tokenizer_config: dict[str, Any]
) -> None:
    """``max_tokens`` within the tokenizer limit and the position embeddings, where declared."""
    limits = [encoder_config.get("max_position_embeddings")]
    limits.append(tokenizer_config.get("model_max_length"))
    for limit in limits:
        if type(limit) is int and limit < _UNBOUNDED_TOKENIZER and settings.max_tokens > limit:
            raise ProtocolError("tokenizer_capacity_exceeded")


def check_heads(raw: bytes, settings: EncoderSettings, hidden: int) -> None:
    try:
        with np.load(io.BytesIO(raw), allow_pickle=False) as archive:
            arrays = {name: archive[name] for name in archive.files}
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        raise ProtocolError("checkpoint_heads_invalid") from error
    expected = head_shapes(settings.variant, hidden)
    if set(arrays) != set(expected) or any(
        arrays[name].shape != shape or arrays[name].dtype.kind != "f"
        for name, shape in expected.items()
    ):
        raise ProtocolError("encoder_architecture_unsupported")
    if not all(np.isfinite(array).all() for array in arrays.values()):
        raise ProtocolError("checkpoint_heads_invalid")


def inspect_encoder(root: Path, manifest_ref: FileRef, *, scope: str) -> EncoderArtifact:
    root = root.resolve()
    manifest = json.loads(read_file(root, manifest_ref))
    if not is_encoder_return(manifest):
        raise ProtocolError("model_return_protocol_invalid")
    stage = validate_encoder_return_identity(manifest, scope=scope)
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
    settings = checkpoint_settings(config)
    if (
        local.get("protocol") != "w08-hf-local-files-v1"
        or local.get("weights_stage") != stage
        or (settings.schema == 2 and stage != TRAINED)
        or not re.fullmatch(r"[0-9a-f]{40}", str(config.get("source_revision", "")))
        or config["source_revision"] != local.get("source_revision")
    ):
        raise ProtocolError("local_checkpoint_revision_or_stage_invalid")
    validate_training_identity(config, settings, stage)
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
    encoder_config = read_json(root / "encoder", "config.json", local_files)
    hidden = encoder_width(encoder_config)
    tokenizer_config = (
        read_json(root / "encoder", "tokenizer_config.json", local_files)
        if "tokenizer_config.json" in local_files
        else {}
    )
    check_capacity(settings, encoder_config, tokenizer_config)
    check_heads(
        read_file(root, FileRef(path="heads.npz", sha256=members["heads.npz"])), settings, hidden
    )
    return EncoderArtifact(
        manifest["model_revision"],
        config["source_revision"],
        files | {manifest_ref.path: manifest_ref.sha256},
        stage,
        dataset_identity(manifest),
        settings,
    )
