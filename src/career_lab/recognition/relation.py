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

When the recognizer registry also holds ``relation-stack-v1`` (``recognition.stack``),
the C1 pair probabilities go through the stacked ensemble with the TF-IDF + feature
logistic regression before aggregation, and the late-fusion weight with the rule comes
from the ensemble's own ``fusion.json``.
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
STACK_ID = "relation-stack-v1"
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
    r"(?:cny|rmb|¥)?\s*(\d+(?:\.\d+)?)\s*(" + "|".join(p for p, _ in _UNITS) + r")",
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
    # What each branch said before the final label: ``encoder`` (C1 alone), ``stack`` (the
    # ensemble, when used), ``pairs`` (per-candidate pair score), ``rule`` (None when the
    # rule had nothing to compare) and ``alpha`` (the late-fusion weight of the model).
    branches: dict = field(default_factory=dict)
    # How the candidates were ranked (C2): ``method`` is what ran ("rrf", "dense" or
    # "bm25"); ``fallback`` is true when rrf or dense was asked for but no embedder was
    # loaded and BM25 ran instead. The same for every candidate of one judgement.
    retrieval: dict = field(default_factory=dict)

    @property
    def confidence(self) -> float:
        return max(self.probabilities.values())


def _distribution(label: str, p: float) -> dict[str, float]:
    rest = (1.0 - p) / 2
    return {name: (p if name == label else rest) for name in LABELS}


