"""E4 / C6 (and E1's C1 row): evaluate a trained C1 export on relation-v3, on CPU.

    python -m experiments.recognition.relation_eval --encoder runs/local/recognizers/c1-xlmr

Loads the export with ``recognition.encoder_relation.EncoderRelation`` (the product's own
loader), predicts every dev/test claim, and reports:

- C1 claim-level metrics by language (macro-F1, per-class, evidence F1, joint, confusion);
- calibration: pair-level ECE with temperature 1 and with the fitted temperature;
- C6: the error-reject curve (decide the lowest-expected-cost claims first), the rate of
  wrong deductions (deciding CONTRADICTED when it is not) at fixed reject rates, the
  share deferred under the cost matrix, and the lift curve used by the review queue.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

from experiments.recognition.common import DATA, jsonl, save

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
REL = ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT")
PAIR = ("SUPPORTS", "CONTRADICTS", "UNRELATED")
_CACHE: dict = {}


def model(path):
    if path not in _CACHE:
        from career_lab.recognition.encoder_relation import EncoderRelation

        _CACHE[path] = EncoderRelation(path)
    return _CACHE[path]


def bodies(row):
    out = []
    for c in row["model_input"]["candidate_evidence"]:
        until = "open" if c.get("valid_until_seq") is None else c["valid_until_seq"]
        out.append(
            f"{c['text']}\nobserved {c['observed_at_seq']}; valid from "
            f"{c['valid_from_seq']}; valid until {until}"
        )
    return out


def query(row):
    mi = row["model_input"]
    return (
        f"{mi['purpose']}\n{mi['claim']}\nreference time {mi['as_of']['business_seq']}; "
        "temporal scope known"
    )


def pair_probabilities(path, rows, temperature=None):
    m = model(path)
    saved = m.temperature
    if temperature is not None:
        m.temperature = temperature
    try:
        return np.vstack([m.pair_probabilities(query(r), bodies(r)) for r in rows])
    finally:
        m.temperature = saved


def ece(probs, labels, bins=10):
    conf, pred = probs.max(1), probs.argmax(1)
    total = 0.0
    for lo in np.linspace(0, 1, bins, endpoint=False):
        m = (conf > lo) & (conf <= lo + 1 / bins)
        if m.any():
            total += m.mean() * abs((pred[m] == labels[m]).mean() - conf[m].mean())
    return float(total)


def main(argv=None) -> int:
    from career_lab.models.v3.huggingface import aggregate_pairs
    from career_lab.recognition.decision import costs

    parser = argparse.ArgumentParser()
    parser.add_argument("--encoder", required=True)
    args = parser.parse_args(argv)
    rows = jsonl(DATA / "relation-v3" / "relation.jsonl")
    report = {"encoder": args.encoder}
    table = costs()
    for split in ("dev", "test"):
        part = [r for r in rows if r["split"] == split]
        probs = pair_probabilities(args.encoder, part)
        raw = pair_probabilities(args.encoder, part, temperature=1.0)
        labels = np.array(
            [
                PAIR.index(r["pair_labels"][c["id"]])
                for r in part
                for c in r["model_input"]["candidate_evidence"]
            ]
        )
        offset = 0
        claims = []
        for r in part:
            n = len(r["model_input"]["candidate_evidence"])
            rel, scores = aggregate_pairs(probs[offset : offset + n], 0.5)
            offset += n
            label = REL[int(np.argmax(rel))]
            p = {k.lower(): float(v) for k, v in zip(REL, rel, strict=False)}
            expected = {d: sum(p[y] * table["decide"][d][y] for y in p) for d in table["decide"]}
            best = min(expected, key=expected.get)
            ids = [c["id"] for c in r["model_input"]["candidate_evidence"]]
            chosen = (
                {i for i, s in zip(ids, scores, strict=False) if s >= 0.5}
                if label != "INSUFFICIENT"
                else set()
            )
            claims.append(
                {
                    "language": r["language"],
                    "gold": r["label"],
                    "pred": label,
                    "joint": label == r["label"] and chosen == set(r["evidence_ids"]),
                    "evidence_exact": chosen == set(r["evidence_ids"]),
                    "cost": expected[best],
                    "defer": expected[best] >= table["defer"],
                    "phenomenon": r["phenomenon"],
                }
            )
        entry = {"ece_t1": ece(raw, labels), "ece_fitted": ece(probs, labels)}
        for lang in ("zh", "en", "all"):
            sub = [c for c in claims if lang == "all" or c["language"] == lang]
            f1 = {}
            for label in REL:
                tp = sum(c["gold"] == label and c["pred"] == label for c in sub)
                fp = sum(c["gold"] != label and c["pred"] == label for c in sub)
                fn = sum(c["gold"] == label and c["pred"] != label for c in sub)
                pr, rc = (tp / (tp + fp) if tp + fp else 0), (tp / (tp + fn) if tp + fn else 0)
                f1[label] = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
            entry[lang] = {
                "n": len(sub),
                "macro_f1": sum(f1.values()) / 3,
                "per_class_f1": f1,
                "accuracy": float(np.mean([c["gold"] == c["pred"] for c in sub])),
                "joint": float(np.mean([c["joint"] for c in sub])),
                "evidence_exact": float(np.mean([c["evidence_exact"] for c in sub])),
                "confusion": [
                    [sum(c["gold"] == x and c["pred"] == y for c in sub) for y in REL] for x in REL
                ],
            }
        # Error-reject curve: keep the lowest-cost claims, defer the rest.
        order = sorted(claims, key=lambda c: c["cost"])
        curve = []
        for reject in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5):
            kept = order[: max(1, int(len(order) * (1 - reject)))]
            wrong_deduction = sum(
                c["pred"] == "CONTRADICTED" and c["gold"] != "CONTRADICTED" for c in kept
            )
            curve.append(
                {
                    "reject_rate": reject,
                    "error_rate": float(np.mean([c["gold"] != c["pred"] for c in kept])),
                    "wrong_deduction_rate": wrong_deduction / len(kept),
                }
            )
        errors = np.array([c["gold"] != c["pred"] for c in claims])
        by_cost = np.argsort([-c["cost"] for c in claims])
        lift = [
            {
                "top_fraction": f,
                "error_coverage": float(
                    errors[by_cost[: max(1, int(len(claims) * f))]].sum() / max(1, errors.sum())
                ),
            }
            for f in (0.1, 0.2, 0.3, 0.5)
        ]
        by_phenomenon = {}
        for c in claims:
            by_phenomenon.setdefault(c["phenomenon"], []).append(c["gold"] == c["pred"])
        entry.update(
            error_reject=curve,
            lift=lift,
            defer_rate=float(np.mean([c["defer"] for c in claims])),
            accuracy_by_phenomenon={k: float(np.mean(v)) for k, v in by_phenomenon.items()},
        )
        report[split] = entry
        print(
            split,
            json.dumps({k: entry[k]["macro_f1"] for k in ("zh", "en", "all")}),
            "ECE",
            round(entry["ece_t1"], 3),
            "->",
            round(entry["ece_fitted"], 3),
            flush=True,
        )
    save("e4_decision", report)
    lift_dev = next(x for x in report["dev"]["lift"] if x["top_fraction"] == 0.2)
    with (Path(args.encoder) / "lift.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump({"top_fraction": 0.2, "error_coverage": lift_dev["error_coverage"]}, handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
