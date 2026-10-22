"""E14a: where the relation chain fails on the public test sets (root-cause tables).

    python -m experiments.recognition.relation.diagnose_public
        --encoder runs/local/recognizers/c1-xlmr-cpu

Reads the E11 C1 pair cache (no encoder pass) and the registered stack, then per source:

- pair level: gold pair label against the C1 and stack argmax, split into gold-evidence
  pairs (SUPPORTS / CONTRADICTS) and the other candidates;
- claim level (product chain, stack + rule): every error put in one bucket by the
  ``pair_aggregate`` decision that produced it (missed gold pair, spurious contradiction or
  support from a non-evidence candidate, contradiction read as support, ...);
- truncation: share of pairs whose C1 input is longer than the encoder's ``max_tokens``,
  for gold-evidence pairs, and how much of the evidence is cut;
- cues: share of gold contradicting pairs that carry a number or negation cue
  (``stack.handcrafted``), the kind of contradiction relation-v3 is built from.

Writes ``results/e14_diagnose_public.json`` and the per-claim product predictions to
``runs/local/diagnostics/e14-<source>.jsonl`` for the error review.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter

import numpy as np

from career_lab.models.v3.huggingface import aggregate_pairs
from career_lab.recognition import stack as product
from career_lab.recognition.stack import RelationStack
from experiments.recognition import fusion
from experiments.recognition.common import RECOGNIZERS, ROOT, jsonl, save
from experiments.recognition.relation.transfer_public import SOURCES, encoder_pairs, stack_pairs
from experiments.recognition.relation_eval import bodies, model, query

PAIR = ("SUPPORTS", "CONTRADICTS", "UNRELATED")
REL = ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT")


def confusion(gold, pred):
    table = np.zeros((3, 3), dtype=int)
    for g, p in zip(gold, pred, strict=True):
        table[g, p] += 1
    recall = (table.diagonal() / np.maximum(table.sum(1), 1)).round(3).tolist()
    return {"table": table.tolist(), "recall": dict(zip(PAIR, recall, strict=True))}


def bucket(row, pairs, final):
    """Why the product chain gave ``final`` for this claim (gold != final)."""
    labels = [row["pair_labels"][c["id"]] for c in row["model_input"]["candidate_evidence"]]
    gold = row["label"]
    s, c, u = pairs[:, 0], pairs[:, 1], pairs[:, 2]
    evidence = np.array([lab != "UNRELATED" for lab in labels])
    if final == "CONTRADICTED":
        hit = c >= 0.5
        if (hit & evidence).any() and gold == "SUPPORTED":
            return "support_read_as_contradiction"
        if hit.any():
            return "spurious_contradiction_non_evidence"
        return "rule_or_fusion"
    if final == "SUPPORTED":
        hit = (s >= 0.5) & (s > u)
        if (hit & evidence).any() and gold == "CONTRADICTED":
            return "contradiction_read_as_support"
        if hit.any():
            return "spurious_support_non_evidence"
        return "rule_or_fusion"
    # final INSUFFICIENT: the gold evidence pair was not recognised
    return "missed_gold_pair"


def truncation(rows, tokenizer, limit):
    over, over_gold, cut_share = [], [], []
    for r in rows:
        q = query(r)
        q_len = len(tokenizer(q, add_special_tokens=False)["input_ids"])
        for cand, body in zip(r["model_input"]["candidate_evidence"], bodies(r), strict=True):
            b_len = len(tokenizer(body, add_special_tokens=False)["input_ids"])
            total = q_len + b_len + 4
            gold = r["pair_labels"][cand["id"]] != "UNRELATED"
            over.append(total > limit)
            if gold:
                over_gold.append(total > limit)
                cut_share.append(max(0, total - limit) / max(b_len, 1))
    return {
        "pairs_over_limit": float(np.mean(over)),
        "gold_pairs_over_limit": float(np.mean(over_gold)) if over_gold else None,
        "gold_evidence_cut_share_mean": float(np.mean(cut_share)) if cut_share else None,
    }


def cues(rows):
    out = Counter()
    for r in rows:
        if r["label"] != "CONTRADICTED":
            continue
        mi = r["model_input"]
        for cand in mi["candidate_evidence"]:
            if r["pair_labels"][cand["id"]] != "CONTRADICTS":
                continue
            h = product.handcrafted(mi["claim"], cand["text"], mi["as_of"]["business_seq"])
            out["pairs"] += 1
            out["number_cue"] += bool(h[0] or h[1] or h[2])
            out["negation_cue"] += bool(h[3])
            out["any_cue"] += bool(h[0] or h[1] or h[2] or h[3])
    n = max(out["pairs"], 1)
    return {
        "pairs": out["pairs"],
        **{k: out[k] / n for k in ("number_cue", "negation_cue", "any_cue")},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--encoder", required=True)
    args = parser.parse_args(argv)
    enc = model(args.encoder)
    stack = RelationStack(RECOGNIZERS / "relation-stack-v1", "diagnose")
    alpha = stack.alpha if stack.alpha is not None else 0.4
    out_dir = ROOT / "runs/local/diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"encoder_max_tokens": enc.max_tokens, "alpha": alpha, "sources": {}}
    for name in SOURCES:
        rows = [r for r in jsonl(SOURCES[name]) if r["split"] == "test"]
        c1 = encoder_pairs(args.encoder, name, rows)
        _, stacked = stack_pairs(stack, rows, c1)
        rule, active = fusion.rule_probs(rows)
        gold_pairs, owner = [], []
        for i, r in enumerate(rows):
            for cand in r["model_input"]["candidate_evidence"]:
                gold_pairs.append(PAIR.index(r["pair_labels"][cand["id"]]))
                owner.append(i)
        gold_pairs, owner = np.array(gold_pairs), np.array(owner)
        ev = gold_pairs != 2
        entry = {
            "claims": len(rows),
            "pairs": int(len(gold_pairs)),
            "pair_c1_evidence": confusion(gold_pairs[ev], c1[ev].argmax(1)),
            "pair_c1_other": confusion(gold_pairs[~ev], c1[~ev].argmax(1)),
            "pair_stack_evidence": confusion(gold_pairs[ev], stacked[ev].argmax(1)),
            "pair_stack_other": confusion(gold_pairs[~ev], stacked[~ev].argmax(1)),
        }
        buckets, lines = Counter(), []
        for i, r in enumerate(rows):
            p = stacked[owner == i]
            claim = np.asarray(aggregate_pairs(p, 0.5)[0], dtype=float)
            fused = fusion.fuse(claim[None], rule[i : i + 1], active[i : i + 1], alpha)[0]
            final = REL[int(np.argmax(fused))]
            why = None if final == r["label"] else bucket(r, p, final)
            if why:
                buckets[f"{r['label']}->{final}:{why}"] += 1
            lines.append(
                {
                    "record_id": r.get("record_id") or r.get("item_id") or str(i),
                    "index": i,
                    "language": r["language"],
                    "gold": r["label"],
                    "pred": final,
                    "bucket": why,
                    "rule_active": bool(active[i]),
                    "pair_probs": p.round(3).tolist(),
                }
            )
        wrong = sum(buckets.values())
        entry["claim_errors"] = wrong
        entry["claim_error_buckets"] = {k: v for k, v in buckets.most_common()}
        entry["truncation"] = truncation(rows, enc.tokenizer, enc.max_tokens)
        entry["contradiction_cues"] = cues(rows)
        report["sources"][name] = entry
        with (out_dir / f"e14-{name}.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
            for line in lines:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        top = list(entry["claim_error_buckets"].items())[:4]
        print(
            name,
            f"err {wrong}/{len(rows)}",
            "evid-recall",
            entry["pair_c1_evidence"]["recall"],
            "trunc",
            round(entry["truncation"]["gold_pairs_over_limit"] or 0, 3),
            "cue",
            round(entry["contradiction_cues"]["any_cue"], 3),
            top,
            flush=True,
        )
    print("saved", save("e14_diagnose_public", report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
