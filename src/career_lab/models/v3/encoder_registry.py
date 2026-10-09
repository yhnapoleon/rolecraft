"""Immutable local registrations for the agreed dual-head encoder return format."""

import json
from pathlib import Path
from typing import Any

from career_lab.contracts.v2.core import FileRef, ProtocolError, digest, read_file
from career_lab.models.v3.core import LABELS
from career_lab.models.v3.encoder_artifact import EncoderArtifact, inspect_encoder, verify_file
from career_lab.models.v3.huggingface import HuggingFaceCandidate
from career_lab.models.v3.registry import _publish_registration

PROTOCOL = "advisory-encoder-registration-v1"


def _entry(
    artifact: EncoderArtifact, ref: FileRef, scope: str, runtime: dict[str, Any]
) -> dict[str, Any]:
    identity = {
        "protocol": PROTOCOL,
        "kind": "huggingface_encoder",
        "bundle": ref.model_dump(mode="json"),
        "scope": scope,
        "inference_runtime": runtime,
        "files": artifact.files,
    }
    return identity | {
        "id": "encoder-" + digest(identity)[:32],
        "task_type": "relation",
        "labels": list(LABELS["relation"]),
        "model_revision": artifact.model_revision,
        "source_revision": artifact.source_revision,
        "mode": "advisory",
        "affects_score": False,
        "quality_validated": False,
    }


def register_encoder(
    registry_root: Path, bundle_root: Path, ref: FileRef, *, scope: str, runtime: dict[str, Any]
) -> FileRef:
    artifact = inspect_encoder(bundle_root, ref, scope=scope)
    entry = _entry(artifact, ref, scope, runtime)

    def write_artifact(target: Path) -> None:
        for name, checksum in artifact.files.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                verify_file(bundle_root, FileRef(path=name, sha256=checksum), stream)
        copied = inspect_encoder(target, ref, scope=scope)
        if _entry(copied, ref, scope, runtime) != entry:
            raise ProtocolError("model_registration_drift")

    return _publish_registration(
        registry_root,
        entry,
        write_artifact,
        lambda registration: inspect_registration(registry_root, registration, runtime=runtime),
    )


def inspect_registration(root: Path, ref: FileRef, *, runtime: dict[str, Any]) -> dict[str, Any]:
    entry = json.loads(read_file(root, ref))
    if entry.get("protocol") != PROTOCOL or entry.get("scope") not in {
        "synthetic_fixture",
        "external_candidate",
    }:
        raise ProtocolError("model_registration_protocol_invalid")
    if entry.get("inference_runtime") != runtime:
        raise ProtocolError("registered_inference_runtime_changed")
    identity_keys = ("protocol", "kind", "bundle", "scope", "inference_runtime", "files")
    try:
        identifier = "encoder-" + digest({key: entry[key] for key in identity_keys})[:32]
        if entry.get("id") != identifier or ref.path != identifier + "/registration.json":
            raise ProtocolError("model_registration_identity_mismatch")
        bundle_ref = FileRef.model_validate(entry["bundle"])
        artifact = inspect_encoder(root / identifier / "artifact", bundle_ref, scope=entry["scope"])
        if _entry(artifact, bundle_ref, entry["scope"], runtime) != entry:
            raise ProtocolError("registered_model_identity_mismatch")
    except KeyError as exc:
        raise ProtocolError("model_registration_identity_mismatch") from exc
    return entry


def load_encoder(
    root: Path, ref: FileRef, *, runtime: dict[str, Any]
) -> tuple[HuggingFaceCandidate, dict[str, Any]]:
    entry = inspect_registration(root, ref, runtime=runtime)
    model = HuggingFaceCandidate.load_checkpoint(root / entry["id"] / "artifact")
    if model.revision != entry["model_revision"] or model.task_type != entry["task_type"]:
        raise ProtocolError("registered_model_identity_mismatch")
    return model, entry
