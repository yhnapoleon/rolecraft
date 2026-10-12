"""Immutable local registrations of encoder returns (v3 and fixture v2 era layouts).

Each registration pins the installed encoder runtime versions next to the inference
source identity; see docs/data/return-v3/encoder-return.md section 11.
"""

import importlib.metadata
import json
from pathlib import Path
from typing import Any

from career_lab.contracts.v2.core import FileRef, ProtocolError, digest, read_file
from career_lab.models.v3.core import LABELS
from career_lab.models.v3.encoder_artifact import EncoderArtifact, inspect_encoder, verify_file
from career_lab.models.v3.huggingface import HuggingFaceCandidate
from career_lab.models.v3.registration import (
    RegistrationProtocol,
    RegistrationSummary,
    publish_registration,
)

PROTOCOL = "advisory-encoder-registration-v2"
# Registrations made before the runtime pin; feedback they produced stays readable as
# recorded, but they serve no new advice. Re-register the same return instead.
RETIRED_PROTOCOLS = frozenset({"advisory-encoder-registration-v1"})
# Inference libraries whose installed versions an encoder registration pins.
ENCODER_RUNTIME = ("torch", "transformers", "tokenizers", "safetensors")


def encoder_runtime() -> dict[str, str | None]:
    """Installed encoder runtime versions from package metadata; never imports torch."""
    versions: dict[str, str | None] = {}
    for name in ENCODER_RUNTIME:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


IDENTITY_KEYS = (
    "protocol",
    "kind",
    "bundle",
    "scope",
    "inference_runtime",
    "encoder_runtime",
    "files",
)


def _entry(
    artifact: EncoderArtifact,
    ref: FileRef,
    scope: str,
    runtime: dict[str, Any],
    pinned: dict[str, str | None],
) -> dict[str, Any]:
    identity = {
        "protocol": PROTOCOL,
        "kind": "huggingface_encoder",
        "bundle": ref.model_dump(mode="json"),
        "scope": scope,
        "inference_runtime": runtime,
        "encoder_runtime": pinned,
        "files": artifact.files,
    }
    return identity | {
        "id": "encoder-" + digest(identity)[:32],
        "task_type": "relation",
        "labels": list(LABELS["relation"]),
        "model_revision": artifact.model_revision,
        "source_revision": artifact.source_revision,
        "weights_stage": artifact.weights_stage,
        "variant": artifact.settings.variant,
        "evidence_threshold": artifact.settings.evidence_threshold,
        "max_tokens": artifact.settings.max_tokens,
        "dataset": artifact.dataset,
        "mode": "advisory",
        "affects_score": False,
        "quality_validated": False,
    }


def register_encoder(
    registry_root: Path, bundle_root: Path, ref: FileRef, *, scope: str, runtime: dict[str, Any]
) -> FileRef:
    pinned = encoder_runtime()
    if None in pinned.values():
        raise ProtocolError("encoder_runtime_unavailable", status=503)
    artifact = inspect_encoder(bundle_root, ref, scope=scope)
    entry = _entry(artifact, ref, scope, runtime, pinned)

    def write_artifact(target: Path) -> None:
        for name, checksum in artifact.files.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                verify_file(bundle_root, FileRef(path=name, sha256=checksum), stream)
        copied = inspect_encoder(target, ref, scope=scope)
        if _entry(copied, ref, scope, runtime, pinned) != entry:
            raise ProtocolError("model_registration_drift")

    return publish_registration(
        registry_root,
        entry,
        write_artifact,
        lambda registration: inspect_registration(registry_root, registration, runtime=runtime),
    )


def inspect_registration(root: Path, ref: FileRef, *, runtime: dict[str, Any]) -> dict[str, Any]:
    """Verify a registration and every pinned file; an installed but different encoder
    runtime is refused here, an absent one only when loading."""
    entry = json.loads(read_file(root, ref))
    if entry.get("protocol") in RETIRED_PROTOCOLS:
        raise ProtocolError("encoder_registration_retired", status=410)
    if entry.get("protocol") != PROTOCOL or entry.get("scope") not in {
        "synthetic_fixture",
        "external_candidate",
    }:
        raise ProtocolError("model_registration_protocol_invalid")
    installed = encoder_runtime()
    if entry.get("inference_runtime") != runtime or (
        None not in installed.values() and entry.get("encoder_runtime") != installed
    ):
        raise ProtocolError("registered_inference_runtime_changed")
    try:
        identifier = "encoder-" + digest({key: entry[key] for key in IDENTITY_KEYS})[:32]
        if entry.get("id") != identifier or ref.path != identifier + "/registration.json":
            raise ProtocolError("model_registration_identity_mismatch")
        bundle_ref = FileRef.model_validate(entry["bundle"])
        artifact = inspect_encoder(root / identifier / "artifact", bundle_ref, scope=entry["scope"])
        if _entry(artifact, bundle_ref, entry["scope"], runtime, entry["encoder_runtime"]) != entry:
            raise ProtocolError("registered_model_identity_mismatch")
    except KeyError as exc:
        raise ProtocolError("model_registration_identity_mismatch") from exc
    return entry


def load_encoder(
    root: Path, ref: FileRef, *, runtime: dict[str, Any]
) -> tuple[HuggingFaceCandidate, dict[str, Any]]:
    entry = inspect_registration(root, ref, runtime=runtime)
    if None in encoder_runtime().values():
        raise ProtocolError("pretrained_encoder_dependencies_unavailable", status=503)
    model = HuggingFaceCandidate.load_checkpoint(root / entry["id"] / "artifact")
    if model.revision != entry["model_revision"] or model.task_type != entry["task_type"]:
        raise ProtocolError("registered_model_identity_mismatch")
    return model, entry


def describe(root: Path, ref: FileRef, runtime: dict[str, Any]) -> RegistrationSummary:
    """Verified summary without optional inference dependencies (no torch import)."""
    entry = inspect_registration(root, ref, runtime=runtime)
    return RegistrationSummary(
        id=entry["id"],
        scope=entry["scope"],
        model_revision=entry["model_revision"],
        task_type=entry["task_type"],
        labels=tuple(entry["labels"]),
        kind=entry["kind"],
        dataset=entry["dataset"],
        weights_stage=entry["weights_stage"],
    )


REGISTRATION = RegistrationProtocol(
    handles=lambda entry: entry.get("protocol") in RETIRED_PROTOCOLS | {PROTOCOL},
    describe=describe,
    load=lambda root, ref, runtime: load_encoder(root, ref, runtime=runtime),
)
