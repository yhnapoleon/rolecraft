from typing import Literal
from pydantic import Field, JsonValue, model_validator
from .core import *
from .world import (
    Observation,
    SessionBindings,
    WorldStateV2,
    PublicState,
    PublicEvent,
    JobRefreshRecord,
)
from .data import Lineage, ActionProposal, ObservedStep


class RuntimeBundle(V2):
    id: Identifier
    revision: Identifier
    model: FileRef
    prompts: tuple[FileRef, ...]
    skills: FileRef | None = None
    acquisition: FileRef
    retrieval: FileRef
    decision: FileRef
    tools: FileRef
    source: SourceIdentity


class EvaluationBundle(V2):
    id: Identifier
    revision: Identifier
    rubric: FileRef
    rules: FileRef
    graders: tuple[FileRef, ...]
    calibration: FileRef | None = None
    model: FileRef | None = None
    protocol: FileRef
    mode: Literal["advisory", "scoring"] = "advisory"
    adoption_record: FileRef | None = None

    @model_validator(mode="after")
    def scoring(self):
        if self.mode == "scoring" and (not self.calibration or not self.adoption_record):
            raise ValueError("scoring needs calibration and adoption")
        return self


class CandidateBundle(V2):
    id: Identifier
    parent: FileRef
    runtime: FileRef
    evaluation: FileRef
    changes: dict[
        Literal["agent_prompt", "acquisition_parameters", "retrieval_parameters"], FileRef
    ]
    hypothesis: str
    allowed_data: tuple[FileRef, ...]
    source_splits: tuple[Literal["train", "dev"], ...]
    budget: Budget
    evaluations: tuple[FileRef, ...] = ()
    selection_reason: str | None = None


class ModelBundle(V2):
    id: Identifier
    task_type: Literal["relation", "criterion", "trajectory_diagnosis", "acquisition"]
    labels: tuple[str, ...]
    model_revision: Identifier
    tokenizer_revision: Identifier
    adapter_revision: str | None = None
    weights: tuple[FileRef, ...] = Field(min_length=1)
    preprocessing: FileRef
    inference_entrypoint: Identifier
    training_release: FileRef
    split_manifest: FileRef
    source: SourceIdentity
    mode: Literal["advisory"] = "advisory"

    @model_validator(mode="after")
    def label_order(self):
        validate_labels(self.task_type, self.labels)
        return self


class ModelPrediction(V2):
    task_type: Literal["relation", "criterion", "trajectory_diagnosis", "acquisition"]
    input_hash: Hash
    model_revision: Identifier
    status: Literal["success", "unavailable", "invalid", "timeout"]
    labels: tuple[str, ...]
    probabilities: tuple[Annotated[float, Field(ge=0, le=1)], ...] | None = None
    evidence_ids: tuple[str, ...] = ()
    error_code: str | None = None

    @model_validator(mode="after")
    def probability_space(self):
        validate_labels(self.task_type, self.labels)
        if self.status == "success":
            if (
                self.probabilities is None
                or len(self.probabilities) != len(self.labels)
                or abs(sum(self.probabilities) - 1) > 1e-6
            ):
                raise ValueError("probabilities must align with ordered task labels and sum to one")
        elif self.probabilities is not None:
            raise ValueError("unavailable prediction cannot invent probabilities")
        return self


def validate_labels(task_type, labels):
    spaces = {
        "relation": {"SUPPORTED", "CONTRADICTED", "INSUFFICIENT"},
        "criterion": {"MET", "PARTIAL", "NOT_MET", "INSUFFICIENT", "NOT_APPLICABLE"},
        "trajectory_diagnosis": {"diagnosed", "no_issue", "insufficient"},
        "acquisition": {"effective", "ineffective", "undetermined"},
    }
    if len(labels) != len(set(labels)) or set(labels) != spaces[task_type]:
        raise ValueError("model labels do not match task type")


class RunManifest(V2):
    id: Identifier
    session_id: Identifier
    executor: Executor
    scenario: FileRef
    runtime: FileRef
    evaluation: FileRef
    seed: NonNegativeInt
    split: Literal["train", "dev", "test", "regression"]
    budget: Budget
    provider: Identifier
    model_revision: Identifier
    source: SourceIdentity
    lineage: Lineage
    attempts: tuple[ModelAttemptUsage, ...] = ()
    campaign: FileRef | None = None
    policy: FileRef | None = None
    tools_schema_digest: Hash | None = None
    started_at: Timestamp | None = None
    ended_at: Timestamp | None = None
    status: Literal["created", "running", "completed", "failed", "cancelled", "blocked"] = "created"
    actual_consumption: ActualConsumption | None = None


