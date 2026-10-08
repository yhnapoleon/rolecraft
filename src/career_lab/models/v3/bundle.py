"""Immutable W01 ModelBundle creation and hash-verified, non-pickle loading."""

from pathlib import Path
import hashlib
import io
import json
import os
import shutil
import tempfile
import zipfile
import numpy as np

from career_lab.contracts.v2.core import (
    FileRef,
    SourceIdentity,
    ProtocolError,
    canonical,
    digest,
    read_file,
)
from career_lab.contracts.v2.research import ModelBundle
from .core import LABELS
from .linear import LinearCandidate
from .encoder import AttentionEncoder
from .legacy import LegacyMLP

ENTRYPOINTS = {
    "linear": "career_lab.models.v3.linear:LinearCandidate",
    "numpy_attention": "career_lab.models.v3.encoder:AttentionEncoder",
    "legacy_character_mlp": "career_lab.models.v3.legacy:LegacyMLP",
}


def json_bytes(value):
    return (canonical(value) + "\n").encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(json_bytes(value))


def save_bundle(
    model, target, *, source_root, training_release, split_manifest, source: SourceIdentity
):
    if model.kind not in ENTRYPOINTS:
        raise ProtocolError("bundle_backend_not_registered")
    target = Path(target).absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.with_name(target.name + ".lock")
    try:
        lock.mkdir()
    except FileExistsError:
        raise ProtocolError("bundle_publish_busy", status=409) from None
    stage = None
    try:
        if target.exists() or target.is_symlink():
            raise ProtocolError("immutable_bundle_exists", status=409)
        stage = Path(tempfile.mkdtemp(prefix=".model-", dir=target.parent))
        (stage / "weights").mkdir()
        config = model.configuration()
        write_json(stage / "preprocessing.json", config)
        arrays = model.arrays()
        if any(not np.isfinite(a).all() for a in arrays.values()):
            raise ProtocolError("nonfinite_model_weights")
        np.savez(stage / "weights/model.npz", **arrays)

        def copy_ref(ref, name):
            raw = read_file(Path(source_root), ref)
            p = stage / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(raw)
            return FileRef(path=name, sha256=sha(raw), media_type=ref.media_type)

        release = copy_ref(training_release, "provenance/training-release.json")
        split = copy_ref(split_manifest, "provenance/split-manifest.json")
        locks = tuple(
            copy_ref(ref, f"provenance/lock-{i}.txt")
            for i, ref in enumerate(source.dependency_locks)
        )
        overlay = copy_ref(source.overlay, "provenance/source-overlay") if source.overlay else None
        source_copy = SourceIdentity(
            base_commit=source.base_commit,
            source_digest=source.source_digest,
            overlay=overlay,
            dependency_locks=locks,
        )
        weights = FileRef(
            path="weights/model.npz",
            sha256=sha((stage / "weights/model.npz").read_bytes()),
            media_type="application/x-npz",
        )
        pre = FileRef(
            path="preprocessing.json", sha256=sha((stage / "preprocessing.json").read_bytes())
        )
        revision = (
            model.kind
            + ":"
            + digest(
                {
                    "weights": weights.sha256,
                    "config": pre.sha256,
                    "release": release.sha256,
                    "source": source_copy.model_dump(mode="json"),
                }
            )
        )
        bundle = ModelBundle(
            id="model-" + digest(revision)[:24],
            task_type=model.task_type,
            labels=LABELS[model.task_type],
            model_revision=revision,
            tokenizer_revision="train-only-" + model.kind + "-v1",
            weights=(weights,),
            preprocessing=pre,
            inference_entrypoint=ENTRYPOINTS[model.kind],
            training_release=release,
            split_manifest=split,
            source=source_copy,
        )
        write_json(stage / "model-bundle.json", bundle)
        ref = FileRef(
            path="model-bundle.json", sha256=sha((stage / "model-bundle.json").read_bytes())
        )
        load_bundle(stage, ref)
        os.rename(stage, target)
        stage = None
        model.revision = revision
        return ref
    finally:
        if stage is not None:
            shutil.rmtree(stage)
        lock.rmdir()


def load_bundle(root, ref: FileRef, _depth=0):
    if _depth > 2:
        raise ProtocolError("bundle_recursion_limit")
    root = Path(root)
    bundle = ModelBundle.model_validate_json(read_file(root, ref))
    if bundle.task_type not in LABELS or tuple(bundle.labels) != LABELS[bundle.task_type]:
        raise ProtocolError("bundle_label_order_mismatch")
    config = json.loads(read_file(root, bundle.preprocessing))
    if config.get("preprocessing_revision") != "historical-time-v1":
        raise ProtocolError("legacy_bundle_requires_frozen_runtime")
    kind = config.get("kind")
    if kind == "probability_fusion":
        from .fusion_bundle import ENTRYPOINT, load_fusion

        if bundle.inference_entrypoint != ENTRYPOINT:
            raise ProtocolError("bundle_entrypoint_not_allowed")
        for r in (
            *bundle.weights,
            bundle.training_release,
            bundle.split_manifest,
            *bundle.source.dependency_locks,
        ):
            read_file(root, r)
        if bundle.source.overlay:
            read_file(root, bundle.source.overlay)
        return load_fusion(root, bundle, config, _depth)
    if kind not in ENTRYPOINTS or bundle.inference_entrypoint != ENTRYPOINTS[kind]:
        raise ProtocolError("bundle_entrypoint_not_allowed")
    if config.get("task_type") != bundle.task_type or len(bundle.weights) != 1:
        raise ProtocolError("bundle_task_or_weights_mismatch")
    for r in (bundle.training_release, bundle.split_manifest, *bundle.source.dependency_locks):
        read_file(root, r)
    if bundle.source.overlay:
        read_file(root, bundle.source.overlay)
    raw = read_file(root, bundle.weights[0])
    if len(raw) > 64 * 1024 * 1024:
        raise ProtocolError("bundle_requires_large_model_loader")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(i.file_size for i in archive.infolist()) > 64 * 1024 * 1024:
            raise ProtocolError("model_archive_expansion_limit")
    with np.load(io.BytesIO(raw), allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    cls = {
        "linear": LinearCandidate,
        "numpy_attention": AttentionEncoder,
        "legacy_character_mlp": LegacyMLP,
    }[kind]
    model = cls.restore(config, arrays)
    expected = (
        kind
        + ":"
        + digest(
            {
                "weights": bundle.weights[0].sha256,
                "config": bundle.preprocessing.sha256,
                "release": bundle.training_release.sha256,
                "source": bundle.source.model_dump(mode="json"),
            }
        )
    )
    if bundle.model_revision != expected:
        raise ProtocolError("bundle_model_revision_mismatch")
    model.revision = bundle.model_revision
    return model, bundle
