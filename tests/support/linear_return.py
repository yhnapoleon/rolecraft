"""Linear-return builders and published reference scripts for 145 tests. No quality claim.

Weights here are constructed or fitted on in-repo synthetic fixture examples only.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np

from career_lab.contracts.v2.core import FileRef, canonical

ROOT = Path(__file__).resolve().parents[2]
RETURN_V3 = ROOT / "docs/data/return-v3"
REFERENCE = RETURN_V3 / "reference"
GOLDEN = RETURN_V3 / "linear-text-v1.golden.jsonl"
LABELS = ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"]
MECHANISM_DATASET = "rolecraft-linear-mechanism-synthetic"
# Character uni/bigrams seen in both the Chinese and English synthetic work texts.
VOCABULARY = {"2": 0, "1": 1, "版本": 2, "ve": 3, "ca": 4, "[e": 5}
DELETE = object()


@functools.cache
def reference_module(name: str) -> ModuleType:
    """Load a published reference script the way a producer runs it: by file, beside its peers."""
    spec = importlib.util.spec_from_file_location(name, REFERENCE / (name + ".py"))
    if spec is None or spec.loader is None:
        raise FileNotFoundError(REFERENCE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def golden_rows() -> list[dict]:
    return [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines()]


def text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (canonical(value) + "\n").encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def linear_revision(model_sha: str, arrays_sha: str, dataset_sha: str) -> str:
    """The published ``rolecraft-linear-return-v1`` revision formula (linear-return.md)."""
    identity = {
        "arrays_npz_sha256": arrays_sha,
        "dataset_manifest_sha256": dataset_sha,
        "model_json_sha256": model_sha,
    }
    return "linear-return:" + sha(canonical(identity).encode())


def constructed_model() -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Fixed constructed weights over a tiny shared character vocabulary; never fitted."""
    model = {
        "text_template": "rolecraft-linear-text-v1",
        "vectorizer": {
            "analyzer": "char",
            "ngram_range": [1, 2],
            "lowercase": True,
            "sublinear_tf": False,
            "norm": "l2",
            "smooth_idf": True,
            "use_idf": True,
            "vocabulary": VOCABULARY,
        },
        "classifier": {"kind": "multinomial_logistic", "label_order": LABELS},
        "evidence_head": {"kind": "pair_logistic", "vectorizer": "shared", "threshold": 0.5},
        "training": {"scope": "synthetic_constructed_weights", "fit_performed": False},
    }
    arrays = {
        "idf": np.array([1.0, 1.2, 1.5, 1.1, 1.3, 1.0]),
        "coef": np.array(
            [
                [2.0, -1.0, 1.5, 0.5, 0.0, 0.0],
                [-1.0, 2.5, 0.0, 0.0, 0.5, 0.0],
                [0.0, 0.0, -0.5, 0.0, 0.0, 0.0],
            ]
        ),
        "intercept": np.array([0.1, -0.2, 0.3]),
        "evidence_coef": np.array([3.0, -2.0, 2.0, 0.0, 0.0, 0.5]),
        "evidence_intercept": np.array([-0.6]),
    }
    return model, arrays


def npz_bytes(arrays: dict[str, Any]) -> bytes:
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    return buffer.getvalue()


def write_linear_return(
    root: Path,
    *,
    dataset_id: str = MECHANISM_DATASET,
    dataset_sha: str = "d" * 64,
    model: dict[str, Any] | None = None,
    arrays: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    label_tiers: list[str] | None = None,
) -> FileRef:
    """Write a ``rolecraft-linear-return-v1`` return; ``DELETE`` removes an override key."""
    base_model, base_arrays = constructed_model()
    for target, changes in ((base_model, model), (base_arrays, arrays)):
        for key, value in (changes or {}).items():
            if value is DELETE:
                target.pop(key, None)
            else:
                target[key] = value
    model_raw = json_bytes(base_model)
    arrays_raw = npz_bytes(base_arrays)
    (root / "linear").mkdir(parents=True)
    (root / "linear/model.json").write_bytes(model_raw)
    (root / "linear/arrays.npz").write_bytes(arrays_raw)
    outer: dict[str, Any] = {
        "template": False,
        "completed": True,
        "return_protocol": "rolecraft-label-evidence-v2",
        "artifact_kind": "linear",
        "artifact_protocol": "rolecraft-linear-return-v1",
        "model_revision": linear_revision(sha(model_raw), sha(arrays_raw), dataset_sha),
        "framework": "scikit-learn",
        "framework_version": "synthetic-constructed",
        "task_type": "relation",
        "label_order": LABELS,
        "dataset_id": dataset_id,
        "dataset_manifest_sha256": dataset_sha,
        "training_partitions": ["train"],
        "selection_partition": "dev",
        "test_used_for_selection": False,
        "evidence_selection_implemented": True,
        "evidence_selection_required": True,
        "checkpoint_files": {
            "linear/arrays.npz": sha(arrays_raw),
            "linear/model.json": sha(model_raw),
        },
        "load_and_predict_command": "RoleCraft loader only; producer commands are not executed",
        "training_notes_file": "notes.md",
        "predictions_file": "predictions.dev.jsonl",
    }
    if label_tiers is not None:
        outer["label_tiers"] = label_tiers
    for key, value in (manifest or {}).items():
        if value is DELETE:
            outer.pop(key, None)
        else:
            outer[key] = value
    raw = json_bytes(outer)
    (root / "checkpoint-manifest.json").write_bytes(raw)
    return FileRef(path="checkpoint-manifest.json", sha256=sha(raw))
