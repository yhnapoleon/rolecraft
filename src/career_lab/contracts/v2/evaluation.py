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
        if any(x.ref.observed_at_seq>self.as_of.business_seq for x in self.candidate_evidence):raise ValueError('future evidence')
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

class FeedbackV2(V2):
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
    @model_validator(mode='after')
    def adoption(self):
        if self.mode=='scoring' and not self.adoption_record:raise ValueError('scoring requires independent adoption record')
        return self

class TerminalEvaluation(V2):
    subject: ObjectRef
    evaluation: FileRef
    outcome: Literal['satisfied','unsatisfied','undetermined']
    decision: str
    verified_facts: tuple[EvidenceRefV2, ...]
    pending_questions: tuple[str, ...]
    reason: str
