"""C11 question intent: what the learner is asking a colleague for.

Five classes: ``ask_limit`` (limits, constraints), ``ask_resource`` (people, days, budget),
``ask_process`` (how to, steps), ``seek_approval`` (asking for a yes), ``other``.
Model: character 2-4 gram TF-IDF + logistic regression, one bilingual model, at
``$CAREER_LAB_RECOGNIZERS/intent-tfidf-lr-v1/{model.joblib, labels.json}`` (a fitted
sklearn ``Pipeline``). Without it a keyword rule decides, marked ``fallback``.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

from career_lab.recognition import registry
from career_lab.recognition.base import FALLBACK_REVISION, record, stopwatch

ID = "intent-tfidf-lr-v1"
LABELS = ("ask_limit", "ask_resource", "ask_process", "seek_approval", "other")

_RULES = (
    (
        "seek_approval",
        r"批准|审批|同意|批一下|签字|放行|能不能给|可否给|approve|approval|sign off|"
        r"green[- ]light|can you grant|will you grant|ok to go",
    ),
    (
        "ask_limit",
        r"上限|最多|多少人|容量|限制|不能超过|极限|门槛|limit|maximum|\bmax\b|cap\b|capacity|"
        r"how many (people|users|seats)|at most|constraint",
    ),
    (
        "ask_resource",
        r"人日|资源|人力|几天|多少天|预算|开发量|工作量|排期|resource|developer|dev days|"
        r"person[- ]days|budget|headcount|staffing|how long|timeline",
    ),
    (
        "ask_process",
        r"怎么|如何|流程|步骤|先做什么|下一步|怎样|how do|how should|process|steps|procedure|"
        r"what should i do|next step",
    ),
)


def rule_intent(text: str) -> tuple[str, float]:
    for label, pattern in _RULES:
        if re.search(pattern, text, re.IGNORECASE):
            return label, 0.7
    return "other", 0.5


@lru_cache(maxsize=1)
def _model():
    entry = registry.get(ID)
    if entry is None:
        return None
    try:
        import joblib

        model = joblib.load(entry.path / "model.joblib")
        labels = json.loads((entry.path / "labels.json").read_text(encoding="utf-8"))
        return model, labels, entry.revision
    except Exception:  # noqa: BLE001 - a broken artifact falls back to the rule
        return None


def recognize(text: str, *, as_of=None):
    with stopwatch() as clock:
        loaded = _model()
        if loaded is None:
            label, confidence = rule_intent(text)
            probabilities = None
            revision = FALLBACK_REVISION
        else:
            model, labels, revision = loaded
            row = model.predict_proba([text])[0]
            probabilities = {labels[i]: float(p) for i, p in enumerate(row)}
            label = max(probabilities, key=probabilities.get)
            confidence = probabilities[label]
    return record(
        ID,
        revision,
        "intent",
        {"text": text},
        label=label,
        score=confidence,
        outputs={"probabilities": probabilities} if probabilities else {"rule": "keywords"},
        as_of=as_of,
        duration_ms=clock.ms,
    )
