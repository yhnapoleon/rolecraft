"""C1 relation judgement for the recognition layer: claim sentence vs. evidence units.

The trained XLM-R pair model lives in ``models/v3`` and is registered through
``registry_cli``; ``encoder_relation()`` loads it when ``CAREER_LAB_RELATION_ENCODER``
names an exported model directory (S6). Until then every call uses the rule fallback
below, marked ``fallback`` in its record:

- numbers with units are read from the claim and each candidate (people, CNY, days,
  person-days, hours, percent);
- a candidate that states a limit (cap / at most / capacity / reserved ...) in the same
  unit with a smaller number than the claim contradicts it;
- the same number in the same unit with lexical overlap supports it; strong lexical
  overlap alone weakly supports it; everything else is insufficient.

Probabilities are calibrated by hand for the fallback, so the cost-sensitive decision
(C6) treats rule contradictions with appropriate caution.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache

from career_lab.recognition import retrieval
from career_lab.recognition.base import FALLBACK_REVISION

LABELS = ("supported", "contradicted", "insufficient")
RULE_ID = "relation-rule-v1"
ENCODER_ID = "xlm-r-pair-v1"
TOP_K = 5

_UNITS = (
    (r"人日|person[- ]days?|developer[- ]days?|dev[- ]days?", "pday"),
    (r"人|名|位|people|persons?|seats?|users?|employees?|staff", "person"),
    (r"元|cny|yuan|rmb", "cny"),
    (r"小时|hours?|h\b", "hour"),
    (r"天|日|days?", "day"),
    (r"%|percent", "pct"),
)
_NUMBER = re.compile(
    r"(?:cny|rmb|¥)?\s*(\d+(?:\.\d+)?)\s*("
    + "|".join(p for p, _ in _UNITS)
    + r")",
    re.IGNORECASE,
)
_CURRENCY_FIRST = re.compile(r"(?:cny|rmb|¥|yuan)\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_DAY_INDEX = re.compile(r"第\s*(\d+)\s*天|day\s*(\d+)", re.IGNORECASE)
_LIMIT = re.compile(
    r"上限|最多|不超过|至多|容量|预留|可用|限额|封顶|limit|cap\b|caps|capacity|maximum|\bmax\b|"
    r"at most|up to|reserved|available|no more than",
    re.IGNORECASE,
)


def quantities(text: str) -> set[tuple[float, str]]:
    found = set()
    for value, unit in _NUMBER.findall(text):
        for pattern, name in _UNITS:
            if re.fullmatch(pattern, unit, re.IGNORECASE):
                found.add((float(value), name))
                break
    for value in _CURRENCY_FIRST.findall(text):
        found.add((float(value), "cny"))
    for a, b in _DAY_INDEX.findall(text):
        found.add((float(a or b), "day_index"))
    return found


@dataclass(frozen=True)
class Judgement:
    label: str
    probabilities: dict[str, float]
    evidence_ids: tuple[str, ...] = ()
    recognizer_id: str = RULE_ID
    revision: str = FALLBACK_REVISION
    fallback: bool = True
    reason: str = ""
    top: tuple[dict, ...] = field(default_factory=tuple)

    @property
    def confidence(self) -> float:
        return max(self.probabilities.values())


def _distribution(label: str, p: float) -> dict[str, float]:
    rest = (1.0 - p) / 2
    return {name: (p if name == label else rest) for name in LABELS}


def rule_judge(claim: str, candidates: Sequence[tuple[str, str]], lexical: Sequence[float]):
    """Rule fallback over already retrieved (id, text) candidates and their BM25 scores."""
    claimed = quantities(claim)
    contradiction: tuple[float, str, str] | None = None
    support: tuple[float, str, str] | None = None
    for cand, lex in zip(candidates, lexical):
        cid, text = cand[0], cand[1]
        stated = quantities(text)
        limited = bool(_LIMIT.search(text))
        for value, unit in claimed:
            same_unit = [v for v, u in stated if u == unit]
            if not same_unit:
                continue
            if value in same_unit and lex >= 0.1:
                score = 0.72 + 0.2 * min(lex, 1.0)
                if support is None or score > support[0]:
                    support = (score, cid, f"same_quantity:{value:g} {unit}")
            elif limited and unit != "day_index" and all(value > v for v in same_unit):
                score = 0.9 if lex >= 0.1 else 0.82
                if contradiction is None or score > contradiction[0]:
                    contradiction = (
                        score,
                        cid,
                        f"exceeds_limit:{value:g}>{max(same_unit):g} {unit}",
                    )
            elif lex >= 0.35 and unit != "day_index" and value not in same_unit:
                score = 0.62
                if contradiction is None or score > contradiction[0]:
                    contradiction = (score, cid, f"different_quantity:{value:g}!={same_unit[0]:g} {unit}")
        if not claimed and lex >= 0.55:
            score = 0.5 + 0.25 * min(lex, 1.0)
            if support is None or score > support[0]:
                support = (score, cid, "lexical_overlap")
    if contradiction is not None and (support is None or contradiction[0] >= support[0]):
        p, cid, reason = contradiction
        return Judgement("contradicted", _distribution("contradicted", p), (cid,), reason=reason)
    if support is not None and support[0] >= 0.6:
        p, cid, reason = support
        return Judgement("supported", _distribution("supported", p), (cid,), reason=reason)
    return Judgement("insufficient", _distribution("insufficient", 0.6), (), reason="no_comparable_evidence")


@lru_cache(maxsize=1)
def encoder_relation():
    """The exported C1 pair model, when configured (S6); None otherwise."""
    path = os.environ.get("CAREER_LAB_RELATION_ENCODER")
    if not path:
        return None
    try:
        from career_lab.recognition.encoder_relation import EncoderRelation

        return EncoderRelation(path)
    except Exception:  # noqa: BLE001 - missing torch or a broken export falls back
        return None


def judge(
    claim: str,
    candidates: Sequence[tuple],
    *,
    language: str = "zh",
    k: int = TOP_K,
    as_of: int = 0,
) -> Judgement:
    """C2 picks the top-k candidates for the claim, then C1 (or the rule) judges them.

    Candidates are ``(id, text)`` or ``(id, text, observed, valid_from, valid_until)``.
    """
    if not candidates:
        return Judgement("insufficient", _distribution("insufficient", 0.6), reason="no_candidates")
    texts = [c[1] for c in candidates]
    hits, method, _ = retrieval.search(claim, texts, k=k, method="rrf")
    chosen = [candidates[h.index] for h in hits]
    top = tuple(
        {
            "evidence_id": candidates[h.index][0],
            "rank": h.rank,
            "bm25": h.bm25,
            "dense": h.dense,
            "quote": candidates[h.index][1][:120],
        }
        for h in hits
    )
    model = encoder_relation()
    found = rule_judge(claim, chosen, [h.bm25 for h in hits])
    if model is not None:
        result = model.judge(claim, chosen, language=language, as_of=as_of)
        alpha = fusion_alpha()
        if alpha is not None and found.reason != "no_comparable_evidence":
            # E10 late fusion: the learned model and the number-and-limit rule, weighted
            # by the dev-chosen alpha; the rule abstains when it has nothing to compare.
            fused = {
                k: alpha * result.probabilities[k] + (1 - alpha) * found.probabilities[k]
                for k in LABELS
            }
            label = max(fused, key=fused.get)
            evidence = result.evidence_ids if label == result.label else found.evidence_ids
            return Judgement(
                label=label,
                probabilities=fused,
                evidence_ids=evidence if label != "insufficient" else (),
                recognizer_id=ENCODER_ID + "+rule",
                revision=result.revision,
                fallback=False,
                reason=f"late_fusion:{alpha:g}|{found.reason}",
                top=top,
            )
        return Judgement(**{**result.__dict__, "top": top})
    return Judgement(**{**found.__dict__, "top": top})


@lru_cache(maxsize=1)
def fusion_alpha() -> float | None:
    """The dev-chosen C1 weight from ``<encoder>/fusion.json`` (E10), if present."""
    path = os.environ.get("CAREER_LAB_RELATION_ENCODER")
    if not path:
        return None
    try:
        import json
        from pathlib import Path

        return float(json.loads((Path(path) / "fusion.json").read_text(encoding="utf-8"))["alpha"])
    except (OSError, ValueError, KeyError):
        return None


def criterion_label(counts: dict[str, int]) -> str | None:
    """Aggregate decided sentences to a rubric label (design 3.1 item 6)."""
    decided = counts.get("supported", 0) + counts.get("contradicted", 0) + counts.get(
        "insufficient", 0
    )
    if not decided:
        return None
    if counts.get("contradicted", 0):
        return "NOT_MET"
    if counts.get("supported", 0) == decided:
        return "MET"
    return "PARTIAL"
