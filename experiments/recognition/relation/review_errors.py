"""E14b: are the product chain's errors on the public test sets real errors?

    python -m experiments.recognition.relation.review_errors [--per-bucket 30 --control 40]

Needs the per-claim predictions of ``diagnose_public.py``. Per real source, a random
control sample and the three largest error buckets are re-judged by a label-blind DeepSeek
pass that sees the claim and the same candidate passages the model saw (temperature 0).
For each group: how often the reviewer agrees with the gold label, with the model's
prediction, or with neither. The control gives the reviewer's ordinary agreement with the
gold labels, so an error bucket where it sides with the model much more often points to
label noise rather than model error. Writes ``results/e14_review_errors.json`` and the
raw verdicts to ``runs/local/diagnostics/e14-review.jsonl``.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from experiments.recognition.common import ROOT, jsonl, save
from experiments.recognition.relation.transfer_public import SOURCES
from scripts.recognition import synth

REAL = ("contractnli", "vitaminc", "cfever")
SYSTEM = (
    "You check fact-verification labels. You get a CLAIM and numbered PASSAGES. Decide from "
    "the passages only: SUPPORTED (some passage states or directly implies the claim), "
    "CONTRADICTED (some passage states something incompatible with the claim), or "
    "INSUFFICIENT (the passages do neither). Contracts: a clause that obliges or permits what "
    "the claim says supports it. Answer in JSON: "
    '{"label": "SUPPORTED|CONTRADICTED|INSUFFICIENT", "passages": [numbers], '
    '"reason": "at most 25 words"}'
)


def prompt(row):
    mi = row["model_input"]
    lines = [f"CLAIM: {mi['claim']}", "PASSAGES:"]
    for i, c in enumerate(mi["candidate_evidence"], start=1):
        lines.append(f"[{i}] {c['text']}")
    return "\n".join(lines)


def judge(item):
    out = synth.chat(SYSTEM, prompt(item["row"]), temperature=0.0)
    label = str((out or {}).get("label", "")).upper()
    return {**{k: v for k, v in item.items() if k != "row"}, "review": label, "raw": out}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-bucket", type=int, default=30)
    parser.add_argument("--control", type=int, default=40)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    rng = random.Random(14)
    items = []
    for name in REAL:
        rows = [r for r in jsonl(SOURCES[name]) if r["split"] == "test"]
        preds = jsonl(ROOT / f"runs/local/diagnostics/e14-{name}.jsonl")
        for p in rng.sample(preds, args.control):
            items.append({"source": name, "group": "control", **p, "row": rows[p["index"]]})
        buckets = Counter(f"{p['gold']}->{p['pred']}:{p['bucket']}" for p in preds if p["bucket"])
        for key, _ in buckets.most_common(3):
            members = [p for p in preds if f"{p['gold']}->{p['pred']}:{p['bucket']}" == key]
            for p in rng.sample(members, min(args.per_bucket, len(members))):
                items.append({"source": name, "group": key, **p, "row": rows[p["index"]]})
    with ThreadPoolExecutor(args.workers) as pool:
        verdicts = list(pool.map(judge, items))
    out_dir = ROOT / "runs/local/diagnostics"
    with (out_dir / "e14-review.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for v in verdicts:
            fh.write(
                json.dumps({k: v[k] for k in v if k != "pair_probs"}, ensure_ascii=False) + "\n"
            )
    report = {"usage": dict(synth.USAGE), "groups": {}}
    for v in verdicts:
        key = f"{v['source']}|{v['group']}"
        g = report["groups"].setdefault(key, Counter())
        g["n"] += 1
        g["agrees_gold"] += v["review"] == v["gold"]
        g["agrees_pred"] += v["review"] == v["pred"] and v["pred"] != v["gold"]
        g["neither"] += v["review"] not in (v["gold"], v["pred"])
        g["failed"] += v["review"] not in ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT")
    report["groups"] = {k: dict(v) for k, v in report["groups"].items()}
    for key, g in report["groups"].items():
        print(key, g, flush=True)
    print("saved", save("e14_review_errors", report), report["usage"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
