"""Shared recognizer protocol and the one helper every recognizer uses to sign a result."""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, Protocol

from career_lab.contracts.v2.core import EvidenceRefV2, VersionPoint, digest
from career_lab.contracts.v2.recognition import RecognitionRecord, RecognitionTask

FALLBACK_REVISION = "rule-fallback"


class Recognizer(Protocol):
    id: str
    revision: str

    def recognize(self, inputs: dict, *, work_language: str) -> RecognitionRecord: ...


def public_hash(inputs: Any) -> str:
    """Digest of the public projection of a recognizer's input (never private facts)."""
    return digest(inputs)


def record(
    recognizer_id: str,
    revision: str,
    task: RecognitionTask,
    inputs: Any,
    *,
    label: str | None = None,
    score: float | None = None,
    threshold: float | None = None,
    outputs: Mapping[str, Any] | None = None,
    citations: Sequence[EvidenceRefV2] = (),
    as_of: VersionPoint | None = None,
    duration_ms: float = 0.0,
    fallback: bool | None = None,
) -> RecognitionRecord:
    return RecognitionRecord(
        recognizer_id=recognizer_id,
        revision=revision,
        task=task,
        input_hash=public_hash(inputs),
        label=label,
        score=None if score is None else round(float(score), 4),
        threshold=None if threshold is None else round(float(threshold), 4),
        outputs=_json(dict(outputs or {})),
        citations=tuple(citations),
        as_of=as_of,
        duration_ms=max(0, int(round(duration_ms))),
        fallback=revision == FALLBACK_REVISION if fallback is None else fallback,
    )


def _json(value: Any) -> Any:
    """Round floats and turn tuples into lists so outputs are plain JSON."""
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, Mapping):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    if hasattr(value, "item"):  # numpy scalar
        return _json(value.item())
    return value


class Stopwatch:
    def __init__(self) -> None:
        self.started = time.perf_counter()

    @property
    def ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000.0


@contextmanager
def stopwatch() -> Iterator[Stopwatch]:
    yield Stopwatch()
