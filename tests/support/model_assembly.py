"""Fixed-weight relation bundles for model-assembly tests. No fitting or quality claim.

The same builders run on the pre-move baseline and on this tree, so a registered
model's predictions can be compared across the move.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from career_lab.contracts.v2.core import FileRef, SourceIdentity, digest
from career_lab.models.v3.bundle import json_bytes, save_bundle, sha
from career_lab.models.v3.core import LABELS
from career_lab.models.v3.linear import LinearCandidate

# Characters present in both the Chinese and English work and source texts.
VOCABULARY = {"e": 0, "n": 1, "人": 2, "工": 3, "a": 4, "试": 5}


def fixed_linear_bundle(root: Path, *, fixture: bool) -> tuple[Path, FileRef]:
    """Constructed weights; ``fixture=False`` yields a registrable external candidate."""
    config = {
        "preprocessing_revision": "historical-time-v1",
        "kind": "linear",
        "task_type": "relation",
        "seed": 5002,
        "max_features": len(VOCABULARY),
        "vocabulary": VOCABULARY,
        "evidence_threshold": 0.5,
        "labels": list(LABELS["relation"]),
        "training_report": {"scope": "synthetic_fixed_weights", "fit_performed": False},
    }
    arrays = {
        "coef": np.array(
            [
                [1.5, 0.0, 1.5, 0.0, 0.5, 0.0],
                [0.0, 1.5, 0.0, 1.5, 0.0, 0.5],
                [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            ]
        ),
        "intercept": np.array([0.0, 0.0, 0.2]),
        "evidence_coef": np.array([2.5, 0.0, 3.0, 0.0, 0.0, 1.0]),
        "evidence_intercept": np.array([-0.4]),
        "idf": np.ones(len(VOCABULARY)),
    }
    model = LinearCandidate.restore(config, arrays)
    data = root / "source"
    data.mkdir(parents=True)
    scope = "synthetic_fixed_weights_no_training"
    release = json_bytes({"fixture": fixture, "scope": scope})
    split = json_bytes({"fixture": fixture, "scope": "synthetic_no_held_out_data"})
    (data / "release.json").write_bytes(release)
    (data / "split.json").write_bytes(split)
    ref = save_bundle(
        model,
        root / "bundle",
        source_root=data,
        training_release=FileRef(path="release.json", sha256=sha(release)),
        split_manifest=FileRef(path="split.json", sha256=sha(split)),
        source=SourceIdentity(base_commit="a" * 40, source_digest=digest("synthetic-no-fit")),
    )
    return root / "bundle", ref
