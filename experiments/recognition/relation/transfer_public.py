"""E11: does the product's relation chain transfer to real public text?

    python -m experiments.recognition.relation.transfer_public
        --encoder runs/local/recognizers/c1-xlmr-cpu [--limit 300]

Every model here was fitted on relation-v3 only (pm_pilot materials, DeepSeek claims);
nothing is re-trained. Evaluated on the test split of each public release
(``docs/data/public-sources-v1.md``):

- ``contractnli`` / ``vitaminc`` / ``cfever`` (public-real-v1): real claims, real labels;
- ``public-synth`` (public-synth-v1): DeepSeek claims against real evidence units;
- ``relation-v3`` test as the in-domain reference.

Rows: lexical LR alone (the stack's base learner), C1, C1 + rule (alpha 0.4), stack, and
stack + rule (the product chain). Claim-level macro-F1 and accuracy by language, per-class
F1 and the predicted-label distribution. C1 pair probabilities are cached under
``runs/local/cache/c1-pairs/``.
"""

from __future__ import annotations

import argparse
import random
from collections import Counter

import numpy as np

from career_lab.models.v3.huggingface import aggregate_pairs
from career_lab.recognition.stack import RelationStack
from experiments.recognition import fusion
from experiments.recognition.common import DATA, RECOGNIZERS, ROOT, jsonl, per_class, save
from experiments.recognition.relation_eval import model, pair_probabilities

REL = ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT")
SOURCES = {
    "relation-v3": DATA / "relation-v3" / "relation.jsonl",
    "contractnli": DATA / "public-real-v1" / "relation-contractnli.jsonl",
    "vitaminc": DATA / "public-real-v1" / "relation-vitaminc.jsonl",
    "cfever": DATA / "public-real-v1" / "relation-cfever.jsonl",
    "public-synth": DATA / "public-synth-v1" / "relation.jsonl",
}


def encoder_pairs(encoder: str, name: str, rows: list[dict]) -> np.ndarray:
    revision = model(encoder).revision
    cache = ROOT / "runs/local/cache/c1-pairs" / f"{revision}-public-{name}-{len(rows)}.npy"
    if cache.is_file():
        return np.load(cache)
    probs = pair_probabilities(encoder, rows)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache, probs)
    return probs


def aggregate(rows: list[dict], pairs: np.ndarray) -> np.ndarray:
    out, offset = [], 0
    for r in rows:
        n = len(r["model_input"]["candidate_evidence"])
        out.append(np.asarray(aggregate_pairs(pairs[offset : offset + n], 0.5)[0], dtype=float))
        offset += n
    return np.vstack(out)


def stack_pairs(stack: RelationStack, rows: list[dict], encoder: np.ndarray):
    base_rows, combined, offset = [], [], 0
    for r in rows:
        mi = r["model_input"]
        cands = [
            (
                c["id"],
                c["text"],
                c["observed_at_seq"],
                c["valid_from_seq"],
                c.get("valid_until_seq"),
            )
            for c in mi["candidate_evidence"]
        ]
        n = len(cands)
        base = stack.base_probabilities(mi["claim"], mi["as_of"]["business_seq"], cands)
        base_rows.append(base)
        combined.append(stack.combine(base, encoder[offset : offset + n]))
        offset += n
    return np.vstack(base_rows), np.vstack(combined)


def report(rows: list[dict], probs: np.ndarray) -> dict:
    gold = [r["label"] for r in rows]
    out = {}
    for lang in ("zh", "en", "all"):
        idx = [i for i, r in enumerate(rows) if lang == "all" or r["language"] == lang]
        if not idx:
            continue
        macro, pred = fusion.macro([gold[i] for i in idx], probs[idx])
        out[lang] = {
            "n": len(idx),
            "macro_f1": macro,
            "accuracy": float(np.mean([p == gold[i] for p, i in zip(pred, idx, strict=True)])),
        }
    _, pred = fusion.macro(gold, probs)
    out["per_class"] = per_class(gold, pred, list(REL))
    out["predicted"] = dict(Counter(pred))
    return out


def sample(rows: list[dict], limit: int, seed: int = 0) -> list[dict]:
    if not limit or len(rows) <= limit:
        return rows
    by = {}
    for r in rows:
        by.setdefault((r["language"], r["label"]), []).append(r)
    share = limit / len(rows)
    rng = random.Random(seed)
    picked = []
    for key in sorted(by):
        group = by[key]
        picked += rng.sample(group, max(1, round(len(group) * share)))
    return picked


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--encoder", required=True)
    parser.add_argument("--limit", type=int, default=0, help="stratified test sample per source")
    parser.add_argument("--sources", nargs="*", default=list(SOURCES))
    args = parser.parse_args(argv)
    stack_dir = RECOGNIZERS / "relation-stack-v1"
    stack = RelationStack(stack_dir, "transfer")
    alpha = stack.alpha if stack.alpha is not None else 0.4
    results = {
        "encoder": args.encoder,
        "encoder_revision": model(args.encoder).revision,
        "stack_encoder_revision": stack.encoder_revision,
        "alpha": alpha,
        "limit": args.limit,
        "sources": {},
    }
    for name in args.sources:
        rows = sample([r for r in jsonl(SOURCES[name]) if r["split"] == "test"], args.limit)
        pairs = encoder_pairs(args.encoder, name, rows)
        c1 = aggregate(rows, pairs)
        rule, active = fusion.rule_probs(rows)
        base_pairs, stacked_pairs = stack_pairs(stack, rows, pairs)
        lr = aggregate(rows, base_pairs)
        stacked = aggregate(rows, stacked_pairs)
        results["sources"][name] = {
            "n": len(rows),
            "labels": dict(Counter(r["label"] for r in rows)),
            "rule_active": float(np.mean(active)),
            "lr": report(rows, lr),
            "c1": report(rows, c1),
            "c1_rule": report(rows, fusion.fuse(c1, rule, active, alpha)),
            "stack": report(rows, stacked),
            "stack_rule": report(rows, fusion.fuse(stacked, rule, active, alpha)),
        }
        row = results["sources"][name]
        print(
            name,
            row["n"],
            {
                k: round(row[k]["all"]["macro_f1"], 3)
                for k in ("lr", "c1", "c1_rule", "stack", "stack_rule")
            },
            flush=True,
        )
    path = save("e11_transfer_public" + (f"_n{args.limit}" if args.limit else ""), results)
    print("saved", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
