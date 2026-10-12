"""Typed receiver for label/evidence return rows: v2 and the v3 relation row.

A v3 row (``return_schema_version=3``) carries the same relation fields as v2; criterion
rows are not received in this release.
"""

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from career_lab.contracts import v2 as C

from .core import Example, Prediction, evidence_missing


class EvidenceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    candidate_id: str = Field(min_length=1)
    candidate_sha256: C.Hash


RETURN_SCHEMA_VERSIONS = (2, 3)


class ReturnedPrediction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    return_schema_version: Literal[2, 3]
    record_id: str = Field(min_length=1)
    input_hash: C.Hash
    model_revision: str = Field(min_length=1)
    task_type: Literal["relation"]
    status: Literal["ok", "abstained", "failed"]
    probabilities: list[float] | None
    label: Literal["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"] | None
    evidence_ids: list[str]
    evidence_bindings: list[EvidenceBinding]
    reason: str | None = None

    @field_validator("return_schema_version", mode="before")
    @classmethod
    def schema_version_is_integer(cls, value: object) -> int:
        if type(value) is not int or value not in RETURN_SCHEMA_VERSIONS:
            raise ValueError("integer return schema version 2 or 3 required")
        return value

    @model_validator(mode="after")
    def shape(self) -> "ReturnedPrediction":
        if not self.model_revision.strip() or type(self.return_schema_version) is not int:
            raise ValueError("return identity required")
        if len(set(self.evidence_ids)) != len(self.evidence_ids) or any(
            not x for x in self.evidence_ids
        ):
            raise ValueError("duplicate or empty selected evidence")
        bound = [binding.candidate_id for binding in self.evidence_bindings]
        if len(bound) != len(set(bound)) or set(bound) != set(self.evidence_ids):
            raise ValueError("one binding required per selected evidence")
        if (not self.evidence_ids or self.status != "ok") and not (
            self.reason and self.reason.strip()
        ):
            raise ValueError("empty or unsuccessful return needs reason")
        if self.status != "ok" and (
            self.probabilities is not None or self.label is not None or self.evidence_ids
        ):
            raise ValueError("failed or abstained return cannot claim output")
        if self.status == "ok" and (
            self.probabilities is None
            or len(self.probabilities) != 3
            or any(not math.isfinite(value) or not 0 <= value <= 1 for value in self.probabilities)
            or abs(sum(self.probabilities) - 1) > 1e-6
        ):
            raise ValueError("three finite probabilities summing to one within 1e-6 required")
        return self

    def checked_prediction(self, row: Example) -> Prediction:
        if self.record_id != row.record_id or self.input_hash != row.annotation.input_hash:
            raise C.ProtocolError("return_prediction_input_mismatch")
        candidates = {candidate.id: candidate for candidate in row.item.evidence.candidate_evidence}
        for binding in self.evidence_bindings:
            candidate = candidates.get(binding.candidate_id)
            if candidate is None or C.digest(candidate) != binding.candidate_sha256:
                raise C.ProtocolError("return_evidence_binding_mismatch")
        if evidence_missing(
            self.status, self.label, self.evidence_ids, row.annotation.final.evidence_evaluable
        ):
            raise C.ProtocolError("return_evidence_selection_required")
        prediction = Prediction(
            self.task_type,
            self.input_hash,
            self.model_revision,
            self.status,
            self.label,
            tuple(self.probabilities) if self.probabilities is not None else None,
            tuple(self.evidence_ids),
            reason_code=f"producer_{self.status}" if self.status != "ok" else None,
        )
        return prediction.validate(row.item)


def parse_returned(row: dict) -> ReturnedPrediction:
    """One returned row, with an explicit code for an unsupported version or task."""
    if "return_schema_version" not in row:
        raise C.ProtocolError("return_schema_version_required")
    version = row["return_schema_version"]
    if type(version) is not int or version not in RETURN_SCHEMA_VERSIONS:
        raise C.ProtocolError("return_schema_version_unsupported")
    if row.get("task_type") != "relation":
        raise C.ProtocolError("return_task_type_unsupported")
    return ReturnedPrediction.model_validate(row)


# Absolute per-probability tolerance (143 §5.2): producers may run other hardware or library
# builds, so probabilities need not be bit-identical; labels and evidence sets must be.
ENCODER_KINDS = {"huggingface_encoder", "numpy_attention"}
TOLERANCE = {"linear": 1e-6, "encoder": 1e-4}


def comparison_tolerance(kinds) -> dict[str, Any]:
    """Unknown kinds use the strict tier: a false rejection is safer than a false match."""
    basis = "encoder" if set(kinds) & ENCODER_KINDS else "linear"
    return {"absolute": TOLERANCE[basis], "basis": basis, "model_kinds": sorted(kinds)}


def compare_prediction(actual: dict[str, Any], expected: ReturnedPrediction, tolerance: float):
    """Fields that differ, and the largest absolute probability difference seen."""
    fields = [
        key
        for key in ("input_hash", "model_revision", "task_type", "status", "label")
        if actual[key] != getattr(expected, key)
    ]
    if set(actual["evidence_ids"]) != set(expected.evidence_ids):
        fields.append("evidence_ids")
    left, right = actual["probabilities"], expected.probabilities
    deviation = 0.0
    if (left is None) != (right is None) or (left is not None and len(left) != len(right)):
        fields.append("probabilities")
    elif left is not None:
        deviation = max(abs(a - b) for a, b in zip(left, right, strict=True))
        if deviation > tolerance:
            fields.append("probabilities")
    return fields, deviation
