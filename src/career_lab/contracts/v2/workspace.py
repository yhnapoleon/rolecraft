from typing import Annotated, Literal, Union
from pydantic import Field, JsonValue, model_validator
from .core import *

class WorkspaceTask(V2):
    id: Identifier
    session_id: Identifier
    title: str
    goal: str = ''
    priority: int = 0
    order: int = 0
    status: Literal['open','active','paused','blocked','done','removed'] = 'open'
    parent: ObjectRef | None = None
    relations: tuple[ObjectRef, ...] = ()
    revision: PositiveInt
    created_at: Timestamp
    updated_at: Timestamp

class TestCase(V2):
    id: Identifier
    revision: PositiveInt = 1
    query: str
    intent: str = ""
    refs: tuple[EvidenceRefV2,...] = ()
    declared_category: str | None = None
    declared_expected: str | None = None
    run: ObjectRef | None = None

class InvestigationBlock(V2):
    id: Identifier
    revision: PositiveInt = 1
    type: Literal['text','note','source_check','retest','test_compare']
    title: str = ''
    test_refs: tuple[ObjectRef,...] = ()
    text: str = ''
    test_ref: ObjectRef | None = None
    source_ref: EvidenceRefV2 | None = None

class TextPayload(V2):
    type: Literal['text'] = 'text'
    body: str

class PlanPayload(V2):
    type: Literal['plan'] = 'plan'
    sections: dict[str, str]

class TestPlanPayload(V2):
    type: Literal['test_plan'] = 'test_plan'
    cases: tuple[TestCase, ...] = ()

class Option(V2):
    id: Identifier
    title: str
    rationale: str = ''
    tradeoffs: tuple[str, ...] = ()

class OptionsPayload(V2):
    type: Literal['options'] = 'options'
    options: tuple[Option, ...] = ()

class InvestigationPayload(V2):
    type: Literal['investigation'] = 'investigation'
    question: str = ''
    blocks: tuple[InvestigationBlock, ...] = ()
    review_note: str = ''
    review_focus: Literal['index','source','uncertain','other'] = 'uncertain'
    review_direction: Literal['unknown','supports','contradicts','mixed'] = 'unknown'

ProductPayload = Annotated[Union[TextPayload,PlanPayload,TestPlanPayload,OptionsPayload,InvestigationPayload], Field(discriminator='type')]

class Adoption(V2):
    status: Literal['unadopted','adopted','rejected'] = 'unadopted'
    adopter: Executor | None = None
    adopted_at: Timestamp | None = None
    @model_validator(mode='after')
    def identity(self):
        if self.status=='adopted' and (self.adopter is None or self.adopted_at is None):
            raise ValueError('adoption requires actual adopter and time')
        return self

class LegacyProvenance(V2):
    source_schema: Identifier
    source_session_id: Identifier
    original_id: Identifier
    original_kind: str
    original_purpose: str | None = None
    # Kept as inert provenance; never interpreted as an action or verified test.
    raw: dict[str, JsonValue]
    original_hash: Hash
    @model_validator(mode='after')
    def safe(self):
        def visit(value):
            if isinstance(value,dict):
                for k,v in value.items():
                    if k.lower() in {'token','authorization','session_token','api_key','password','credential'}:
                        raise ValueError('credentials cannot be imported')
                    visit(v)
            elif isinstance(value,list):
                for x in value:visit(x)
        visit(self.raw)
        if digest(self.raw)!=self.original_hash:raise ValueError('legacy hash mismatch')
        return self

class WorkProductVersion(V2):
    product_id: Identifier
    session_id: Identifier
    version: PositiveInt
    cycle: ObjectRef
    task: ObjectRef | None = None
    kind: Literal['text','plan','test_plan','options','investigation'] = 'text'
    purpose: str = 'exploration'
    title: str = ''
    content: str = ''
    structured_payload: ProductPayload | None = None
    evidence_refs: tuple[EvidenceRefV2, ...] = ()
    author: Executor
    executor: Executor
    source_return_id: str | None = None
    visibility: Literal['private','shared'] = 'private'
    shares: tuple[ObjectRef, ...] = ()
    adoption: Adoption = Adoption()
    draft: bool = True
    removed_at: Timestamp | None = None
    content_hash: Hash
    created_at: Timestamp
    legacy: LegacyProvenance | None = None
    @model_validator(mode='after')
    def content_identity(self):
        if self.structured_payload is not None and self.structured_payload.type!=self.kind:
            raise ValueError('payload type must match kind')
        value={'content':self.content,'structured_payload':self.structured_payload.model_dump(mode='json') if self.structured_payload else None}
        if digest(value)!=self.content_hash:raise ValueError('product content hash mismatch')
        return self

class ProductShare(V2):
    id: Identifier
    session_id: Identifier
    version: PositiveInt
    product: ObjectRef
    recipient_role: Identifier
    question: str = ''
    purpose: str = 'discussion'
    shared_at: VersionPoint
    revoked_at: VersionPoint | None = None
    @model_validator(mode='after')
    def local(self):
        if self.product.session_id!=self.session_id:raise ValueError('cross-session share')
        if self.revoked_at and self.revoked_at.storage_revision<self.shared_at.storage_revision:raise ValueError('revocation before share')
        return self

class ShareChange(V2):
    share: ObjectRef
    operation: Literal['revoke','restore']

class RevisionCycle(V2):
    id: Identifier
    session_id: Identifier
    version: PositiveInt = 1
    parent_submission: ObjectRef | None = None
    opened_at: VersionPoint
    base_state_ref: Identifier
    status: Literal['open','submitted'] = 'open'
    reason: str = ''

