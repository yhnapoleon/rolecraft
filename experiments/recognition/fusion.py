"""E10: late fusion of the learned relation model (C1) and the knowledge rule.

    python -m experiments.recognition.fusion --encoder runs/local/recognizers/c1-xlmr-cpu

Late (decision-level) fusion: for every claim, p = a * p_C1 + (1 - a) * p_rule when the
number-and-limit rule found comparable evidence, and p = p_C1 when it abstained
("no_comparable_evidence"). ``a`` is chosen on dev by macro-F1 and reported on test,
next to C1 alone and the rule alone, by language and by phenomenon. Early fusion (the
structured facts concatenated into the encoder input) would need retraining and is
reported as not run. The chosen ``a`` is written to ``<encoder>/fusion.json``, which the
product's ``recognition.relation.judge`` reads.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from experiments.recognition.common import DATA, jsonl, save

REL = ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT")
LOWER = ("supported", "contradicted", "insufficient")


def claim_probs(encoder, rows):
    from career_lab.models.v3.huggingface import aggregate_pairs
    from experiments.recognition.relation_eval import pair_probabilities

    pairs = pair_probabilities(encoder, rows)
    out, offset = [], 0
    for r in rows:
        n = len(r["model_input"]["candidate_evidence"])
        probs, _ = aggregate_pairs(pairs[offset : offset + n], 0.5)
        offset += n
        out.append(np.asarray(probs, dtype=float))
    return np.vstack(out)


def rule_probs(rows):
    from career_lab.recognition import relation, retrieval

    out, active = [], []
    for r in rows:
        mi = r["model_input"]
        cands = [(c["id"], c["text"]) for c in mi["candidate_evidence"]]
        lexical = retrieval.bm25_normalized(mi["claim"], [c[1] for c in cands])
        found = relation.rule_judge(mi["claim"], cands, list(lexical))
        out.append(np.array([found.probabilities[k] for k in LOWER]))
        active.append(found.reason != "no_comparable_evidence")
    return np.vstack(out), np.array(active)


def macro(gold, probs):
    pred = [REL[i] for i in probs.argmax(1)]
    f1 = []
    for label in REL:
        tp = sum(g == label and p == label for g, p in zip(gold, pred, strict=False))
        fp = sum(g != label and p == label for g, p in zip(gold, pred, strict=False))
        fn = sum(g == label and p != label for g, p in zip(gold, pred, strict=False))
        pr, rc = (tp / (tp + fp) if tp + fp else 0), (tp / (tp + fn) if tp + fn else 0)
        f1.append(2 * pr * rc / (pr + rc) if pr + rc else 0.0)
    return float(np.mean(f1)), pred


def fuse(c1, rule, active, alpha):
    fused = c1.copy()
    fused[active] = alpha * c1[active] + (1 - alpha) * rule[active]
    return fused


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--encoder", required=True)
    args = parser.parse_args(argv)
    rows = jsonl(DATA / "relation-v3" / "relation.jsonl")
    part = {s: [r for r in rows if r["split"] == s] for s in ("dev", "test")}
    c1 = {s: claim_probs(args.encoder, part[s]) for s in part}
    rule = {s: rule_probs(part[s]) for s in part}
    gold = {s: [r["label"] for r in part[s]] for s in part}
    grid = {
        round(float(a), 2): macro(gold["dev"], fuse(c1["dev"], *rule["dev"], a))[0]
        for a in np.linspace(0, 1, 21)
    }
    alpha = max(grid, key=grid.get)
    report = {
        "dev_grid": grid,
        "alpha": alpha,
        "rule_active_rate": {s: float(rule[s][1].mean()) for s in part},
    }
    test = {
        "c1": c1["test"],
        "rule": np.where(rule["test"][1][:, None], rule["test"][0], np.array([[0.2, 0.2, 0.6]])),
        "late_fusion": fuse(c1["test"], *rule["test"], alpha),
    }
    for name, probs in test.items():
        entry = {}
        for lang in ("zh", "en", "all"):
            idx = [i for i, r in enumerate(part["test"]) if lang == "all" or r["language"] == lang]
            entry[lang] = macro([gold["test"][i] for i in idx], probs[idx])[0]
        _, pred = macro(gold["test"], probs)
        by = {}
        for r, p in zip(part["test"], pred, strict=False):
            by.setdefault(r["phenomenon"], []).append(p == r["label"])
        entry["by_phenomenon"] = {k: float(np.mean(v)) for k, v in by.items()}
        report[name] = entry
    report["early_fusion"] = (
        "not run: needs the structured facts in the encoder input and retraining"
    )
    save("e10_fusion", report)
    with (Path(args.encoder) / "fusion.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {
                "alpha": alpha,
                "dev_macro_f1": grid[alpha],
                "policy": "late fusion with the number-and-limit rule when it is active",
            },
            handle,
        )
    for name in test:
        print(name, {k: round(v, 3) for k, v in report[name].items() if k != "by_phenomenon"})
    print("alpha", alpha, "dev", round(grid[alpha], 3))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
