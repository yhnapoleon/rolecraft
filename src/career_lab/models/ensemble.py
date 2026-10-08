import numpy as np

from career_lab.models.linear import TextClassifier


def blend(linear, encoder, alpha):
    if not 0 <= alpha <= 1 or linear.shape != encoder.shape:
        raise ValueError("invalid blend weight or probability shape")
    return (1 - alpha) * linear + alpha * encoder


class Ensemble(TextClassifier):
    def __init__(self, linear, encoder, alpha):
        self.linear, self.encoder, self.alpha = linear, encoder, alpha
        self.kind = "ensemble"

    def predict_proba(self, items):
        return blend(
            self.linear.predict_proba(items), self.encoder.predict_proba(items), self.alpha
        )
