"""E5 / C4: out-of-scope question detection for the knowledge assistant.

    python -m experiments.recognition.scope [--register]

Fit (per language x scope setting): e5-small vectors of the in-domain knowledge-base
units plus the in-domain paraphrased questions (paraphrases-v1); Ledoit-Wolf shrunk
covariance; score = Mahalanobis distance / sqrt(d). ``scope_off`` = every KB domain is in
scope; ``scope_on`` = the learner narrowed scope and the policy domains are out (the
case the scenario teaches). Threshold = in-domain dev quantile at 95 % TPR.

Evaluation on assistant-queries-v1 (dev for thresholds, test for numbers): AUROC, FPR at
95 % TPR, accuracy at the threshold, a near-domain subset, and six baselines on the same
vectors (K-Means centroid distance, max cosine to in-domain units, Gaussian naive Bayes
likelihood, autoencoder reconstruction error, one-class SVM, isolation forest). A 2-D PCA
projection of units and queries is saved for the lab page. Drift: the mean and standard
deviation of cosine distance between units of the same KB material set the drift threshold.
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np
from sklearn.cluster import KMeans
from sklearn.covariance import LedoitWolf
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.metrics import roc_auc_score
from sklearn.neural_network import MLPRegressor
from sklearn.svm import OneClassSVM

from experiments.recognition.common import DATA, RECOGNIZERS, jsonl, register, save

os.environ.setdefault("CAREER_LAB_RECOGNIZERS", str(RECOGNIZERS))


def embed(texts, kind):
    from career_lab.recognition.embedder import Embedder

    embedder = Embedder.get()
    if embedder is None:
        raise SystemExit("embedder unavailable: run under .venv-encoder with retrieval-e5 present")
    return embedder.encode(list(texts), kind)


def kb(language):
    from scripts.recognition.synth import kb_units

    return kb_units(language)


def fpr_at_tpr(in_scores, out_scores, tpr=0.95):
    threshold = float(np.quantile(in_scores, tpr))
    return float(np.mean(np.asarray(out_scores) <= threshold)), threshold


def evaluate(scores_in, scores_out):
    y = [0] * len(scores_in) + [1] * len(scores_out)
    s = list(scores_in) + list(scores_out)
    fpr, _ = fpr_at_tpr(scores_in, scores_out)
    return {"auroc": float(roc_auc_score(y, s)), "fpr_at_tpr95": fpr}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--register", action="store_true")
    args = parser.parse_args(argv)
    queries = jsonl(DATA / "assistant-queries-v1" / "queries.jsonl")
    paraphrases = jsonl(DATA / "paraphrases-v1" / "paraphrases.jsonl")
    rng = np.random.default_rng(5)
    report = {"fits": {}, "baselines": {}, "pca": {}, "drift": {}}
    fits_json = {}
    target = RECOGNIZERS / "scope-mahalanobis-v1"
    target.mkdir(parents=True, exist_ok=True)
    for language in ("zh", "en"):
        units = kb(language)
        unit_vectors = embed([u["text"] for u in units], "passage")
        unit_as_query = embed([u["text"] for u in units], "query")
        para = [p for p in paraphrases if p["language"] == language]
        para_vectors = embed([p["query"] for p in para], "query")
        qs = [q for q in queries if q["language"] == language]
        # Stratified dev/test halves of the evaluation queries, by kind.
        for q in qs:
            q["half"] = "dev" if rng.random() < 0.5 else "test"
        q_vectors = embed([q["query"] for q in qs], "query")
        # Drift baseline: distances between units of the same material.
        same = [
            1.0 - float(unit_vectors[i] @ unit_vectors[j])
            for i in range(len(units))
            for j in range(i + 1, len(units))
            if units[i]["material_id"] == units[j]["material_id"]
        ]
        drift_mean, drift_std = float(np.mean(same)), float(np.std(same))
        report["drift"][language] = {"mean": drift_mean, "std": drift_std, "pairs": len(same)}
        for setting in ("scope_off", "scope_on"):

            def in_scope(domain, setting=setting):
                return setting == "scope_off" or not str(domain).startswith("policy")

            keep_u = [i for i, u in enumerate(units) if in_scope(u["domain"])]
            keep_p = [i for i, p in enumerate(para) if in_scope(p["domain"])]
            fit = np.vstack([unit_as_query[keep_u], para_vectors[keep_p]])
            lw = LedoitWolf().fit(fit)
            mean, precision = lw.location_, lw.precision_
            d = fit.shape[1]

            def score(vectors, mean=mean, precision=precision, d=d):
                delta = vectors - mean
                return np.sqrt(np.einsum("ij,jk,ik->i", delta, precision, delta).clip(0)) / np.sqrt(
                    d
                )

            labels = np.array(
                [
                    0 if (q["kind"].startswith("in_") and in_scope(q.get("domain"))) else 1
                    for q in qs
                ]
            )
            scores = score(q_vectors)
            dev = np.array([q["half"] == "dev" for q in qs])
            threshold = float(np.quantile(scores[dev & (labels == 0)], 0.95))
            test = ~dev
            result = evaluate(scores[test & (labels == 0)], scores[test & (labels == 1)])
            result["threshold"] = threshold
            result["accuracy_at_threshold"] = float(
                np.mean((scores[test] > threshold).astype(int) == labels[test])
            )
            near = np.array([q["kind"] == "out_near" for q in qs])
            if (test & near).any():
                result["near_domain"] = evaluate(
                    scores[test & (labels == 0)], scores[test & near & (labels == 1)]
                )
            result["n_fit"] = int(fit.shape[0])
            result["n_test_in"] = int((test & (labels == 0)).sum())
            result["n_test_out"] = int((test & (labels == 1)).sum())
            key = f"pm_pilot/{language}/{setting}"
            report["fits"][key] = result
            fits_json[key] = {
                "threshold": threshold,
                "dims": d,
                "n": int(fit.shape[0]),
                "drift_mean": drift_mean,
                "drift_std": drift_std,
            }
            np.savez(target / (key.replace("/", "__") + ".npz"), mean=mean, precision=precision)
            # Baselines on the same vectors (scope_off only, to keep the table small).
            if setting == "scope_off":
                base = {}
                cos = -(q_vectors @ unit_vectors[keep_u].T).max(1)
                base["max_cosine"] = cos
                km = KMeans(n_clusters=min(8, len(fit) // 4), n_init=10, random_state=0).fit(fit)
                base["kmeans_centroid"] = km.transform(q_vectors).min(1)
                mu, var = fit.mean(0), fit.var(0) + 1e-4
                base["gaussian_nb"] = (((q_vectors - mu) ** 2) / var + np.log(var)).sum(1)
                ae = MLPRegressor(hidden_layer_sizes=(32,), max_iter=3000, random_state=0).fit(
                    fit, fit
                )
                base["autoencoder"] = ((ae.predict(q_vectors) - q_vectors) ** 2).sum(1)
                base["one_class_svm"] = (
                    -OneClassSVM(nu=0.1, gamma="scale").fit(fit).score_samples(q_vectors)
                )
                base["isolation_forest"] = (
                    -IsolationForest(random_state=0).fit(fit).score_samples(q_vectors)
                )
                base["mahalanobis"] = scores
                report["baselines"][language] = {
                    name: evaluate(s[test & (labels == 0)], s[test & (labels == 1)])
                    for name, s in base.items()
                }
                pca = PCA(n_components=2, random_state=0).fit(np.vstack([fit, q_vectors]))
                report["pca"][language] = {
                    "units": pca.transform(unit_as_query[keep_u]).round(4).tolist(),
                    "queries": [
                        {"xy": xy, "kind": q["kind"], "score": float(s), "text": q["query"][:40]}
                        for xy, q, s in zip(
                            pca.transform(q_vectors).round(4).tolist(), qs, scores, strict=False
                        )
                    ],
                    "threshold": threshold,
                }
    with (target / "fits.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(fits_json, handle, indent=2)
    save("e5_scope", report)
    for key, r in report["fits"].items():
        print(
            f"{key:<26} AUROC {r['auroc']:.3f} FPR@95 {r['fpr_at_tpr95']:.3f} "
            f"acc {r['accuracy_at_threshold']:.3f} thr {r['threshold']:.2f} "
            f"near {r.get('near_domain', {}).get('auroc', float('nan')):.3f}"
        )
    for language, rows in report["baselines"].items():
        print(language, {k: round(v["auroc"], 3) for k, v in rows.items()})
    if args.register:
        print(register("scope-mahalanobis-v1", "scope"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
