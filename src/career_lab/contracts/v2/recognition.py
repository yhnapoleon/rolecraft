"""Recognition provenance: one record per recognizer call, attached to the result it shaped.

Every pattern recognizer (retrieval, relation, scope, drift, intent, behavior, reply check,
cost-sensitive decision, Judge/recognizer arbiter) reports through this one shape so the
workbench can sign each result with the recognizer's name, label, score and threshold.
``fallback`` is true when the recognizer's weights were unavailable and a rule produced
the result instead. Demo edition: added without re-exporting the contract fingerprints.
"""

from typing import Literal

from pydantic import Field, JsonValue

from .core import V2, EvidenceRefV2, Hash, Identifier, NonNegativeInt, VersionPoint

RecognitionTask = Literal[
    "relation",
    "retrieval",
    "scope",
    "drift",
    "intent",
    "behavior",
    "reply_check",
    "decision",
    "arbiter",
]


class RecognitionRecord(V2):
    recognizer_id: Identifier
    # Weight hash prefix, or "rule-fallback" when no weights were loaded.
    revision: Identifier
    task: RecognitionTask
    input_hash: Hash
    label: str | None = None
    # Meaning set by the task: probability, distance, cost or retrieval score.
    score: float | None = None
    threshold: float | None = None
    outputs: dict[str, JsonValue] = Field(default_factory=dict)
    citations: tuple[EvidenceRefV2, ...] = ()
    as_of: VersionPoint | None = None
    duration_ms: NonNegativeInt = 0
    fallback: bool = False


__all__ = ["RecognitionRecord", "RecognitionTask"]
