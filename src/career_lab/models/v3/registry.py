"""Local, immutable advisory registrations for already-produced relation model bundles.

This module never fits a model, downloads weights, or promotes scoring/quality.
Only files referenced by a validated ModelBundle, local encoder return or linear return
are copied.
"""

import json
from importlib.metadata import version
from pathlib import Path
from typing import Any

from career_lab.contracts.v2.core import FileRef, ProtocolError, digest, read_file
from career_lab.contracts.v2.research import ModelBundle

from . import encoder_registry, linear_return
from .bundle import load_bundle, sha
from .registration import RegistrationProtocol, RegistrationSummary, publish_registration

# Kept for existing importers; the lifecycle lives with the other registration primitives.
_publish_registration = publish_registration

SCOPES = {"synthetic_fixture", "external_candidate"}
PROTOCOL = "w08-advisory-registration-v1"


# Source that decides a registered model's predictions: model code plus the input and file
# contracts it validates against. Other product changes leave registrations valid.
INFERENCE_CLOSURE = ("models/v3/**/*.py", "contracts/v2/core.py", "contracts/v2/data.py")


def inference_runtime():
    root = Path(__file__).resolve().parents[2]
    paths = sorted({path for pattern in INFERENCE_CLOSURE for path in root.glob(pattern)})
    files = {path.relative_to(root).as_posix(): sha(path.read_bytes()) for path in paths}
    return {
        "source_digest": digest(files),
        "dependencies": {name: version(name) for name in ("numpy", "scikit-learn", "pydantic")},
    }


def _collect(root, ref, prefix="", depth=0):
    """Use the same explicit component layout supported by load_bundle."""
    root = Path(root)
    bundle = ModelBundle.model_validate_json(read_file(root, ref))
    refs = [
        ref,
        bundle.preprocessing,
        bundle.training_release,
        bundle.split_manifest,
        *bundle.weights,
        *bundle.source.dependency_locks,
    ]
    if bundle.source.overlay:
        refs.append(bundle.source.overlay)
    files = {}
    for item in refs:
        name = prefix + item.path
        raw = read_file(root, item)
        if name in files and files[name] != raw:
            raise ProtocolError("registered_artifact_collision")
        files[name] = raw
    config = json.loads(read_file(root, bundle.preprocessing))
    if config.get("kind") == "probability_fusion":
        if depth:
            raise ProtocolError("nested_fusion_not_supported")
        for side in ("left", "right"):
            child = config[side]
            relative = FileRef(path=child["root"], sha256="0" * 64).path
            child_root = (root / relative).resolve()
            if not child_root.is_relative_to(root.resolve()):
                raise ProtocolError("component_outside_bundle")
            additions = _collect(
                child_root,
                FileRef.model_validate(child["manifest"]),
                prefix + relative + "/",
                depth + 1,
            )
            for name, raw in additions.items():
                if name in files and files[name] != raw:
                    raise ProtocolError("registered_artifact_collision")
                files[name] = raw
    return files


def register_bundle(
    registry_root: Path | str,
    bundle_root: Path | str,
    bundle_ref: FileRef | dict[str, Any],
    *,
    scope: str,
) -> FileRef:
    if scope not in SCOPES:
        raise ProtocolError("registration_scope_required")
    bundle_ref = FileRef.model_validate(bundle_ref)
    manifest = json.loads(read_file(Path(bundle_root), bundle_ref))
    if isinstance(manifest, dict) and "return_protocol" in manifest:
        if linear_return.is_linear_return(manifest):
            return linear_return.register_linear(
                Path(registry_root),
                Path(bundle_root),
                bundle_ref,
                scope=scope,
                runtime=inference_runtime(),
            )
        return encoder_registry.register_encoder(
            Path(registry_root),
            Path(bundle_root),
            bundle_ref,
            scope=scope,
            runtime=inference_runtime(),
        )
    _, bundle = load_bundle(bundle_root, bundle_ref)
    release = json.loads(read_file(Path(bundle_root), bundle.training_release))
    if release.get("fixture") is True and scope != "synthetic_fixture":
        raise ProtocolError("fixture_cannot_be_registered_as_external")
    files = _collect(bundle_root, bundle_ref)
    identity = {
        "protocol": PROTOCOL,
        "bundle": bundle_ref.model_dump(mode="json"),
        "scope": scope,
        "inference_runtime": inference_runtime(),
        "files": {p: sha(raw) for p, raw in sorted(files.items())},
    }
    entry = identity | {
        "id": "w08-" + digest(identity)[:32],
        "task_type": bundle.task_type,
        "model_revision": bundle.model_revision,
        "labels": list(bundle.labels),
        "mode": "advisory",
        "affects_score": False,
        "quality_validated": False,
    }

    def write_artifact(target: Path) -> None:
        for name, raw in files.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        load_bundle(target, bundle_ref)

    return publish_registration(
        Path(registry_root),
        entry,
        write_artifact,
        lambda ref: load_registration(registry_root, ref)[1],
    )


