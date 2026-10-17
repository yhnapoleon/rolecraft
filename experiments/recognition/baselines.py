"""E1 (classical part) / C3: classical pair classifiers and ensembles on relation-v3.

    python -m experiments.recognition.baselines [--encoder runs/local/recognizers/c1-xlmr]

Every model classifies (claim, candidate) pairs into SUPPORTS / CONTRADICTS / UNRELATED
from ``rolecraft-linear-text-v1`` pair text (TF-IDF character 2-4 grams); the claim-level
label and evidence follow the same ``pair_aggregate`` rule as C1, so the table compares
like with like. Models: multinomial NB (Laplace), kNN (k by dev), decision tree (entropy,
depth by dev), RBF SVM and MLP (on a 300-d SVD of the TF-IDF), logistic regression,
bagging (LR), AdaBoost (trees), random forest (OOB, permutation importance on the
hand-crafted features), and a feature-engineered LR (TF-IDF plus number / unit / negation
/ limit-word agreement features). With ``--encoder`` the C1 pair probabilities are added
for stacking (LR on [baseline probs, encoder probs]) and an alpha-grid probability fusion.
Results per language: macro-F1, per-class F1, evidence F1, joint, confusion. Pairs are
3:1 UNRELATED, so every model that accepts class weights uses ``balanced`` (C1 trains
with class-weighted cross-entropy); NB, kNN, MLP and AdaBoost run unweighted.
"""

from __future__ import annotations

import argparse
import re

import numpy as np
from career_lab.recognition.relation import quantities
from scipy.sparse import csr_matrix, hstack
from sklearn.decomposition import TruncatedSVD
from sklearn.ensemble import AdaBoostClassifier, BaggingClassifier, RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import MultinomialNB
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

from career_lab.models.v3.huggingface import aggregate_pairs
from experiments.recognition.common import DATA, jsonl, save

PAIR = ("SUPPORTS", "CONTRADICTS", "UNRELATED")
REL = ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT")
NEG = re.compile(r"不|没|未|无|非|并不|别|not|no|never|isn't|aren't|doesn't|don't|without", re.I)
LIMIT = re.compile(r"上限|最多|不超过|容量|可用|预留|limit|cap|capacity|max|at most|reserved", re.I)
APPROVED = re.compile(r"已批|批准了|已经拿到|已获|approved|granted|already got", re.I)


def pair_text(row, candidate):
    mi = row["model_input"]
    until = "open" if candidate.get("valid_until_seq") is None else candidate["valid_until_seq"]
    return (
        f"{mi['claim']}\nreference time {mi['as_of']['business_seq']}; temporal scope known\n"
        f"[EVIDENCE]\n{candidate['text']}\nobserved {candidate['observed_at_seq']}; "
        f"valid from {candidate['valid_from_seq']}; valid until {until}"
    )


def handcrafted(row, candidate):
    claim, text = row["model_input"]["claim"], candidate["text"]
    cq, tq = quantities(claim), quantities(text)
    same_unit = {u for _, u in cq} & {u for _, u in tq}
    claim_neg, text_neg = bool(NEG.search(claim)), bool(NEG.search(text))
    expired = candidate.get("valid_until_seq") is not None and (
        candidate["valid_until_seq"] <= row["model_input"]["as_of"]["business_seq"]
    )
    char_overlap = len(set(claim) & set(text)) / max(1, len(set(claim)))
    return [
        float(bool(cq & tq)),  # same number and unit
        float(bool(same_unit) and not (cq & tq)),  # same unit, different number
        float(
            bool(same_unit)
            and bool(LIMIT.search(text))
            and any(v > w for v, u in cq for w, x in tq if u == x)
        ),
        float(claim_neg != text_neg),
        float(bool(APPROVED.search(claim)) and not APPROVED.search(text)),
        float(expired),
        char_overlap,
    ]


HAND_NAMES = [
    "same_quantity",
    "unit_conflict",
    "exceeds_limit",
    "negation_mismatch",
    "approval_claimed",
    "expired_evidence",
    "char_overlap",
]


