"""E7 / C11: question-intent recognition.

    python -m experiments.recognition.intent [--register]

Main model: TF-IDF character 2-4 grams + multinomial logistic regression, one bilingual
model, C chosen on dev. Baselines on the same features: multinomial naive Bayes and a
linear SVM; plus the keyword rule the product falls back to. Reports accuracy, macro-F1,
per-class P/R/F1 and confusion matrices per language on test; with ``--register`` the
model is saved to ``$CAREER_LAB_RECOGNIZERS/intent-tfidf-lr-v1`` and entered in the manifest.
"""

from __future__ import annotations

import argparse
import json

import joblib
from career_lab.recognition.intent import LABELS, rule_intent
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

from experiments.recognition.common import (
    DATA,
    RECOGNIZERS,
    confusion,
    jsonl,
    macro_f1,
    per_class,
    register,
    save,
)


def features():
    return TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1, sublinear_tf=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--register", action="store_true")
    args = parser.parse_args(argv)
    rows = jsonl(DATA / "intent-v1" / "intent.jsonl")
    part = {s: [r for r in rows if r["split"] == s] for s in ("train", "dev", "test")}
    labels = list(LABELS)

    def xy(split):
        return [r["text"] for r in part[split]], [r["intent"] for r in part[split]]

    x_train, y_train = xy("train")
    x_dev, y_dev = xy("dev")
    x_test, y_test = xy("test")
    grid = {}
    for c in (0.5, 1, 2, 4, 8, 16):
        model = Pipeline([("tfidf", features()), ("lr", LogisticRegression(C=c, max_iter=2000))])
        model.fit(x_train, y_train)
        grid[c] = macro_f1(y_dev, list(model.predict(x_dev)), labels)
    best_c = max(grid, key=grid.get)
    main_model = Pipeline(
        [("tfidf", features()), ("lr", LogisticRegression(C=best_c, max_iter=2000))]
    )
    main_model.fit(x_train + x_dev, y_train + y_dev)
    candidates = {
        "tfidf_lr": main_model,
        "tfidf_nb": Pipeline([("tfidf", features()), ("nb", MultinomialNB(alpha=0.1))]).fit(
            x_train + x_dev, y_train + y_dev
        ),
        "tfidf_svm": Pipeline([("tfidf", features()), ("svm", LinearSVC(C=1.0))]).fit(
            x_train + x_dev, y_train + y_dev
        ),
    }
    report = {"labels": labels, "dev_grid_macro_f1": grid, "best_C": best_c, "models": {}}
    for name, model in [*candidates.items(), ("keyword_rule", None)]:
        entry = {}
        for language in ("zh", "en", "all"):
            subset = [
                (x, y)
                for x, y, r in zip(x_test, y_test, part["test"], strict=False)
                if language == "all" or r["language"] == language
            ]
            xs, ys = [x for x, _ in subset], [y for _, y in subset]
            pred = [rule_intent(x)[0] for x in xs] if model is None else list(model.predict(xs))
            entry[language] = {
                "n": len(ys),
                "accuracy": sum(a == b for a, b in zip(ys, pred, strict=False)) / max(1, len(ys)),
                "macro_f1": macro_f1(ys, pred, labels),
                "per_class": per_class(ys, pred, labels),
                "confusion": confusion(ys, pred, labels),
            }
        report["models"][name] = entry
    save("e7_intent", report)
    for name, entry in report["models"].items():
        print(
            f"{name:<13} acc zh {entry['zh']['accuracy']:.3f} en {entry['en']['accuracy']:.3f} "
            f"macroF1 all {entry['all']['macro_f1']:.3f}"
        )
    if args.register:
        target = RECOGNIZERS / "intent-tfidf-lr-v1"
        target.mkdir(parents=True, exist_ok=True)
        joblib.dump(main_model, target / "model.joblib")
        with (target / "labels.json").open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(list(main_model.classes_), handle)
        print(register("intent-tfidf-lr-v1", "intent"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
