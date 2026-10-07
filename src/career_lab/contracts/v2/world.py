"""Scenario providers implement behavior against these frozen public types."""
from typing import Literal
from pydantic import Field, JsonValue, model_validator
from .core import *
from .provider import ProviderMessage

class DisclosurePolicy(V2):
    mode: Literal['public', 'role_only', 'paraphrase_only', 'never']
    actors: tuple[str, ...] = ()
    paraphrase: str | None = None
    @model_validator(mode='after')
    def has_paraphrase(self):
        if self.mode == 'paraphrase_only' and not self.paraphrase:
            raise ValueError('paraphrase_only requires approved text')
        return self

class SourceFragment(V2):
    ref: EvidenceRefV2
    text: str
    channel: Literal['fact', 'material', 'memory', 'attachment', 'event', 'error', 'export']
    disclosure: DisclosurePolicy
    fact_ids: tuple[str, ...] = ()

class DisclosedFragment(V2):
    ref: EvidenceRefV2
    text: str
    channel: str
    fact_ids: tuple[str, ...] = ()
    verification: Literal['unverified','model_extracted','verified','rejected'] = 'unverified'

class ObservedFragment(DisclosedFragment):
    audience: Literal['learner','role_private','model_only']
    acquired_via: Literal['material_read','tool_result','role_reply','displayed']
    acquired_at_seq: NonNegativeInt
    disclosure_ref: ObjectRef | None = None
    @model_validator(mode='after')
    def actual_reply(self):
        if self.acquired_via=='role_reply' and self.disclosure_ref is None:raise ValueError('role reply needs actual disclosure record')
        return self

class MaterialMetadata(V2):
    id: Identifier
    version: PositiveInt
    title: str
    domain: Identifier

class FactV2(V2):
    id: Identifier
    version: PositiveInt
    value: JsonValue
    unit: str | None = None
    source: EvidenceRefV2
    disclosure: DisclosurePolicy

class MaterialV2(V2):
    id: Identifier
    version: PositiveInt
    title: str
    fragments: tuple[SourceFragment, ...]
    domain: Identifier

class RoleSpecV2(V2):
    id: Identifier
    name: str
    responsibilities: tuple[str, ...]
    goals: tuple[str, ...]
    known_materials: tuple[str, ...]
    known_facts: tuple[str, ...]
    disclosure_policy: dict[str, DisclosurePolicy]
    approval_authority: tuple[str, ...] = ()
    event_subscriptions: tuple[str, ...] = ()
    acceptable_conditions: tuple[str, ...] = ()
    unacceptable_conditions: tuple[str, ...] = ()

class AssistantConfig(V2):
    id: Identifier
    session_id: Identifier
    version: PositiveInt = 1
    config_version: NonNegativeInt = 0
    domains: tuple[str, ...]
    scope_filter: bool = True
    update_strategy: Literal['daily', 'realtime', 'manual_policy'] = 'daily'
    fallback: Literal['human', 'none'] = 'human'
    chunk_size: PositiveInt = 500
    retrieval_limit: PositiveInt = 3
    min_score: Annotated[float,Field(ge=0)] = 0.35
    min_score_calibration: FileRef | None = None
    freshness_guard: Literal['none','warn','fallback'] = 'none'
    manual_domains: tuple[str,...] = ()
    prohibited_topics: tuple[str, ...] = ()
    work_items: tuple[str, ...] = ()
    participants: NonNegativeInt = 0
    launch_day: PositiveInt = 7

class EffectiveConfig(V2):
    requested: AssistantConfig
    effective: AssistantConfig
    differences: dict[str, str] = {}

class TestRequestV2(V2):
    query: Annotated[str, Field(min_length=1, max_length=4000)]
    config_version: NonNegativeInt
    declared_category: str | None = None
    declared_expected: str | None = None

class RetrievedChunk(V2):
    id: Identifier
    material_id: Identifier
    version: PositiveInt
    ref: EvidenceRefV2
    score: Annotated[float,Field(ge=0)]

class TestExecutionMetadata(V2):
    executed_at: Timestamp
    executor: Executor
    source_versions: dict[str,PositiveInt]
    indexed_versions: dict[str,PositiveInt]
    used_versions: dict[str,PositiveInt]
    chunks: tuple[RetrievedChunk,...]
    projection_actor: Identifier
    attempts: tuple[ModelAttemptUsage,...] = ()
    cost_complete: bool = False

