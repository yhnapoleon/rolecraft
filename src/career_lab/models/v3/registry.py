"""Local, immutable advisory registrations for already-produced relation model bundles.

This module never fits a model, downloads weights, or promotes scoring/quality.
Only files referenced by the existing validated ModelBundle are copied.
"""

import json
import os
import shutil
import tempfile
from importlib.metadata import version
from pathlib import Path

from career_lab.contracts.v2.core import FileRef, ProtocolError, digest, read_file
from career_lab.contracts.v2.research import ModelBundle

from .bundle import json_bytes, load_bundle, sha, write_json

SCOPES = {"synthetic_fixture", "external_candidate"}
PROTOCOL = "w08-advisory-registration-v1"


def inference_runtime():
    root = Path(__file__).resolve().parents[2]
    files = {
        p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in sorted(root.rglob("*.py"))
    }
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


def register_bundle(registry_root, bundle_root, bundle_ref, *, scope):
    if scope not in SCOPES:
        raise ProtocolError("registration_scope_required")
    bundle_ref = FileRef.model_validate(bundle_ref)
    manifest = json.loads(read_file(Path(bundle_root), bundle_ref))
    if isinstance(manifest, dict) and "return_protocol" in manifest:
        from .encoder_registry import register_encoder

        return register_encoder(
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
    identifier = "w08-" + digest(identity)[:32]
    registry_root = Path(registry_root).resolve()
    registry_root.mkdir(parents=True, exist_ok=True)
    destination = registry_root / identifier
    lock = registry_root / (identifier + ".lock")
    try:
        lock.mkdir()
    except FileExistsError:
        raise ProtocolError("model_registration_busy", status=409) from None
    stage = None
    try:
        entry = identity | {
            "id": identifier,
            "task_type": bundle.task_type,
            "model_revision": bundle.model_revision,
            "labels": list(bundle.labels),
            "mode": "advisory",
            "affects_score": False,
            "quality_validated": False,
        }
        entry_hash = sha(json_bytes(entry))
        ref = FileRef(path=identifier + "/registration.json", sha256=entry_hash)
        if destination.exists():
            _, existing = load_registration(registry_root, ref)
            if existing != entry:
                raise ProtocolError("model_registration_drift")
            return ref
        stage = Path(tempfile.mkdtemp(prefix=".registration-", dir=registry_root))
        for name, raw in files.items():
            path = stage / "artifact" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        # Verify the copied artifact before publication; no producer directory dependency.
        load_bundle(stage / "artifact", bundle_ref)
        write_json(stage / "registration.json", entry)
        os.rename(stage, destination)
        stage = None
        return ref
    finally:
        if stage is not None:
            shutil.rmtree(stage)
        lock.rmdir()


def load_registration(registry_root, registration_ref):
    registration_ref = FileRef.model_validate(registration_ref)
    root = Path(registry_root).resolve()
    entry = json.loads(read_file(root, registration_ref))
    from .encoder_registry import PROTOCOL as encoder_protocol
    from .encoder_registry import load_encoder

    if entry.get("protocol") == encoder_protocol:
        return load_encoder(root, registration_ref, runtime=inference_runtime())
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
    if entry["inference_runtime"] != inference_runtime():
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
