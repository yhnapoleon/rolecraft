"""Export fitted scikit-learn objects as a ``rolecraft-linear-return-v1`` return.

Run in the producer's own training environment (numpy, scikit-learn, Python standard
library and the sibling ``linear_text_v1.py``; no RoleCraft code). Typical use::

    import sys; sys.path.insert(0, "<this reference directory>")
    from export_sklearn_linear import export_linear_return
    export_linear_return(
        "linear-return",                 # new directory; never overwritten
        vectorizer=tfidf,                # fitted TfidfVectorizer on relation_text(...)
        classifier=relation_lr,          # multinomial LogisticRegression, 3 relation classes
        evidence_classifier=evidence_lr, # binary {0, 1} LogisticRegression on pair_text(...)
        evidence_vectorizer=None,        # None: evidence head reuses ``vectorizer``
        evidence_threshold=0.5,          # chosen on dev only
        dataset_manifest="dataset-manifest.json",
        dev_inputs="data/dev.inputs.jsonl",
        training_notes_file="training-notes.md",
    )

It writes ``linear/model.json``, ``linear/arrays.npz``, ``checkpoint-manifest.json``,
``predictions.dev.jsonl`` (v2 rows, predicted by *your* sklearn objects) and a
``training_notes_file`` template to fill in. RoleCraft reloads the return with its own
loader and compares labels, statuses and evidence sets exactly and probabilities within an
absolute difference of 1e-6 (``verify-return``). After the freeze, write the test rows with
the same objects, in the same format, outside the return directory::

    from export_sklearn_linear import write_predictions
    write_predictions("linear-return", vectorizer=tfidf, classifier=relation_lr,
                      evidence_classifier=evidence_lr, evidence_vectorizer=None,
                      inputs="data/test.inputs.jsonl", output="predictions.test.jsonl")

The script refuses objects the loader
cannot rebuild exactly (custom analyzers/tokenizers/preprocessors, non-default token
patterns, accent stripping, stop words, binary counts, non-float64 output, one-vs-rest
or non-logistic probabilities). Fill ``training_notes_file`` and the
``training_partitions``/``test_used_for_selection`` declarations truthfully.
"""

import hashlib
import io
import json
import sys
from pathlib import Path

import numpy as np
import sklearn
from linear_text_v1 import TEMPLATE, pair_text, relation_text
from sklearn.feature_extraction.text import TfidfVectorizer

ARTIFACT_PROTOCOL = "rolecraft-linear-return-v1"
LABELS = ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT")
LABEL_TIERS = ("G0", "G1", "G2", "G2v")
TIME_POLICY = "historical-evidence-time-v1"
TOLERANCE = 1e-9
# Transform-affecting TfidfVectorizer parameters the loader cannot express otherwise.
DEFAULTS = {
    "input": "content",
    "strip_accents": None,
    "preprocessor": None,
    "tokenizer": None,
    "stop_words": None,
    "token_pattern": r"(?u)\b\w\w+\b",
    "binary": False,
}


class ExportError(ValueError):
    """The fitted objects cannot be represented exactly as a linear return."""


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def json_bytes(value):
    return (canonical(value) + "\n").encode("utf-8")


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def model_revision(model_sha, arrays_sha, dataset_sha):
    """``linear-return:`` + sha256 of the canonical identity (see linear-return.md)."""
    identity = {
        "model_json_sha256": model_sha,
        "arrays_npz_sha256": arrays_sha,
        "dataset_manifest_sha256": dataset_sha,
    }
    return "linear-return:" + sha256(canonical(identity).encode("utf-8"))


def vectorizer_spec(vectorizer):
    if type(vectorizer) is not TfidfVectorizer:
        raise ExportError("vectorizer must be a fitted sklearn TfidfVectorizer")
    params = vectorizer.get_params()
    if not isinstance(params["analyzer"], str) or params["analyzer"] not in {
        "char",
        "char_wb",
        "word",
    }:
        raise ExportError("only the built-in char, char_wb and word analyzers are supported")
    for name, default in DEFAULTS.items():
        if params[name] != default:
            raise ExportError(f"TfidfVectorizer {name}={params[name]!r} is not supported")
    if np.dtype(params["dtype"]) != np.float64:
        raise ExportError("TfidfVectorizer dtype must be float64")
    if not hasattr(vectorizer, "vocabulary_"):
        raise ExportError("vectorizer is not fitted")
    spec = {
        "analyzer": params["analyzer"],
        "ngram_range": [int(n) for n in params["ngram_range"]],
        "lowercase": bool(params["lowercase"]),
        "sublinear_tf": bool(params["sublinear_tf"]),
        "norm": params["norm"],
        "smooth_idf": bool(params["smooth_idf"]),
        "use_idf": bool(params["use_idf"]),
        "vocabulary": {term: int(index) for term, index in vectorizer.vocabulary_.items()},
    }
    idf = np.asarray(vectorizer.idf_, dtype=np.float64) if spec["use_idf"] else None
    return spec, idf