def rule_judge(claim: str, candidates: Sequence[tuple[str, str]], lexical: Sequence[float]):
    """Rule fallback over already retrieved (id, text) candidates and their BM25 scores.

    Conflicting figures: a claim that itself states a limit ("the approval cap is 60") and
    a candidate that states that exact limit agree, even when another candidate's figure of
    the same unit is lower (a reserved capacity of 30; the taxi cap next to the lodging
    cap): the two measure different things. A claim without a limit word ("invite 50
    people") that exceeds a stated limit stays a contradiction whatever else repeats its
    figure, and a fresher contradicting candidate (by ``valid_from``, 0 for a plain
    ``(id, text)`` pair: the notice that replaced the figure) wins in every case.
    """
    claimed = quantities(claim)
    contradiction: tuple[float, str, str] | None = None
    support: tuple[float, str, str] | None = None
    since = {cand[0]: (cand[3] or 0) if len(cand) >= 5 else 0 for cand in candidates}
    for cand, lex in zip(candidates, lexical, strict=False):
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
                    contradiction = (
                        score,
                        cid,
                        f"different_quantity:{value:g}!={same_unit[0]:g} {unit}",
                    )
        if not claimed and lex >= 0.55:
            score = 0.5 + 0.25 * min(lex, 1.0)
            if support is None or score > support[0]:
                support = (score, cid, "lexical_overlap")
    if (
        contradiction is not None
        and support is not None
        and support[2].startswith("same_quantity")
        and _LIMIT.search(claim)
        and since.get(contradiction[1], 0) <= since.get(support[1], 0)
    ):
        p, cid, _ = support
        return Judgement(
            "supported",
            _distribution("supported", p),
            (cid,),
            reason=f"conflicting_figures|{contradiction[2]}|{support[2]}",
        )
    if contradiction is not None and (support is None or contradiction[0] >= support[0]):
        p, cid, reason = contradiction
        return Judgement("contradicted", _distribution("contradicted", p), (cid,), reason=reason)
    if support is not None and support[0] >= 0.6:
        p, cid, reason = support
        return Judgement("supported", _distribution("supported", p), (cid,), reason=reason)
    return Judgement(
        "insufficient", _distribution("insufficient", 0.6), (), reason="no_comparable_evidence"
    )


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
    figure_first: bool = False,
) -> Judgement:
    """C2 picks the top-k candidates for the claim, then C1 (or the rule) judges them.

    Candidates are ``(id, text)`` or ``(id, text, observed, valid_from, valid_until)``.
    The rule additionally reads every limit that came into force during the session
    (``valid_from > 0``) in the claim's unit of measure, wherever retrieval ranked it.

    ``figure_first`` (the colleague reply check): when the rule found the claim's exact
    figure in a candidate and the model only abstains ("insufficient"), the rule's
    support stands instead of being averaged away. The model's contradiction still
    fuses as usual. Off by default: the review path keeps its measured fusion (E10).
    """
    if not candidates:
        return Judgement(
            "insufficient",
            _distribution("insufficient", 0.6),
            reason="no_candidates",
            retrieval={"method": None, "fallback": False},
        )
    texts = [c[1] for c in candidates]
    ranked, method, fell_back = retrieval.search(claim, texts, k=len(texts), method="rrf")
    searched = {"method": method, "fallback": fell_back}
    hits = ranked[:k]
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
    # The rule also reads the limits that came into force during the session (a notice
    # published mid-session: valid_from > 0) when they are stated in the claim's own unit
    # of measure, wherever retrieval ranked them: a claim repeating the superseded figure
    # is matched best by the older answers that repeat it, which push the new notice
    # below the model's top-k. Limits in force from the start stay subject to retrieval,
    # so an unrelated allowance (meals) does not reach a lodging claim.
    rule_hits = hits + [
        h
        for h in ranked[k:]
        if _fresh(candidates[h.index])
        and h.bm25 >= 0.1
        and _states_limit_for(claim, texts[h.index])
    ]
    model = encoder_relation()
    found = rule_judge(claim, [candidates[h.index] for h in rule_hits], [h.bm25 for h in rule_hits])
    if model is not None:
        ensemble = stack_for(model)
        result = model.judge(claim, chosen, language=language, as_of=as_of, stack=ensemble)
        alpha = fusion_alpha() if ensemble is None else ensemble.alpha
        abstained = found.reason == "no_comparable_evidence"
        branches = {
            **result.branches,
            "rule": None if abstained else found.probabilities,
            "rule_window": len(rule_hits),
            "alpha": alpha,
        }
        if alpha is not None and alpha < 1 and not abstained:
            # E10 late fusion: the learned model and the number-and-limit rule, weighted
            # by the dev-chosen alpha; the rule abstains when it has nothing to compare.
            fused = {
                k: alpha * result.probabilities[k] + (1 - alpha) * found.probabilities[k]
                for k in LABELS
            }
            label = max(fused, key=fused.get)
            # Evidence of the fused label. When both sides agree, the candidate the rule
            # compared against (the limit or figure it read, e.g. the current policy) comes
            # first and the model's cited candidates follow in pair-score order; otherwise
            # the evidence of the side the label came from.
            if label == result.label == found.label:
                evidence = found.evidence_ids + tuple(
                    e for e in result.evidence_ids if e not in found.evidence_ids
                )
            elif label == result.label:
                evidence = result.evidence_ids
            else:
                evidence = found.evidence_ids
            reason = f"late_fusion:{alpha:g}|{found.reason}"
            if figure_first and label == "insufficient" and _figure_found(found):
                label, fused, evidence = found.label, found.probabilities, found.evidence_ids
                reason += "|figure_found"
            return Judgement(
                label=label,
                probabilities=fused,
                evidence_ids=evidence if label != "insufficient" else (),
                recognizer_id=result.recognizer_id + "+rule",
                revision=result.revision,
                fallback=False,
                reason=reason,
                top=top,
                branches=branches,
                retrieval=searched,
            )
        if figure_first and result.label == "insufficient" and _figure_found(found):
            return Judgement(
                **{
                    **found.__dict__,
                    "recognizer_id": result.recognizer_id + "+rule",
                    "revision": result.revision,
                    "fallback": False,
                    "reason": found.reason + "|figure_found",
                    "top": top,
                    "branches": branches,
                    "retrieval": searched,
                }
            )
        return Judgement(
            **{**result.__dict__, "top": top, "branches": branches, "retrieval": searched}
        )
    return Judgement(
        **{
            **found.__dict__,
            "top": top,
            "branches": {"rule": found.probabilities, "rule_window": len(rule_hits)},
            "retrieval": searched,
        }
    )


def _figure_found(found: Judgement) -> bool:
    """Did the rule find the claim's exact figure (and side with it)?"""
    return found.label == "supported" and found.reason.startswith(
        ("same_quantity", "conflicting_figures")
    )


def _fresh(candidate: tuple) -> bool:
    """Did the candidate come into force after the session started?"""
    return len(candidate) >= 5 and (candidate[3] or 0) > 0


def _states_limit_for(claim: str, text: str) -> bool:
    """Does ``text`` state a limit in one of the claim's units of measure?"""
    units = {unit for _, unit in quantities(claim) if unit != "day_index"}
    return (
        bool(units)
        and bool(_LIMIT.search(text))
        and any(unit in units for _, unit in quantities(text))
    )


def stack_for(model):
    """The stacked ensemble (E1) when registered and fitted against this C1 revision."""
    from career_lab.recognition import stack

    ensemble = stack.load()
    if ensemble is None or ensemble.encoder_revision != model.revision:
        return None
    return ensemble


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
    decided = (
        counts.get("supported", 0) + counts.get("contradicted", 0) + counts.get("insufficient", 0)
    )
    if not decided:
        return None
    if counts.get("contradicted", 0):
        return "NOT_MET"
    if counts.get("supported", 0) == decided:
        return "MET"
    return "PARTIAL"
