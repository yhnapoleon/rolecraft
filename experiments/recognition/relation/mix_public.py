"""E12: mixed training with the real public data (lexical branch and stack; C1 unchanged).

    python -m experiments.recognition.relation.mix_public
        --encoder runs/local/recognizers/c1-xlmr-cpu [--save]

E11 showed that the product chain, fitted on relation-v3 alone, falls to about 0.35
macro-F1 on human-written claims. Here the ``fit_stack.py`` recipe is refitted with the
train splits of public-real-v1 added. C1 itself is not re-trained: the encoder stays the
relation-v3 one, so its test pair probabilities come from the E11 cache.

- ``v3``: relation-v3 only (the product stack, the E11 reference);
- ``mix``: relation-v3 + ContractNLI + VitaminC + CFEVER train pairs for the lexical LR,
  the same sources' dev pairs for the meta-learner (CFEVER dev sampled to 1,000 claims);
- ``mix_balanced``: as ``mix``, each public source weighted to the pair total of relation-v3
  in the lexical LR;
- ``loso_<source>``: as ``mix`` without that source in train and dev, so its test is an
  unseen real source.

The rule weight alpha is chosen as in ``fit_stack.py``: five-fold out-of-fold meta
predictions on the variant's dev, grouped by claim, smallest weight within 0.005 of the
best; each variant is also read at the product's alpha (0.4). Every variant is evaluated on
the full test splits of the five E11 sources.
``--save`` writes the ``mix`` stack to ``<recognizers>/relation-stack-mix-v1/`` in the
product layout (not registered).
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

from career_lab.recognition import stack as product
from experiments.recognition import fusion
from experiments.recognition.common import RECOGNIZERS, jsonl, save
from experiments.recognition.relation import fit_stack
from experiments.recognition.relation.transfer_public import (
    SOURCES,
    aggregate,
    encoder_pairs,
    report,
    sample,
)

PAIR = ("SUPPORTS", "CONTRADICTS", "UNRELATED")
REAL = ("contractnli", "vitaminc", "cfever")
DEV_LIMIT = {"cfever": 1000}
TIE = 0.005
# The rule weight of the registered product stack (relation-stack-v1/fusion.json). On the
# mixed dev the alpha grid is flat (the rule is rarely active on the public claims), so the
# tie rule picks 0; every variant is therefore also read at the product's weight.
PRODUCT_ALPHA = 0.4


def pairs_of(rows):
    texts, hand, labels, owner = [], [], [], []
    for i, row in enumerate(rows):
        mi = row["model_input"]
        claim, as_of = mi["claim"], mi["as_of"]["business_seq"]
        for c in mi["candidate_evidence"]:
            until = c.get("valid_until_seq")
            texts.append(
                product.pair_text(
                    claim, as_of, c["text"], c["observed_at_seq"], c["valid_from_seq"], until
                )
            )
            hand.append(product.handcrafted(claim, c["text"], as_of, until))
            labels.append(PAIR.index(row["pair_labels"][c["id"]]))
            owner.append(i)
    return {
        "texts": texts,
        "hand": np.asarray(hand, dtype=float),
        "y": np.asarray(labels),
        "owner": np.asarray(owner),
    }


def load(encoder):
    data = {}
    for name in SOURCES:
        rows = jsonl(SOURCES[name])
        part = {s: [r for r in rows if r["split"] == s] for s in ("train", "dev", "test")}
        if name in DEV_LIMIT:
            part["dev"] = sample(part["dev"], DEV_LIMIT[name])
        entry = {"rows": part, "feats": {}, "enc": {}}
        for s in ("train", "dev", "test"):
            if s != "test" and name == "public-synth":
                continue
            entry["feats"][s] = pairs_of(part[s])
        entry["enc"]["test"] = encoder_pairs(encoder, name, part["test"])
        if name == "relation-v3":
            entry["enc"]["dev"] = fit_stack.encoder_pairs(encoder, part["dev"], "dev")
        elif name in REAL:
            entry["enc"]["dev"] = encoder_pairs(encoder, f"{name}-dev", part["dev"])
        data[name] = entry
        print(name, {s: len(part[s]) for s in part}, "ready", flush=True)
    return data


class Variant:
    def __init__(self, data, sources, balanced=False):
        self.sources = list(sources)
        train = [data[n]["feats"]["train"] for n in self.sources]
        y = np.concatenate([f["y"] for f in train])
        weight = None
        if balanced:
            ref = len(data["relation-v3"]["feats"]["train"]["y"])
            weight = np.concatenate([np.full(len(f["y"]), ref / len(f["y"])) for f in train])
        self.tfidf = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(2, 4), min_df=2, sublinear_tf=True, max_features=200000
        )
        x = self.tfidf.fit_transform(sum((f["texts"] for f in train), []))
        x = hstack([x, csr_matrix(np.vstack([f["hand"] for f in train]) * product.HAND_SCALE)])
        self.base = LogisticRegression(C=8.0, max_iter=3000, class_weight="balanced").fit(
            x.tocsr(), y, sample_weight=weight
        )
        self.train_pairs = int(len(y))
        self._fit_meta(data)

    def base_p(self, feats):
        x = hstack(
            [self.tfidf.transform(feats["texts"]), csr_matrix(feats["hand"] * product.HAND_SCALE)]
        )
        return self.base.predict_proba(x.tocsr())

    def _fit_meta(self, data):
        mx, my, groups, spans, offset, owners = [], [], [], [], 0, 0
        for n in self.sources:
            f = data[n]["feats"]["dev"]
            mx.append(np.hstack([self.base_p(f), data[n]["enc"]["dev"]]))
            my.append(f["y"])
            groups.append(f["owner"] + owners)
            spans.append((n, offset, offset + len(f["y"])))
            offset += len(f["y"])
            owners += len(data[n]["rows"]["dev"])
        mx, my, groups = np.vstack(mx), np.concatenate(my), np.concatenate(groups)
        self.meta = LogisticRegression(max_iter=2000).fit(mx, my)
        oof = np.zeros((len(my), 3))
        for fit_idx, held in GroupKFold(n_splits=5).split(mx, my, groups):
            fold = LogisticRegression(max_iter=2000).fit(mx[fit_idx], my[fit_idx])
            oof[held] = fold.predict_proba(mx[held])
        rows, claims = [], []
        for n, lo, hi in spans:
            rows += data[n]["rows"]["dev"]
            claims.append(aggregate(data[n]["rows"]["dev"], oof[lo:hi]))
        claims = np.vstack(claims)
        gold = [r["label"] for r in rows]
        rule, active = fusion.rule_probs(rows)
        self.grid = {
            round(float(a), 2): fusion.macro(gold, fusion.fuse(claims, rule, active, a))[0]
            for a in np.linspace(0, 1, 21)
        }
        best = max(self.grid.values())
        self.alpha = min(a for a, v in self.grid.items() if v >= best - TIE)
        self.dev_claims = len(rows)

    def evaluate(self, entry):
        rows, feats, enc = entry["rows"]["test"], entry["feats"]["test"], entry["enc"]["test"]
        base = self.base_p(feats)
        stacked = self.meta.predict_proba(np.hstack([base, enc]))
        claims = aggregate(rows, stacked)
        rule, active = fusion.rule_probs(rows)
        return {
            "lr": report(rows, aggregate(rows, base)),
            "stack": report(rows, claims),
            "stack_rule": report(rows, fusion.fuse(claims, rule, active, self.alpha)),
            "stack_rule_product_alpha": report(
                rows, fusion.fuse(claims, rule, active, PRODUCT_ALPHA)
            ),
        }

    def summary(self):
        return {
            "sources": self.sources,
            "train_pairs": self.train_pairs,
            "dev_claims": self.dev_claims,
            "alpha": self.alpha,
            "dev_grid_oof": self.grid,
            "meta_coef": self.meta.coef_.tolist(),
        }


def save_stack(variant: Variant, out: Path, encoder_revision: str) -> None:
    import joblib

    out.mkdir(parents=True, exist_ok=True)
    if hasattr(variant.tfidf, "stop_words_"):
        variant.tfidf.stop_words_ = None
    joblib.dump(variant.tfidf, out / "tfidf.joblib", compress=3)
    joblib.dump(variant.base, out / "base_lr.joblib", compress=3)
    meta = {
        "coef": variant.meta.coef_.tolist(),
        "intercept": variant.meta.intercept_.tolist(),
        "classes": list(PAIR),
        "inputs": [f"lr_{p}" for p in PAIR] + [f"c1_{p}" for p in PAIR],
    }
    (out / "stacker.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    fusion_cfg = {"alpha": variant.alpha, "dev_macro_f1_oof": variant.grid[variant.alpha]}
    (out / "fusion.json").write_text(json.dumps(fusion_cfg, indent=2) + "\n", encoding="utf-8")
    config = {
        "id": "relation-stack-mix-v1",
        "encoder_revision": encoder_revision,
        "pair_text": "rolecraft-linear-text-v1",
        "hand_features": list(product.HAND_NAMES),
        "hand_scale": product.HAND_SCALE,
        "base": "LogisticRegression(C=8, class_weight=balanced) on relation-v3 + "
        "ContractNLI + VitaminC + CFEVER train pairs",
        "meta": "LogisticRegression on [LR, C1] pair probabilities, the same sources' dev pairs",
    }
    (out / "stack.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--encoder", required=True)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args(argv)
    data = load(args.encoder)
    plan = {
        "v3": (["relation-v3"], False),
        "mix": (["relation-v3", *REAL], False),
        "mix_balanced": (["relation-v3", *REAL], True),
        **{f"loso_{n}": (["relation-v3", *(m for m in REAL if m != n)], False) for n in REAL},
    }
    results = {"encoder": args.encoder, "dev_limit": DEV_LIMIT, "variants": {}}
    for name, (sources, balanced) in plan.items():
        variant = Variant(data, sources, balanced)
        row = {**variant.summary(), "test": {}}
        for source in SOURCES:
            row["test"][source] = variant.evaluate(data[source])
        results["variants"][name] = row
        for chain in ("stack", "stack_rule", "stack_rule_product_alpha"):
            print(
                name,
                chain,
                "alpha",
                variant.alpha,
                {s: round(row["test"][s][chain]["all"]["macro_f1"], 3) for s in SOURCES},
                flush=True,
            )
        if name == "mix" and args.save:
            from experiments.recognition.relation_eval import model

            save_stack(variant, RECOGNIZERS / "relation-stack-mix-v1", model(args.encoder).revision)
    print("saved", save("e12_mix_public", results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
