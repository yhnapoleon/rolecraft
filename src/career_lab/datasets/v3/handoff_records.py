"""Typed rows and label spaces at the responsible-party intake boundary."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, PrivateAttr

from career_lab.contracts.v2.core import FileRef, ProtocolError, digest
from career_lab.contracts.v2.data import AnnotationDecision, Lineage, ModelInput, Provenance

RawRow = dict[str, JsonValue]
RowIndex = dict[str, RawRow]

LABEL_ORDERS = {
    "relation": ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"],
    "criterion": ["MET", "PARTIAL", "NOT_MET", "INSUFFICIENT", "NOT_APPLICABLE"],
    "trajectory_diagnosis": ["diagnosed", "no_issue", "insufficient"],
    "acquisition": ["effective", "ineffective", "undetermined"],
}


class InputRow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    record_id: str
    input_hash: str
    model_input: ModelInput

    _candidate_hashes: dict[str, str] = PrivateAttr(default_factory=dict)

    @classmethod
    def from_wire(cls, raw: RawRow) -> "InputRow":
        row = cls.model_validate(raw)
        payload = raw["model_input"]
        if digest(payload) != row.input_hash:
            raise ProtocolError("handoff_input_hash_mismatch")
        # Preserve original candidate object identity before defaults are injected.
        if isinstance(payload, dict) and isinstance(payload.get("evidence"), dict):
            candidates = payload["evidence"].get("candidate_evidence", [])
            row._candidate_hashes = {item["id"]: digest(item) for item in candidates}
        return row

    def candidate_hash(self, candidate_id: str) -> str:
        return self._candidate_hashes[candidate_id]


class Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: str
    input_hash: str
    language: str
    bucket: str
    split: str
    connected_component_id: str
    lineage: Lineage
    provenance: Provenance
    packaged_sources: list[FileRef]


class LabelRow(AnnotationDecision):
    record_id: str
    input_hash: str
    label_tier: Literal["G0", "G1", "G2", "G2v"]
    label_index: int = Field(strict=True, ge=0)
    annotation_version: str | None = None
    verifier_id: str | None = None

    def decision(self) -> AnnotationDecision:
        return AnnotationDecision.model_validate(
            self.model_dump(include=AnnotationDecision.model_fields.keys())
        )
