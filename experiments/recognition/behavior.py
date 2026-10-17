"""E6 / C5: behaviour trajectories (strategy, phases, anomalies, unsupervised structure).

    python -m experiments.recognition.behavior [--register]

Data: trajectories-v1 (scripted strategies over the real backend, both languages).
Split 80/20 stratified by strategy (seeded). Experiments:

- strategy recognition: DTW (substitution 0 / 0.5 same prefix / 1) + 1-NN against the
  training library, vs. 1-3 gram counts + random forest, vs. edit-distance 1-NN;
- phases: categorical HMM (hmmlearn), 3-5 states chosen by BIC, states named by their
  emission mass (explore / test / decide / adjust);
- anomalies: per-step HMM log-likelihood (fitted on trajectories of the regular
  strategies) vs. isolation forest on n-grams vs. DTW distance to the nearest regular
  reference, AUROC against the strategies' deliberate anomaly labels;
- unsupervised: DTW distance matrix + Ward clustering, silhouette-chosen k, ARI with the
  strategy labels.

``--register`` writes ``behavior-v1/{references.json, hmm.npz}`` (five medoid references
per strategy, the HMM and its state naming) and enters it in the manifest.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter

import numpy as np
from hmmlearn.hmm import CategoricalHMM
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.feature_extraction import DictVectorizer
from sklearn.metrics import adjusted_rand_score, roc_auc_score, silhouette_score

from career_lab.recognition.behavior import dtw
from experiments.recognition.common import (
    DATA,
    RECOGNIZERS,
    confusion,
    jsonl,
    macro_f1,
    register,
    save,
)

PHASE_NAMES = {"zh": ["探索", "测试", "决策", "调整"], "en": ["explore", "test", "decide", "adjust"]}
REGULAR = {"thorough", "request_first", "test_heavy", "ask_heavy", "revise_loop"}


def load():
    rows = []
    for language in ("zh", "en"):
        path = DATA / "trajectories-v1" / f"raw-{language}.jsonl"
        if path.exists():
            rows += [r for r in jsonl(path) if r["sequence"] and not r["error"]]
    return rows


def edit(a, b):
    n, m = len(a), len(b)
    d = np.zeros((n + 1, m + 1))
    d[:, 0], d[0, :] = np.arange(n + 1), np.arange(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (a[i - 1] != b[j - 1]))
    return d[n, m]


def ngrams(seq, n_max=3):
    feats = Counter()
    for n in range(1, n_max + 1):
        for i in range(len(seq) - n + 1):
            feats["|".join(seq[i : i + n])] += 1
    return feats


def norm_dtw(a, b):
    return dtw(a, b) / max(len(a), len(b), 1)


def fit_hmm(train_seqs, vocabulary, states, seed=0):
    index = {v: i for i, v in enumerate(vocabulary)}
    x = np.concatenate([[index[s] for s in seq] for seq in train_seqs]).reshape(-1, 1)
    lengths = [len(s) for s in train_seqs]
    model = CategoricalHMM(n_components=states, n_iter=200, random_state=seed, n_features=len(vocabulary))
    model.fit(x, lengths)
    # Additive smoothing: symbols unseen in a state must not make a sequence impossible.
    smoothed = model.emissionprob_ + 1e-3
    model.emissionprob_ = smoothed / smoothed.sum(1, keepdims=True)
    log_l = model.score(x, lengths)
    params = states - 1 + states * (states - 1) + states * (len(vocabulary) - 1)
    bic = -2 * log_l + params * np.log(len(x))
    return model, bic, index


def name_states_by_rule(model, index, sequences):
    """Name each HMM state by the rule phase it co-occurs with most (Viterbi on train).

    Co-occurrence is normalised by phase frequency so rare phases (decide, adjust) can win
    a state; the Hungarian assignment first gives every phase one state, the remaining
    states take their best phase.
    """
    from scipy.optimize import linear_sum_assignment

    from career_lab.recognition.behavior import rule_phase

    states = model.n_components
    table = np.zeros((states, 4))
    for seq in sequences:
        path = model.predict(np.array([index[s] for s in seq]).reshape(-1, 1))
        submitted = False
        for symbol, state in zip(seq, path):
            table[state, rule_phase(symbol, submitted)] += 1
            submitted = submitted or symbol == "submit"
    share = table / np.maximum(table.sum(0, keepdims=True), 1)
    order = [int(share[s].argmax()) for s in range(states)]
    rows, cols = linear_sum_assignment(-share)
    for s, p in zip(rows, cols):
        order[int(s)] = int(p)
    return order, table.astype(int).tolist()


def name_states(model, vocabulary):
    """Order states by what they emit: reads/asks, configure/test, request/submit, revise."""
    groups = [
        ("read:", "ask:"),
        ("configure", "test:", "refresh_index"),
        ("request:", "approved:", "denied:", "counter:", "submit", "event:"),
        ("revise",),
    ]
    mass = np.array(
        [
            [
                sum(model.emissionprob_[s, i] for i, v in enumerate(vocabulary) if v.startswith(g))
                for g in groups
            ]
            for s in range(model.n_components)
        ]
    )
    order = []
    for state in range(model.n_components):
        order.append(int(mass[state].argmax()))
    return order, mass.round(3).tolist()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--register", action="store_true")
    args = parser.parse_args(argv)
    rows = load()
    rng = random.Random(17)
    by_strategy = {}
    for r in rows:
        by_strategy.setdefault(r["strategy"], []).append(r)
    train, test = [], []
    for name, items in sorted(by_strategy.items()):
        rng.shuffle(items)
        cut = max(1, int(len(items) * 0.8))
        train += items[:cut]
        test += items[cut:]
    labels = sorted(by_strategy)
    report = {"n_train": len(train), "n_test": len(test), "strategies": labels}

    # Strategy recognition.
    def nn(distance):
        pred = []
        for r in test:
            best = min(train, key=lambda t: distance(r["sequence"], t["sequence"]))
            pred.append(best["strategy"])
        return pred

    gold = [r["strategy"] for r in test]
    vec = DictVectorizer()
    x_train = vec.fit_transform([ngrams(r["sequence"]) for r in train])
    forest = RandomForestClassifier(n_estimators=300, random_state=0, oob_score=True)
    forest.fit(x_train, [r["strategy"] for r in train])
    results = {
        "dtw_1nn": nn(norm_dtw),
        "edit_1nn": nn(lambda a, b: edit(a, b) / max(len(a), len(b), 1)),
        "ngram_rf": list(forest.predict(vec.transform([ngrams(r["sequence"]) for r in test]))),
    }
    report["strategy"] = {
        name: {
            "accuracy": sum(a == b for a, b in zip(gold, pred)) / max(1, len(gold)),
            "macro_f1": macro_f1(gold, pred, labels),
            "confusion": confusion(gold, pred, labels),
            "by_language": {
                lang: sum(
                    a == b for a, b, r in zip(gold, pred, test) if r["language"] == lang
                ) / max(1, sum(r["language"] == lang for r in test))
                for lang in ("zh", "en")
            },
        }
        for name, pred in results.items()
    }
    report["strategy"]["ngram_rf"]["oob_score"] = float(forest.oob_score_)

    # Robustness: scripted strategies are easy to separate, so perturb the test sequences
    # (each step dropped, replaced by a random symbol, or swapped with its neighbour).
    vocab_all = sorted({s for r in rows for s in r["sequence"]})

    def perturb(seq, p, rnd):
        out = list(seq)
        i = 0
        while i < len(out):
            roll = rnd.random()
            if roll < p / 3 and len(out) > 2:
                out.pop(i)
                continue
            if roll < 2 * p / 3:
                out[i] = rnd.choice(vocab_all)
            elif roll < p and i + 1 < len(out):
                out[i], out[i + 1] = out[i + 1], out[i]
            i += 1
        return out

    robustness = {}
    for p in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5):
        rnd = random.Random(int(p * 100) + 7)
        noisy = [perturb(r["sequence"], p, rnd) for r in test]
        dtw_pred = [min(train, key=lambda t: norm_dtw(s, t["sequence"]))["strategy"] for s in noisy]
        rf_pred = list(forest.predict(vec.transform([ngrams(s) for s in noisy])))
        robustness[str(p)] = {
            "dtw_1nn": sum(a == b for a, b in zip(gold, dtw_pred)) / len(gold),
            "ngram_rf": sum(a == b for a, b in zip(gold, rf_pred)) / len(gold),
        }
    report["strategy_robustness"] = robustness
    importances = sorted(
        zip(vec.get_feature_names_out(), forest.feature_importances_), key=lambda p: -p[1]
    )[:15]
    report["strategy"]["ngram_rf"]["top_features"] = [[f, float(v)] for f, v in importances]

    # Phases: HMM with BIC-chosen state count.
    vocabulary = sorted({s for r in rows for s in r["sequence"]})
    regular_train = [r["sequence"] for r in train if r["strategy"] in REGULAR]
    bics, models = {}, {}
    for states in (3, 4, 5):
        model, bic, index = fit_hmm([r["sequence"] for r in train], vocabulary, states)
        bics[states], models[states] = float(bic), model
    best_states = min(bics, key=bics.get)
    hmm = models[best_states]
    _, mass = name_states(hmm, vocabulary)
    order, cooccurrence = name_states_by_rule(
        hmm, {v: i for i, v in enumerate(vocabulary)}, [r["sequence"] for r in train]
    )
    top_symbols = [
        [vocabulary[i] for i in np.argsort(-hmm.emissionprob_[s])[:5]] for s in range(best_states)
    ]
    report["hmm"] = {
        "bic": bics,
        "states": best_states,
        "state_phase": order,
        "state_rule_cooccurrence": cooccurrence,
        "emission_mass_by_group": mass,
        "top_symbols": top_symbols,
        "transition": hmm.transmat_.round(3).tolist(),
    }

    # Anomalies.
    anomaly_model, _, index = fit_hmm(regular_train, vocabulary, best_states, seed=1)

    def hmm_score(seq):
        known = [index[s] for s in seq if s in index]
        if not known:
            return 0.0
        return -anomaly_model.score(np.array(known).reshape(-1, 1)) / len(known)

    regular_refs = [r["sequence"] for r in train if r["strategy"] in REGULAR]
    forest_if = IsolationForest(random_state=0).fit(
        vec.transform([ngrams(s) for s in regular_refs])
    )
    y = [1 if r["expected_anomalies"] else 0 for r in test]
    scores = {
        "hmm_loglik": [hmm_score(r["sequence"]) for r in test],
        "isolation_forest": list(-forest_if.score_samples(vec.transform([ngrams(r["sequence"]) for r in test]))),
        "dtw_to_regular": [min(norm_dtw(r["sequence"], s) for s in regular_refs) for r in test],
    }
    rule_hits = [1 if r["rule_anomalies"] else 0 for r in test]
    report["anomaly"] = {
        name: {"auroc": float(roc_auc_score(y, s)) if 0 < sum(y) < len(y) else None}
        for name, s in scores.items()
    }
    report["anomaly"]["rules"] = {
        "precision": sum(a and b for a, b in zip(rule_hits, y)) / max(1, sum(rule_hits)),
        "recall": sum(a and b for a, b in zip(rule_hits, y)) / max(1, sum(y)),
    }

    # Unsupervised structure.
    sample = rows if len(rows) <= 240 else random.Random(3).sample(rows, 240)
    n = len(sample)
    dist = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            dist[i, j] = dist[j, i] = norm_dtw(sample[i]["sequence"], sample[j]["sequence"])
    tree = linkage(squareform(dist, checks=False), method="ward")
    sil = {}
    for k in range(3, 11):
        assign = fcluster(tree, k, criterion="maxclust")
        if len(set(assign)) > 1:
            sil[k] = float(silhouette_score(dist, assign, metric="precomputed"))
    best_k = max(sil, key=sil.get)
    assign = fcluster(tree, best_k, criterion="maxclust")
    report["clustering"] = {
        "silhouette": sil,
        "k": best_k,
        "ari_vs_strategy": float(adjusted_rand_score([r["strategy"] for r in sample], assign)),
        "ari_at_8": float(
            adjusted_rand_score(
                [r["strategy"] for r in sample], fcluster(tree, 8, criterion="maxclust")
            )
        ),
    }
    save("e6_behavior", report)
    for name, r in report["strategy"].items():
        print(f"strategy {name:<9} acc {r['accuracy']:.3f} macroF1 {r['macro_f1']:.3f} {r['by_language']}")
    print("hmm", report["hmm"]["bic"], "states", best_states, "phase", order)
    print("anomaly", report["anomaly"])
    print("cluster k", best_k, "ARI", round(report["clustering"]["ari_vs_strategy"], 3), "ARI@8", round(report["clustering"]["ari_at_8"], 3))

    if args.register:
        target = RECOGNIZERS / "behavior-v1"
        target.mkdir(parents=True, exist_ok=True)
        references = []
        for name in labels:
            seqs = [r["sequence"] for r in train if r["strategy"] == name]
            costs = [sum(norm_dtw(a, b) for b in seqs) for a in seqs]
            for i in np.argsort(costs)[:5]:
                references.append({"strategy": name, "sequence": seqs[int(i)]})
        with (target / "references.json").open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                {"phase_names": PHASE_NAMES, "references": references, "strategies": labels},
                handle,
                ensure_ascii=False,
                indent=1,
            )
        np.savez(
            target / "hmm.npz",
            start=hmm.startprob_,
            transition=hmm.transmat_,
            emission=hmm.emissionprob_,
            vocabulary=np.array(vocabulary),
            state_order=np.array(order),
        )
        print(register("behavior-v1", "behavior"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