class BeliefFact(V2):
    id: Identifier
    status: Literal["known", "unknown", "conflict", "hypothesis"]
    statement: str
    observed_refs: tuple[EvidenceRefV2, ...]

    @model_validator(mode="after")
    def known(self):
        if self.status in {"known", "conflict"} and not self.observed_refs:
            raise ValueError("knowledge requires observed sources")
        return self


class BeliefState(V2):
    session_id: Identifier
    as_of: VersionPoint
    facts: tuple[BeliefFact, ...]
    observation_hashes: tuple[Hash, ...]


class DecisionQuestion(V2):
    id: Identifier
    type: Literal["boolean", "choice", "score", "text"]
    text: str
    choices: tuple[str, ...] = ()


class DecisionRequest(V2):
    id: Identifier
    purpose: str
    actor: Executor
    branch: str | None = None
    as_of: VersionPoint
    observation: Observation
    questions: tuple[DecisionQuestion, ...]
    expected_provider: Identifier
    expected_model_revision: Identifier
    deadline: Timestamp
    budget: Budget
    input_hash: Hash

    @model_validator(mode="after")
    def identity(self):
        if digest(self.observation) != self.input_hash:
            raise ValueError("decision input hash mismatch")
        return self


class DecisionResult(V2):
    request_id: Identifier
    input_hash: Hash
    provider: Identifier
    model_revision: Identifier
    status: Literal["success", "unavailable", "invalid", "timeout"]
    answers: dict[str, JsonValue] | None = None
    raw_distribution: dict[str, dict[str, float]] | None = None
    attempts: tuple[ModelAttemptUsage, ...]
    elapsed_seconds: Annotated[float, Field(ge=0)]
    error_code: str | None = None

    @model_validator(mode="after")
    def success(self):
        if self.status == "success" and self.answers is None:
            raise ValueError("success requires answers")
        if self.status != "success" and self.answers is not None:
            raise ValueError("failed provider cannot supply answers")
        return self


class SkillSpec(V2):
    id: Identifier
    version: PositiveInt
    goal: str
    preconditions: tuple[str, ...]
    postconditions: tuple[str, ...]
    steps: tuple[ActionProposal, ...]
    failure_conditions: tuple[str, ...]
    source_trajectories: tuple[FileRef, ...]
    source_splits: tuple[Literal["train", "dev"], ...]
    applicable_structures: tuple[str, ...]
    counterexamples: tuple[str, ...]
    tool_versions: dict[str, str]
    status: Literal["candidate", "validated", "deprecated"]
    validation_records: tuple[FileRef, ...] = ()
    content_hash: Hash

    @model_validator(mode="after")
    def validated(self):
        if self.status == "validated" and not self.validation_records:
            raise ValueError("validated skill needs evidence")
        if digest(self.model_dump(mode="json", exclude={"content_hash"})) != self.content_hash:
            raise ValueError("skill hash mismatch")
        return self


class SkillBundle(V2):
    id: Identifier
    revision: Identifier
    members: tuple[FileRef, ...]


class ActionBoundary(V2):
    transaction_id: Identifier
    request_id: Identifier
    start_seq: NonNegativeInt
    end_seq: NonNegativeInt
    storage_revision: NonNegativeInt

    @model_validator(mode="after")
    def ordered(self):
        if self.start_seq > self.end_seq:
            raise ValueError("invalid action boundary")
        return self


class Trajectory(V2):
    id: Identifier
    session_id: Identifier
    boundaries: tuple[ActionBoundary, ...]
    steps: tuple[ObservedStep, ...]
    executors: tuple[Executor, ...]
    state_digests: tuple[Hash, ...]
    lineage: Lineage


class Diagnosis(V2):
    trajectory: FileRef
    event_facts: tuple[EvidenceRefV2, ...]
    interpretation: str
    uncertainty: str
    alternatives: tuple[str, ...]
    evaluation: FileRef


class BranchManifest(V2):
    id: Identifier
    parent_run: FileRef
    fork: VersionPoint
    boundary: ActionBoundary
    intervention: ActionProposal
    id_map: dict[str, str]
    prefix_digest: Hash
    executor: Executor
    runtime: FileRef
    evaluation: FileRef
    lineage: Lineage
    split: Literal["train", "dev", "test", "regression"]

    @model_validator(mode="after")
    def boundary_only(self):
        if (
            self.fork.business_seq != self.boundary.end_seq
            or self.fork.storage_revision != self.boundary.storage_revision
        ):
            raise ValueError("branch must fork at complete transaction boundary")
        return self