def _softmax(scores):
    exp = np.exp(scores - scores.max(axis=1, keepdims=True))
    return exp / exp.sum(axis=1, keepdims=True)


def relation_arrays(classifier, features):
    classes = [str(c) for c in getattr(classifier, "classes_", [])]
    if sorted(classes) != sorted(LABELS):
        raise ExportError("classifier classes must be exactly the three relation labels")
    order = [classes.index(label) for label in LABELS]
    coef = np.asarray(classifier.coef_, dtype=np.float64)[order]
    intercept = np.asarray(classifier.intercept_, dtype=np.float64)[order]
    produced = np.asarray(classifier.predict_proba(features))[:, order]
    rebuilt = _softmax(np.asarray(features @ coef.T) + intercept)
    if np.abs(produced - rebuilt).max() > TOLERANCE:
        raise ExportError("classifier probabilities are not a multinomial softmax of linear scores")
    return coef, intercept, order


def evidence_arrays(classifier, features):
    classes = [int(c) for c in getattr(classifier, "classes_", [])]
    if classes != [0, 1] or np.asarray(classifier.coef_).shape[0] != 1:
        raise ExportError("evidence classifier must be binary with classes [0, 1]")
    coef = np.asarray(classifier.coef_, dtype=np.float64)[0]
    intercept = np.asarray(classifier.intercept_, dtype=np.float64).reshape(1)
    produced = np.asarray(classifier.predict_proba(features))[:, 1]
    rebuilt = 1 / (1 + np.exp(-(np.asarray(features @ coef).reshape(-1) + intercept[0])))
    if produced.size and np.abs(produced - rebuilt).max() > TOLERANCE:
        raise ExportError("evidence probabilities are not a logistic function of linear scores")
    return coef, intercept


def input_problem(model_input):
    """Inputs the RoleCraft loader abstains on; the reason equals its reason_code."""
    package = model_input["evidence"]
    if package["completeness"] != "complete":
        return "input_" + package["completeness"]
    if not package["claim"].strip():
        return "empty_claim"
    context = package["rule_context"].get("evidence_time_context")
    if (
        not isinstance(context, dict)
        or context.get("policy") != TIME_POLICY
        or context.get("status") != "known"
    ):
        return "temporal_scope_undetermined"
    if context.get("reference_seq") != package["as_of"]["business_seq"]:
        return "temporal_reference_mismatch"
    known = context.get("validity_known_ids")
    expected = {c["id"] for c in package["candidate_evidence"]}
    if (
        not isinstance(known, list)
        or any(not isinstance(value, str) for value in known)
        or len(known) != len(set(known))
        or set(known) != expected
    ):
        return "evidence_validity_undetermined"
    return None


