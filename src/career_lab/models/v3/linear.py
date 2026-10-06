"""Train-only TF-IDF + LR baseline with a separately trained evidence selector."""
import time
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from career_lab.contracts.v2.core import ProtocolError
from .temporal import temporal_text
from .core import (LABELS, training_examples, evidence_target, checked_input, input_problem,
                   abstention, prediction, softmax)


def text(item):
    p = item.evidence
    return p.purpose+"\n"+p.claim+"\n"+temporal_text(item)+"\n"+"\n".join(c.text+"\n"+temporal_text(item,c) for c in p.candidate_evidence)


def pair_text(item, candidate):
    return item.evidence.claim+"\n"+temporal_text(item)+"\n[EVIDENCE]\n"+candidate.text+"\n"+temporal_text(item,candidate)


class ConstantCandidate:
    kind = "constant"
    def __init__(self, task_type="relation"):
        self.task_type = task_type
        self.revision = "constant-" + task_type + "-v1"
    def predict(self, item):
        item = checked_input(item)
        if item.task_type != self.task_type:
            raise ProtocolError("candidate_task_mismatch")
        if input_problem(item):
            return abstention(item, self.revision, input_problem(item))
        probs = np.zeros(len(LABELS[self.task_type]));probs[0] = 1
        return prediction(item, self.revision, probs, np.zeros(len(item.evidence.candidate_evidence)))


class LinearCandidate:
    kind = "linear"
    def __init__(self, task_type="relation", seed=5002, max_features=4000):
        if task_type not in LABELS: raise ProtocolError("unsupported_model_task")
        self.task_type, self.seed, self.max_features = task_type, seed, max_features
        self.revision = "untrained-linear"
        self.evidence_threshold=.5
        self.vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(1, 3), max_features=max_features)

    def fit(self, examples):
        rows = training_examples(examples, self.task_type)
        start = time.perf_counter()
        self.vectorizer.fit([text(r.item) for r in rows])
        X = self.vectorizer.transform([text(r.item) for r in rows])
        target = [r.annotation.final.label for r in rows]
        classifier = LogisticRegression(max_iter=500, class_weight="balanced", random_state=self.seed).fit(X, target)
        order = [list(classifier.classes_).index(label) for label in LABELS[self.task_type]]
        self.coef, self.intercept = classifier.coef_[order].copy(), classifier.intercept_[order].copy()
        pairs, gold = [], []
        for row in rows:
            accepted = evidence_target(row)
            if accepted is None: continue
            for candidate in row.item.evidence.candidate_evidence:
                pairs.append(pair_text(row.item, candidate));gold.append(int(candidate.id in accepted))
        if set(gold) != {0, 1}:
            raise ProtocolError("evidence_selector_class_coverage_missing")
        selector = LogisticRegression(max_iter=500, class_weight="balanced", random_state=self.seed).fit(self.vectorizer.transform(pairs), gold)
        self.evidence_coef, self.evidence_intercept = selector.coef_[0].copy(), float(selector.intercept_[0])
        self.revision = "trained-linear-pending-bundle"
        self.training_report = {"fit_seconds": time.perf_counter()-start, "seed": self.seed, "train_records": len(rows),
            "fit_split": "train", "architecture": "character TF-IDF + multinomial LR + binary evidence LR", "pretrained": False,
            "train_ids": [r.record_id for r in rows], "input_hashes": [r.annotation.input_hash for r in rows],
            "optimizer_iterations": classifier.n_iter_.tolist(), "evidence_pairs": len(pairs)}
        return self.training_report

    def predict(self, item):
        item = checked_input(item)
        if item.task_type != self.task_type: raise ProtocolError("candidate_task_mismatch")
        if input_problem(item): return abstention(item, self.revision, input_problem(item))
        if not hasattr(self, "coef"): raise ProtocolError("model_not_trained")
        probs = softmax(np.asarray(self.vectorizer.transform([text(item)]) @ self.coef.T)[0]+self.intercept)
        candidates = item.evidence.candidate_evidence
        scores = []
        if candidates:
            logits = np.asarray(self.vectorizer.transform([pair_text(item, c) for c in candidates]) @ self.evidence_coef).reshape(-1)+self.evidence_intercept
            scores = 1/(1+np.exp(-np.clip(logits, -50, 50)))
        return prediction(item, self.revision, probs, scores,self.evidence_threshold)

    def arrays(self):
        return {"coef": self.coef, "intercept": self.intercept, "evidence_coef": self.evidence_coef,
                "evidence_intercept": np.array([self.evidence_intercept]), "idf": self.vectorizer.idf_}

    def configuration(self):
        return {"preprocessing_revision":"historical-time-v1","kind": self.kind, "task_type": self.task_type, "seed": self.seed, "max_features": self.max_features,
                "vocabulary": {k:int(v) for k,v in self.vectorizer.vocabulary_.items()},"evidence_threshold":self.evidence_threshold, "labels": list(LABELS[self.task_type]), "training_report": self.training_report}

    @classmethod
    def restore(cls, config, arrays):
        obj = cls(config["task_type"], config["seed"], config["max_features"])
        vocab = config["vocabulary"]
        if set(vocab.values()) != set(range(len(vocab))) or config["labels"] != list(LABELS[obj.task_type]):
            raise ProtocolError("model_vocabulary_or_labels_invalid")
        obj.vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(1, 3), vocabulary=vocab)
        obj.vectorizer.idf_ = arrays["idf"]
        n, k = len(vocab), len(LABELS[obj.task_type])
        shapes = {"coef": (k,n), "intercept": (k,), "evidence_coef": (n,), "evidence_intercept": (1,), "idf": (n,)}
        if set(arrays) != set(shapes) or any(arrays[a].shape != shape or not np.isfinite(arrays[a]).all() for a, shape in shapes.items()):
            raise ProtocolError("model_array_shape_invalid")
        obj.coef, obj.intercept, obj.evidence_coef = arrays["coef"], arrays["intercept"], arrays["evidence_coef"]
        obj.evidence_intercept = float(arrays["evidence_intercept"][0]);obj.training_report=config["training_report"];obj.evidence_threshold=config["evidence_threshold"]
        return obj
