from typing import Literal
from pydantic import Field, model_validator
from .core import *

Applicability = Literal['applicable','not_applicable','undetermined']
CriterionLabel = Literal['MET','PARTIAL','NOT_MET','INSUFFICIENT','NOT_APPLICABLE']
RelationLabel = Literal['SUPPORTED','CONTRADICTED','INSUFFICIENT']

class CandidateEvidenceV2(V2):
    id: Identifier
    text: str
    ref: EvidenceRefV2

class RuleBound(V2):
    lower: Literal['NOT_MET','PARTIAL','MET']
    upper: Literal['NOT_MET','PARTIAL','MET']
    @model_validator(mode='after')
    def ordered(self):
        order=['NOT_MET','PARTIAL','MET']
        if order.index(self.lower)>order.index(self.upper):raise ValueError('inverted rule bound')
        return self

class EvidencePackageV2(V2):
    item_id: Identifier
    task_type: Literal['relation','criterion']
    criterion: str | None = None
    claim: str
    subjects: tuple[EvidenceRefV2, ...]
    purpose: str
    as_of: VersionPoint
    applicability: Applicability
    candidate_evidence: tuple[CandidateEvidenceV2, ...]
    rule_context: dict[str, JsonValue]
    rule_bound: RuleBound | None = None
    completeness: Literal['complete','missing','text_overflow']
    dropped_refs: tuple[ObjectRef, ...] = ()
    missing_refs: tuple[ObjectRef, ...] = ()
    input_hash: Hash
    @model_validator(mode='after')
    def consistent(self):
        if self.applicability!='applicable' and self.rule_bound is not None:raise ValueError('inapplicable/undetermined cannot be scored')
        ids=[x.id for x in self.candidate_evidence]
        if len(set(ids))!=len(ids):raise ValueError('duplicate candidate id')
        if any(x.observed_at_seq>self.as_of.business_seq for x in self.subjects) or any(x.ref.observed_at_seq>self.as_of.business_seq for x in self.candidate_evidence):raise ValueError('future evidence')
        data=self.model_dump(mode='json',exclude={'input_hash'})
        if digest(data)!=self.input_hash:raise ValueError('evidence input hash mismatch')
        return self

class FeedbackItem(V2):
    criterion: Identifier
    label: CriterionLabel
    applicability: Applicability
    source: Literal['verified_rule','model_advice','pending']
    explanation: str
    citations: tuple[EvidenceRefV2, ...]
    rule_bound: RuleBound | None = None
    @model_validator(mode='after')
    def score(self):
        if (self.label in {'NOT_APPLICABLE','INSUFFICIENT'} or self.source!='verified_rule') and self.rule_bound:
            raise ValueError('unknown/advisory labels cannot tighten score bounds')
        return self

ActivityKind = Literal['material_read','test_run','question_sent','reply_received','learner_displayed']

def feedback_point_before(left, right):
    return all(getattr(left,key)<=getattr(right,key) for key in ('business_seq','workspace_revision','storage_revision'))

class FeedbackReferenceCheck(V2):
    # An unavailable source is represented only by a digest of the submitted reference.
    submitted_reference_hash: Hash | None
    status: Literal['exact_reference_verified','unavailable','future_evidence','evidence_version_mismatch','evidence_quote_mismatch','evidence_time_mismatch','source_time_unknown']
    verified_ref: EvidenceRefV2 | None = None
    valid_at_subject: bool | None = None
    semantic_support: Literal['not_established'] = 'not_established'
    @model_validator(mode='after')
    def evidence(self):
        if (self.status=='exact_reference_verified')!=(self.verified_ref is not None):raise ValueError('verified reference status mismatch')
        if self.verified_ref is None and self.valid_at_subject is not None:raise ValueError('unavailable reference validity is unknown')
        return self

class FeedbackActivity(V2):
    kind: ActivityKind
    ref: EvidenceRefV2
    occurred_at: VersionPoint
    executor: Executor
    actor_id: Identifier
    target: ObjectRef | None = None
    counterparty: str | None = None

class FeedbackActivityCount(V2):
    status: Literal['complete','unknown'] = 'unknown'
    count: NonNegativeInt | None = None
    verified_records: NonNegativeInt = 0
    @model_validator(mode='after')
    def completeness(self):
        if self.status=='unknown' and self.count is not None:raise ValueError('unknown log cannot assert a count')
        if self.status=='complete' and self.count!=self.verified_records:raise ValueError('complete count must match verified records')
        return self

class FeedbackActivityWindow(V2):
    covered_from: VersionPoint
    covered_through: VersionPoint
    captured_at: VersionPoint
    @model_validator(mode='after')
    def order(self):
        if not feedback_point_before(self.covered_from,self.covered_through) or not feedback_point_before(self.covered_through,self.captured_at):raise ValueError('invalid activity window')
        return self