def _read_jsonl(path):
    with open(path, encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def prediction_rows(
    records,
    *,
    revision,
    vectorizer,
    classifier,
    order,
    evidence_classifier,
    pair_vectorizer,
    evidence_threshold,
):
    """v2 rows for ``*.inputs.jsonl`` records, predicted by the producer's own objects."""
    rows = []
    unbacked = 0
    for record in records:
        model_input = record["model_input"]
        problem = input_problem(model_input)
        base = {
            "return_schema_version": 2,
            "record_id": record["record_id"],
            "input_hash": record["input_hash"],
            "model_revision": revision,
            "task_type": "relation",
        }
        if problem is not None:
            rows.append(
                base
                | {
                    "status": "abstained",
                    "probabilities": None,
                    "label": None,
                    "evidence_ids": [],
                    "evidence_bindings": [],
                    "reason": problem,
                }
            )
            continue
        features = vectorizer.transform([relation_text(model_input)])
        probabilities = [float(p) for p in np.asarray(classifier.predict_proba(features))[0][order]]
        label = LABELS[int(np.argmax(probabilities))]
        candidates = model_input["evidence"]["candidate_evidence"]
        selected = []
        if candidates:
            scores = np.asarray(
                evidence_classifier.predict_proba(
                    pair_vectorizer.transform([pair_text(model_input, c) for c in candidates])
                )
            )[:, 1]
            selected = [
                c
                for c, score in zip(candidates, scores, strict=True)
                if score >= evidence_threshold
            ]
        row = base | {
            "status": "ok",
            "probabilities": probabilities,
            "label": label,
            "evidence_ids": [c["id"] for c in selected],
            "evidence_bindings": [
                {"candidate_id": c["id"], "candidate_sha256": sha256(canonical(c).encode("utf-8"))}
                for c in selected
            ],
        }
        if not selected:
            row["reason"] = "no candidate reached the evidence threshold"
            if label != "INSUFFICIENT":
                unbacked += 1
        rows.append(row)
    return rows, unbacked


def warn_unbacked(unbacked):
    if unbacked:
        # verify-return refuses such rows where the record's evidence is evaluable
        # (return_evidence_selection_required); fusion selection never picks such a point.
        print(
            f"warning: {unbacked} SUPPORTED/CONTRADICTED rows have no selected evidence",
            file=sys.stderr,
        )


def notes_template(manifest, evidence_threshold):
    """The training notes the manifest names, pre-filled with what the export knows."""
    selection = str(manifest["test_used_for_selection"]).lower()
    return f"""# 训练说明（交付前逐项填写）

我方按 SHA-256 绑定本文件，并给复核的人看；不解析其中内容。

- model_revision: {manifest["model_revision"]}
- dataset_id: {manifest["dataset_id"]}
- dataset_manifest_sha256: {manifest["dataset_manifest_sha256"]}
- training_partitions: {json.dumps(manifest["training_partitions"])}（只用 train 拟合）
- selection_partition: dev；test_used_for_selection: {selection}
- evidence_threshold: {evidence_threshold}（在 dev 上选定）
- framework: scikit-learn {manifest["framework_version"]}，numpy {np.__version__}
- 训练代码 commit（40 位）：<填写>
- 超参数（C、class_weight、n-gram、随机种子等）：<填写>
- 训练数据（各 split 条数、标签等级、语言）：<填写>
- 证据头逐候选 0/1 目标的取法（一条记录有多个可接受证据集合时怎样取）：<填写>
- 其他需要复核者知道的事：<填写>
"""


def write_predictions(
    return_dir,
    *,
    vectorizer,
    classifier,
    evidence_classifier,
    evidence_vectorizer=None,
    inputs,
    output,
):
    """Rows for any partition (the test after the freeze) in the dev rows' format.

    The objects must be the exported ones (their arrays equal ``linear/arrays.npz``); the
    revision and threshold come from the return. ``output`` must lie outside the return
    directory: a file added there would not be in its manifest.
    """
    return_dir, output = Path(return_dir).resolve(), Path(output).resolve()
    if output.is_relative_to(return_dir):
        raise ExportError("write prediction rows outside the return directory")
    if output.exists():
        raise ExportError(f"{output} already exists; rows are never overwritten")
    manifest = json.loads((return_dir / "checkpoint-manifest.json").read_bytes())
    model = json.loads((return_dir / "linear/model.json").read_bytes())
    with np.load(return_dir / "linear/arrays.npz", allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    classes = [str(c) for c in getattr(classifier, "classes_", [])]
    if sorted(classes) != sorted(LABELS):
        raise ExportError("classifier classes must be exactly the three relation labels")
    order = [classes.index(label) for label in LABELS]
    exported = (
        np.array_equal(np.asarray(classifier.coef_, dtype=np.float64)[order], arrays["coef"])
        and np.array_equal(
            np.asarray(classifier.intercept_, dtype=np.float64)[order], arrays["intercept"]
        )
        and np.array_equal(
            np.asarray(evidence_classifier.coef_, dtype=np.float64)[0], arrays["evidence_coef"]
        )
        and vectorizer_spec(vectorizer)[0] == model["vectorizer"]
    )
    if not exported:
        raise ExportError("these objects are not the ones exported to " + str(return_dir))
    rows, unbacked = prediction_rows(
        _read_jsonl(inputs),
        revision=manifest["model_revision"],
        vectorizer=vectorizer,
        classifier=classifier,
        order=order,
        evidence_classifier=evidence_classifier,
        pair_vectorizer=vectorizer if evidence_vectorizer is None else evidence_vectorizer,
        evidence_threshold=model["evidence_head"]["threshold"],
    )
    warn_unbacked(unbacked)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(b"".join(json_bytes(row) for row in rows))
    return {
        "model_revision": manifest["model_revision"],
        "predictions": len(rows),
        "output": str(output),
    }


def export_linear_return(
    target,
    *,
    vectorizer,
    classifier,
    evidence_classifier,
    evidence_vectorizer=None,
    evidence_threshold=0.5,
    dataset_manifest,
    dev_inputs,
    training_notes_file,
    training=None,
    label_tiers=None,
    training_partitions=("train",),
    test_used_for_selection=False,
    load_and_predict_command=(
        "RoleCraft: career_lab.models.v3.registry_cli register/predict "
        "(RoleCraft loader; producer commands are not executed)"
    ),
):
    target = Path(target)
    if target.exists():
        raise ExportError(f"{target} already exists; exports are never overwritten")
    if not 0 <= evidence_threshold <= 1:
        raise ExportError("evidence_threshold must be within [0, 1]")
    dataset_raw = Path(dataset_manifest).read_bytes()
    dataset = json.loads(dataset_raw)
    dataset_sha = sha256(dataset_raw)
    if label_tiers is None:
        splits = dataset.get("splits", {})
        label_tiers = sorted(
            {
                tier
                for split in training_partitions
                for tier in splits.get(split, {}).get("label_tiers", {})
            }
        )
    if any(tier not in LABEL_TIERS for tier in label_tiers):
        raise ExportError("label tiers must come from G0, G1, G2, G2v")
    records = _read_jsonl(dev_inputs)
    usable = [r for r in records if input_problem(r["model_input"]) is None]
    if not usable:
        raise ExportError("dev inputs contain no record the loader would predict")
    spec, idf = vectorizer_spec(vectorizer)
    texts = [relation_text(r["model_input"]) for r in usable]
    coef, intercept, order = relation_arrays(classifier, vectorizer.transform(texts))
    pair_vectorizer = vectorizer if evidence_vectorizer is None else evidence_vectorizer
    pairs = [
        pair_text(r["model_input"], c)
        for r in usable
        for c in r["model_input"]["evidence"]["candidate_evidence"]
    ]
    pair_features = pair_vectorizer.transform(pairs)
    evidence_coef, evidence_intercept = evidence_arrays(evidence_classifier, pair_features)
    arrays = {
        "coef": coef,
        "intercept": intercept,
        "evidence_coef": evidence_coef,
        "evidence_intercept": evidence_intercept,
    }
    if idf is not None:
        arrays["idf"] = idf
    head_vectorizer = "shared"
    if evidence_vectorizer is not None:
        head_vectorizer, evidence_idf = vectorizer_spec(evidence_vectorizer)
        if evidence_idf is not None:
            arrays["evidence_idf"] = evidence_idf
    model = {
        "text_template": TEMPLATE,
        "vectorizer": spec,
        "classifier": {"kind": "multinomial_logistic", "label_order": list(LABELS)},
        "evidence_head": {
            "kind": "pair_logistic",
            "vectorizer": head_vectorizer,
            "threshold": float(evidence_threshold),
        },
    }
    if training is not None:
        model["training"] = training
    model_raw = json_bytes(model)
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    arrays_raw = buffer.getvalue()
    revision = model_revision(sha256(model_raw), sha256(arrays_raw), dataset_sha)

    rows, unbacked = prediction_rows(
        records,
        revision=revision,
        vectorizer=vectorizer,
        classifier=classifier,
        order=order,
        evidence_classifier=evidence_classifier,
        pair_vectorizer=pair_vectorizer,
        evidence_threshold=evidence_threshold,
    )
    warn_unbacked(unbacked)

    manifest = {
        "template": False,
        "completed": True,
        "return_protocol": "rolecraft-label-evidence-v2",
        "artifact_kind": "linear",
        "artifact_protocol": ARTIFACT_PROTOCOL,
        "model_revision": revision,
        "framework": "scikit-learn",
        "framework_version": sklearn.__version__,
        "task_type": "relation",
        "label_order": list(LABELS),
        "label_tiers": list(label_tiers),
        "dataset_id": dataset["dataset_id"],
        "dataset_manifest_sha256": dataset_sha,
        "training_partitions": list(training_partitions),
        "selection_partition": "dev",
        "test_used_for_selection": bool(test_used_for_selection),
        "evidence_selection_implemented": True,
        "evidence_selection_required": True,
        "checkpoint_files": {
            "linear/arrays.npz": sha256(arrays_raw),
            "linear/model.json": sha256(model_raw),
        },
        "load_and_predict_command": load_and_predict_command,
        "training_notes_file": training_notes_file,
        "predictions_file": "predictions.dev.jsonl",
    }
    manifest_raw = json_bytes(manifest)
    (target / "linear").mkdir(parents=True)
    (target / "linear/model.json").write_bytes(model_raw)
    (target / "linear/arrays.npz").write_bytes(arrays_raw)
    (target / "predictions.dev.jsonl").write_bytes(b"".join(json_bytes(row) for row in rows))
    notes = target / training_notes_file
    if not notes.resolve().is_relative_to(target.resolve()) or notes.resolve() == target.resolve():
        raise ExportError("training_notes_file must be a file inside the return directory")
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text(notes_template(manifest, evidence_threshold), encoding="utf-8")
    (target / "checkpoint-manifest.json").write_bytes(manifest_raw)
    return {
        "model_revision": revision,
        "manifest_sha256": sha256(manifest_raw),
        "predictions": len(rows),
    }


if __name__ == "__main__":
    print(__doc__)
