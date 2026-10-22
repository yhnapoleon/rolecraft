"""E13: the recognizers on the public data (``docs/data/public-sources-v1.md`` section 7).

    python -m experiments.recognition.public_eval reply|scope|retrieval|sequence|intent|all
        [--limit 300]

Each task writes ``results/e13_<task>.json``. The product recognizers are either run as they
are (C10, C2, C11 transfer), or their method is refitted on the public dataset's own train
split (C4, C5, C11 in domain), with the E5 / E6 / E7 baselines alongside.

- reply (C10): the calls ``check_reply`` makes (C2 top-3 over the visible sources, then
  C1 + stack + rule; the private facts likewise for leaks) on public-reply-v1 test
  (RAGTruth; a sample of replies stratified by task and by whether the reply has a problem,
  ``--limit``) and public-reply-synth-v1 test (with leaks). Baseline: the rule fallback
  (no C1). Sentence level: grounded / conflict / baseless against supported /
  contradicted / insufficient, the binary "not grounded" decision and the AUROC of
  1 - P(supported); reply level: has a problem; leak precision / recall.
- scope (C4): the product's detector (Ledoit-Wolf Mahalanobis on e5-small query vectors of
  the in-scope examples, threshold at 95 % TPR on dev in-scope) fitted on each dataset's
  in-scope train questions; baselines as E5 (autoencoder at 500 iterations, one-class SVM
  fitted on at most 3,000 points) plus two that use intent labels: class-conditional
  Mahalanobis (shared covariance) and maximum softmax probability of a logistic
  regression. CLINC150 (en), MASSIVE (zh, en; near and far), public-queries-synth-v1
  (zh, en; KB units plus in-scope train questions are the fit set, topic source as class).
- retrieval (C2): BM25 / e5 dense / RRF as the product calls them, within the question's own
  document: PrivacyQA (test with any-annotator and majority relevance, train + dev with the
  expert label) and the in-scope questions of public-queries-synth-v1 (within their
  context, and over the whole KB). Recall@1/3/5 and MRR of the first relevant unit;
  PrivacyQA answerability as the AUROC of the top dense and BM25 scores.
- sequence (C5): tau-bench success / failure and the Jira outcome, the latter cut before the
  first resolution or closing event so the label is not in the input. DTW 1-NN (the
  product's substitution cost), edit-distance 1-NN, 1-3 gram random forest, one HMM per
  class (per-step log-likelihood), sequence length alone and the majority class.
- intent (C11): the registered model on public-intent-synth-v1 test (transfer), the E7
  recipe refitted on the synthetic train (in domain) and on intent-v1 + synthetic train
  (mixed), each read on both test sets, plus the keyword rule.
"""

from __future__ import annotations

import argparse
import os
import random
import re
from collections import Counter

import numpy as np
from sklearn.metrics import roc_auc_score

from experiments.recognition.common import (
    DATA,
    RECOGNIZERS,
    confusion,
    jsonl,
    macro_f1,
    per_class,
    save,
)

os.environ.setdefault("CAREER_LAB_RECOGNIZERS", str(RECOGNIZERS))
os.environ.setdefault("CAREER_LAB_RELATION_ENCODER", str(RECOGNIZERS / "c1-xlmr-cpu"))

INF = float("inf")


def auroc(y, score):
    y = [int(bool(v)) for v in y]
    return float(roc_auc_score(y, score)) if 0 < sum(y) < len(y) else None


def prf(y, flagged):
    tp = sum(a and b for a, b in zip(y, flagged, strict=True))
    fp = sum(b and not a for a, b in zip(y, flagged, strict=True))
    fn = sum(a and not b for a, b in zip(y, flagged, strict=True))
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {
        "precision": p,
        "recall": r,
        "f1": 2 * p * r / (p + r) if p + r else 0.0,
        "positives": int(sum(y)),
        "flagged": int(sum(flagged)),
        "n": len(y),
    }


def classification(gold, pred, labels):
    return {
        "n": len(gold),
        "accuracy": float(np.mean([a == b for a, b in zip(gold, pred, strict=True)])),
        "macro_f1": macro_f1(gold, pred, labels),
        "per_class": per_class(gold, pred, labels),
        "confusion": confusion(gold, pred, labels),
    }


