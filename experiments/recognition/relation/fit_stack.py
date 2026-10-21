"""Fit, evaluate and register the stacked relation ensemble that the product uses.

    python -m experiments.recognition.relation.fit_stack
        --encoder runs/local/recognizers/c1-xlmr-cpu

Same recipe as the E1 ``stack_lr_encoder`` row, with the fitted parts saved:

1. Lexical branch: TF-IDF character 2-4 grams of the pair text plus seven hand-crafted
   features (``career_lab.recognition.stack``, checked identical to ``baselines.py``),
   class-balanced logistic regression on the train pairs.
2. Neural branch: C1 pair probabilities for dev and test through the product loader
   (cached under ``runs/local/cache/c1-pairs/``; about an hour on CPU the first time).
3. Meta-learner: logistic regression on the six pair probabilities, fitted on the dev pairs.
   Five-fold out-of-fold predictions on dev (grouped by claim) choose whether the
   number-and-limit rule is still blended in by late fusion, and with which weight, so the
   choice is not made on the meta-learner's own training predictions. Among weights within
   0.005 of the best, the smallest is taken, so the rule keeps the final say on the
   number-and-limit claims it can compare.
4. Test report (``results/e1_stack.json``): C1, C1 + rule (E10), stack, stack + rule;
   claim-level macro-F1 by language, joint and evidence F1, pair-level ECE, and the C6
   wrong-deduction rate at fixed reject rates.
5. Writes ``<recognizers>/relation-stack-v1/`` and registers it in the manifest.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold

from career_lab.models.v3.huggingface import aggregate_pairs
from career_lab.recognition import stack as product
from experiments.recognition import baselines, fusion
from experiments.recognition.common import DATA, RECOGNIZERS, ROOT, jsonl, register, save
from experiments.recognition.relation_eval import ece, model, pair_probabilities

PAIR = ("SUPPORTS", "CONTRADICTS", "UNRELATED")
REL = ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT")
LOWER = ("supported", "contradicted", "insufficient")
TIE = 0.005


def candidates(row):
    return [
        (c["id"], c["text"], c["observed_at_seq"], c["valid_from_seq"], c.get("valid_until_seq"))
        for c in row["model_input"]["candidate_evidence"]
    ]


def features(rows):
    texts, hand, labels, owner = [], [], [], []
    for i, row in enumerate(rows):
        claim = row["model_input"]["claim"]
        as_of = row["model_input"]["as_of"]["business_seq"]
        for c, raw in zip(candidates(row), row["model_input"]["candidate_evidence"], strict=True):
            text = product.pair_text(claim, as_of, c[1], c[2], c[3], c[4])
            feats = product.handcrafted(claim, c[1], as_of, c[4])
            assert text == baselines.pair_text(row, raw), "pair text differs from E1"
            assert feats == baselines.handcrafted(row, raw), "features differ from E1"
            texts.append(text)
            hand.append(feats)
            labels.append(PAIR.index(row["pair_labels"][c[0]]))
            owner.append(i)
    return texts, np.asarray(hand), np.asarray(labels), np.asarray(owner)


def encoder_pairs(encoder, rows, split):
    revision = model(encoder).revision
    cache = ROOT / "runs" / "local" / "cache" / "c1-pairs" / f"{revision}-{split}.npy"
    if cache.is_file():
        return np.load(cache)
    probs = pair_probabilities(encoder, rows)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache, probs)
    return probs


def claim_probs(rows, pairs, owner):
    return np.vstack(
        [
            np.asarray(aggregate_pairs(pairs[owner == i], 0.5)[0], dtype=float)
            for i in range(len(rows))
        ]
    )


def by_language(rows, probs):
    gold = [r["label"] for r in rows]
    out = {}
    for lang in ("zh", "en", "all"):
        idx = [i for i, r in enumerate(rows) if lang == "all" or r["language"] == lang]
        macro, pred = fusion.macro([gold[i] for i in idx], probs[idx])
        out[lang] = {
            "macro_f1": macro,
            "accuracy": float(np.mean([p == gold[i] for p, i in zip(pred, idx, strict=True)])),
        }
    return out


def reject_curve(rows, probs):
    from career_lab.recognition.decision import costs

    table = costs()
    claims = []
    for row, p in zip(rows, probs, strict=True):
        dist = dict(zip(LOWER, p, strict=True))
        expected = {d: sum(dist[y] * table["decide"][d][y] for y in dist) for d in table["decide"]}
        best = min(expected, key=expected.get)
        claims.append(
            {
                "gold": row["label"],
                "pred": REL[int(np.argmax(p))],
                "cost": expected[best],
                "defer": expected[best] >= table["defer"],
            }
        )
    order = sorted(claims, key=lambda c: c["cost"])
    curve = []
    for reject in (0.0, 0.1, 0.2):
        kept = order[: max(1, int(len(order) * (1 - reject)))]
        wrong = sum(c["pred"] == "CONTRADICTED" and c["gold"] != "CONTRADICTED" for c in kept)
        curve.append(
            {
                "reject_rate": reject,
                "error_rate": float(np.mean([c["gold"] != c["pred"] for c in kept])),
                "wrong_deduction_rate": wrong / len(kept),
            }
        )
    return {"error_reject": curve, "defer_rate": float(np.mean([c["defer"] for c in claims]))}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--encoder", required=True)
    parser.add_argument("--out", default=str(RECOGNIZERS / product.STACK_ID))
    args = parser.parse_args(argv)
    rows = jsonl(DATA / "relation-v3" / "relation.jsonl")
    part = {s: [r for r in rows if r["split"] == s] for s in ("train", "dev", "test")}
    data = {s: features(part[s]) for s in part}
    print("features identical to E1 on", sum(len(d[2]) for d in data.values()), "pairs", flush=True)

    tfidf = TfidfVectorizer(
        analyzer="char_wb", ngram_range=(2, 4), min_df=2, sublinear_tf=True, max_features=200000
    )
    x = {"train": tfidf.fit_transform(data["train"][0])}
    for s in ("dev", "test"):
        x[s] = tfidf.transform(data[s][0])
    xh = {s: hstack([x[s], csr_matrix(data[s][1] * product.HAND_SCALE)]).tocsr() for s in x}
    y = {s: data[s][2] for s in data}
    owner = {s: data[s][3] for s in data}
    base = LogisticRegression(C=8.0, max_iter=3000, class_weight="balanced").fit(
        xh["train"], y["train"]
    )
    base_p = {s: base.predict_proba(xh[s]) for s in ("dev", "test")}

    enc = {s: encoder_pairs(args.encoder, part[s], s) for s in ("dev", "test")}
    print("C1 pair probabilities ready", flush=True)

    meta_x = {s: np.hstack([base_p[s], enc[s]]) for s in ("dev", "test")}
    stacker = LogisticRegression(max_iter=2000).fit(meta_x["dev"], y["dev"])
    stacked = stacker.predict_proba(meta_x["test"])

    oof = np.zeros_like(meta_x["dev"][:, :3])
    for fit_idx, held in GroupKFold(n_splits=5).split(meta_x["dev"], y["dev"], owner["dev"]):
        fold = LogisticRegression(max_iter=2000).fit(meta_x["dev"][fit_idx], y["dev"][fit_idx])
        oof[held] = fold.predict_proba(meta_x["dev"][held])

    rule = {s: fusion.rule_probs(part[s]) for s in ("dev", "test")}
    gold_dev = [r["label"] for r in part["dev"]]
    stack_dev = claim_probs(part["dev"], oof, owner["dev"])
    grid = {
        round(float(a), 2): fusion.macro(gold_dev, fusion.fuse(stack_dev, *rule["dev"], a))[0]
        for a in np.linspace(0, 1, 21)
    }
    # The grid is flat near its best. Within TIE of the best, take the smallest weight: the
    # number-and-limit rule then decides the claims it can compare (numbers and limits by
    # rule, semantics by the learned models), which the stack alone gets wrong on the
    # scenario's own capacity and policy figures.
    best = max(grid.values())
    ties = [a for a, v in grid.items() if v >= best - TIE]
    alpha = min(ties)
    blend = alpha if alpha < 1 else max((a for a in grid if a < 1), key=grid.get)

    c1_alpha = json.loads((Path(args.encoder) / "fusion.json").read_text(encoding="utf-8"))["alpha"]
    c1_test = claim_probs(part["test"], enc["test"], owner["test"])
    stack_test = claim_probs(part["test"], stacked, owner["test"])
    variants = {
        "c1": c1_test,
        f"c1_rule_alpha{c1_alpha:g}": fusion.fuse(c1_test, *rule["test"], c1_alpha),
        "stack": stack_test,
        f"stack_rule_alpha{blend:g}": fusion.fuse(stack_test, *rule["test"], blend),
    }
    report = {
        "encoder": args.encoder,
        "encoder_revision": model(args.encoder).revision,
        "pairs": {s: int(len(y[s])) for s in y},
        "meta_coef": stacker.coef_.tolist(),
        "fusion_dev_grid_oof": grid,
        "fusion_alpha": alpha,
        "fusion_dev_ties": ties,
        "test": {},
        "pair_ece_test": {"c1": ece(enc["test"], y["test"]), "stack": ece(stacked, y["test"])},
        "claim_metrics_test": {
            "c1": baselines.claim_metrics(part["test"], enc["test"], owner["test"]),
            "stack": baselines.claim_metrics(part["test"], stacked, owner["test"]),
        },
    }
    for name, probs in variants.items():
        report["test"][name] = {
            **by_language(part["test"], probs),
            **reject_curve(part["test"], probs),
        }
        print(name, {k: round(report["test"][name][k]["macro_f1"], 4) for k in ("zh", "en", "all")})
    print("alpha (oof dev)", alpha, "grid best", round(grid[alpha], 4))
    save("e1_stack", report)

    import joblib

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if hasattr(tfidf, "stop_words_"):
        tfidf.stop_words_ = None
    joblib.dump(tfidf, out / "tfidf.joblib", compress=3)
    joblib.dump(base, out / "base_lr.joblib", compress=3)
    meta = {
        "coef": stacker.coef_.tolist(),
        "intercept": stacker.intercept_.tolist(),
        "classes": list(PAIR),
        "inputs": [f"lr_{p}" for p in PAIR] + [f"c1_{p}" for p in PAIR],
    }
    (out / "stacker.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (out / "fusion.json").write_text(
        json.dumps(
            {
                "alpha": alpha,
                "dev_macro_f1_oof": grid[alpha],
                "policy": "late fusion of the stacked claim probabilities with the "
                "number-and-limit rule when it is active; alpha 1 means stack only",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "stack.json").write_text(
        json.dumps(
            {
                "id": product.STACK_ID,
                "encoder_revision": report["encoder_revision"],
                "pair_text": "rolecraft-linear-text-v1",
                "hand_features": list(product.HAND_NAMES),
                "hand_scale": product.HAND_SCALE,
                "tfidf": {"analyzer": "char_wb", "ngram_range": [2, 4], "min_df": 2},
                "base": "LogisticRegression(C=8, class_weight=balanced) on relation-v3 train pairs",
                "meta": "LogisticRegression on [LR, C1] pair probabilities, relation-v3 dev pairs",
                "test_macro_f1": {
                    k: report["test"]["stack"][k]["macro_f1"] for k in ("zh", "en", "all")
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(register(product.STACK_ID, "relation"), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
