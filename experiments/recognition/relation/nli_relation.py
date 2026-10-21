"""E15: a multilingual NLI cross-encoder as the relation pair classifier (zero-shot and mixed).

    python -m experiments.recognition.relation.nli_relation predict --model <dir> [--tag zs]
    python -m experiments.recognition.relation.nli_relation train --base <dir> --out <dir>

E14 traced the E11 failure to the pair classifier: C1 recognises 7 % of ContractNLI's gold
clauses and 8 % of VitaminC's contradicting revisions, and the reviewed errors are real
(``results/e14_*.json``). Here the pair classifier starts from
``MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`` (MIT; XNLI + multilingual NLI
in 26 languages including Chinese) instead of a raw XLM-R:

- ``predict``: premise = candidate text, hypothesis = claim; entailment / contradiction /
  neutral read as SUPPORTS / CONTRADICTS / UNRELATED; the product's ``pair_aggregate`` rule
  (threshold 0.5) gives the claim label, alone and with the number-and-limit rule at the
  product's alpha 0.4. All five E11 test sets in full; pair probabilities are cached under
  ``runs/local/cache/nli-pairs/``. ``--time`` appends the candidate's validity window and
  the reference time to the premise (what the fine-tuned model is trained with).
- ``train``: fine-tunes the same model on relation-v3 train plus a per-source sample of the
  ContractNLI, VitaminC and CFEVER train claims (every candidate of a sampled claim), one
  epoch, embeddings and the lower layers frozen, length-bucketed batches.

- ``reply``: C10 on the E13 samples (RAGTruth test, 300 stratified replies; synthetic replies
  with leaks): C2 top-3 units per sentence, judged per unit and aggregated (``unit``) or as
  one chunk of the three units in source order (``chunk``, the MiniCheck reading), for
  the visible sources and, for leaks, the private facts.

Results: ``results/e15_nli_<tag>.json``, ``results/e15_reply_<tag>.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from collections import Counter
from pathlib import Path

import numpy as np

from career_lab.models.v3.huggingface import aggregate_pairs
from experiments.recognition import fusion
from experiments.recognition.common import ROOT, jsonl, per_class, save
from experiments.recognition.relation.transfer_public import SOURCES, sample

os.environ.setdefault("USE_TF", "0")
PAIR = ("SUPPORTS", "CONTRADICTS", "UNRELATED")
REL = ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT")
NLI_INDEX = {"SUPPORTS": 0, "UNRELATED": 1, "CONTRADICTS": 2}  # entailment, neutral, contra
PRODUCT_ALPHA = 0.4
TRAIN_CLAIMS = {"contractnli": 1500, "vitaminc": 3000, "cfever": 1500}


def premise(row, cand, with_time):
    if not with_time:
        return cand["text"]
    until = "open" if cand.get("valid_until_seq") is None else cand["valid_until_seq"]
    return (
        f"{cand['text']}\n[valid from {cand['valid_from_seq']} until {until}; "
        f"checked at {row['model_input']['as_of']['business_seq']}]"
    )


def pairs_of(rows, with_time):
    out = []
    for r in rows:
        claim = r["model_input"]["claim"]
        for c in r["model_input"]["candidate_evidence"]:
            out.append((premise(r, c, with_time), claim, NLI_INDEX[r["pair_labels"][c["id"]]]))
    return out


class Scorer:
    def __init__(self, path, max_length=256, threads=16):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        torch.set_num_threads(threads)
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForSequenceClassification.from_pretrained(path).eval()
        self.max_length = max_length

    def probs(self, pairs, batch=32, log_every=0):
        """(S, C, U) probabilities, length-sorted batches."""
        order = sorted(range(len(pairs)), key=lambda i: len(pairs[i][0]) + len(pairs[i][1]))
        out = np.zeros((len(pairs), 3), dtype=np.float32)
        with self.torch.no_grad():
            for b, start in enumerate(range(0, len(order), batch)):
                idx = order[start : start + batch]
                x = self.tok(
                    [pairs[i][0] for i in idx],
                    [pairs[i][1] for i in idx],
                    return_tensors="pt",
                    padding=True,
                    truncation="only_first",
                    max_length=self.max_length,
                )
                p = self.torch.softmax(self.model(**x).logits, -1).numpy()
                out[idx] = p[:, [0, 2, 1]]
                if log_every and b % log_every == 0:
                    print(f"  {start}/{len(order)}", flush=True)
        return out


def claim_report(rows, pair_probs):
    claims, offset = [], 0
    for r in rows:
        n = len(r["model_input"]["candidate_evidence"])
        claims.append(np.asarray(aggregate_pairs(pair_probs[offset : offset + n], 0.5)[0]))
        offset += n
    claims = np.vstack(claims)
    rule, active = fusion.rule_probs(rows)
    gold = [r["label"] for r in rows]
    out = {}
    for name, probs in (
        ("nli", claims),
        ("nli_rule", fusion.fuse(claims, rule, active, PRODUCT_ALPHA)),
    ):
        entry = {}
        for lang in ("zh", "en", "all"):
            idx = [i for i, r in enumerate(rows) if lang == "all" or r["language"] == lang]
            if idx:
                macro, _ = fusion.macro([gold[i] for i in idx], probs[idx])
                entry[lang] = {"n": len(idx), "macro_f1": macro}
        _, pred = fusion.macro(gold, probs)
        entry["per_class"] = per_class(gold, pred, list(REL))
        entry["predicted"] = dict(Counter(pred))
        out[name] = entry
    return out


def run_predict(args):
    scorer = Scorer(args.model, args.max_length)
    rev = args.tag
    cache_dir = ROOT / "runs/local/cache/nli-pairs"
    cache_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "model": args.model,
        "time_suffix": args.time,
        "max_length": args.max_length,
        "sources": {},
    }
    for name in args.sources:
        rows = sample([r for r in jsonl(SOURCES[name]) if r["split"] == "test"], args.limit)
        pairs = pairs_of(rows, args.time)
        cache = cache_dir / f"{rev}-{name}-{len(rows)}.npy"
        if cache.is_file():
            probs = np.load(cache)
        else:
            t = time.time()
            probs = scorer.probs(pairs)
            np.save(cache, probs)
            print(name, "pairs", len(pairs), f"{time.time() - t:.0f}s", flush=True)
        gold = np.array([p[2] for p in pairs])
        ev = gold != 1
        recall = {
            "SUPPORTS": float(np.mean(probs[gold == 0].argmax(1) == 0))
            if (gold == 0).any()
            else None,
            "CONTRADICTS": float(np.mean(probs[gold == 2].argmax(1) == 1))
            if (gold == 2).any()
            else None,
            "UNRELATED": float(np.mean(probs[gold == 1].argmax(1) == 2)) if (~ev).any() else None,
        }
        report["sources"][name] = {
            "claims": len(rows),
            "pair_recall": recall,
            **claim_report(rows, probs),
        }
        e = report["sources"][name]
        print(
            name,
            "nli",
            round(e["nli"]["all"]["macro_f1"], 3),
            "nli+rule",
            round(e["nli_rule"]["all"]["macro_f1"], 3),
            {k: (round(v, 3) if v is not None else None) for k, v in recall.items()},
            flush=True,
        )
    print("saved", save(f"e15_nli_{args.tag}", report))
    return 0


def run_train(args):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    torch.set_num_threads(args.threads)
    torch.manual_seed(15)
    rng = random.Random(15)
    rows = [r for r in jsonl(SOURCES["relation-v3"]) if r["split"] == "train"]
    for name, n in TRAIN_CLAIMS.items():
        train = [r for r in jsonl(SOURCES[name]) if r["split"] == "train"]
        rows += sample(train, n, seed=15)
    pairs = pairs_of(rows, True)
    print(
        "train claims",
        len(rows),
        "pairs",
        len(pairs),
        dict(Counter(p[2] for p in pairs)),
        flush=True,
    )
    tok = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForSequenceClassification.from_pretrained(args.base)
    for p in model.deberta.embeddings.parameters():
        p.requires_grad = False
    for layer in model.deberta.encoder.layer[: args.freeze_layers]:
        for p in layer.parameters():
            p.requires_grad = False
    params = [p for p in model.parameters() if p.requires_grad]
    optim = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.01)
    # Length buckets of ``batch`` pairs, shuffled bucket order: little padding, mixed sources.
    order = sorted(range(len(pairs)), key=lambda i: len(pairs[i][0]) + len(pairs[i][1]))
    batches = [order[i : i + args.batch] for i in range(0, len(order), args.batch)]
    if args.smoke:
        batches = random.Random(0).sample(batches, args.smoke)
    steps = len(batches) * args.epochs
    sched = torch.optim.lr_scheduler.LambdaLR(
        optim, lambda s: min(1.0, (s + 1) / (0.06 * steps)) * max(0.0, (steps - s) / steps)
    )
    model.train()
    step, t0, running = 0, time.time(), 0.0
    for _epoch in range(args.epochs):
        rng.shuffle(batches)
        for idx in batches:
            x = tok(
                [pairs[i][0] for i in idx],
                [pairs[i][1] for i in idx],
                return_tensors="pt",
                padding=True,
                truncation="only_first",
                max_length=args.max_length,
            )
            y = torch.tensor([pairs[i][2] for i in idx])
            loss = torch.nn.functional.cross_entropy(model(**x).logits, y)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            optim.step()
            sched.step()
            optim.zero_grad()
            step += 1
            value = float(loss.detach())
            running = 0.98 * running + 0.02 * value if step > 1 else value
            if step % 50 == 0 or step == steps:
                rate = step / (time.time() - t0)
                eta = (steps - step) / max(rate, 1e-9) / 60
                print(f"step {step}/{steps} loss {running:.3f} eta {eta:.0f} min", flush=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    model.eval()
    model.save_pretrained(out, safe_serialization=True)
    tok.save_pretrained(out)
    meta = {
        "base": args.base,
        "train_claims": len(rows),
        "train_pairs": len(pairs),
        "sources": {
            "relation-v3": "all train",
            **{k: f"{v} train claims" for k, v in TRAIN_CLAIMS.items()},
        },
        "epochs": args.epochs,
        "freeze_layers": args.freeze_layers,
        "lr": args.lr,
        "batch": args.batch,
        "max_length": args.max_length,
        "premise": "candidate text + validity window and reference time",
        "minutes": round((time.time() - t0) / 60, 1),
    }
    (out / "e15_train.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print("saved", out, flush=True)
    return 0


def run_reply(args):
    """C10 with the NLI pair classifier: C2 top-3 per sentence, per unit or as one chunk."""
    from experiments.recognition import public_eval as pe  # sets the recognizer env first

    from career_lab.recognition import retrieval

    scorer = Scorer(args.model, args.max_length)
    suffix = "\n[valid from 0 until open; checked at 0]" if args.time else ""
    real = [r for r in jsonl(pe.DATA / "public-reply-v1" / "replies.jsonl") if r["split"] == "test"]
    real = pe.stratified(real, args.limit, lambda r: (r["task_type"], r["has_problem"]))
    sources = {s["source_id"]: s for s in jsonl(pe.DATA / "public-reply-v1" / "sources.jsonl")}
    synth = [
        r
        for r in jsonl(pe.DATA / "public-reply-synth-v1" / "replies.jsonl")
        if r["split"] == "test"
    ]

    def inputs(row):
        if "visible" in row:
            return [u["text"] for u in row["visible"]], [u["text"] for u in row.get("private", [])]
        return [u["text"] for u in sources[row["source_id"]]["units"]], []

    def requests(sentence, texts):
        hits, _, _ = retrieval.search(sentence, texts, k=3, method="rrf")
        top = sorted(h.index for h in hits)
        unit = [(texts[i] + suffix, sentence, 1) for i in top]
        chunk = [(" ".join(texts[i] for i in top) + suffix, sentence, 1)] if top else []
        return {"unit": unit, "chunk": chunk}

    def decide(probs):
        if not len(probs):
            return np.array([0.125, 0.125, 0.75])
        return np.asarray(aggregate_pairs(probs, 0.5)[0])

    report = {"model": args.model, "time_suffix": args.time, "limit": args.limit, "datasets": {}}
    for name, rows in (("ragtruth", real), ("synth", synth)):
        plan, pairs = [], []
        for row in rows:
            visible, private = inputs(row)
            for s in row["sentences"]:
                if sum(not c.isspace() for c in s["text"]) < 6:
                    continue
                entry = {"row": row, "gold": s["label"], "spans": {}}
                for side, texts in (("seen", visible), ("hidden", private)):
                    if not texts:
                        continue
                    for mode, req in requests(s["text"], texts).items():
                        entry["spans"][(side, mode)] = (len(pairs), len(pairs) + len(req))
                        pairs += req
                plan.append(entry)
        t = time.time()
        probs = scorer.probs(pairs)
        print(name, "pairs", len(pairs), f"{time.time() - t:.0f}s", flush=True)
        for mode in ("unit", "chunk"):
            judged = {}
            for e in plan:
                lo, hi = e["spans"].get(("seen", mode), (0, 0))
                seen = decide(probs[lo:hi])
                label = ("supported", "contradicted", "insufficient")[int(np.argmax(seen))]
                leak = False
                if ("hidden", mode) in e["spans"]:
                    hlo, hhi = e["spans"][("hidden", mode)]
                    leak = int(np.argmax(decide(probs[hlo:hhi]))) == 0 and label != "supported"
                sent = {
                    "gold": e["gold"],
                    "pred": label,
                    "p_supported": float(seen[0]),
                    "leak": leak,
                    "fallback": False,
                }
                judged.setdefault(id(e["row"]), (e["row"], []))[1].append(sent)
            metrics = pe.reply_metrics(list(judged.values()))
            report["datasets"].setdefault(name, {})[mode] = metrics
            print(
                name,
                mode,
                "3-class",
                round(metrics["three_class"]["macro_f1"], 3),
                "not-grounded F1",
                round(metrics["not_grounded"]["f1"], 3),
                "AUROC",
                metrics["not_grounded"]["auroc"],
                "leak F1",
                metrics.get("leak", {}).get("f1"),
                flush=True,
            )
    print("saved", save(f"e15_reply_{args.tag}", report))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("predict")
    p.add_argument("--model", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--time", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--max-length", type=int, default=256)
    p.add_argument("--sources", nargs="*", default=list(SOURCES))
    t = sub.add_parser("train")
    t.add_argument("--base", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--epochs", type=int, default=1)
    t.add_argument("--freeze-layers", type=int, default=6)
    t.add_argument("--lr", type=float, default=2e-5)
    t.add_argument("--batch", type=int, default=16)
    t.add_argument("--max-length", type=int, default=256)
    t.add_argument("--threads", type=int, default=16)
    t.add_argument("--smoke", type=int, default=0, help="train on N batches only")
    r = sub.add_parser("reply")
    r.add_argument("--model", required=True)
    r.add_argument("--tag", required=True)
    r.add_argument("--time", action="store_true")
    r.add_argument("--limit", type=int, default=300)
    r.add_argument("--max-length", type=int, default=384)
    args = parser.parse_args(argv)
    return {"predict": run_predict, "train": run_train, "reply": run_reply}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