def pairs(rows):
    texts, hand, labels, owner = [], [], [], []
    for i, row in enumerate(rows):
        for c in row["model_input"]["candidate_evidence"]:
            texts.append(pair_text(row, c))
            hand.append(handcrafted(row, c))
            labels.append(PAIR.index(row["pair_labels"][c["id"]]))
            owner.append(i)
    return texts, np.array(hand), np.array(labels), np.array(owner)


def claim_metrics(rows, probs, owner):
    gold, pred, joint, ev = [], [], [], []
    for i, row in enumerate(rows):
        p = probs[owner == i]
        rel, scores = aggregate_pairs(p, 0.5)
        label = REL[int(np.argmax(rel))]
        ids = [c["id"] for c in row["model_input"]["candidate_evidence"]]
        chosen = (
            {x for x, s in zip(ids, scores, strict=False) if s >= 0.5}
            if label != "INSUFFICIENT"
            else set()
        )
        want = set(row["evidence_ids"])
        tp = len(chosen & want)
        ev.append(1.0 if not chosen and not want else 2 * tp / max(1, len(chosen) + len(want)))
        gold.append(row["label"])
        pred.append(label)
        joint.append(label == row["label"] and chosen == want)
    out = {}
    for lang in ("zh", "en", "all"):
        idx = [i for i, r in enumerate(rows) if lang == "all" or r["language"] == lang]
        g, p = [gold[i] for i in idx], [pred[i] for i in idx]
        f1s = {}
        for label in REL:
            tp = sum(a == label and b == label for a, b in zip(g, p, strict=False))
            fp = sum(a != label and b == label for a, b in zip(g, p, strict=False))
            fn = sum(a == label and b != label for a, b in zip(g, p, strict=False))
            pr, rc = (tp / (tp + fp) if tp + fp else 0.0), (tp / (tp + fn) if tp + fn else 0.0)
            f1s[label] = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
        out[lang] = {
            "macro_f1": sum(f1s.values()) / 3,
            "per_class_f1": f1s,
            "accuracy": sum(a == b for a, b in zip(g, p, strict=False)) / max(1, len(idx)),
            "evidence_f1": float(np.mean([ev[i] for i in idx])),
            "joint": float(np.mean([joint[i] for i in idx])),
            "confusion": [
                [sum(a == x and b == y for a, b in zip(g, p, strict=False)) for y in REL]
                for x in REL
            ],
        }
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--encoder", default=None)
    args = parser.parse_args(argv)
    rows = jsonl(DATA / "relation-v3" / "relation.jsonl")
    part = {s: [r for r in rows if r["split"] == s] for s in ("train", "dev", "test")}
    data = {s: pairs(part[s]) for s in part}
    tfidf = TfidfVectorizer(
        analyzer="char_wb", ngram_range=(2, 4), min_df=2, sublinear_tf=True, max_features=200000
    )
    x = {"train": tfidf.fit_transform(data["train"][0])}
    for s in ("dev", "test"):
        x[s] = tfidf.transform(data[s][0])
    svd = TruncatedSVD(300, random_state=0).fit(x["train"])
    z = {s: svd.transform(x[s]) for s in x}
    y = {s: data[s][2] for s in data}
    hand = {s: data[s][1] for s in data}
    xh = {s: hstack([x[s], csr_matrix(hand[s] * 3.0)]).tocsr() for s in x}
    zh_ = {s: np.hstack([z[s], hand[s]]) for s in z}

    def dev_macro(model, feats):
        model.fit(feats["train"], y["train"])
        return claim_metrics(part["dev"], model.predict_proba(feats["dev"]), data["dev"][3])["all"][
            "macro_f1"
        ]

    best_k = max(
        (3, 7, 15, 31),
        key=lambda k: dev_macro(KNeighborsClassifier(k, metric="cosine", weights="distance"), x),
    )
    best_depth = max(
        (8, 16, 32),
        key=lambda d: dev_macro(
            DecisionTreeClassifier(criterion="entropy", max_depth=d, random_state=0), zh_
        ),
    )
    models = {
        "naive_bayes": (MultinomialNB(alpha=1.0), x),
        f"knn_k{best_k}": (KNeighborsClassifier(best_k, metric="cosine", weights="distance"), x),
        f"decision_tree_d{best_depth}": (
            DecisionTreeClassifier(
                criterion="entropy",
                max_depth=best_depth,
                ccp_alpha=1e-4,
                random_state=0,
                class_weight="balanced",
            ),
            zh_,
        ),
        "svm_rbf": (
            SVC(C=4.0, gamma="scale", probability=True, random_state=0, class_weight="balanced"),
            z,
        ),
        "logistic_regression": (
            LogisticRegression(C=8.0, max_iter=3000, class_weight="balanced"),
            x,
        ),
        "mlp": (
            MLPClassifier(
                hidden_layer_sizes=(256,), max_iter=200, early_stopping=True, random_state=0
            ),
            z,
        ),
        "bagging_lr": (
            BaggingClassifier(
                LogisticRegression(C=8.0, max_iter=2000, class_weight="balanced"),
                n_estimators=10,
                random_state=0,
            ),
            x,
        ),
        "adaboost_trees": (
            AdaBoostClassifier(
                DecisionTreeClassifier(max_depth=3), n_estimators=150, random_state=0
            ),
            zh_,
        ),
        "random_forest": (
            RandomForestClassifier(
                n_estimators=400, oob_score=True, random_state=0, n_jobs=-1, class_weight="balanced"
            ),
            zh_,
        ),
        "lr_tfidf_plus_features": (
            LogisticRegression(C=8.0, max_iter=3000, class_weight="balanced"),
            xh,
        ),
    }
    report = {
        "models": {},
        "k": best_k,
        "depth": best_depth,
        "pairs": {s: int(len(y[s])) for s in y},
    }
    probs_test = {}
    for name, (model, feats) in models.items():
        model.fit(feats["train"], y["train"])
        probs_test[name] = model.predict_proba(feats["test"])
        report["models"][name] = {
            "test": claim_metrics(part["test"], probs_test[name], data["test"][3])
        }
        if name == "random_forest":
            report["models"][name]["oob_score"] = float(model.oob_score_)
            imp = permutation_importance(
                model, zh_["dev"], y["dev"], n_repeats=3, random_state=0, n_jobs=-1
            )
            report["models"][name]["permutation_importance_handcrafted"] = {
                n: float(v)
                for n, v in zip(HAND_NAMES, imp.importances_mean[-len(HAND_NAMES) :], strict=False)
            }
        print(
            f"{name:<24} macroF1 zh {report['models'][name]['test']['zh']['macro_f1']:.3f} "
            f"en {report['models'][name]['test']['en']['macro_f1']:.3f} joint "
            f"{report['models'][name]['test']['all']['joint']:.3f}",
            flush=True,
        )
    if args.encoder:
        from experiments.recognition.relation_eval import pair_probabilities

        enc = {s: pair_probabilities(args.encoder, part[s]) for s in ("dev", "test")}
        base = models["lr_tfidf_plus_features"][0]
        dev_base = base.predict_proba(xh["dev"])
        stack = LogisticRegression(max_iter=2000).fit(np.hstack([dev_base, enc["dev"]]), y["dev"])
        stacked = stack.predict_proba(
            np.hstack([probs_test["lr_tfidf_plus_features"], enc["test"]])
        )
        report["models"]["stack_lr_encoder"] = {
            "test": claim_metrics(part["test"], stacked, data["test"][3])
        }
        grid = {}
        for alpha in np.linspace(0, 1, 11):
            fused = alpha * enc["dev"] + (1 - alpha) * dev_base
            grid[round(float(alpha), 1)] = claim_metrics(part["dev"], fused, data["dev"][3])["all"][
                "macro_f1"
            ]
        alpha = max(grid, key=grid.get)
        fused = alpha * enc["test"] + (1 - alpha) * probs_test["lr_tfidf_plus_features"]
        report["models"][f"fusion_alpha{alpha}"] = {
            "test": claim_metrics(part["test"], fused, data["test"][3]),
            "dev_grid": grid,
        }
        report["models"]["encoder_c1"] = {
            "test": claim_metrics(part["test"], enc["test"], data["test"][3])
        }
    save("e1_baselines", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