class TestResultV2(V2):
    id: Identifier
    session_id: Identifier
    version: PositiveInt = 1
    query: str
    execution: TestExecutionMetadata
    config_ref: ObjectRef
    config: EffectiveConfig
    status: Literal['answered', 'answered_with_warning', 'fallback', 'failed']
    answer: str
    citations: tuple[EvidenceRefV2, ...]
    as_of: VersionPoint
    declared_category: str | None = None
    declared_expected: str | None = None
    observed_coverage: tuple[str, ...] = ()
    error_code: str | None = None

class ScenarioBundle(V2):
    id: Identifier
    revision: Identifier
    structure_id: Identifier
    files: tuple[FileRef, ...]
    public_files: tuple[str, ...]
    private_files: tuple[str, ...]
    role_specs: tuple[RoleSpecV2, ...]
    domains: dict[str, tuple[str, ...]]
    capabilities: tuple[str, ...]
    baseline_config: AssistantConfig
    initial_resources: dict[str, NonNegativeInt]
    lineage: tuple[str, ...] = ()
    split: Literal['train', 'dev', 'test', 'regression']
    @model_validator(mode='after')
    def complete_manifest(self):
        paths=[f.path for f in self.files]
        if len(paths)!=len(set(paths)) or set(self.public_files)&set(self.private_files):
            raise ValueError('duplicate files or ambiguous visibility')
        if set(paths)!=set(self.public_files)|set(self.private_files):
            raise ValueError('every runtime file requires visibility classification')
        return self

class SessionBindings(V2):
    scenario: FileRef
    runtime: FileRef
    evaluation: FileRef
    rules_revision: Literal['rules-v4'] = 'rules-v4'
    rubric_revision: str = 'rubric-v2'
    evidence_revision: str = 'evidence-v2'

class WorldStateV2(VersionPoint):
    session_id: Identifier
    status: Literal['active', 'paused', 'submitted'] = 'active'
    cycle_id: Identifier
    config_version: NonNegativeInt = 0
    resources: dict[str, NonNegativeInt]
    applied_milestones: tuple[str, ...] = ()

class ScenarioStateV2(V2):
    id: Identifier
    session_id: Identifier
    version: PositiveInt
    current_config: ObjectRef
    source_versions: dict[str,PositiveInt]
    indexed_versions: dict[str,PositiveInt]
    material_activation: dict[str,NonNegativeInt]

def assistant_config_content_hash(config:AssistantConfig):
    return digest(config.model_dump(mode='json',exclude={'id','session_id','version','config_version'}))

class BusinessBasis(V2):
    mode: Literal['proposed','applied']
    config: AssistantConfig
    config_ref: ObjectRef | None = None
    based_on: ObjectRef | None = None
    content_hash: Hash
    @model_validator(mode='after')
    def immutable_basis(self):
        if self.content_hash!=assistant_config_content_hash(self.config):raise ValueError('request configuration basis hash mismatch')
        if self.mode=='applied' and (self.config_ref is None or self.config_ref.kind!='config'):raise ValueError('applied basis requires exact config reference')
        if self.mode=='proposed' and self.config_ref is not None:raise ValueError('proposed basis is not an applied config')
        return self

class BusinessRequest(V2):
    basis: BusinessBasis
    id: Identifier
    session_id: Identifier
    version: PositiveInt
    requested: dict[str, NonNegativeInt]
    reason: Annotated[str, Field(min_length=1)]
    evidence_refs: tuple[EvidenceRefV2, ...] = ()
    status: Literal['pending', 'approved', 'rejected', 'countered', 'accepted', 'withdrawn'] = 'pending'
    previous_request: ObjectRef | None = None
    as_of: VersionPoint
    executor: Executor

class BusinessDecision(V2):
    id: Identifier
    session_id: Identifier
    version: PositiveInt
    request: ObjectRef
    status: Literal['approved', 'rejected', 'countered', 'accepted']
    decider: Identifier
    rule_revision: Identifier
    granted: dict[str, NonNegativeInt] = {}
    countered: dict[str, NonNegativeInt] = {}
    reason_code: Identifier
    reason: str
    evidence_refs: tuple[EvidenceRefV2, ...] = ()
    as_of: VersionPoint
    @model_validator(mode='after')
    def no_unapproved_grants(self):
        if self.status not in {'approved','accepted'} and self.granted:
            raise ValueError('non-approved decision cannot grant resources')
        return self