class StoredObject(V2):
    creator: Executor | None = None
    ref: ObjectRef
    content: dict[str, JsonValue]
    visible_to: tuple[str, ...]
    dependencies: tuple[ObjectRef, ...] = ()
    created_storage_revision: NonNegativeInt


class StoredEvent(V2):
    id: Identifier
    session_id: Identifier
    seq: PositiveInt
    transaction_id: Identifier
    type: Identifier
    executor: Executor
    visible_to: tuple[str, ...]
    refs: tuple[ObjectRef, ...] = ()
    data: dict[str, JsonValue] = {}


class SnapshotExport(V2):
    external_references: tuple[ExternalReference, ...] = ()
    id: Identifier
    session_id: Identifier
    bindings: SessionBindings
    state: WorldStateV2
    objects: tuple[StoredObject, ...]
    events: tuple[StoredEvent, ...]
    boundaries: tuple[ActionBoundary, ...]
    source_digest: Hash
    snapshot_hash: Hash

    @model_validator(mode="after")
    def identity(self):
        if digest(self.model_dump(mode="json", exclude={"snapshot_hash"})) != self.snapshot_hash:
            raise ValueError("snapshot hash mismatch")
        return self


class RestoreResult(V2):
    parent_session_id: Identifier
    replayed: bool = False
    session_id: Identifier
    source_snapshot_hash: Hash
    id_map: dict[str, str]
    state: WorldStateV2
    prefix_digest: Hash
    external_calls: Literal[0] = 0


class EngineerPack(V2):
    id: Identifier
    scenario: FileRef
    config: ObjectRef
    failures: tuple[ObjectRef, ...]
    public_probes: tuple[FileRef, ...]
    requirements: tuple[str, ...]


class EngineerSubmission(V2):
    id: Identifier
    pack: FileRef
    config: FileRef
    explanation: str
    claimed_results: tuple[str, ...]
    executor: Executor


class RegressionReport(V2):
    id: Identifier
    submission: FileRef
    scenario: FileRef
    config: FileRef
    public_results: tuple[ObjectRef, ...]
    hidden_result_summary: str
    unresolved: tuple[str, ...]
    reviewer: Executor
    input_hash: Hash


class StepResult(V2):
    effect_request_id: Identifier | None = None
    request_id: Identifier
    status: Literal["success", "failed", "pending"]
    executor: Executor
    observation: Observation | None = None
    step: ObservedStep | None = None
    boundary: ActionBoundary | None = None
    job_id: Identifier | None = None
    error_code: Identifier | None = None
    replayed: bool = False
    model_attempts: tuple[ModelAttemptUsage, ...] = ()
    actual_consumption: ActualConsumption

    @model_validator(mode="after")
    def outcome(self):
        if self.status == "pending" and self.job_id is None:
            raise ValueError("pending requires job id")
        if self.status == "failed" and self.error_code is None:
            raise ValueError("failure requires error code")
        if self.status == "success" and (self.observation is None or self.step is None):
            raise ValueError("success requires actual observation and step")
        if self.status == "success":
            if self.step.as_of != self.observation.as_of or self.observation.actor != self.executor:
                raise ValueError("step observation/executor mismatch")
            if self.boundary is not None and (
                self.boundary.end_seq != self.observation.as_of.business_seq
                or self.boundary.storage_revision != self.observation.as_of.storage_revision
            ):
                raise ValueError("step observation boundary mismatch")
            effect = self.effect_request_id or self.request_id
            if self.step.request_id != effect or (
                self.boundary is not None and self.boundary.request_id != effect
            ):
                raise ValueError("step/request/boundary association mismatch")
        ids = [
            (a.request_id, a.attempt_id, a.provider, a.model_revision) for a in self.model_attempts
        ]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate model attempt cost")
        return self


class PublicTransactionResult(V2):
    transaction_id: Identifier
    boundary: ActionBoundary
    executor: Executor
    state: PublicState
    objects: tuple[ObjectRef, ...]
    events: tuple[PublicEvent, ...]
    result: dict[str, JsonValue]
    replayed: bool = False


class RequestJobResult(V2):
    job_id: Identifier
    origin_request_id: Identifier
    effect_request_id: Identifier
    status: Literal["queued", "running", "completed", "failed", "needs_context"]
    effect: PublicTransactionResult | None = None
    error_code: str | None = None
    refresh_count: NonNegativeInt = 0
    refresh_history: tuple[JobRefreshRecord, ...] = ()


class RequestResult(V2):
    session_id: Identifier
    request_id: Identifier
    operation: Identifier
    executor: Executor
    status: Literal["completed", "pending", "failed", "unresolved", "needs_context"]
    response: PublicTransactionResult
    jobs: tuple[RequestJobResult, ...] = ()
    read_only: Literal[True] = True
