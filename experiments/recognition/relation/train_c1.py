"""C1 relation encoder: XLM-R base, ``pair_aggregate``, trained on relation-v3 (E1 / E2).

Self-contained so it runs on Colab (GPU) or locally (CPU, slow):

    pip install "transformers==4.57.1" "safetensors==0.6.2"
    python train_c1.py --data relation.jsonl --base FacebookAI/xlm-roberta-base \
        --out c1-out --freeze-layers 8 --epochs 3 --batch 16 --lr 2e-5

Model (encoder-return v3 ``pair_aggregate``): each (query, candidate body) pair is encoded
by XLM-R, mean-pooled over the attention mask, and a linear head gives SUPPORTS /
CONTRADICTS / UNRELATED. Claim-level label and evidence follow the deterministic
aggregation rule of the specification (contradiction first, support must beat unrelated,
threshold 0.5). Text is built exactly as the reference ``encoder_inputs``.

Selection: dev "joint" (label correct and evidence set exact) after each epoch; the best
epoch is kept. Afterwards: temperature scaling of the pair logits on dev (NLL), the C6 lift
curve on dev (how many real errors the top 20 % by expected cost contain), and one test
evaluation. ``--freeze-layers 12`` is the linear-adapter baseline, ``0`` full fine-tuning
(E2). Outputs: ``encoder/`` (safetensors + tokenizer), ``heads.npz``, ``c1.json``,
``temperature.json``, ``lift.json``, ``metrics.json``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

os.environ.setdefault("USE_TF", "0")
from transformers import AutoModel, AutoTokenizer  # noqa: E402

PAIR_LABELS = ("SUPPORTS", "CONTRADICTS", "UNRELATED")
RELATION_LABELS = ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT")
COSTS = {  # recognition/costs.json: decide[d][y]
    "SUPPORTED": {"SUPPORTED": 0, "CONTRADICTED": 1, "INSUFFICIENT": 1},
    "CONTRADICTED": {"SUPPORTED": 3, "CONTRADICTED": 0, "INSUFFICIENT": 3},
    "INSUFFICIENT": {"SUPPORTED": 0.5, "CONTRADICTED": 1, "INSUFFICIENT": 0},
}
DEFER = 0.5


def encoder_inputs(model_input: dict) -> tuple[str, list[str]]:
    """rolecraft-encoder-text-v1 (reference export_hf_return.encoder_inputs), flat candidates."""
    scope = model_input.get("rule_context", {}).get("evidence_time_context", {})
    query = (
        f"{model_input['purpose']}\n{model_input['claim']}\n"
        f"reference time {model_input['as_of']['business_seq']}; "
        f"temporal scope {scope.get('status', 'undetermined')}"
    )
    bodies = []
    for c in model_input["candidate_evidence"]:
        until = "open" if c.get("valid_until_seq") is None else c["valid_until_seq"]
        bodies.append(
            f"{c['text']}\nobserved {c['observed_at_seq']}; "
            f"valid from {c['valid_from_seq']}; valid until {until}"
        )
    return query, bodies


def aggregate_pairs(pairs: np.ndarray, threshold: float = 0.5):
    """pair_aggregate v1 (reference export_hf_return.aggregate_pairs)."""
    supports, contradicts, unrelated = pairs[:, 0], pairs[:, 1], pairs[:, 2]
    support = np.where(supports > unrelated, supports, 0.0)
    if (contradicts >= threshold).any():
        decided, confidence, scores = 1, contradicts.max(), contradicts
    elif (support >= threshold).any():
        decided, confidence, scores = 0, support.max(), support
    else:
        strongest = max(supports.max(), contradicts.max())
        decided, confidence, scores = 2, 1 - strongest, np.maximum(support, contradicts)
    probabilities = np.full(3, (1 - confidence) / 4)
    probabilities[decided] = (1 + confidence) / 2
    return probabilities, scores


class PairModel(nn.Module):
    def __init__(self, base: str, freeze_layers: int):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(base)
        hidden = self.encoder.config.hidden_size
        torch.manual_seed(13)
        self.pair = nn.Linear(hidden, 3)
        for p in self.encoder.embeddings.parameters():
            p.requires_grad = freeze_layers == 0
        for i, layer in enumerate(self.encoder.encoder.layer):
            for p in layer.parameters():
                p.requires_grad = i >= freeze_layers

    def forward(self, input_ids, attention_mask):
        hidden = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        mask = attention_mask.unsqueeze(-1).to(hidden.dtype)
        pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        return self.pair(pooled)


def load(path: Path):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {s: [r for r in rows if r["split"] == s] for s in ("train", "dev", "test")}


def pairs_of(rows):
    out = []
    for r in rows:
        query, bodies = encoder_inputs(r["model_input"])
        for c, body in zip(r["model_input"]["candidate_evidence"], bodies):
            out.append((query, body, PAIR_LABELS.index(r["pair_labels"][c["id"]])))
    return out


@torch.no_grad()
def pair_logits(model, tokenizer, rows, device, max_len, batch=64):
    model.eval()
    results = []
    for r in rows:
        query, bodies = encoder_inputs(r["model_input"])
        enc = tokenizer([query] * len(bodies), bodies, padding=True, truncation="only_second",
                        max_length=max_len, return_tensors="pt").to(device)
        results.append(model(enc["input_ids"], enc["attention_mask"]).float().cpu().numpy())
    return results


def softmax(x, t=1.0):
    z = x / t
    z = z - z.max(-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(-1, keepdims=True)


def evaluate(rows, logits, temperature=1.0, threshold=0.5):
    gold, pred, joint, ev_f1, probs_all = [], [], [], [], []
    for r, lg in zip(rows, logits):
        probs, scores = aggregate_pairs(softmax(lg, temperature), threshold)
        label = RELATION_LABELS[int(probs.argmax())]
        ids = [c["id"] for c in r["model_input"]["candidate_evidence"]]
        chosen = {i for i, s in zip(ids, scores) if s >= threshold} if label != "INSUFFICIENT" else set()
        want = set(r["evidence_ids"])
        tp = len(chosen & want)
        f1 = 1.0 if not chosen and not want else (2 * tp / (len(chosen) + len(want)) if chosen or want else 0)
        gold.append(r["label"])
        pred.append(label)
        joint.append(label == r["label"] and chosen == want)
        ev_f1.append(f1)
        probs_all.append(probs)
    return gold, pred, joint, ev_f1, probs_all


def summary(rows, gold, pred, joint, ev_f1):
    out = {}
    for language in ("zh", "en", "all"):
        idx = [i for i, r in enumerate(rows) if language == "all" or r["language"] == language]
        if not idx:
            continue
        g = [gold[i] for i in idx]
        p = [pred[i] for i in idx]
        per = {}
        for label in RELATION_LABELS:
            tp = sum(a == label and b == label for a, b in zip(g, p))
            fp = sum(a != label and b == label for a, b in zip(g, p))
            fn = sum(a == label and b != label for a, b in zip(g, p))
            pr = tp / (tp + fp) if tp + fp else 0.0
            rc = tp / (tp + fn) if tp + fn else 0.0
            per[label] = {"precision": pr, "recall": rc, "f1": 2 * pr * rc / (pr + rc) if pr + rc else 0.0}
        out[language] = {
            "n": len(idx),
            "accuracy": sum(a == b for a, b in zip(g, p)) / len(idx),
            "macro_f1": sum(v["f1"] for v in per.values()) / 3,
            "per_class": per,
            "evidence_f1": float(np.mean([ev_f1[i] for i in idx])),
            "joint": float(np.mean([joint[i] for i in idx])),
            "confusion": [[sum(a == x and b == y for a, b in zip(g, p)) for y in RELATION_LABELS]
                          for x in RELATION_LABELS],
        }
    return out


def fit_temperature(rows, logits):
    flat = np.concatenate(logits)
    labels = np.array([PAIR_LABELS.index(r["pair_labels"][c["id"]])
                       for r in rows for c in r["model_input"]["candidate_evidence"]])
    best, best_nll = 1.0, math.inf
    for t in np.linspace(0.5, 4.0, 36):
        p = softmax(flat, t)[np.arange(len(labels)), labels]
        nll = -np.log(p + 1e-12).mean()
        if nll < best_nll:
            best, best_nll = float(t), float(nll)
    return best, best_nll


def ece(rows, logits, temperature, bins=10):
    flat = np.concatenate(logits)
    labels = np.array([PAIR_LABELS.index(r["pair_labels"][c["id"]])
                       for r in rows for c in r["model_input"]["candidate_evidence"]])
    p = softmax(flat, temperature)
    conf, pred = p.max(1), p.argmax(1)
    total = 0.0
    for lo in np.linspace(0, 1, bins, endpoint=False):
        m = (conf > lo) & (conf <= lo + 1 / bins)
        if m.any():
            total += m.mean() * abs((pred[m] == labels[m]).mean() - conf[m].mean())
    return float(total)


def lift(gold, pred, probs_all, fraction=0.2):
    costs = []
    for probs in probs_all:
        expected = {d: sum(probs[j] * COSTS[d][y] for j, y in enumerate(RELATION_LABELS)) for d in RELATION_LABELS}
        costs.append(min(expected.values()))
    errors = np.array([a != b for a, b in zip(gold, pred)])
    order = np.argsort(-np.array(costs))
    top = order[: max(1, int(len(order) * fraction))]
    coverage = float(errors[top].sum() / max(1, errors.sum()))
    deferred = float(np.mean(np.array(costs) >= DEFER))
    return {"top_fraction": fraction, "error_coverage": coverage, "errors": int(errors.sum()),
            "defer_rate_at_cost_0.5": deferred}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--base", default="FacebookAI/xlm-roberta-base")
    ap.add_argument("--out", required=True)
    ap.add_argument("--freeze-layers", type=int, default=8)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--head-lr", type=float, default=1e-3)
    ap.add_argument("--max-len", type=int, default=256)
    ap.add_argument("--limit", type=int, default=0, help="debug: cap training claims")
    args = ap.parse_args()
    random.seed(13)
    np.random.seed(13)
    torch.manual_seed(13)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    data = load(Path(args.data))
    if args.limit:
        data = {k: v[: args.limit if k == "train" else max(1, args.limit // 3)] for k, v in data.items()}
    tokenizer = AutoTokenizer.from_pretrained(args.base, use_fast=True)
    model = PairModel(args.base, args.freeze_layers).to(device)
    train_pairs = pairs_of(data["train"])
    counts = np.bincount([y for _, _, y in train_pairs], minlength=3)
    weights = torch.tensor(counts.sum() / (3 * np.maximum(counts, 1)), dtype=torch.float32, device=device)
    params = [
        {"params": [p for p in model.encoder.parameters() if p.requires_grad], "lr": args.lr},
        {"params": model.pair.parameters(), "lr": args.head_lr},
    ]
    optimizer = torch.optim.AdamW(params, weight_decay=0.01)
    steps = math.ceil(len(train_pairs) / args.batch) * args.epochs
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer, lambda s: min(1.0, (s + 1) / max(1, steps // 10)) * max(0.0, 1 - s / steps)
    )
    loss_fn = nn.CrossEntropyLoss(weight=weights)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    history, best_joint, best_state = [], -1.0, None
    use_amp = device == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    for epoch in range(args.epochs):
        model.train()
        random.shuffle(train_pairs)
        started, total = time.time(), 0.0
        for i in range(0, len(train_pairs), args.batch):
            batch = train_pairs[i : i + args.batch]
            enc = tokenizer([q for q, _, _ in batch], [b for _, b, _ in batch], padding=True,
                            truncation="only_second", max_length=args.max_len, return_tensors="pt").to(device)
            y = torch.tensor([t for _, _, t in batch], device=device)
            with torch.autocast(device_type="cuda", enabled=use_amp):
                loss = loss_fn(model(enc["input_ids"], enc["attention_mask"]).float(), y)
            optimizer.zero_grad()
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            total += loss.item() * len(batch)
        dev_logits = pair_logits(model, tokenizer, data["dev"], device, args.max_len)
        g, p, j, e, _ = evaluate(data["dev"], dev_logits)
        dev = summary(data["dev"], g, p, j, e)
        history.append({"epoch": epoch + 1, "train_loss": total / len(train_pairs),
                        "dev": dev["all"], "seconds": round(time.time() - started, 1)})
        print(json.dumps(history[-1]["dev"] | {"epoch": epoch + 1, "loss": history[-1]["train_loss"]}), flush=True)
        if dev["all"]["joint"] > best_joint:
            best_joint = dev["all"]["joint"]
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    dev_logits = pair_logits(model, tokenizer, data["dev"], device, args.max_len)
    temperature, nll = fit_temperature(data["dev"], dev_logits)
    g, p, j, e, probs = evaluate(data["dev"], dev_logits, temperature)
    lift_info = lift(g, p, probs)
    test_logits = pair_logits(model, tokenizer, data["test"], device, args.max_len)
    tg, tp, tj, te, _ = evaluate(data["test"], test_logits, temperature)
    metrics = {
        "settings": vars(args),
        "history": history,
        "dev": summary(data["dev"], g, p, j, e),
        "test": summary(data["test"], tg, tp, tj, te),
        "temperature": temperature,
        "ece_before": ece(data["dev"], dev_logits, 1.0),
        "ece_after": ece(data["dev"], dev_logits, temperature),
        "lift": lift_info,
        "pair_counts_train": counts.tolist(),
    }
    model.encoder.save_pretrained(out / "encoder", safe_serialization=True)
    tokenizer.save_pretrained(out / "encoder")
    np.savez(out / "heads.npz",
             **{"pair.weight": model.pair.weight.detach().cpu().numpy().astype(np.float32),
                "pair.bias": model.pair.bias.detach().cpu().numpy().astype(np.float32)})
    (out / "c1.json").write_text(json.dumps({
        "variant": "pair_aggregate", "pooling": "mean", "max_tokens": args.max_len,
        "evidence_threshold": 0.5, "seed": 13, "base": args.base,
        "pair_label_order": list(PAIR_LABELS), "freeze_layers": args.freeze_layers,
    }, indent=2), encoding="utf-8")
    (out / "temperature.json").write_text(json.dumps({"temperature": temperature, "dev_nll": nll}), encoding="utf-8")
    (out / "lift.json").write_text(json.dumps(lift_info), encoding="utf-8")
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print("test", json.dumps(metrics["test"]["all"]), "T", temperature, "lift", lift_info)


if __name__ == "__main__":
    main()