class DisclosureRecord(V2):
    fact_id: Identifier
    source: EvidenceRefV2
    reply_ref: ObjectRef
    quote: Annotated[str, Field(min_length=1)]
    verification: Literal['model_extracted', 'verified', 'rejected']
    displayed_at_seq: NonNegativeInt | None = None
    # Actual disclosure is not evidence of understanding.

class PublicDisclosureSource(EvidenceRefV2):
    quote: None = None
    span_start: None = None
    span_end: None = None

class PublicDisclosureRecord(V2):
    fact_id: Identifier
    source: PublicDisclosureSource
    reply_ref: ObjectRef
    quote: Annotated[str, Field(min_length=1)]
    verification: Literal['model_extracted','verified','rejected']
    displayed_at_seq: NonNegativeInt

class RoleAuditScope(V2):
    capabilities: tuple[Literal['read','act','submit','approve','delegate','research'],...]
    actor_id: Identifier
    executor: Executor
    credential_id: Identifier
    allowed_objects: tuple[str,...] | None = None
    allowed_actions: tuple[str,...] | None = None
    expires_at: Timestamp | None = None

class RoleAuditReceivedShare(V2):
    share: ObjectRef
    product: ObjectRef
    role_id: Identifier
    received_at: VersionPoint
    fragment: DisclosedFragment
    @model_validator(mode='after')
    def source(self):
        if self.share.kind!='share' or self.product.kind!='product' or self.fragment.ref.kind!='product':raise ValueError('invalid role share receipt')
        if self.share.session_id!=self.product.session_id or self.fragment.ref.session_id!=self.product.session_id:raise ValueError('cross-session role share receipt')
        if (self.fragment.ref.object_id,self.fragment.ref.version)!=(self.product.object_id,self.product.version) or self.fragment.verification!='verified':raise ValueError('role share receipt source mismatch')
        return self

class RoleAuditMemory(V2):
    fragment: DisclosedFragment
    role_id: Identifier
    learner_refs: tuple[ObjectRef,...] = ()
    provenance: tuple[EvidenceRefV2,...] = ()
    @model_validator(mode='after')
    def source(self):
        if self.fragment.verification!='verified' or any(r.session_id!=self.fragment.ref.session_id for r in (*self.learner_refs,*self.provenance)):raise ValueError('invalid role memory provenance')
        return self

class RoleGenerationAudit(V2):
    phase: Literal['attempt','completed'] = 'attempt'
    job_id: Identifier
    job_attempt: PositiveInt
    request: ObjectRef
    reply: ObjectRef | None = None
    intended_reply_id: Identifier | None = None
    scope: RoleAuditScope
    prompt_messages: tuple[ProviderMessage,...] = Field(min_length=1)
    prompt_hash: Hash
    history_revision: Hash
    refresh_count: NonNegativeInt = 0
    attempts: tuple[ModelAttemptUsage,...] = ()
    error_code: Identifier | None = None
    received_shares: tuple[RoleAuditReceivedShare,...] = ()
    memories: tuple[RoleAuditMemory,...] = ()
    used_sources: tuple[DisclosedFragment,...] = ()
    @model_validator(mode='after')
    def identity(self):
        if self.request.kind!='role_turn':raise ValueError('role audit needs original turn')
        if (self.phase=='completed')!=(self.reply is not None):raise ValueError('completed audit requires exact public reply')
        if self.reply is not None and (self.reply.kind!='role_reply' or self.reply.session_id!=self.request.session_id or self.error_code is not None):raise ValueError('invalid role audit reply')
        wire=[{'role':m.role,'content':m.content,**({'tool_call_id':m.tool_call_id} if m.tool_call_id is not None else {})} for m in self.prompt_messages]
        if digest(wire)!=self.prompt_hash:raise ValueError('role audit prompt hash mismatch')
        if len({a.attempt_id for a in self.attempts})!=len(self.attempts):raise ValueError('duplicate role model attempt')
        if any(a.request_id!=self.request.object_id for a in self.attempts):raise ValueError('role attempt request mismatch')
        refs=[r.share for r in self.received_shares]+[r.product for r in self.received_shares]+[m.fragment.ref for m in self.memories]+[r.ref for r in self.used_sources]
        if any(r.session_id!=self.request.session_id for r in refs):raise ValueError('cross-session role audit')
        return self

