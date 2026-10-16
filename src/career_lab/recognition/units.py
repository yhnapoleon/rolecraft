"""C2 unitization: materials, records and state become sentence-sized evidence units.

Rules: a Markdown heading line is one ``heading`` unit (context only, never a candidate);
a list item is one ``item`` unit; paragraphs are cut into sentences by the product's own
R2.support splitter (``models/v3/units.split_sentences``, reused unchanged); a unit with
fewer than 4 non-space characters joins the previous one; a unit longer than 160
characters is cut again at commas. Spans are offsets into the source text, so every unit
is an exact ``EvidenceRefV2`` quote of the source it came from.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from career_lab.contracts.v2.core import EvidenceRefV2, digest
from career_lab.contracts.v2.evaluation import CandidateEvidenceV2
from career_lab.models.v3.units import split_sentences

MIN_CHARACTERS = 4
MAX_CHARACTERS = 160
# Judge packages carry at most this many candidate units besides the work itself.
MAX_CANDIDATES = 80

UnitKind = Literal["heading", "item", "sentence", "state"]
_HEADING = re.compile(r"[ \t]*#{1,6}[ \t]+\S")
_LIST_ITEM = re.compile(r"[ \t]*(?:[-*•]|\d+\.)[ \t]+")
_COMMAS = "，,、"


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    text: str
    kind: UnitKind


@dataclass(frozen=True)
class Unit:
    unit_id: str
    material_id: str
    version: int
    char_span: tuple[int, int]
    text: str
    kind: UnitKind
    domain: str | None = None
    valid_from_seq: int = 0
    valid_until_seq: int | None = None


def _visible(text: str) -> int:
    return sum(not c.isspace() for c in text)


def split_text(text: str) -> list[Span]:
    """Cut one text into unit spans (offsets into ``text``)."""
    spans: list[Span] = []
    position = 0
    block_start: int | None = None

    def flush(end: int) -> None:
        nonlocal block_start
        if block_start is None:
            return
        block = text[block_start:end]
        for sentence in split_sentences(block):
            start, stop = block_start + sentence.start, block_start + sentence.end
            line_start = text.rfind("\n", 0, start) + 1
            marker = _LIST_ITEM.match(text, line_start)
            kind: UnitKind = (
                "item" if marker is not None and marker.end() == start else "sentence"
            )
            spans.extend(_cut_long(text, start, stop, kind))
        block_start = None

    while position <= len(text):
        newline = text.find("\n", position)
        end = len(text) if newline == -1 else newline
        line = text[position:end]
        if _HEADING.match(line):
            flush(position)
            stripped = line.strip()
            offset = position + line.index(stripped)
            spans.append(Span(offset, offset + len(stripped), stripped, "heading"))
        elif block_start is None and line.strip():
            block_start = position
        if newline == -1:
            break
        position = newline + 1
    flush(len(text))
    return _merge_short(spans, text)


def _cut_long(text: str, start: int, end: int, kind: UnitKind) -> list[Span]:
    """Cut an over-long unit at line breaks, then commas, then hard at the limit."""
    if end - start <= MAX_CHARACTERS:
        return [Span(start, end, text[start:end], kind)]
    pieces: list[Span] = []
    for separators in ("\n", _COMMAS):
        begin = start
        cuts: list[tuple[int, int]] = []
        for index in range(start, end):
            if text[index] in separators and index + 1 - begin >= MIN_CHARACTERS * 4:
                cuts.append((begin, index + 1))
                begin = index + 1
        cuts.append((begin, end))
        if len(cuts) > 1:
            for a, b in cuts:
                pieces.extend(_cut_long(text, *_trim(text, a, b), kind))
            return [p for p in pieces if p.end > p.start]
    for a in range(start, end, MAX_CHARACTERS):
        a, b = _trim(text, a, min(end, a + MAX_CHARACTERS))
        if b > a:
            pieces.append(Span(a, b, text[a:b], kind))
    return pieces


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _merge_short(spans: list[Span], text: str) -> list[Span]:
    merged: list[Span] = []
    for span in spans:
        if (
            merged
            and span.kind != "heading"
            and merged[-1].kind != "heading"
            and _visible(span.text) < MIN_CHARACTERS
        ):
            last = merged[-1]
            merged[-1] = Span(last.start, span.end, text[last.start : span.end], last.kind)
        else:
            merged.append(span)
    return merged


def split_material(
    material_id: str,
    version: int,
    text: str,
    *,
    base: int = 0,
    domain: str | None = None,
    valid_from_seq: int = 0,
    valid_until_seq: int | None = None,
) -> tuple[Unit, ...]:
    return tuple(
        Unit(
            unit_id=digest([material_id, version, base + s.start, base + s.end]),
            material_id=material_id,
            version=version,
            char_span=(base + s.start, base + s.end),
            text=s.text,
            kind=s.kind,
            domain=domain,
            valid_from_seq=valid_from_seq,
            valid_until_seq=valid_until_seq,
        )
        for s in split_text(text)
    )


def candidate_units(candidate: CandidateEvidenceV2) -> list[CandidateEvidenceV2]:
    """One whole-text candidate as sentence candidates; unchanged when it has no span."""
    ref = candidate.ref
    if ref.span_start is None or ref.quote is None or ref.quote != candidate.text:
        return [candidate]
    spans = [s for s in split_text(candidate.text) if s.kind != "heading"]
    if len(spans) <= 1:
        return [candidate]
    found = []
    for span in spans:
        unit_ref = EvidenceRefV2.model_validate(
            ref.model_dump(mode="json")
            | {
                "span_start": ref.span_start + span.start,
                "span_end": ref.span_start + span.end,
                "quote": span.text,
            }
        )
        found.append(
            CandidateEvidenceV2(id="e-" + digest(unit_ref), text=span.text, ref=unit_ref)
        )
    return found


def unitize_candidates(
    candidates: Iterable[CandidateEvidenceV2],
    *,
    keep_whole: Sequence[str] = (),
    query: str = "",
    limit: int = MAX_CANDIDATES,
) -> list[CandidateEvidenceV2]:
    """Split every candidate except ``keep_whole`` ids; cap the units by retrieval score.

    The kept-whole candidates (the work itself) always stay first and do not count
    against ``limit``. Over the limit, units are ranked by C2 retrieval against ``query``
    (the work text) and the best ``limit`` are kept in their original order.
    """
    whole, units = [], []
    for candidate in candidates:
        if candidate.id in keep_whole:
            whole.append(candidate)
        else:
            units.extend(candidate_units(candidate))
    seen: set[str] = set()
    units = [u for u in units if not (u.id in seen or seen.add(u.id))]
    if len(units) > limit:
        from career_lab.recognition.retrieval import rank_texts

        order = rank_texts(query, [u.text for u in units], method="bm25")
        keep = set(order[:limit])
        units = [u for i, u in enumerate(units) if i in keep]
    return whole + units
