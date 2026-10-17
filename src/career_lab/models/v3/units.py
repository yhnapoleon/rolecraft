"""R2.support sentence units (policy ``r2-support-units-v1``): rule splitting, not claim extraction.

The learner's work is cut by fixed punctuation and layout rules into sentences that a
relation model judges one at a time. Product inference uses these functions; the authorized
relation-units export is to reuse them unchanged, so a sentence has one ``unit_hash``.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from career_lab.contracts.v2.core import EvidenceRefV2, ObjectRef, digest
from career_lab.contracts.v2.evaluation import EvidencePackageV2

from .projection import subject_texts

POLICY = "r2-support-units-v1"
# Sentences judged per R2.support package; later ones are counted as over budget.
MAX_UNITS = 24
# Sentences with fewer non-whitespace characters are counted as too short to judge.
MIN_CHARACTERS = 4

_TERMINATORS = frozenset("。！？；!?;")
# Closing quotes and brackets stay with the sentence they close.
_CLOSERS = frozenset("”’\"')）]】」』》")
_OPENERS = "([{“‘\"'（【「『《"
_ABBREVIATIONS = frozenset(("e.g.", "i.e.", "vs.", "etc."))
_LIST_ITEM = re.compile(r"[ \t]*(?:[-*•]|\d+\.)[ \t]+")


@dataclass(frozen=True)
class Sentence:
    """One sentence of a text: ``text[start:end]`` of the original, without outer whitespace."""

    start: int
    end: int
    text: str


@dataclass(frozen=True)
class SupportUnit:
    """One judged sentence: the work version with the sentence's span and exact text."""

    index: int
    subject: EvidenceRefV2
    unit_hash: str

    @property
    def text(self) -> str:
        return self.subject.quote or ""


@dataclass(frozen=True)
class UnitPlan:
    """The sentences of one package sent to a model, and those that were not."""

    units: tuple[SupportUnit, ...]
    skipped_short: int = 0
    over_budget: int = 0


@dataclass(frozen=True)
class UnitResult:
    unit: SupportUnit
    status: Literal["completed", "abstained", "failed"]
    label: str | None = None
    evidence_ids: tuple[str, ...] = ()
    reason_code: str | None = None
    # Relation probabilities (SUPPORTED, CONTRADICTED, INSUFFICIENT order) when known.
    probabilities: tuple[float, ...] | None = None


@dataclass(frozen=True)
class Conclusion:
    """Work-level result: ``label`` is None when no sentence was judged."""

    label: str | None
    counts: dict[str, int]
    evidence_ids: tuple[str, ...]


def support_units(package: EvidencePackageV2) -> UnitPlan:
    """Split every work subject of an R2.support package, in subject order.

    Spans are offsets in the work version the subject names; the unit text is the
    sentence exactly as written. At most ``MAX_UNITS`` sentences are planned.
    """
    units: list[SupportUnit] = []
    short = over = 0
    for ref, text in subject_texts(package):
        base = ref.span_start or 0
        for sentence in split_sentences(text):
            if sum(not character.isspace() for character in sentence.text) < MIN_CHARACTERS:
                short += 1
                continue
            if len(units) >= MAX_UNITS:
                over += 1
                continue
            subject = EvidenceRefV2.model_validate(
                ref.model_dump(mode="json")
                | {
                    "span_start": base + sentence.start,
                    "span_end": base + sentence.end,
                    "quote": sentence.text,
                }
            )
            units.append(SupportUnit(len(units), subject, unit_hash(subject)))
    return UnitPlan(tuple(units), short, over)


def unit_hash(subject: EvidenceRefV2) -> str:
    """Identity of one sentence of one work version under this splitting policy."""
    return digest(
        {
            "policy": POLICY,
            "subject": subject.model_dump(mode="json", include=set(ObjectRef.model_fields)),
            "span": [subject.span_start, subject.span_end],
            "text": subject.quote,
        }
    )


