"""E9: cross-domain generalisation, pm_pilot -> it_ticket_pilot (data edition).

    python -m experiments.recognition.cross_domain [--encoder runs/local/recognizers/c1-xlmr]

- C2 retrieval: Recall@5 / MRR of BM25, e5 and RRF for IT questions (no training).
- C4 scope: (a) the pm_pilot fit applied unchanged to IT questions (in-domain IT questions
  should look out of domain to it: the detector is domain-specific by design);
  (b) a fit on the IT knowledge-base units alone, no paraphrases (how far the method
  carries to a new pack with zero question data); AUROC and FPR at 95 % TPR.
- C1 relation (with ``--encoder``): the pm_pilot-trained model on IT claims, by language
  and phenomenon, next to its in-domain test numbers.
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np
from sklearn.covariance import LedoitWolf
from sklearn.metrics import roc_auc_score

from experiments.recognition.common import DATA, RECOGNIZERS, RESULTS, jsonl, save

os.environ.setdefault("CAREER_LAB_RECOGNIZERS", str(RECOGNIZERS))
IT = DATA / "it-ticket-v1"


def it_units(language: str) -> list[dict]:
    from scripts.recognition.synth_domain import KB, units_of

    materials = json.loads((IT / "materials.json").read_text(encoding="utf-8"))[language][
        "materials"
    ]
    units, _ = units_of(language, materials)
    return [u for u in units if u["material_id"] in KB]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--encoder", default=None)
    args = parser.parse_args(argv)
    from career_lab.recognition.embedder import Embedder
    from career_lab.recognition.scope import _arrays

    from experiments.recognition.retrieval import evaluate as retrieval_eval

    embedder = Embedder.get()
    queries = jsonl(IT / "queries.jsonl")
    report = {"retrieval": {}, "scope": {}, "relation": None}
    for language in ("zh", "en"):
        units = it_units(language)
        rows = [q for q in queries if q["language"] == language]
        inside = [q for q in rows if q["kind"].startswith("in_")]
        for kind in ("in_direct", "in_paraphrase"):
            sub = [q for q in inside if q["kind"] == kind]
            report["retrieval"][f"{language}/{kind}"] = retrieval_eval(
                [q["query"] for q in sub],
                [q["answer_unit_id"] for q in sub],
                [u["unit_id"] for u in units],
                [u["text"] for u in units],
            )
        vectors = embedder.encode([q["query"] for q in rows], "query")
        labels = np.array([0 if q["kind"].startswith("in_") else 1 for q in rows])

        def evaluate(mean, precision, vectors=vectors, labels=labels):
            delta = vectors - mean
            scores = np.sqrt(np.einsum("ij,jk,ik->i", delta, precision, delta).clip(0)) / np.sqrt(
                len(mean)
            )
            threshold = float(np.quantile(scores[labels == 0], 0.95))
            return {
                "auroc": float(roc_auc_score(labels, scores)),
                "fpr_at_tpr95": float(np.mean(scores[labels == 1] <= threshold)),
                "mean_in": float(scores[labels == 0].mean()),
                "mean_out": float(scores[labels == 1].mean()),
            }

        pm_mean, pm_precision = _arrays(f"pm_pilot/{language}/scope_off")
        fit = embedder.encode([u["text"] for u in units], "query")
        lw = LedoitWolf().fit(fit)
        report["scope"][language] = {
            "pm_fit_on_it": evaluate(pm_mean, pm_precision),
            "it_units_only_fit": evaluate(lw.location_, lw.precision_),
            "n_units": len(units),
            "n_in": int((labels == 0).sum()),
            "n_out": int((labels == 1).sum()),
        }
    if args.encoder:
        import experiments.recognition.relation_eval as rel

        rows = jsonl(IT / "relation.jsonl")
        out = {}
        for language in ("zh", "en"):
            part = [r for r in rows if r["language"] == language]
            probs = rel.pair_probabilities(args.encoder, part)
            from career_lab.models.v3.huggingface import aggregate_pairs

            offset, gold, pred, by_phen = 0, [], [], {}
            for r in part:
                n = len(r["model_input"]["candidate_evidence"])
                rp, _ = aggregate_pairs(probs[offset : offset + n], 0.5)
                offset += n
                label = rel.REL[int(np.argmax(rp))]
                gold.append(r["label"])
                pred.append(label)
                by_phen.setdefault(r["phenomenon"], []).append(label == r["label"])
            f1 = []
            for label in rel.REL:
                tp = sum(a == label and b == label for a, b in zip(gold, pred, strict=False))
                fp = sum(a != label and b == label for a, b in zip(gold, pred, strict=False))
                fn = sum(a == label and b != label for a, b in zip(gold, pred, strict=False))
                pr, rc = (tp / (tp + fp) if tp + fp else 0), (tp / (tp + fn) if tp + fn else 0)
                f1.append(2 * pr * rc / (pr + rc) if pr + rc else 0.0)
            out[language] = {
                "n": len(part),
                "macro_f1": float(np.mean(f1)),
                "accuracy": float(np.mean([a == b for a, b in zip(gold, pred, strict=False)])),
                "by_phenomenon": {k: float(np.mean(v)) for k, v in by_phen.items()},
            }
        in_domain = RESULTS / "e4_decision.json"
        if in_domain.exists():
            e4 = json.loads(in_domain.read_text(encoding="utf-8"))
            out["pm_pilot_test_macro_f1"] = {k: e4["test"][k]["macro_f1"] for k in ("zh", "en")}
        report["relation"] = out
    save("e9_cross_domain", report)
    print(
        json.dumps({k: report[k] for k in ("scope", "relation")}, ensure_ascii=False, indent=1)[
            :2500
        ]
    )
    for key, methods in report["retrieval"].items():
        print(key, {m: round(v["recall@5"], 3) for m, v in methods.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
