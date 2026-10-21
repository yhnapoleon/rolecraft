"""Stacked relation ensemble: TF-IDF + feature logistic regression stacked with C1.

E1 showed that a logistic-regression meta-learner over two pair classifiers beats either
one alone on relation-v3 (test macro-F1 zh 0.713 / en 0.633 against C1's 0.656 / 0.608):

- the lexical branch: character 2-4 gram TF-IDF of the pair text plus seven hand-crafted
  agreement features (same quantity, unit conflict, claim exceeds a stated limit, negation
  mismatch, approval claimed without evidence, expired evidence, character overlap), fed
  to a class-balanced logistic regression trained on the train pairs;
- the neural branch: the C1 XLM-R cross-encoder's temperature-scaled pair probabilities.

The meta-learner reads the six pair probabilities ``[LR(S, C, U), C1(S, C, U)]`` and was
fitted on the dev pairs. Its output replaces C1's pair probabilities before the
``pair_aggregate`` claim rule, so every consumer of ``relation.judge`` (Judge input,
pre-submission rehearsal, reply grounding, support check) uses the ensemble.

Weights come from the recognizer registry entry ``relation-stack-v1``
(``experiments/recognition/relation/fit_stack.py`` writes it): ``tfidf.joblib``,
``base_lr.joblib``, ``stacker.json`` and ``stack.json``. The entry names the C1 revision it
was fitted against; with a different C1 the ensemble is not used.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

import numpy as np

from career_lab.recognition import registry
from career_lab.recognition.relation import STACK_ID, quantities

HAND_SCALE = 3.0
NEG = re.compile(r"不|没|未|无|非|并不|别|not|no|never|isn't|aren't|doesn't|don't|without", re.I)
LIMIT = re.compile(r"上限|最多|不超过|容量|可用|预留|limit|cap|capacity|max|at most|reserved", re.I)
APPROVED = re.compile(r"已批|批准了|已经拿到|已获|approved|granted|already got", re.I)
HAND_NAMES = (
    "same_quantity",
    "unit_conflict",
    "exceeds_limit",
    "negation_mismatch",
    "approval_claimed",
    "expired_evidence",
    "char_overlap",
)


def pair_text(
    claim: str,
    as_of: int,
    text: str,
    observed: int = 0,
    valid_from: int = 0,
    valid_until: int | None = None,
) -> str:
    """``rolecraft-linear-text-v1`` pair text (the same string E1 trained on)."""
    until = "open" if valid_until is None else valid_until
    return (
        f"{claim}\nreference time {as_of}; temporal scope known\n"
        f"[EVIDENCE]\n{text}\nobserved {observed}; "
        f"valid from {valid_from}; valid until {until}"
    )


def handcrafted(claim: str, text: str, as_of: int, valid_until: int | None = None) -> list[float]:
    cq, tq = quantities(claim), quantities(text)
    same_unit = {u for _, u in cq} & {u for _, u in tq}
    claim_neg, text_neg = bool(NEG.search(claim)), bool(NEG.search(text))
    expired = valid_until is not None and valid_until <= as_of
    char_overlap = len(set(claim) & set(text)) / max(1, len(set(claim)))
    return [
        float(bool(cq & tq)),
        float(bool(same_unit) and not (cq & tq)),
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


def candidate_fields(candidate: tuple) -> tuple[int, int, int | None]:
    """(observed, valid_from, valid_until) of an ``(id, text[, o, vf, vu])`` candidate."""
    return (candidate[2], candidate[3], candidate[4]) if len(candidate) >= 5 else (0, 0, None)


class RelationStack:
    def __init__(self, path: str | Path, revision: str) -> None:
        import joblib

        root = Path(path)
        self.revision = revision
        self.config = json.loads((root / "stack.json").read_text(encoding="utf-8"))
        self.tfidf = joblib.load(root / "tfidf.joblib")
        self.base = joblib.load(root / "base_lr.joblib")
        meta = json.loads((root / "stacker.json").read_text(encoding="utf-8"))
        self.coef = np.asarray(meta["coef"], dtype=float)
        self.intercept = np.asarray(meta["intercept"], dtype=float)
        fusion = root / "fusion.json"
        self.alpha = (
            json.loads(fusion.read_text(encoding="utf-8")).get("alpha")
            if fusion.is_file()
            else None
        )

    @property
    def encoder_revision(self) -> str:
        return str(self.config.get("encoder_revision", ""))

    def base_probabilities(self, claim: str, as_of: int, candidates: Sequence[tuple]):
        from scipy.sparse import csr_matrix, hstack

        texts, hand = [], []
        for c in candidates:
            observed, valid_from, valid_until = candidate_fields(c)
            texts.append(pair_text(claim, as_of, c[1], observed, valid_from, valid_until))
            hand.append(handcrafted(claim, c[1], as_of, valid_until))
        x = hstack([self.tfidf.transform(texts), csr_matrix(np.asarray(hand) * HAND_SCALE)])
        return self.base.predict_proba(x.tocsr())

    def combine(self, base: np.ndarray, encoder: np.ndarray) -> np.ndarray:
        """Meta-learner (multinomial LR) over ``[base, encoder]`` pair probabilities."""
        logits = np.hstack([base, encoder]) @ self.coef.T + self.intercept
        logits -= logits.max(axis=1, keepdims=True)
        exp = np.exp(logits)
        return exp / exp.sum(axis=1, keepdims=True)

    def pair_probabilities(
        self, claim: str, as_of: int, candidates: Sequence[tuple], encoder: np.ndarray
    ) -> np.ndarray:
        return self.combine(self.base_probabilities(claim, as_of, candidates), encoder)


@lru_cache(maxsize=1)
def load() -> RelationStack | None:
    """The registered stack, or None (registry off, weights missing or unreadable)."""
    entry = registry.get(STACK_ID)
    if entry is None:
        return None
    try:
        return RelationStack(entry.path, entry.revision)
    except Exception:  # noqa: BLE001 - a broken export falls back to C1 alone
        return None