def aggregate(
    results: Sequence[UnitResult], plan: UnitPlan, candidate_order: Sequence[str]
) -> Conclusion:
    """Conservative work-level relation (user decision 2026-10-12, item 5).

    Any judged CONTRADICTED sentence makes the work CONTRADICTED. The work is SUPPORTED
    only when every planned sentence was judged SUPPORTED and none was over budget.
    Everything else is INSUFFICIENT. Evidence is the union of the SUPPORTED and
    CONTRADICTED sentences' evidence, in candidate order.
    """
    completed = [row for row in results if row.status == "completed"]
    labels = [row.label for row in completed]
    if not completed:
        label = None
    elif "CONTRADICTED" in labels:
        label = "CONTRADICTED"
    elif (
        len(completed) == len(results)
        and all(value == "SUPPORTED" for value in labels)
        and plan.over_budget == 0
    ):
        label = "SUPPORTED"
    else:
        label = "INSUFFICIENT"
    selected = {
        evidence
        for row in completed
        if row.label in {"SUPPORTED", "CONTRADICTED"}
        for evidence in row.evidence_ids
    }
    counts = {
        "supported": labels.count("SUPPORTED"),
        "contradicted": labels.count("CONTRADICTED"),
        "insufficient": labels.count("INSUFFICIENT"),
        "abstained": sum(row.status == "abstained" for row in results),
        "failed": sum(row.status == "failed" for row in results),
        "skipped_short": plan.skipped_short,
        "over_budget": plan.over_budget,
    }
    return Conclusion(label, counts, tuple(key for key in candidate_order if key in selected))


def split_sentences(text: str) -> tuple[Sentence, ...]:
    """Cut ``text`` into sentences.

    Blank lines separate paragraphs; a line starting with ``-``, ``*``, ``•`` or ``1.`` is
    a list item of its own (marker excluded). Inside a segment, ``。！？；!?;`` end a
    sentence, and so does an English period followed by whitespace or the end, unless the
    character before it is a digit or the word is e.g., i.e., vs. or etc. Decimals keep
    their period. A single line break is not a boundary.
    """
    found: list[Sentence] = []
    for start, end in _segments(text):
        found.extend(_sentences(text, start, end))
    return tuple(found)


def _segments(text: str) -> list[tuple[int, int]]:
    segments: list[tuple[int, int]] = []
    current: list[int] | None = None
    position = 0
    while True:
        newline = text.find("\n", position)
        end = len(text) if newline == -1 else newline
        line = text[position:end]
        marker = _LIST_ITEM.match(line)
        if not line.strip():
            if current is not None:
                segments.append((current[0], current[1]))
            current = None
        elif marker is not None:
            if current is not None:
                segments.append((current[0], current[1]))
            segments.append((position + marker.end(), end))
            current = None
        elif current is None:
            current = [position, end]
        else:
            current[1] = end
        if newline == -1:
            break
        position = newline + 1
    if current is not None:
        segments.append((current[0], current[1]))
    return segments


def _sentences(text: str, start: int, end: int) -> list[Sentence]:
    found: list[Sentence] = []
    begin = index = start
    while index < end:
        boundary = None
        character = text[index]
        if character in _TERMINATORS:
            boundary = index + 1
            while boundary < end and (text[boundary] in _TERMINATORS or text[boundary] in _CLOSERS):
                boundary += 1
        elif character == ".":
            after = index + 1
            while after < end and text[after] in _CLOSERS:
                after += 1
            if (
                (after == end or text[after].isspace())
                and not (index > 0 and text[index - 1].isdigit())
                and not _abbreviation(text, begin, index)
            ):
                boundary = after
        if boundary is None:
            index += 1
            continue
        _append(found, text, begin, boundary)
        begin = index = boundary
    _append(found, text, begin, end)
    return found


def _abbreviation(text: str, begin: int, period: int) -> bool:
    word_start = period
    while word_start > begin and not text[word_start - 1].isspace():
        word_start -= 1
    word = text[word_start : period + 1].lstrip(_OPENERS).casefold()
    return word in _ABBREVIATIONS


def _append(found: list[Sentence], text: str, start: int, end: int) -> None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start < end:
        found.append(Sentence(start, end, text[start:end]))