class VerifiedFactsSnapshot(V2):
    subject: ObjectRef
    status: Literal['verified','partial','unknown']
    as_of: VersionPoint | None
    requested_at: VersionPoint
    captured_at: VersionPoint
    source_snapshot_hash: Hash | None
    references: tuple[FeedbackReferenceCheck,...] = ()
    activity_records: tuple[FeedbackActivity,...] = ()
    activity_totals: dict[ActivityKind,FeedbackActivityCount] = {}
    activity_window: FeedbackActivityWindow | None = None
    declared_source_count: NonNegativeInt | None = None
    declared_citation_count: NonNegativeInt | None = None
    verified_source_count: NonNegativeInt | None = None
    author: Executor | None = None
    executor: Executor | None = None
    adopter: Executor | None = None
    actor_id: Identifier | None = None
    summary: tuple[str,...] = ()
    independent_understanding: Literal['unobserved'] = 'unobserved'
    conclusion_quality: Literal['not_scored'] = 'not_scored'
    @model_validator(mode='after')
    def historical(self):
        if not feedback_point_before(self.requested_at,self.captured_at):raise ValueError('feedback capture precedes request')
        if self.as_of is None:
            if self.status!='unknown' or self.references or self.activity_records or self.activity_totals or any(v is not None for v in (self.declared_source_count,self.declared_citation_count,self.verified_source_count)):raise ValueError('unknown subject point cannot assert historical facts')
        elif not feedback_point_before(self.as_of,self.requested_at):raise ValueError('future subject point')
        refs=[r.verified_ref for r in self.references if r.verified_ref is not None]+[r.ref for r in self.activity_records]+[r.target for r in self.activity_records if r.target is not None]
        if any(r.session_id!=self.subject.session_id for r in refs):raise ValueError('cross-session factual evidence')
        if self.as_of is not None and any(r.observed_at_seq>self.as_of.business_seq for r in refs if isinstance(r,EvidenceRefV2)):raise ValueError('future factual reference')
        if len({r.submitted_reference_hash for r in self.references})!=len(self.references):raise ValueError('duplicate submitted reference')
        if any(not feedback_point_before(r.occurred_at,self.as_of) for r in self.activity_records):raise ValueError('future activity fact')
        if len({canonical(r.ref) for r in self.activity_records})!=len(self.activity_records):raise ValueError('duplicate activity record')
        for kind,total in self.activity_totals.items():
            if total.verified_records!=sum(r.kind==kind for r in self.activity_records):raise ValueError('activity total mismatch')
            if total.status=='complete':
                zero=VersionPoint(business_seq=0,workspace_revision=0,storage_revision=0)
                if self.as_of is None or self.activity_window is None or self.activity_window.covered_from!=zero or not feedback_point_before(self.as_of,self.activity_window.covered_through):raise ValueError('complete activity count needs full historical window')
        if self.activity_window and not feedback_point_before(self.activity_window.captured_at,self.captured_at):raise ValueError('activity window exceeds captured snapshot')
        if self.declared_citation_count is not None and self.declared_citation_count!=len(self.references):raise ValueError('declared citation count mismatch')
        known={(x.verified_ref.session_id,x.verified_ref.kind,x.verified_ref.object_id,x.verified_ref.version,x.verified_ref.config_version) for x in self.references if x.verified_ref is not None}
        if self.verified_source_count is not None and self.verified_source_count!=len(known):raise ValueError('verified source count mismatch')
        if self.declared_source_count is not None and self.verified_source_count is not None and self.verified_source_count>self.declared_source_count:raise ValueError('verified sources exceed declared sources')
        return self

class HistoricalResponsibilityFinding(V2):
    criterion: Identifier
    kind: Literal['actual_action','commitment','completion_claim','unknown']
    state: Literal['active','withdrawn','unknown']
    occurred_at: VersionPoint | None
    evaluated_at: VersionPoint
    scope: tuple[ObjectRef,...] = Field(min_length=1)
    finding: Literal['unknown','recorded_commitment','verified_breach','verified_within_limit','claim_matches_record','verified_claim_mismatch','claim_has_run_records','recorded_action']
    explanation: str
    sources: tuple[EvidenceRefV2,...] = ()
    actor_id: Identifier | None = None
    executor: Executor | None = None
    @model_validator(mode='after')
    def basis(self):
        if self.occurred_at is not None and not feedback_point_before(self.occurred_at,self.evaluated_at):raise ValueError('future responsibility')
        if self.occurred_at is None and self.finding!='unknown':raise ValueError('known responsibility requires occurrence point')
        if self.finding!='unknown' and not self.sources:raise ValueError('known responsibility needs verified sources')
        if self.kind=='commitment' and self.finding not in {'unknown','recorded_commitment'}:raise ValueError('commitment does not prove action')
        if self.kind=='unknown' and self.finding!='unknown':raise ValueError('unknown responsibility cannot be assessed')
        return self

