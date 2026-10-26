"""L3-specific persisted execution details; shared G0 DTOs remain the base contract."""

from typing import Literal

from pydantic import Field

from career_lab.aipm.types import DTO, AipmAssessment, AipmBatch, BatchCase, MonitoringPlan
from career_lab.contracts.v2 import V2, EvidenceRefV2, ObjectRef


class AbandonedAttempt(DTO):
    """An original the server never received, set aside once conditions moved on.

    Kept for the record; it is not a run and never enters any denominator.
    """

    request_id: str
    original_command: dict
    reason: Literal["conditions_changed"] = "conditions_changed"
    batch_revision: int = Field(ge=1)


class EvaluationCase(BatchCase):
    case_revision: int = Field(ge=1)
    route: Literal["deterministic", "retrieval_generation", "agent_confirmation", "human"]
    coverage: Literal["assistant_answer", "plan_only"]
    abandoned: tuple[AbandonedAttempt, ...] = ()


class EvaluationBatch(AipmBatch):
    cases: tuple[EvaluationCase, ...]
    baseline_hash: str
    created_by: str


class EvaluationAssessment(AipmAssessment):
    batch_ref: ObjectRef
    case_id: str
    case_revision: int = Field(ge=1)
    assessed_by: str
    source: Literal["learner_assessment"] = "learner_assessment"


class CaseSelection(V2):
    case_id: str
    triage_row_id: str
    coverage: Literal["assistant_answer", "plan_only"] = "plan_only"


class BatchCreate(V2):
    design_ref: ObjectRef
    plan_ref: ObjectRef
    selections: tuple[CaseSelection, ...] = Field(min_length=1, max_length=20)
    monitoring: tuple[MonitoringPlan, ...] = Field(default=(), max_length=20)


class BatchUpdate(V2):
    batch_id: str
    expected_revision: int = Field(ge=1)
    action: Literal["prepare", "reconcile", "reprepare", "pause", "resume", "cancel", "monitoring"]
    case_id: str | None = None
    monitoring: tuple[MonitoringPlan, ...] = Field(default=(), max_length=20)


class BatchRead(V2):
    batch_id: str


class AssessmentRecord(V2):
    batch_ref: ObjectRef
    case_id: str
    result: Literal["satisfied", "not_satisfied", "unknown", "unsupported"]
    reason: str = Field(min_length=1, max_length=4000)
    evidence_refs: tuple[EvidenceRefV2, ...] = Field(default=(), max_length=20)