def load_registration(registry_root, registration_ref):
    registration_ref = FileRef.model_validate(registration_ref)
    root = Path(registry_root).resolve()
    entry = json.loads(read_file(root, registration_ref))
    return _protocol(entry).load(root, registration_ref, inference_runtime())


def describe_registration(registry_root, registration_ref) -> RegistrationSummary:
    """Verified generic summary of any supported registration; public identity comes from here.

    Verification matches what loading requires, except optional inference dependencies.
    """
    registration_ref = FileRef.model_validate(registration_ref)
    root = Path(registry_root).resolve()
    entry = json.loads(read_file(root, registration_ref))
    return _protocol(entry).describe(root, registration_ref, inference_runtime())


def _protocol(entry: Any) -> RegistrationProtocol:
    for protocol in REGISTRATION_PROTOCOLS:
        if isinstance(entry, dict) and protocol.handles(entry):
            return protocol
    raise ProtocolError("model_registration_protocol_invalid")


def _load_bundle_registration(root: Path, registration_ref: FileRef, runtime: dict[str, Any]):
    entry = json.loads(read_file(root, registration_ref))
    if entry.get("protocol") != PROTOCOL or entry.get("scope") not in SCOPES:
        raise ProtocolError("model_registration_protocol_invalid")
    if (
        entry.get("mode") != "advisory"
        or entry.get("affects_score") is not False
        or entry.get("quality_validated") is not False
    ):
        raise ProtocolError("registration_cannot_promote_scoring_or_quality")
    identity = {k: entry[k] for k in ("protocol", "bundle", "scope", "files", "inference_runtime")}
    expected = "w08-" + digest(identity)[:32]
    if entry.get("id") != expected or registration_ref.path != expected + "/registration.json":
        raise ProtocolError("model_registration_identity_mismatch")
    if entry["inference_runtime"] != runtime:
        raise ProtocolError("registered_inference_runtime_changed")
    artifact = root / expected / "artifact"
    for path, expected_hash in entry["files"].items():
        read_file(artifact, FileRef(path=path, sha256=expected_hash))
    model, bundle = load_bundle(artifact, FileRef.model_validate(entry["bundle"]))
    if (
        entry["task_type"] != bundle.task_type
        or entry["model_revision"] != bundle.model_revision
        or tuple(entry["labels"]) != bundle.labels
    ):
        raise ProtocolError("registered_model_identity_mismatch")
    return model, entry


def _describe_bundle_registration(
    root: Path, registration_ref: FileRef, runtime: dict[str, Any]
) -> RegistrationSummary:
    _, entry = _load_bundle_registration(root, registration_ref, runtime)
    return RegistrationSummary(
        id=entry["id"],
        scope=entry["scope"],
        model_revision=entry["model_revision"],
        task_type=entry["task_type"],
        labels=tuple(entry["labels"]),
    )


BUNDLE_REGISTRATION = RegistrationProtocol(
    handles=lambda entry: entry.get("protocol") == PROTOCOL,
    describe=_describe_bundle_registration,
    load=_load_bundle_registration,
)
# Dispatch order is irrelevant: each protocol recognises only its own entries.
REGISTRATION_PROTOCOLS: tuple[RegistrationProtocol, ...] = (
    BUNDLE_REGISTRATION,
    encoder_registry.REGISTRATION,
    linear_return.REGISTRATION,
)


def public_registration(entry):
    """Public identity only; do not expose artifact paths, labels/gold files or source overlays."""
    return {
        key: entry[key]
        for key in (
            "id",
            "task_type",
            "model_revision",
            "labels",
            "scope",
            "mode",
            "affects_score",
            "quality_validated",
            "inference_runtime",
        )
    }