class RoleContext(V2):
    # Internal only. Ordinary read/view/replay must never return this carrier.
    generation_audit: RoleGenerationAudit | None = None
    session_id: Identifier
    role_id: Identifier
    as_of: VersionPoint
    sources: tuple[DisclosedFragment, ...]
    shared_products: tuple[ObjectRef, ...] = ()
    conversations: tuple[ObjectRef, ...] = ()
    known_events: tuple[ObjectRef, ...] = ()
    sourced_memory: tuple[DisclosedFragment, ...] = ()
    prompt_fact_ids: tuple[str, ...] = ()
    actual_disclosures: tuple[DisclosureRecord, ...] = ()
    omitted_sources: tuple[ObjectRef, ...] = ()
    context_hash: Hash

class ToolSchema(V2):
    name: Identifier
    capability: Literal['read','act','submit']
    parameters: dict[str, JsonValue]
    parameters_hash: Hash
    available: bool
    unavailable_code: str | None = None
    @model_validator(mode='after')
    def hash_matches(self):
        if digest(self.parameters)!=self.parameters_hash:
            raise ValueError('tool schema hash mismatch')
        return self

class Observation(V2):
    session_id: Identifier
    actor: Executor
    as_of: VersionPoint
    visible_sources: tuple[ObservedFragment, ...]
    catalog: tuple[MaterialMetadata,...] = ()
    actual_disclosures: tuple[PublicDisclosureRecord,...] = ()
    read_versions: tuple[ObjectRef, ...] = ()
    events: tuple[ObjectRef, ...] = ()
    tools: tuple[ToolSchema, ...] = ()
    products: tuple[ObjectRef, ...] = ()
    tests: tuple[ObjectRef, ...] = ()
    next_seq: NonNegativeInt
    budget: Budget | None = None
    @model_validator(mode='after')
    def actual_learner_knowledge(self):
        if any(x.ref.session_id!=self.session_id or x.ref.observed_at_seq>self.as_of.business_seq for x in self.visible_sources):raise ValueError('observation source session/time mismatch')
        if any(r.session_id!=self.session_id for r in (*self.read_versions,*self.events,*self.products,*self.tests)):raise ValueError('observation reference session mismatch')
        if any(x.audience!='learner' or x.acquired_at_seq>self.as_of.business_seq for x in self.visible_sources):raise ValueError('observation requires actual learner-acquired sources')
        if any(x.source.session_id!=self.session_id or x.reply_ref.session_id!=self.session_id or x.source.observed_at_seq>x.displayed_at_seq for x in self.actual_disclosures):raise ValueError('disclosure source/reply session or time mismatch')
        if any(x.displayed_at_seq is None or x.displayed_at_seq>self.as_of.business_seq for x in self.actual_disclosures):raise ValueError('observation cannot claim undisplayed role disclosure')
        return self

class JobRefreshRecord(V2):
    previous_as_of: VersionPoint
    reason: Identifier
    attempt: NonNegativeInt
    queued_at: Timestamp | None = None
    started_at: Timestamp | None = None
    parked_at: Timestamp | None = None
    refreshed_at: Timestamp

class JobContextSnapshot(V2):
    session_id: Identifier
    request_id: Identifier
    credential_id: Identifier
    actor: Executor
    action: Identifier
    as_of: VersionPoint
    context_hash: Hash
    sources: tuple[ObjectRef, ...]
    # sources are immutable inputs. These additional refs/fields require current freshness.
    head_dependencies: tuple[ObjectRef, ...] = ()
    state_dependencies: tuple[Literal['config_version','resources','applied_milestones','status','cycle_id'], ...] = ()
    refresh_count: NonNegativeInt = 0
    refresh_history: tuple[JobRefreshRecord,...] = ()
    conflict_policy: Literal['reject_and_refresh'] = 'reject_and_refresh'


class PublicState(VersionPoint):
    session_id: Identifier
    status: Literal['active','paused','submitted']
    cycle_id: Identifier
    config_version: NonNegativeInt

class PublicEvent(V2):
    id: Identifier
    session_id: Identifier
    seq: PositiveInt
    transaction_id: Identifier
    type: Identifier
    executor: Executor
    refs: tuple[ObjectRef,...] = ()
    data: dict[str,JsonValue] = {}