class HistoricalResponsibilitiesSnapshot(V2):
    subject: ObjectRef
    as_of: VersionPoint | None
    requested_at: VersionPoint
    captured_at: VersionPoint
    source_snapshot_hash: Hash | None
    completeness: Literal['complete','partial','unknown'] = 'unknown'
    coverage: FeedbackActivityWindow | None = None
    entries: tuple[HistoricalResponsibilityFinding,...] = ()
    @model_validator(mode='after')
    def historical(self):
        if not feedback_point_before(self.requested_at,self.captured_at):raise ValueError('responsibility capture precedes request')
        if self.as_of is None and (self.entries or self.completeness!='unknown'):raise ValueError('unknown subject point cannot assert responsibilities')
        if self.as_of is not None and not feedback_point_before(self.as_of,self.requested_at):raise ValueError('future subject point')
        if self.completeness=='complete':
            if self.as_of is None or self.coverage is None or self.coverage.covered_from!=VersionPoint(business_seq=0,workspace_revision=0,storage_revision=0) or not feedback_point_before(self.as_of,self.coverage.covered_through):raise ValueError('complete responsibilities need trusted full coverage')
        if self.coverage and not feedback_point_before(self.coverage.captured_at,self.captured_at):raise ValueError('responsibility coverage exceeds capture')
        for item in self.entries:
            if item.evaluated_at!=self.as_of or self.subject not in item.scope:raise ValueError('responsibility subject anchor mismatch')
            if any(r.session_id!=self.subject.session_id for r in (*item.scope,*item.sources)):raise ValueError('cross-session responsibility')
            if any(r.observed_at_seq>self.as_of.business_seq for r in item.sources):raise ValueError('future responsibility source')
        return self

class FeedbackResponseRecord(V2):
    read_projection: Literal['partial'] | None = None
    id: Identifier
    session_id: Identifier
    version: Literal[1] = 1
    feedback: ObjectRef
    kind: Literal['objection','supplement']
    section: Literal['general','verified_facts','historical_responsibilities','rule_items','model_advice'] = 'general'
    criterion: Identifier | None = None
    text: Annotated[str,Field(min_length=1,max_length=12000)]
    evidence: tuple[EvidenceRefV2,...] = ()
    recorded_at: VersionPoint
    executor: Executor
    @model_validator(mode='after')
    def linked(self):
        if self.feedback.kind!='feedback' or self.feedback.session_id!=self.session_id:raise ValueError('invalid feedback link')
        if not self.text.strip():raise ValueError('response text is empty')
        if self.kind=='supplement' and not self.evidence and self.read_projection is None:raise ValueError('supplement needs exact evidence')
        if any(r.session_id!=self.session_id or r.observed_at_seq>self.recorded_at.business_seq for r in self.evidence):raise ValueError('invalid response evidence')
        if len({canonical(r) for r in self.evidence})!=len(self.evidence):raise ValueError('duplicate response evidence')
        return self

class FeedbackV2(V2):
    read_projection: Literal['partial'] | None = None
    id: Identifier
    session_id: Identifier
    version: PositiveInt = 1
    subject: ObjectRef
    evaluation: FileRef
    as_of: VersionPoint
    mode: Literal['advisory','scoring'] = 'advisory'
    adoption_record: FileRef | None = None
    items: tuple[FeedbackItem, ...]
    business_response: str
    next_options: tuple[str, ...]
    verified_coverage: Annotated[float, Field(ge=0,le=1)]
    model_coverage: Annotated[float, Field(ge=0,le=1)]
    independent_understanding: Literal['unobserved','observed_with_evidence'] = 'unobserved'
    # None means the historical feedback never recorded this section.
    verified_facts: tuple[VerifiedFactsSnapshot,...] | None = None
    historical_responsibilities: tuple[HistoricalResponsibilitiesSnapshot,...] | None = None
    rule_items: tuple[FeedbackItem,...] | None = None
    @model_validator(mode='after')
    def adoption(self):
        if self.mode=='scoring' and not self.adoption_record:raise ValueError('scoring requires independent adoption record')
        if self.read_projection is None:
            if any(x.source_snapshot_hash is None for x in (*(self.verified_facts or ()),*(self.historical_responsibilities or ()))):raise ValueError('stored feedback needs snapshot identity')
            if any(r.submitted_reference_hash is None for facts in self.verified_facts or () for r in facts.references):raise ValueError('stored feedback needs submitted reference identity')
        for section in (self.verified_facts,self.historical_responsibilities):
            if section is None:continue
            if len({canonical(x.subject) for x in section})!=len(section):raise ValueError('duplicate subject feedback section')
            if any(x.subject.session_id!=self.session_id or not feedback_point_before(x.requested_at,self.as_of) for x in section):raise ValueError('feedback section scope or time mismatch')
        return self

class TerminalEvaluation(V2):
    subject: ObjectRef
    evaluation: FileRef
    outcome: Literal['satisfied','unsatisfied','undetermined']
    decision: str
    verified_facts: tuple[EvidenceRefV2, ...]
    pending_questions: tuple[str, ...]
    reason: str
