import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer, CountVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier

from career_lab.contracts.evaluation import JudgeDecision

LABELS = ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT")


def texts(items):
    return [
        item.claim + "\n" + "\n".join(e.text for e in item.candidate_evidence) for item in items
    ]


class TextClassifier:
    labels = LABELS
    revision = "unregistered"

    def __init__(self, kind="linear", seed=5002):
        self.kind = kind
        if kind == "linear":
            self.vectorizer = TfidfVectorizer(
                analyzer="char", ngram_range=(1, 3), max_features=4000
            )
            self.classifier = LogisticRegression(
                max_iter=500, random_state=seed, class_weight="balanced"
            )
        elif kind == "encoder":
            self.vectorizer = CountVectorizer(
                analyzer="char", ngram_range=(1, 2), max_features=2000, binary=True
            )
            self.classifier = MLPClassifier(
                hidden_layer_sizes=(32, 16),
                activation="tanh",
                solver="lbfgs",
                max_iter=500,
                random_state=seed,
            )
        else:
            raise ValueError("unknown model kind")

    def fit(self, items, labels):
        if set(labels) != set(LABELS):
            raise ValueError("training requires all three relation labels")
        matrix = self.vectorizer.fit_transform(texts(items))
        self.classifier.fit(matrix, labels)
        return self

    def predict_proba(self, items):
        raw = self.classifier.predict_proba(self.vectorizer.transform(texts(items)))
        order = [list(self.classifier.classes_).index(label) for label in LABELS]
        return raw[:, order]

    def judge(self, item):
        if item.task_type != "relation":
            raise ValueError("relation classifier cannot evaluate criterion labels")
        label = LABELS[int(np.argmax(self.predict_proba([item])[0]))]
        return JudgeDecision(
            label=label,
            evidence_ids=[e.id for e in item.candidate_evidence],
            reason_code="SUPERVISED_RELATION",
            explanation="Relation classifier; all-candidate citation baseline, not learned evidence selection.",
            model_revision=self.revision,
        )
