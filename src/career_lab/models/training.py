import hashlib
import json
import time
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics import f1_score

from career_lab.contracts.evaluation import EvidencePackage
from career_lab.datasets.release import audit_release, read_jsonl
from career_lab.models.ensemble import Ensemble, blend
from career_lab.models.linear import LABELS, TextClassifier


def load_partition(manifest, split):
    if split not in {"train", "dev"}:
        raise ValueError("trainer cannot read test partition")
    root = Path(manifest).parent
    items = [EvidencePackage.model_validate(r) for r in read_jsonl(root / f"splits/{split}.jsonl")]
    gold = {g["item_id"]: g for g in read_jsonl(root / f"gold/{split}.jsonl")}
    if any(item.task_type != "relation" for item in items):
        raise ValueError("only relation training supported")
    return items, [gold[item.item_id]["label"] for item in items]


def train_baselines(manifest, output):
    manifest, output = Path(manifest), Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("model output must be a new directory")
    audit_release(manifest, allowed_splits=("train", "dev"))
    train, y_train = load_partition(manifest, "train")
    dev, y_dev = load_partition(manifest, "dev")
    if not dev:
        raise ValueError("dev partition required for selection")
    output.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    linear = TextClassifier("linear").fit(train, y_train)
    linear_seconds = time.perf_counter() - start
    start = time.perf_counter()
    encoder = TextClassifier("encoder").fit(train, y_train)
    encoder_seconds = time.perf_counter() - start
    a, b = linear.predict_proba(dev), encoder.predict_proba(dev)
    scores = []
    for alpha in (0,.25,.5,.75,1):
        predictions = [LABELS[i] for i in blend(a,b,alpha).argmax(axis=1)]
        scores.append((f1_score(y_dev, predictions, labels=list(LABELS), average="macro", zero_division=0), alpha))
    best_score, alpha = max(scores, key=lambda p: (p[0], -p[1]))
    ensemble = Ensemble(linear, encoder, alpha)
    result = {"selection_split": "dev", "alpha": alpha, "dev_macro_f1": best_score, "grid": scores,
              "fit_seconds": {"linear": linear_seconds, "encoder": encoder_seconds},
              "encoder_final_loss": float(encoder.classifier.loss_), "encoder_iterations": int(encoder.classifier.n_iter_),
              "curve_available": False, "optimizer": "lbfgs", "seed": 5002}
    dataset_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
    for name, model in (("linear", linear), ("encoder", encoder), ("ensemble", ensemble)):
        target = output / f"{name}.joblib"
        joblib.dump(model, target)
        checksum = hashlib.sha256(target.read_bytes()).hexdigest()
        metadata = {"name": name, "revision": f"{name}:{checksum[:16]}", "sha256": checksum, "file": target.name,
                    "dataset_hash": dataset_hash, "labels": LABELS, "seed": 5002, "training_split": "train", "selection_split": "dev",
                    "train_items": [i.item_id for i in train], "architecture": "character n-gram TF-IDF + logistic regression" if name == "linear" else "character n-gram binary features + trained tanh MLP(32,16)" if name == "encoder" else f"probability blend alpha={alpha}",
                    "pretrained": False, "post_training": False, "input_mode": "oracle", "evidence_selection": "all-candidate baseline"}
        model_manifest = output / f"{name}.json"
        model_manifest.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        result[name] = str(model_manifest)
    (output / "training-report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def load_candidate(manifest):
    """Load only locally trusted joblib artifacts; never accept untrusted uploads."""
    manifest = Path(manifest)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    root = manifest.parent.resolve()
    path = (root / data["file"]).resolve()
    if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != data["sha256"]:
        raise ValueError("model artifact hash mismatch")
    model = joblib.load(path)
    model.revision = data["revision"]
    return model
