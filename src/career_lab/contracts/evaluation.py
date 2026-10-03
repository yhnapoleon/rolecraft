from typing import Literal

from pydantic import AliasChoices, Field, JsonValue, model_validator

from career_lab.contracts.base import Contract, Identifier, NonNegativeInt, PositiveInt
from career_lab.contracts.actions import EvidenceRef
from career_lab.contracts.scenario import PilotPlan
from career_lab.contracts.deliverables import Deliverable

RelationLabel = Literal["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"]
CriterionLabel = Literal["MET", "PARTIAL", "NOT_MET", "INSUFFICIENT", "NOT_APPLICABLE"]
TaskType = Literal["relation", "criterion"]
RELATION_LABELS = {"SUPPORTED", "CONTRADICTED", "INSUFFICIENT"}
CRITERION_LABELS = {"MET", "PARTIAL", "NOT_MET", "INSUFFICIENT", "NOT_APPLICABLE"}


class CandidateEvidence(Contract):
    id: Identifier
    version: PositiveInt
    text: str = Field(min_length=1)


class TestObservation(Contract):
    id: Identifier
    query: str
    fallback: bool
    stale: bool
    config_version: NonNegativeInt
    as_of_seq: NonNegativeInt


class RuleContext(Contract):
    capacity: PositiveInt
    dev_days: NonNegativeInt
    deadline_day: PositiveInt
    plan: PilotPlan
    deliverable: Deliverable
    tests: tuple[TestObservation, ...]
    work_costs: dict[str, NonNegativeInt]
    approvals: tuple[str, ...]
    policy_updated: bool
    logs_complete: bool
    config_version: NonNegativeInt = 0
    policy_update_seq: NonNegativeInt | None = None


class EvidencePackage(Contract):
    item_id: Identifier
    task_type: TaskType
    criterion: Identifier = Field(validation_alias=AliasChoices("criterion", "criterion_id"))
    claim: Identifier
    as_of_seq: NonNegativeInt
    candidate_evidence: tuple[CandidateEvidence, ...]
    completeness: Literal["complete", "missing", "overflow"]
    # Task 5 supplies canonical hashing and source mapping; legacy example has neither.
    input_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    context: RuleContext | None = None
    source_map: dict[str, EvidenceRef] = Field(default_factory=dict, exclude=True)

    @model_validator(mode="after")
    def unique_evidence(self):
        ids = [e.id for e in self.candidate_evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate evidence IDs must be unique")
        return self


class LabeledDecision(Contract):
    task_type: TaskType = "relation"
    label: RelationLabel | CriterionLabel

    @model_validator(mode="after")
    def correct_label_namespace(self):
        allowed = RELATION_LABELS if self.task_type == "relation" else CRITERION_LABELS
        if self.label not in allowed:
            raise ValueError("label does not belong to task_type")
        return self


class GoldAnnotation(LabeledDecision):
    item_id: Identifier
    label_tier: Literal["G0", "G1", "G2"]
    acceptable_evidence_sets: tuple[tuple[Identifier, ...], ...]
    missing_requirement: str | None = None
    annotation_version: Identifier
    evidence_evaluable: bool = True
    verifier_id: Identifier | None = None


class JudgeDecision(LabeledDecision):
    abstained: bool = False
    evidence_ids: tuple[Identifier, ...]
    reason_code: Identifier
    explanation: Identifier
    model_revision: Identifier

    @model_validator(mode="after")
    def unique_citations(self):
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("duplicate evidence IDs")
        return self


class ItemGrade(Contract):
    item_id: Identifier
    schema_valid: bool
    label_correct: bool | None
    evidence_score: float | None = Field(ge=0, le=1)
    joint_correct: bool | None
    error_class: Identifier | None


class RewardBreakdown(Contract):
    total: float
    format_valid: bool
    label_correct: bool
    evidence_valid: bool
    evidence_score: float = Field(ge=0, le=1)
    reward_version: Identifier


class EvalConfig(Contract):
    suite: Identifier
    dataset_manifest: Identifier
    candidate: Identifier
    prompt_version: Identifier
    input_mode: Literal["oracle", "retrieved"]
    decode: dict[str, JsonValue]
    seeds: tuple[NonNegativeInt, ...] = Field(min_length=1)
    concurrency: PositiveInt


class RunReport(Contract):
    run_id: Identifier
    manifest_path: Identifier
    metrics: dict[str, float | None]
    slices: dict[str, dict[str, float | None]]
    paired_diff_path: str | None
    errors_path: str | None

