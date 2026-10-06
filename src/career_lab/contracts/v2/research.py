from typing import Literal
from pydantic import Field, JsonValue, model_validator
from .core import *
from .world import Observation, SessionBindings, WorldStateV2
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
    mode: Literal['advisory','scoring'] = 'advisory'
    adoption_record: FileRef | None = None
    @model_validator(mode='after')
    def scoring(self):
        if self.mode=='scoring' and (not self.calibration or not self.adoption_record):raise ValueError('scoring needs calibration and adoption')
        return self

class CandidateBundle(V2):
    id: Identifier
    parent: FileRef
    runtime: FileRef
    evaluation: FileRef
    changes: dict[Literal['agent_prompt','acquisition_parameters','retrieval_parameters'], FileRef]
    hypothesis: str
    allowed_data: tuple[FileRef, ...]
    source_splits: tuple[Literal['train','dev'], ...]
    budget: Budget
    evaluations: tuple[FileRef, ...] = ()
    selection_reason: str | None = None

class ModelBundle(V2):
    id: Identifier
    task_type: Literal['relation','criterion','trajectory_diagnosis','acquisition']
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
    mode: Literal['advisory'] = 'advisory'

class RunManifest(V2):
    id: Identifier
    session_id: Identifier
    executor: Executor
    scenario: FileRef
    runtime: FileRef
    evaluation: FileRef
    seed: NonNegativeInt
    split: Literal['train','dev','test','regression']
    budget: Budget
    provider: Identifier
    model_revision: Identifier
    source: SourceIdentity
    lineage: Lineage
    attempts: tuple[ModelAttemptUsage, ...] = ()
    campaign: FileRef | None = None

class BeliefFact(V2):
    id: Identifier
    status: Literal['known','unknown','conflict','hypothesis']
    statement: str
    observed_refs: tuple[EvidenceRefV2, ...]
    @model_validator(mode='after')
    def known(self):
        if self.status in {'known','conflict'} and not self.observed_refs:raise ValueError('knowledge requires observed sources')
        return self

class BeliefState(V2):
    session_id: Identifier
    as_of: VersionPoint
    facts: tuple[BeliefFact, ...]
    observation_hashes: tuple[Hash, ...]

class DecisionQuestion(V2):
    id: Identifier
    type: Literal['boolean','choice','score','text']
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
    @model_validator(mode='after')
    def identity(self):
        if digest(self.observation)!=self.input_hash:raise ValueError('decision input hash mismatch')
        return self

class DecisionResult(V2):
    request_id: Identifier
    input_hash: Hash
    provider: Identifier
    model_revision: Identifier
    status: Literal['success','unavailable','invalid','timeout']
    answers: dict[str, JsonValue] | None = None
    raw_distribution: dict[str, dict[str,float]] | None = None
    attempts: tuple[ModelAttemptUsage, ...]
    elapsed_seconds: Annotated[float, Field(ge=0)]
    error_code: str | None = None
    @model_validator(mode='after')
    def success(self):
        if self.status=='success' and self.answers is None:raise ValueError('success requires answers')
        if self.status!='success' and self.answers is not None:raise ValueError('failed provider cannot supply answers')
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
    source_splits: tuple[Literal['train','dev'], ...]
    applicable_structures: tuple[str, ...]
    counterexamples: tuple[str, ...]
    tool_versions: dict[str,str]
    status: Literal['candidate','validated','deprecated']
    validation_records: tuple[FileRef, ...] = ()
    content_hash: Hash
    @model_validator(mode='after')
    def validated(self):
        if self.status=='validated' and not self.validation_records:raise ValueError('validated skill needs evidence')
        if digest(self.model_dump(mode='json',exclude={'content_hash'}))!=self.content_hash:raise ValueError('skill hash mismatch')
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
    @model_validator(mode='after')
    def ordered(self):
        if self.start_seq>self.end_seq:raise ValueError('invalid action boundary')
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
    id_map: dict[str,str]
    prefix_digest: Hash
    executor: Executor
    runtime: FileRef
    evaluation: FileRef
    lineage: Lineage
    split: Literal['train','dev','test','regression']
    @model_validator(mode='after')
    def boundary_only(self):
        if self.fork.business_seq!=self.boundary.end_seq or self.fork.storage_revision!=self.boundary.storage_revision:
            raise ValueError('branch must fork at complete transaction boundary')
        return self

class StoredObject(V2):
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
    id: Identifier
    session_id: Identifier
    bindings: SessionBindings
    state: WorldStateV2
    objects: tuple[StoredObject, ...]
    events: tuple[StoredEvent, ...]
    boundaries: tuple[ActionBoundary, ...]
    source_digest: Hash
    snapshot_hash: Hash
    @model_validator(mode='after')
    def identity(self):
        if digest(self.model_dump(mode='json',exclude={'snapshot_hash'}))!=self.snapshot_hash:raise ValueError('snapshot hash mismatch')
        return self

class RestoreResult(V2):
    session_id: Identifier
    source_snapshot_hash: Hash
    id_map: dict[str,str]
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
