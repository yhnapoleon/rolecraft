"""E3 / C2: retrieval of evidence units, BM25 vs e5 dense vs reciprocal rank fusion.

    python -m experiments.recognition.retrieval

Two gold sets, per language: (a) in-domain assistant questions -> their source KB unit
(assistant-queries-v1, all splits; retrieval has no training), searched over every KB
unit; (b) relation-v3 claims (supported / contradicted) -> their gold material unit,
searched over every material unit (the Judge's setting). Recall@1/3/5 and MRR.
"""

from __future__ import annotations

import os

import numpy as np

from experiments.recognition.common import DATA, RECOGNIZERS, jsonl, save

os.environ.setdefault("CAREER_LAB_RECOGNIZERS", str(RECOGNIZERS))


def evaluate(queries, gold_ids, unit_ids, texts):
    from career_lab.recognition import retrieval

    out = {}
    for method in ("bm25", "dense", "rrf"):
        ranks = []
        for query, gold in zip(queries, gold_ids):
            hits, used, _ = retrieval.search(query, texts, k=len(texts), method=method)
            order = [unit_ids[h.index] for h in hits]
            ranks.append(order.index(gold) + 1 if gold in order else len(texts) + 1)
        ranks = np.array(ranks)
        out[method] = {
            "recall@1": float(np.mean(ranks <= 1)),
            "recall@3": float(np.mean(ranks <= 3)),
            "recall@5": float(np.mean(ranks <= 5)),
            "mrr": float(np.mean(1.0 / ranks)),
            "n": int(len(ranks)),
        }
    return out


def main() -> int:
    from scripts.recognition.synth import kb_units
    from scripts.recognition.synth_relation import load_units

    report = {"assistant": {}, "relation": {}}
    # Kept plus rejected: the release kept only questions whose unit was in the RRF
    # top-5, so evaluating on the kept set alone would favour RRF by construction.
    queries = jsonl(DATA / "assistant-queries-v1" / "queries.jsonl") + jsonl(
        DATA / "assistant-queries-v1" / "rejected.jsonl"
    )
    relation = jsonl(DATA / "relation-v3" / "relation.jsonl")
    for language in ("zh", "en"):
        units = kb_units(language)
        rows = [q for q in queries if q["language"] == language and q["kind"].startswith("in_")]
        for kind in ("in_direct", "in_paraphrase"):
            subset = [q for q in rows if q["kind"] == kind]
            report["assistant"][f"{language}/{kind}"] = evaluate(
                [q["query"] for q in subset],
                [q["answer_unit_id"] for q in subset],
                [u["unit_id"] for u in units],
                [u["text"] for u in units],
            )
        material_units, _ = load_units(language)
        claims = [
            r for r in relation
            if r["language"] == language and r["label"] in {"SUPPORTED", "CONTRADICTED"} and r["split"] == "test"
        ]
        report["relation"][language] = evaluate(
            [r["model_input"]["claim"] for r in claims],
            [r["gold_unit_ids"][0] for r in claims],
            [u["unit_id"] for u in material_units],
            [u["text"] for u in material_units],
        )
    save("e3_retrieval", report)
    for scope, rows in report.items():
        for key, methods in rows.items():
            print(scope, key, {m: (round(v["recall@5"], 3), round(v["mrr"], 3)) for m, v in methods.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