class ReviewRequest(V2):
    id: Identifier
    session_id: Identifier
    version: PositiveInt = 1
    subjects: tuple[ObjectRef, ...] = Field(min_length=1)
    purpose: str
    as_of: VersionPoint
    question: str = ''
    scope: tuple[str, ...]
    evaluation: FileRef
    executor: Executor

class SubmissionV2(V2):
    id: Identifier
    session_id: Identifier
    version: PositiveInt = 1
    cycle: ObjectRef
    decision: Literal['launch','launch_narrow','defer_with_conditions','no_go']
    products: tuple[ObjectRef, ...]
    config: ObjectRef | None = None
    evidence_refs: tuple[EvidenceRefV2, ...] = ()
    as_of: VersionPoint
    scenario: FileRef
    evaluation: FileRef
    rules_revision: Literal['rules-v4'] = 'rules-v4'
    executor: Executor

class ImportReference(V2):
    original_id: Identifier
    original_session_id: Identifier
    status: Literal['resolved','missing','foreign_session','unverified_local']
    resolved: ObjectRef | None = None
    @model_validator(mode='after')
    def resolution(self):
        if (self.status=='resolved')!=(self.resolved is not None):raise ValueError('invalid import resolution')
        return self

class WorkspaceImport(V2):
    package_id: Identifier
    mode: Literal['preview','apply']
    source_schema: Identifier
    source_session_id: Identifier
    items: tuple[LegacyProvenance, ...]
    references: tuple[ImportReference, ...] = ()
    package_hash: Hash
    preview_storage_revision: NonNegativeInt | None = None
    @model_validator(mode='after')
    def package(self):
        if self.mode=='apply' and self.preview_storage_revision is None:raise ValueError('apply requires preview version')
        raw=[x.model_dump(mode='json') for x in self.items]
        if digest(raw)!=self.package_hash:raise ValueError('import hash mismatch')
        return self

class ImportResult(V2):
    package_id: Identifier
    mode: Literal['preview','apply']
    id_map: dict[str,ObjectRef]
    unresolved: tuple[ImportReference, ...]
    as_of: VersionPoint
    applied: bool
    conflicts: tuple["ImportConflict",...] = ()
    version_map: tuple["ImportVersionMap",...] = ()


class ImportConflict(V2):
    original_id: Identifier
    original_version: PositiveInt | None = None
    reason: Literal['missing_history','version_conflict','content_conflict','foreign_session','unresolved_reference']
    existing: ObjectRef | None = None
    source_content_hash: Hash | None = None

class ImportVersionMap(V2):
    original_session_id: Identifier
    original_id: Identifier
    original_version: PositiveInt
    target: ObjectRef | None = None
    status: Literal['resolved','unresolved','unverified_local']

ImportResult.model_rebuild()


class ImportedTaskSource(V2):
    task: ObjectRef
    source: LegacyProvenance
    @model_validator(mode='after')
    def identity(self):
        if self.task.kind!='task' or self.source.original_kind!='task':raise ValueError('task provenance kind mismatch')
        return self

class WorkspaceImportReceipt(V2):
    id: Identifier
    session_id: Identifier
    version: PositiveInt = 1
    package_id: Identifier
    package_hash: Hash
    source_schema: Identifier
    source_session_id: Identifier
    fingerprint: Hash
    result: ImportResult
    task_sources: tuple[ImportedTaskSource,...] = ()
    executor: Executor
    created_at: Timestamp
    @model_validator(mode='after')
    def identity(self):
        if self.version!=1 or self.result.mode!='apply' or not self.result.applied:raise ValueError('receipt requires one applied import')
        if self.result.package_id!=self.package_id:raise ValueError('import package identity mismatch')
        refs=tuple(self.result.id_map.values())+tuple(x.target for x in self.result.version_map if x.target is not None)+tuple(x.task for x in self.task_sources)
        if any(r.session_id!=self.session_id for r in refs):raise ValueError('import receipt session mismatch')
        if len({x.task.object_id for x in self.task_sources})!=len(self.task_sources):raise ValueError('duplicate task provenance')
        if any(x.source.source_schema!=self.source_schema or x.source.source_session_id!=self.source_session_id for x in self.task_sources):raise ValueError('import source identity mismatch')
        return self


class WorkspaceProductRead(WorkProductVersion):
    # Unknown sharing completeness must not default to a private assertion.
    visibility: Literal['private','shared'] | None = None

class WorkspaceProductPage(V2):
    items: tuple[WorkspaceProductRead,...]
    shares: tuple[ProductShare,...]
    sharing_complete: bool
    as_of: VersionPoint
    next_cursor: NonNegativeInt | None = None
    @model_validator(mode='after')
    def projection(self):
        if len({s.id for s in self.shares})!=len(self.shares):raise ValueError('duplicate share page entry')
        ids={p.product_id for p in self.items}
        if any(s.product.object_id not in ids for s in self.shares):raise ValueError('share outside product page')
        for product in self.items:
            active=any(s.product.object_id==product.product_id and s.product.version==product.version and s.revoked_at is None for s in self.shares)
            if active and product.visibility!='shared':raise ValueError('active exact-version share must be shared')
            if not active and self.sharing_complete and product.visibility!='private':raise ValueError('complete unshared version must be private')
            if not active and not self.sharing_complete and product.visibility is not None:raise ValueError('incomplete sharing is unknown')
        return self

class WorkspaceSharePage(V2):
    items: tuple[ProductShare,...]
    sharing_complete: bool
    as_of: VersionPoint
    next_cursor: NonNegativeInt | None = None
    @model_validator(mode='after')
    def unique(self):
        if len({s.id for s in self.items})!=len(self.items):raise ValueError('duplicate share page entry')
        return self