# --- C10 reply check -------------------------------------------------------------------

GOLD3 = {"grounded": "supported", "conflict": "contradicted", "baseless": "insufficient"}
REL3 = ["supported", "contradicted", "insufficient"]


def stratified(rows, limit, key, seed=0):
    if not limit or len(rows) <= limit:
        return rows
    groups = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r)
    per = max(1, limit // len(groups))
    rng = random.Random(seed)
    picked = []
    for k in sorted(groups):
        picked += rng.sample(groups[k], min(per, len(groups[k])))
    return picked


def judge_reply(row, visible, private):
    """The two ``relation.judge`` calls of ``check_reply`` per sentence, keeping P(supported).

    Sentences are the gold ones (the product's splitter does not end a sentence at a period
    after a digit, so "version 1.5.2. It was" stays one sentence); whether the splitter
    agrees is reported separately.
    """
    from career_lab.models.v3.units import split_sentences
    from career_lab.recognition import relation
    from career_lab.recognition.reply import MIN_CHARACTERS

    def long_enough(text):
        return sum(not c.isspace() for c in text) >= MIN_CHARACTERS

    kept = [s.text for s in split_sentences(row["reply"]) if long_enough(s.text)]
    gold = [s for s in row["sentences"] if long_enough(s["text"])]
    row["_splitter_agrees"] = [s["text"] for s in gold] == kept
    out = []
    for s in gold:
        seen = relation.judge(s["text"], visible, language=row["language"], k=3)
        leak = False
        if private:
            hidden = relation.judge(s["text"], private, language=row["language"], k=3)
            leak = hidden.label == "supported" and seen.label != "supported"
        out.append(
            {
                "gold": s["label"],
                "pred": seen.label,
                "p_supported": float(seen.probabilities["supported"]),
                "leak": leak,
                "fallback": seen.fallback,
            }
        )
    return out


def reply_metrics(judged):
    sents = [s for _, out in judged for s in out]
    three = [s for s in sents if s["gold"] in GOLD3]
    bad = [s["gold"] != "grounded" for s in sents]
    report = {
        "replies": len(judged),
        "sentences": len(sents),
        "gold": dict(Counter(s["gold"] for s in sents)),
        "predicted": dict(Counter(s["pred"] for s in sents)),
        "fallback_share": float(np.mean([s["fallback"] for s in sents])) if sents else None,
        "three_class": classification(
            [GOLD3[s["gold"]] for s in three], [s["pred"] for s in three], REL3
        ),
        "not_grounded": {
            **prf(bad, [s["pred"] != "supported" for s in sents]),
            "auroc": auroc(bad, [1 - s["p_supported"] for s in sents]),
        },
    }
    reply_bad = [any(s["gold"] != "grounded" for s in out) for _, out in judged]
    report["reply_level"] = {
        **prf(
            reply_bad, [any(s["pred"] != "supported" or s["leak"] for s in o) for _, o in judged]
        ),
        "auroc": auroc(
            reply_bad, [max((1 - s["p_supported"] for s in o), default=0) for _, o in judged]
        ),
    }
    if any(s["gold"] == "leak" for s in sents):
        report["leak"] = prf([s["gold"] == "leak" for s in sents], [s["leak"] for s in sents])
    return report


def run_reply(args):
    from career_lab.recognition import relation

    if relation.encoder_relation() is None:
        raise SystemExit("C1 unavailable: run under .venv-encoder with CAREER_LAB_RELATION_ENCODER")
    real = [r for r in jsonl(DATA / "public-reply-v1" / "replies.jsonl") if r["split"] == "test"]
    real = stratified(real, args.limit, lambda r: (r["task_type"], r["has_problem"]))
    sources = {s["source_id"]: s for s in jsonl(DATA / "public-reply-v1" / "sources.jsonl")}
    synth = [
        r for r in jsonl(DATA / "public-reply-synth-v1" / "replies.jsonl") if r["split"] == "test"
    ]

    def inputs(row):
        if "visible" in row:
            return (
                [(u["id"], u["text"]) for u in row["visible"]],
                [(u["id"], u["text"]) for u in row.get("private", [])],
            )
        return [(u["id"], u["text"]) for u in sources[row["source_id"]]["units"]], []

    report = {"limit": args.limit, "datasets": {}}
    original = relation.encoder_relation
    for chain in ("product", "rule_fallback"):
        if chain == "rule_fallback":
            relation.encoder_relation = lambda: None
        try:
            for name, rows in (("ragtruth", real), ("synth", synth)):
                judged = []
                for i, row in enumerate(rows):
                    judged.append((row, judge_reply(row, *inputs(row))))
                    if (i + 1) % 50 == 0:
                        print(chain, name, i + 1, "/", len(rows), flush=True)
                entry = {
                    **reply_metrics(judged),
                    "splitter_agreement": float(np.mean([r["_splitter_agrees"] for r in rows])),
                }
                groups = "task_type" if name == "ragtruth" else "language"
                entry["by_" + groups] = {
                    g: reply_metrics([(r, o) for r, o in judged if r[groups] == g])
                    for g in sorted({r[groups] for r, _ in judged})
                }
                report["datasets"].setdefault(name, {})[chain] = entry
                print(
                    chain,
                    name,
                    "3-class",
                    round(entry["three_class"]["macro_f1"], 3),
                    "not-grounded F1",
                    round(entry["not_grounded"]["f1"], 3),
                    "AUROC",
                    entry["not_grounded"]["auroc"],
                    flush=True,
                )
        finally:
            relation.encoder_relation = original
    return report


# --- C4 scope --------------------------------------------------------------------------


def embed(texts, kind="query"):
    from career_lab.recognition.embedder import Embedder

    embedder = Embedder.get()
    if embedder is None:
        raise SystemExit("embedder unavailable: run under .venv-encoder with retrieval-e5 present")
    return embedder.encode(list(texts), kind)


def whitener(vectors):
    """Mean and Cholesky factor of the Ledoit-Wolf precision: Mahalanobis = |(x - m) L|."""
    from sklearn.covariance import LedoitWolf

    lw = LedoitWolf().fit(vectors)
    return lw.location_, np.linalg.cholesky(lw.precision_)


def scope_scores(fit, fit_labels, queries):
    from scipy.spatial.distance import cdist
    from sklearn.cluster import KMeans
    from sklearn.ensemble import IsolationForest
    from sklearn.linear_model import LogisticRegression
    from sklearn.neural_network import MLPRegressor
    from sklearn.svm import OneClassSVM

    d = fit.shape[1]
    mean, chol = whitener(fit)
    scores = {"mahalanobis": np.linalg.norm((queries - mean) @ chol, axis=1) / np.sqrt(d)}
    classes = sorted(set(fit_labels))
    labels = np.array(fit_labels)
    centred = np.vstack([fit[labels == c] - fit[labels == c].mean(0) for c in classes])
    _, chol_c = whitener(centred)
    means = np.vstack([fit[labels == c].mean(0) for c in classes]) @ chol_c
    scores["class_mahalanobis"] = cdist(queries @ chol_c, means).min(1) / np.sqrt(d)
    msp = LogisticRegression(max_iter=2000).fit(fit, labels)
    scores["max_softmax"] = -msp.predict_proba(queries).max(1)
    scores["max_cosine"] = -(queries @ fit.T).max(1)
    km = KMeans(n_clusters=min(8, len(fit) // 4), n_init=10, random_state=0).fit(fit)
    scores["kmeans_centroid"] = km.transform(queries).min(1)
    mu, var = fit.mean(0), fit.var(0) + 1e-4
    scores["gaussian_nb"] = (((queries - mu) ** 2) / var + np.log(var)).sum(1)
    ae = MLPRegressor(hidden_layer_sizes=(32,), max_iter=500, random_state=0).fit(fit, fit)
    scores["autoencoder"] = ((ae.predict(queries) - queries) ** 2).sum(1)
    sub = fit[np.random.default_rng(0).permutation(len(fit))[:3000]]
    scores["one_class_svm"] = -OneClassSVM(nu=0.1, gamma="scale").fit(sub).score_samples(queries)
    scores["isolation_forest"] = -IsolationForest(random_state=0).fit(fit).score_samples(queries)
    return scores


def scope_case(fit_texts, fit_labels, rows):
    """rows: dev / test questions with ``split`` and ``kind``; in scope = ``in_*`` kinds."""
    from experiments.recognition.scope import evaluate

    fit = embed(fit_texts)
    vectors = embed([r["query"] for r in rows])
    scores = scope_scores(fit, fit_labels, vectors)
    split = np.array([r["split"] for r in rows])
    kind = np.array([r["kind"] for r in rows])
    inside = np.char.startswith(kind.astype(str), "in")
    dev_in, test = (split == "dev") & inside, split == "test"
    groups = {"all_out": test & ~inside}
    for k in ("out_near", "out_far"):
        if (test & (kind == k)).any():
            groups[k] = test & (kind == k)
    out = {
        "n_fit": len(fit_texts),
        "classes": len(set(fit_labels)),
        "n_test_in": int((test & inside).sum()),
        **{f"n_test_{g}": int(m.sum()) for g, m in groups.items()},
        "methods": {},
    }
    for name, s in scores.items():
        threshold = float(np.quantile(s[dev_in], 0.95))
        entry = {g: evaluate(s[test & inside], s[mask]) for g, mask in groups.items() if mask.any()}
        entry["dev_threshold"] = threshold
        entry["in_rejected_at_threshold"] = float(np.mean(s[test & inside] > threshold))
        entry["out_accepted_at_threshold"] = float(np.mean(s[groups["all_out"]] <= threshold))
        entry["accuracy_at_threshold"] = float(np.mean((s[test] > threshold) == ~inside[test]))
        out["methods"][name] = entry
    return out


def run_scope(args):
    report = {}
    clinc = jsonl(DATA / "public-scope-v1" / "clinc150.jsonl")
    fit = [r for r in clinc if r["split"] == "train" and r["kind"] == "in_direct"]
    report["clinc150/en"] = scope_case(
        [r["query"] for r in fit],
        [r["intent"] for r in fit],
        [r for r in clinc if r["split"] != "train"],
    )
    massive = jsonl(DATA / "public-scope-v1" / "massive.jsonl")
    for language in ("zh", "en"):
        rows = [r for r in massive if r["language"] == language]
        fit = [r for r in rows if r["split"] == "train" and r["kind"] == "in_direct"]
        report[f"massive/{language}"] = scope_case(
            [r["query"] for r in fit],
            [r["intent"] for r in fit],
            [r for r in rows if r["split"] != "train"],
        )
    queries = jsonl(DATA / "public-queries-synth-v1" / "queries.jsonl")
    kb = jsonl(DATA / "public-queries-synth-v1" / "kb.jsonl")
    for language in ("zh", "en"):
        units = {}
        for context in kb:
            for u in context["units"]:
                units[u["id"]] = (u[language], context["source_id"])
        rows = [q for q in queries if q["language"] == language]
        fit = [q for q in rows if q["split"] == "train" and q["kind"].startswith("in")]
        report[f"queries-synth/{language}"] = scope_case(
            [t for t, _ in units.values()] + [q["query"] for q in fit],
            [s for _, s in units.values()] + [q["domain"] for q in fit],
            [q for q in rows if q["split"] != "train"],
        )
    for key, case in report.items():
        print(
            key,
            {m: round(v["all_out"]["auroc"], 3) for m, v in case["methods"].items()},
            flush=True,
        )
    return report


# --- C2 retrieval ----------------------------------------------------------------------


def first_relevant(query, texts, ids, gold, method):
    from career_lab.recognition import retrieval

    hits, _, _ = retrieval.search(query, texts, k=len(texts), method=method)
    for h in hits:
        if ids[h.index] in gold:
            return h.rank, hits
    return len(texts) + 1, hits


def rank_report(ranks):
    ranks = np.asarray(ranks)
    return {
        "n": int(len(ranks)),
        "recall@1": float(np.mean(ranks <= 1)),
        "recall@3": float(np.mean(ranks <= 3)),
        "recall@5": float(np.mean(ranks <= 5)),
        "mrr": float(np.mean(1.0 / ranks)),
    }


def run_retrieval(args):
    report = {"privacyqa": {}, "queries-synth": {}}
    policies = {
        p["doc_id"]: p["units"] for p in jsonl(DATA / "public-retrieval-v1" / "policies.jsonl")
    }
    queries = jsonl(DATA / "public-retrieval-v1" / "queries.jsonl")
    embed([u["text"] for units in policies.values() for u in units], "passage")
    cases = {
        "test_any": ([q for q in queries if q["split"] == "test"], "relevant_unit_ids"),
        "test_majority": (
            [q for q in queries if q["split"] == "test"],
            "relevant_majority_unit_ids",
        ),
        "train_dev_expert": ([q for q in queries if q["split"] != "test"], "relevant_unit_ids"),
    }
    for case, (rows, field) in cases.items():
        entry = {}
        for method in ("bm25", "dense", "rrf"):
            ranks, top_dense, top_bm25, answerable = [], [], [], []
            for q in rows:
                units = policies[q["doc_id"]]
                gold = set(q.get(field) or [])
                rank, hits = first_relevant(
                    q["query"], [u["text"] for u in units], [u["id"] for u in units], gold, method
                )
                if gold:
                    ranks.append(rank)
                if method == "rrf":
                    top_dense.append(max((h.dense or 0.0) for h in hits))
                    top_bm25.append(max(h.bm25 for h in hits))
                    answerable.append(q["answerable"])
            entry[method] = rank_report(ranks)
            if method == "rrf" and case != "test_majority":
                entry["answerability_auroc"] = {
                    "top_dense": auroc(answerable, top_dense),
                    "top_bm25": auroc(answerable, top_bm25),
                    "answerable": int(sum(answerable)),
                    "n": len(answerable),
                }
        report["privacyqa"][case] = entry
        print(
            "privacyqa",
            case,
            {m: round(entry[m]["mrr"], 3) for m in ("bm25", "dense", "rrf")},
            flush=True,
        )
    kb = jsonl(DATA / "public-queries-synth-v1" / "kb.jsonl")
    synth = jsonl(DATA / "public-queries-synth-v1" / "queries.jsonl")
    for language in ("zh", "en"):
        units = {u["id"]: u[language] for c in kb for u in c["units"]}
        all_ids = list(units)
        rows = [q for q in synth if q["language"] == language and q["kind"].startswith("in")]
        entry = {}
        for scope in ("context", "whole_kb"):
            for method in ("bm25", "dense", "rrf"):
                ranks, by_kind = [], {}
                for q in rows:
                    ids = q["kb_unit_ids"] if scope == "context" else all_ids
                    rank, _ = first_relevant(
                        q["query"], [units[i] for i in ids], ids, {q["answer_unit_id"]}, method
                    )
                    ranks.append(rank)
                    by_kind.setdefault(q["kind"], []).append(rank)
                entry[f"{scope}/{method}"] = {
                    **rank_report(ranks),
                    "by_kind": {k: rank_report(v) for k, v in sorted(by_kind.items())},
                }
        report["queries-synth"][language] = entry
        print(
            "queries-synth",
            language,
            {k: round(v["mrr"], 3) for k, v in entry.items()},
            flush=True,
        )
    return report


# --- C5 behaviour ----------------------------------------------------------------------

TERMINAL = re.compile(r"^(resolution:|status:(closed|resolved|done|verified))")


def jira_prefix(sequence):
    for i, symbol in enumerate(sequence):
        if TERMINAL.match(symbol):
            return sequence[:i]
    return sequence


def dtw_fast(a, b):
    """``career_lab.recognition.behavior.dtw`` with plain lists (same recurrence and costs)."""
    heads = [y.split(":")[0] for y in b]
    prev = [0.0] + [INF] * len(b)
    for x in a:
        hx = x.split(":")[0]
        cur = [INF] * (len(b) + 1)
        for j, y in enumerate(b, start=1):
            cost = 0.0 if x == y else (0.5 if hx == heads[j - 1] else 1.0)
            cur[j] = cost + min(prev[j], cur[j - 1], prev[j - 1])
        prev = cur
    return prev[-1] / max(len(a), len(b), 1)


def edit_fast(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, start=1):
        cur = [i] + [0] * len(b)
        for j, y in enumerate(b, start=1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y))
        prev = cur
    return prev[-1] / max(len(a), len(b), 1)


def sequence_case(train, test, labels, positive=None):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.linear_model import LogisticRegression

    from career_lab.recognition.behavior import dtw
    from experiments.recognition.behavior import fit_hmm, ngrams

    rnd = random.Random(0)
    for _ in range(20):
        a, b = rnd.choice(train)["sequence"], rnd.choice(test)["sequence"]
        assert abs(dtw_fast(a, b) - dtw(a, b) / max(len(a), len(b), 1)) < 1e-9
    gold = [r["label"] for r in test]
    y_train = [r["label"] for r in train]
    preds, scores = {}, {}

    for name, distance in (("dtw_1nn", dtw_fast), ("edit_1nn", edit_fast)):
        nearest = []
        for r in test:
            best = {}
            for t in train:
                d = distance(r["sequence"], t["sequence"])
                if d < best.get(t["label"], INF):
                    best[t["label"]] = d
            nearest.append(best)
        preds[name] = [min(b, key=b.get) for b in nearest]
        if positive:
            other = [lab for lab in labels if lab != positive][0]
            scores[name] = [b.get(other, INF) - b.get(positive, INF) for b in nearest]

    vec = DictVectorizer()
    x_train = vec.fit_transform([ngrams(r["sequence"]) for r in train])
    x_test = vec.transform([ngrams(r["sequence"]) for r in test])
    forest = RandomForestClassifier(n_estimators=300, random_state=0).fit(x_train, y_train)
    preds["ngram_rf"] = list(forest.predict(x_test))
    if positive:
        scores["ngram_rf"] = list(
            forest.predict_proba(x_test)[:, list(forest.classes_).index(positive)]
        )
    top = sorted(
        zip(vec.get_feature_names_out(), forest.feature_importances_, strict=True),
        key=lambda p: -p[1],
    )

    vocabulary = sorted({s for r in train + test for s in r["sequence"]})
    bics = {k: fit_hmm([r["sequence"] for r in train], vocabulary, k)[1] for k in (3, 4, 5)}
    states = min(bics, key=bics.get)
    per_label = {
        lab: fit_hmm([r["sequence"] for r in train if r["label"] == lab], vocabulary, states)
        for lab in labels
    }

    def loglik(lab, seq):
        model, _, index = per_label[lab]
        return model.score(np.array([index[s] for s in seq]).reshape(-1, 1)) / len(seq)

    ll = [{lab: loglik(lab, r["sequence"]) for lab in labels} for r in test]
    preds["hmm_per_class"] = [max(v, key=v.get) for v in ll]
    if positive:
        other = [lab for lab in labels if lab != positive][0]
        scores["hmm_per_class"] = [v[positive] - v[other] for v in ll]

    length = LogisticRegression(class_weight="balanced").fit(
        [[len(r["sequence"])] for r in train], y_train
    )
    preds["length_only"] = list(length.predict([[len(r["sequence"])] for r in test]))
    if positive:
        index = list(length.classes_).index(positive)
        scores["length_only"] = list(
            length.predict_proba([[len(r["sequence"])] for r in test])[:, index]
        )
    majority = Counter(y_train).most_common(1)[0][0]
    preds["majority"] = [majority] * len(test)

    out = {
        "n_train": len(train),
        "n_test": len(test),
        "labels": dict(Counter(gold)),
        "vocabulary": len(vocabulary),
        "hmm_states_bic": states,
        "methods": {},
        "ngram_rf_top_features": [[f, float(v)] for f, v in top[:12]],
    }
    for name, pred in preds.items():
        entry = classification(gold, pred, labels)
        if name in scores:
            entry["auroc"] = auroc([g == positive for g in gold], scores[name])
        out["methods"][name] = entry
    return out


def run_sequence(args):
    report = {}
    tau = jsonl(DATA / "public-sequence-v1" / "taubench.jsonl")
    report["tau-bench"] = sequence_case(
        [r for r in tau if r["split"] == "train"],
        [r for r in tau if r["split"] == "test"],
        ["success", "failure"],
        positive="failure",
    )
    jira, dropped = [], 0
    for r in jsonl(DATA / "public-sequence-v1" / "jira.jsonl"):
        prefix = jira_prefix(r["sequence"])
        if not prefix:
            dropped += 1
            continue
        jira.append({**r, "sequence": prefix})
    report["jira"] = sequence_case(
        [r for r in jira if r["split"] == "train"],
        [r for r in jira if r["split"] == "test"],
        ["fixed", "closed_other", "unresolved"],
    )
    report["jira"]["cut"] = "before the first resolution:* or status:closed|resolved|done|verified"
    report["jira"]["dropped_empty_prefix"] = dropped
    for key, case in report.items():
        print(
            key,
            {m: (round(v["macro_f1"], 3), v.get("auroc")) for m, v in case["methods"].items()},
            flush=True,
        )
    return report


# --- C11 intent ------------------------------------------------------------------------


def run_intent(args):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    from career_lab.recognition.intent import LABELS, _model, rule_intent
    from experiments.recognition.intent import features

    labels = list(LABELS)
    sets = {
        "intent-v1": jsonl(DATA / "intent-v1" / "intent.jsonl"),
        "intent-synth": jsonl(DATA / "public-intent-synth-v1" / "intent.jsonl"),
    }

    def part(name, split):
        return [r for r in sets[name] if r["split"] == split]

    def refit(train, dev):
        grid = {}
        for c in (0.5, 1, 2, 4, 8, 16):
            model = Pipeline(
                [("tfidf", features()), ("lr", LogisticRegression(C=c, max_iter=2000))]
            )
            model.fit([r["text"] for r in train], [r["intent"] for r in train])
            grid[c] = macro_f1(
                [r["intent"] for r in dev], list(model.predict([r["text"] for r in dev])), labels
            )
        best = max(grid, key=grid.get)
        model = Pipeline([("tfidf", features()), ("lr", LogisticRegression(C=best, max_iter=2000))])
        model.fit([r["text"] for r in train + dev], [r["intent"] for r in train + dev])
        return model, best

    loaded = _model()
    if loaded is None:
        raise SystemExit("intent-tfidf-lr-v1 not registered under CAREER_LAB_RECOGNIZERS")
    product = loaded[0]
    synth_model, synth_c = refit(part("intent-synth", "train"), part("intent-synth", "dev"))
    mixed_model, mixed_c = refit(
        part("intent-v1", "train") + part("intent-synth", "train"),
        part("intent-v1", "dev") + part("intent-synth", "dev"),
    )
    models = {
        "product (intent-v1)": product.predict,
        f"refit synth (C={synth_c:g})": synth_model.predict,
        f"refit intent-v1 + synth (C={mixed_c:g})": mixed_model.predict,
        "keyword_rule": lambda texts: [rule_intent(t)[0] for t in texts],
    }
    report = {"labels": labels, "models": {}}
    for name, predict in models.items():
        entry = {}
        for test in sets:
            rows = part(test, "test")
            entry[test] = {
                lang: classification(
                    [r["intent"] for r in rows if lang == "all" or r["language"] == lang],
                    list(
                        predict([r["text"] for r in rows if lang == "all" or r["language"] == lang])
                    ),
                    labels,
                )
                for lang in ("zh", "en", "all")
            }
        report["models"][name] = entry
        print(
            name,
            {
                t: {lang: round(entry[t][lang]["macro_f1"], 3) for lang in ("zh", "en")}
                for t in sets
            },
            flush=True,
        )
    return report


TASKS = {
    "intent": run_intent,
    "sequence": run_sequence,
    "retrieval": run_retrieval,
    "scope": run_scope,
    "reply": run_reply,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", choices=[*TASKS, "all"])
    parser.add_argument("--limit", type=int, default=300, help="RAGTruth test replies (reply)")
    args = parser.parse_args(argv)
    for task in TASKS if args.task == "all" else [args.task]:
        print("saved", save(f"e13_{task}", TASKS[task](args)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
