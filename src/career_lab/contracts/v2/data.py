"""Four input families; labels remain separately referenced artifacts."""
from typing import Annotated, Literal, Union
from pydantic import Field, model_validator
from .core import *
from .evaluation import EvidencePackageV2, Applicability

class Lineage(V2):
    structure_id: Identifier
    fact_root_ids: tuple[str, ...] = ()
    run_id: str | None = None
    session_id: str | None = None
    branch_id: str | None = None
    decision_id: str | None = None
    candidate_id: str | None = None
    source_record_ids: tuple[str, ...] = ()
    derivation_ids: tuple[str, ...] = ()
    component_id: Identifier

class Provenance(V2):
    command: str
    source: SourceIdentity
    executor: Executor
    actual_sources: tuple[FileRef, ...]
    transformations: tuple[str, ...] = ()
    license: str | None = None
    captured_at: Timestamp

class RelationInput(V2):
    task_type: Literal['relation'] = 'relation'
    evidence: EvidencePackageV2
    @model_validator(mode='after')
    def kind(self):
        if self.evidence.task_type!='relation':raise ValueError('wrong evidence task')
        return self

class CriterionInput(V2):
    task_type: Literal['criterion'] = 'criterion'
    evidence: EvidencePackageV2
    @model_validator(mode='after')
    def kind(self):
        if self.evidence.task_type!='criterion':raise ValueError('wrong evidence task')
        return self

class ObservedStep(V2):
    id: Identifier
    action: str
    as_of: VersionPoint
    observations: tuple[str, ...]
    evidence_refs: tuple[EvidenceRefV2, ...]
    outcome: Literal['success','failed','unknown']
    error_code: str | None = None

class TrajectoryInput(V2):
    task_type: Literal['trajectory_diagnosis'] = 'trajectory_diagnosis'
    task: str
    steps: tuple[ObservedStep, ...]
    question: str
    logs_complete: bool

class ActionProposal(V2):
    id: Identifier
    tool: Identifier
    arguments: dict[str, JsonValue]
    purpose: str
    expected_cost: Budget | None = None

class DecisionPointInput(V2):
    task_type: Literal['acquisition'] = 'acquisition'
    task: str
    as_of: VersionPoint
    observed_steps: tuple[ObservedStep, ...]
    candidates: tuple[ActionProposal, ...]
    question: str

ModelInput = Annotated[Union[RelationInput,CriterionInput,TrajectoryInput,DecisionPointInput],Field(discriminator='task_type')]
FAMILY_TASK={'relation':'relation','criterion':'criterion','trajectory':'trajectory_diagnosis','acquisition':'acquisition'}

class DatasetRecordV2(V2):
    record_id: Identifier
    family: Literal['relation','criterion','trajectory','acquisition']
    label_tier: Literal['G0','G1','G2','G2v']
    bucket: Literal['env_run','human_session','public_aux','business_synth']
    language: Identifier
    lineage: Lineage
    split: Literal['train','dev','test','regression']
    provenance: Provenance
    model_input: ModelInput
    label_ref: FileRef
    input_hash: Hash
    @model_validator(mode='after')
    def mapping(self):
        if self.model_input.task_type!=FAMILY_TASK[self.family]:raise ValueError('family/task_type mismatch')
        if digest(self.model_input)!=self.input_hash:raise ValueError('input hash mismatch')
        if self.label_ref.path.split('/')[0]!='labels':raise ValueError('labels must live in separate labels/ directory')
        return self

def model_input(record: DatasetRecordV2) -> dict:
    """The only payload accepted by a labeling worker; no lineage/label_ref/gold."""
    return record.model_input.model_dump(mode='json')

class AnnotationDecision(V2):
    task_type: Literal['relation','criterion','trajectory_diagnosis','acquisition']
    label: str
    applicability: Applicability = 'undetermined'
    evidence_ids: tuple[str, ...] = ()
    acceptable_evidence_sets: tuple[tuple[str, ...], ...] = ()
    evidence_evaluable: bool
    missing_reason: str | None = None
    @model_validator(mode='after')
    def label_space(self):
        spaces={'relation':{'SUPPORTED','CONTRADICTED','INSUFFICIENT'},'criterion':{'MET','PARTIAL','NOT_MET','INSUFFICIENT','NOT_APPLICABLE'},'trajectory_diagnosis':{'diagnosed','no_issue','insufficient'},'acquisition':{'effective','ineffective','undetermined'}}
        if self.label not in spaces[self.task_type]:raise ValueError('wrong label namespace')
        if len(set(self.evidence_ids))!=len(self.evidence_ids):raise ValueError('duplicate evidence')
        return self

class AnnotationPass(V2):
    id: Identifier
    executor: Executor
    status: Literal['pending','success','failed','empty']
    input_hash: Hash
    prompt_revision: str | None = None
    model_revision: str | None = None
    evidence_order: tuple[str, ...] = ()
    raw_output: str | None = None
    decision: AnnotationDecision | None = None
    @model_validator(mode='after')
    def result(self):
        if self.status=='success' and (self.decision is None or not self.raw_output):raise ValueError('successful pass needs raw output and parsed result')
        if self.status!='success' and self.decision is not None:raise ValueError('failed pass cannot supply a label')
        return self

