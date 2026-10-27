"""C10 colleague reply check: is each sentence of a role reply grounded, and does it leak?

Grounding: every reply sentence is matched (C2) against the sources the role could see
and judged by C1 (rule fallback without weights). Leak: the same sentence is matched
against the role's private facts that the learner cannot see; a sentence those facts
support is a possible leak. Leaked sentences never carry evidence ids to the learner.
The check never blocks or edits the reply; the existing LLM stance verifier still runs.

The visible sources are cut into units (sentences and list items, headings dropped)
before retrieval, the way the review's candidates are: a whole material as one candidate
was truncated to the encoder's first tokens, so a passage the colleague quoted from further
down was never seen (judged "insufficient"), and the number rule read every figure of the
whole material at once (a correct "60 people" next to an unrelated "50 people" became a
contradiction). Over ``MAX_UNITS`` units, the ones most relevant to the reply are kept.
Each sentence also carries the C6 cost decision, so a reader can act only where the
expected cost says to and abstain elsewhere. The judgement runs ``figure_first``: a figure
the rule found verbatim in a visible unit is not averaged away by a model that merely
abstains (the pair model reads most colleague paraphrases as "insufficient").
"""

from __future__ import annotations

from collections.abc import Sequence

from career_lab.models.v3.units import split_sentences
from career_lab.recognition import decision, relation, retrieval, units
from career_lab.recognition.base import record, stopwatch

ID = "reply-check-v2"
MIN_CHARACTERS = 6
MAX_UNITS = units.MAX_CANDIDATES
TOP_K = 3


def unitize(sources: Sequence[tuple[str, str]], query: str = "") -> list[dict]:
    """``(id, text)`` or ``(id, text, observed, valid_from, valid_until)`` sources as unit
    candidates: ``{"id", "text", "source", "span"}`` (plus ``validity`` when given, so the
    rule can tell a replacing notice from the figure it replaced).

    A source of a single unit stays whole (``span`` None). Over ``MAX_UNITS`` units in
    all, C2 ranks them against ``query`` (the reply) and keeps the best, in source order.
    """
    found = []
    for source in sources:
        source_id, body, validity = source[0], source[1], tuple(source[2:])
        spans = [s for s in units.split_text(body or "") if s.kind != "heading"]
        if len(spans) <= 1:
            found.append(
                {"id": source_id, "text": body, "source": source_id, "span": None} | _when(validity)
            )
            continue
        for span in spans:
            found.append(
                {
                    "id": f"{source_id}#{span.start}-{span.end}",
                    "text": span.text,
                    "source": source_id,
                    "span": (span.start, span.end),
                }
                | _when(validity)
            )
    if len(found) > MAX_UNITS and query:
        keep = set(retrieval.rank_texts(query, [u["text"] for u in found])[:MAX_UNITS])
        found = [u for i, u in enumerate(found) if i in keep]
    return found


def _when(validity: tuple) -> dict:
    """``(observed, valid_from, valid_until)`` of a source, when the caller gave them."""
    return {"validity": validity} if len(validity) == 3 else {}


def _candidate(unit: dict) -> tuple:
    return (unit["id"], unit["text"], *unit.get("validity", ()))


def check_reply(
    text: str,
    visible: Sequence[tuple[str, str]],
    private: Sequence[tuple[str, str]] = (),
    *,
    language: str = "zh",
    as_of=None,
):
    with stopwatch() as clock:
        candidates = unitize(visible, text or "")
        by_id = {u["id"]: u for u in candidates}
        pairs = [_candidate(u) for u in candidates]
        rows = []
        fallback = True
        revision = "rule-fallback"
        searched = None
        for sentence in split_sentences(text or ""):
            quote = sentence.text
            if sum(not c.isspace() for c in quote) < MIN_CHARACTERS:
                continue
            grounded = relation.judge(quote, pairs, language=language, k=TOP_K, figure_first=True)
            fallback = fallback and grounded.fallback
            revision = grounded.revision
            searched = searched or grounded.retrieval or None
            choice = decision.decide(grounded.probabilities)
            leak = False
            if private:
                hidden = relation.judge(quote, list(private), language=language, k=TOP_K)
                leak = hidden.label == "supported" and grounded.label != "supported"
            cited = [by_id[i] for i in grounded.evidence_ids if i in by_id]
            sources = []
            for unit in cited:
                if unit["source"] not in sources:
                    sources.append(unit["source"])
            rows.append(
                {
                    "quote": quote[:200],
                    "label": grounded.label,
                    "confidence": grounded.confidence,
                    "decision": choice.action,
                    "expected_cost": round(choice.expected_cost, 3),
                    # Source ids as before (what the learner may be shown); the units
                    # the judgement cited, with their place in the source, for a reader
                    # who wants the matching original text.
                    "evidence_ids": [] if leak else sources,
                    "evidence_units": []
                    if leak
                    else [
                        {
                            "source": u["source"],
                            "span": list(u["span"]) if u["span"] else None,
                            "quote": u["text"][:160],
                        }
                        for u in cited
                    ],
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
            "sources": len(visible),
            "candidates": len(candidates),
            "retrieval": searched,
        },
        as_of=as_of,
        duration_ms=clock.ms,
        fallback=fallback,
    )
