"""C10 colleague reply check: is each sentence of a role reply grounded, and does it leak?

Grounding: every reply sentence is matched (C2) against the sources the role could see
and judged by C1 (rule fallback without weights). Leak: the same sentence is matched
against the role's private facts that the learner cannot see; a sentence those facts
support is a possible leak. Leaked sentences never carry evidence ids to the learner.
The check never blocks or edits the reply; the existing LLM stance verifier still runs.
"""

from __future__ import annotations

from collections.abc import Sequence

from career_lab.models.v3.units import split_sentences
from career_lab.recognition import relation
from career_lab.recognition.base import record, stopwatch

ID = "reply-check-v1"
MIN_CHARACTERS = 6


def check_reply(
    text: str,
    visible: Sequence[tuple[str, str]],
    private: Sequence[tuple[str, str]] = (),
    *,
    language: str = "zh",
    as_of=None,
):
    with stopwatch() as clock:
        rows = []
        fallback = True
        revision = "rule-fallback"
        for sentence in split_sentences(text or ""):
            quote = sentence.text
            if sum(not c.isspace() for c in quote) < MIN_CHARACTERS:
                continue
            grounded = relation.judge(quote, list(visible), language=language, k=3)
            fallback = fallback and grounded.fallback
            revision = grounded.revision
            leak = False
            if private:
                hidden = relation.judge(quote, list(private), language=language, k=3)
                leak = hidden.label == "supported" and grounded.label != "supported"
            rows.append(
                {
                    "quote": quote[:200],
                    "label": grounded.label,
                    "confidence": grounded.confidence,
                    "evidence_ids": [] if leak else list(grounded.evidence_ids),
                    "leak": leak,
                }
            )
    supported = sum(row["label"] == "supported" for row in rows)
    leaks = sum(row["leak"] for row in rows)
    return record(
        ID,
        revision,
        "reply_check",
        {"text": text},
        label="grounded" if rows and supported == len(rows) else "partly_grounded",
        score=(supported / len(rows)) if rows else None,
        outputs={
            "sentences": rows,
            "grounded": supported,
            "ungrounded": len(rows) - supported,
            "leaks": leaks,
        },
        as_of=as_of,
        duration_ms=clock.ms,
        fallback=fallback,
    )