class AnnotationV2(V2):
    record_id: Identifier
    annotation_version: Identifier
    input_hash: Hash
    label_tier: Literal['G0','G1','G2','G2v']
    status: Literal['pending','accepted','disputed','failed']
    passes: tuple[AnnotationPass, ...]
    final: AnnotationDecision | None = None
    verifier_id: str | None = None
    adjudication_ref: FileRef | None = None
    @model_validator(mode='after')
    def evidence(self):
        if len({p.id for p in self.passes})!=len(self.passes):raise ValueError('duplicate annotation pass')
        if any(p.input_hash!=self.input_hash for p in self.passes):raise ValueError('input receipt mismatch')
        if self.status!='accepted':
            if self.final is not None:raise ValueError('unaccepted annotation cannot publish final label')
            return self
        if self.final is None:raise ValueError('accepted annotation needs decision')
        successful=[p for p in self.passes if p.status=='success']
        if self.label_tier=='G0' and not self.verifier_id:raise ValueError('G0 needs deterministic verifier')
        if self.label_tier=='G1':
            humans={p.executor.id for p in successful if p.executor.kind=='human'}
            if len(humans)<2 or not self.adjudication_ref:raise ValueError('new G1 requires two independent humans and adjudication')
        if self.label_tier in {'G2','G2v'}:
            if not successful or any(not p.model_revision or not p.prompt_revision for p in successful):raise ValueError('model label needs actual model/prompt identities')
        if self.label_tier=='G2v':
            if len(successful)<2:raise ValueError('G2v needs two successful independent passes')
            a,b=successful[:2]
            if a.prompt_revision==b.prompt_revision or a.evidence_order==b.evidence_order:raise ValueError('G2v needs distinct prompt revisions and evidence orders')
            if a.decision!=b.decision:
                if len(successful)<3 or not self.adjudication_ref or self.final!=successful[2].decision:raise ValueError('disagreement requires actual third-pass adjudication')
            elif self.final!=a.decision:raise ValueError('consensus label differs')
        return self

class LegacyAnnotation(V2):
    original_schema: Literal[1] = 1
    original_tier: Literal['G0','G1','G2']
    original: dict[str, JsonValue]
    original_hash: Hash
    semantics: Literal['legacy_source_semantics_unrevalidated'] = 'legacy_source_semantics_unrevalidated'
    eligible_as_new_g1: Literal[False] = False

class SplitEntry(V2):
    record_id: Identifier
    structure_id: Identifier
    component_id: Identifier
    ancestors: tuple[str, ...] = ()
    split: Literal['train','dev','test','regression']
    seen_test: bool = False
    file: FileRef
    @model_validator(mode='after')
    def seen(self):
        if self.seen_test and self.split not in {'train','regression'}:raise ValueError('seen test cannot remain confirmatory')
        return self

class SplitManifest(V2):
    id: Identifier
    entries: tuple[SplitEntry, ...]
    independent_structure_count: NonNegativeInt
    campaign_id: str | None = None
    test_opened: bool = False
    @model_validator(mode='after')
    def isolation(self):
        by_id={x.record_id:x for x in self.entries}
        if len(by_id)!=len(self.entries):raise ValueError('duplicate record')
        components={};structures={}
        for x in self.entries:
            for groups,key in ((components,x.component_id),(structures,x.structure_id)):
                if key in groups and groups[key]!=x.split:raise ValueError('connected records cross splits')
                groups[key]=x.split
            for ancestor in x.ancestors:
                if ancestor not in by_id:raise ValueError('unknown ancestor')
                if by_id[ancestor].split!=x.split:raise ValueError('derivation crosses split')
        if len(structures)!=self.independent_structure_count:raise ValueError('structure count mismatch')
        return self

class CampaignCandidate(V2):
    id: Identifier
    runtime: FileRef
    evaluation: FileRef
    source: SourceIdentity
    budget: Budget

class TestCampaign(V2):
    id: Identifier
    candidates: tuple[CampaignCandidate, ...] = Field(min_length=1)
    split_manifest: FileRef
    frozen_at: Timestamp
    opened_at: Timestamp | None = None
    output_audience: tuple[str, ...]
    @model_validator(mode='after')
    def chronology(self):
        if len({x.id for x in self.candidates})!=len(self.candidates):raise ValueError('duplicate candidate')
        if self.opened_at and self.opened_at<self.frozen_at:raise ValueError('campaign opened before freeze')
        return self

def require_confirmatory(campaign: TestCampaign, candidate: CampaignCandidate, split_manifest: FileRef):
    if campaign.opened_at is None or split_manifest!=campaign.split_manifest or candidate not in campaign.candidates:
        raise ProtocolError('campaign_not_authorized',status=403)

def require_training_split(split: str):
    if split not in {'train','dev'}:raise ProtocolError('training_split_forbidden',status=403)
