"""AIPM phase 1 extension contract (not part of frozen contracts.v2 discovery).

Read DTOs use schema_version=1; Gateway commands and persisted objects remain v2
(V2Store.register_object requires V2 models). Only the human
may write. L2/L3 handlers return Mutation; their registration is owned by L4.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from career_lab.contracts.v2 import V2, EvidenceRefV2, ObjectRef, VersionPoint

StepId = Literal[
    "business", "stakeholders", "need", "boundary", "solution", "assurance", "decision"
]
STEP_IDS = ("business", "stakeholders", "need", "boundary", "solution", "assurance", "decision")
EXPERIENCE_REVISION = "aipm-phase1-v1"
WorkStatus = Literal["not_started", "working", "recorded", "recheck", "uncovered"]
SourceKind = Literal[
    "rule", "authored_guidance", "colleague_opinion", "model_suggestion", "learner_assessment"
]


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Projection(DTO):
    complete: bool = True
    reason: str | None = None


class PublicAction(DTO):
    action: Literal[
        "open_step",
        "open_work",
        "open_material",
        "ask_colleague",
        "request_review",
        "open_settings",
        "open_feedback",
    ]
    label: str
    target: ObjectRef | None = None
    step_id: StepId | None = None


class PublicGap(DTO):
    code: str
    message: str


class ProcessFeedback(DTO):
    id: str
    input_ref: ObjectRef
    step_id: StepId
    section_or_row_id: str | None = None
    rule_revision: str | None = None
    content_revision: str | None = None
    source: SourceKind
    finding: Literal["violation", "improve", "supported_for_scope", "unknown"]
    message: str
    basis_refs: tuple[EvidenceRefV2, ...] = ()
    checked_scope: str
    next_action: PublicAction | None = None
    stale: bool = False
    affects_formal_score: Literal[False] = False


class ProcessFeedbackRecord(ProcessFeedback, V2):
    session_id: str
    revision: int = Field(default=1, ge=1)


class FeedbackSummary(DTO):
    id: str
    source: SourceKind
    finding: Literal["violation", "improve", "supported_for_scope", "unknown"]
    message: str
    input_ref: ObjectRef
    stale: bool = False


class ReadShortcut(DTO):
    tool: Literal["feedback.records.read", "objects.read"]
    arguments: dict


class FeedbackDiscovery(DTO):
    schema_version: Literal[1] = 1
    subject: ObjectRef
    status: Literal["ready", "not_ready"]
    feedback_ref: ObjectRef | None = None
    read: ReadShortcut | None = None
    exact_read: ReadShortcut | None = None
    reason: str | None = None
    as_of: VersionPoint
    work_language: Literal["zh", "en"]
    record_ready_is_not_quality_verified: Literal[True] = True


class GuideStep(DTO):
    id: StepId
    order: int = Field(ge=1, le=7)
    label: str
    goal: str
    expected_outputs: tuple[str, ...] = ()
    suggested_questions: tuple[str, ...] = ()
    help: tuple[dict, ...] = ()


class AipmGuide(DTO):
    schema_version: Literal[1] = 1
    experience_revision: Literal["aipm-phase1-v1"] = EXPERIENCE_REVISION
    content_revision: str
    work_language: Literal["zh", "en"]
    steps: tuple[GuideStep, ...]


class ProgressStep(GuideStep):
    work_status: WorkStatus
    completed: bool
    completion_meaning: Literal["work_recorded_not_mastery"] = "work_recorded_not_mastery"
    evidence_refs: tuple[ObjectRef, ...] = ()
    missing: tuple[PublicGap, ...] = ()
    quality_status: Literal["unverified", "has_findings", "checked_for_declared_scope"] = (
        "unverified"
    )
    open_feedback: tuple[FeedbackSummary, ...] = ()
    next_actions: tuple[PublicAction, ...] = ()


class AipmProgress(DTO):
    schema_version: Literal[1] = 1
    session_id: str
    experience_revision: str = EXPERIENCE_REVISION
    content_revision: str
    work_language: Literal["zh", "en"]
    as_of: VersionPoint
    focus_step: StepId
    suggested_step: StepId
    projection: Projection = Projection()
    steps: tuple[ProgressStep, ...]
    submission_feedback: tuple[FeedbackDiscovery, ...] = ()
    unresolved_business_items: tuple[PublicGap, ...] = ()
    next_cursor: str | None = None


class AipmProfile(V2):
    id: Literal["aipm-profile"] = "aipm-profile"
    session_id: str
    revision: Literal[1] = 1
    experience_revision: Literal["aipm-phase1-v1"] = EXPERIENCE_REVISION
    content_revision: str
    scenario_hash: str
    work_language: Literal["zh", "en"]
    enrolled_at: datetime


class AipmFocus(V2):
    id: Literal["aipm-focus"] = "aipm-focus"
    session_id: str
    step_id: StepId
    revision: int = Field(ge=1)
    changed_by: str
    changed_at: datetime


class AipmStepLink(V2):
    id: str
    session_id: str
    step_id: StepId
    product_ref: ObjectRef
    section_key: str | None = None
    linked_by: str
    source_kind: Literal["learner_link", "structured_record"] = "learner_link"
    revision: int = Field(ge=1)


class EmptyRead(V2):
    pass


class PageRead(V2):
    cursor: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=50)
    step_id: StepId | None = None


class FeedbackRead(V2):
    submission_id: str
    version: int = Field(ge=1)


class EnrollInput(V2):
    pass  # Identity comes only from the server's installed binding.


class FocusInput(V2):
    step_id: StepId


class StepLinkInput(V2):
    step_id: StepId
    product_ref: ObjectRef
    section_key: str | None = None


class BusinessDeclaration(DTO):
    audience: Literal["internal", "external", "both", "unknown"]
    offering_explanation: str
    task_goal: str
    source_refs: tuple[EvidenceRefV2, ...] = ()


class StakeholderDeclaration(DTO):
    id: str
    name_or_role: str
    relationships: tuple[Literal["user", "buyer", "approver", "operator", "affected"], ...]
    responsibility: str
    fact_or_hypothesis: Literal["fact", "hypothesis", "unknown"]
    source_refs: tuple[EvidenceRefV2, ...] = ()


class MetricDeclaration(DTO):
    kind: Literal["elapsed_time", "labor_time", "case_count", "other"]
    source_field: str
    unit: str
    population: str
    window: str
    formula_description: str
    claimed_interpretation: str


class NeedDeclaration(DTO):
    id: str
    stakeholder_ids: tuple[str, ...] = ()
    problem: str
    claim_status: Literal["hypothesis", "supported", "unresolved"]
    source_refs: tuple[EvidenceRefV2, ...] = ()
    counterevidence_or_unknown: str
    next_validation: str
    metric: MetricDeclaration | None = None


class TriageRow(DTO):
    id: str
    revision: int = Field(default=1, ge=1)
    need_ref: str
    source_refs: tuple[EvidenceRefV2, ...] = ()
    user_request: str
    target_action: Literal[
        "explain", "calculate", "prepare_draft", "execute_change", "approve", "unknown"
    ]
    route: Literal["deterministic", "retrieval_generation", "agent_confirmation", "human"]
    rationale: str
    final_authority: Literal["learner", "named_human_role", "ai", "unknown"]
    confirmation_point: str | None = None
    tool_assumptions: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    execution_support: Literal["supported", "plan_only", "unknown"] = "unknown"


class SolutionIntent(DTO):
    selected_approach: str
    rationale: str
    dependencies: tuple[str, ...] = ()
    alternative: str
    source_refs: tuple[EvidenceRefV2, ...] = ()


class AipmDesign(V2):
    id: str
    session_id: str
    revision: int = Field(ge=1)
    prd_ref: ObjectRef | None = None
    business: BusinessDeclaration | None = None
    stakeholders: tuple[StakeholderDeclaration, ...] = ()
    needs: tuple[NeedDeclaration, ...] = ()
    rows: tuple[TriageRow, ...] = ()
    solution: SolutionIntent | None = None


class MonitoringPlan(DTO):
    metric: str
    definition: str
    observation_window: str
    owner: str
    trigger: str
    response: str
    rollback_target: str
    verification_plan: str


class BatchCase(DTO):
    id: str
    need_ref: str
    triage_row_id: str
    triage_row_revision: int = Field(ge=1)
    request_id: str
    test_case_ref: ObjectRef
    expected_ref: ObjectRef
    original_command: dict | None = None
    run_ref: ObjectRef | None = None
    status: Literal["completed", "execution_failed", "unsupported", "cancelled", "pending"] = (
        "pending"
    )


class AipmBatch(V2):
    id: str
    session_id: str
    revision: int = Field(ge=1)
    design_ref: ObjectRef
    plan_ref: ObjectRef
    config_ref: ObjectRef
    material_refs: tuple[ObjectRef, ...] = ()
    cases: tuple[BatchCase, ...]
    execution_mode: str
    pause_reason: str | None = None
    monitoring: tuple[MonitoringPlan, ...] = ()


class AipmAssessment(V2):
    id: str
    session_id: str
    revision: Literal[1] = 1
    test_case_ref: ObjectRef
    expected_ref: ObjectRef
    run_ref: ObjectRef | None = None
    source: Literal["rule", "learner_assessment", "model_suggestion"]
    result: Literal["satisfied", "not_satisfied", "unknown", "unsupported"]
    reason: str
    evidence_refs: tuple[EvidenceRefV2, ...] = ()
