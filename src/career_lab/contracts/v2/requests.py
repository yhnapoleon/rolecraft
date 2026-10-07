"""Module request payloads inside Command; identity/version are server-owned."""
from .core import *
from .workspace import ProductPayload,WorkspaceImport,LegacyProvenance
from .world import AssistantConfig

class TaskCreate(V2):
    title: str
    goal: str = ''
    priority: int = 0
    order: int = 0
    parent: ObjectRef | None = None
    relations: tuple[ObjectRef,...] = ()
class TaskPatch(V2):
    item_id: Identifier
    expected_revision: PositiveInt
    title: str | None = None
    goal: str | None = None
    priority: int | None = None
    order: int | None = None
    status: Literal['open','active','paused','blocked','done','removed'] | None = None
    parent: ObjectRef | None = None
    clear_parent: bool = False
    relations: tuple[ObjectRef,...] | None = None
class ProductCreate(V2):
    source_return_id: str | None = None
    task: ObjectRef | None = None
    kind: Literal['text','plan','test_plan','options','investigation']
    purpose: str = 'exploration'
    title: str = ''
    content: str = ''
    structured_payload: ProductPayload | None = None
    evidence_refs: tuple[EvidenceRefV2,...] = ()
    legacy: LegacyProvenance | None = None
class ProductEdit(ProductCreate):
    product_id: Identifier
    expected_head: PositiveInt
    removed: bool = False
class ShareCreate(V2):
    product_id: Identifier
    product_version: PositiveInt
    recipient_role: Identifier
    question: str = ''
    purpose: str = 'discussion'
class ShareUpdate(V2):
    product_id: Identifier
    share_id: Identifier
    expected_revision: PositiveInt
    operation: Literal['revoke','restore']
class ResourcePage(PageRequest):
    import_id: str | None = None
    product_id: str | None = None
    review_id: str | None = None
    submission_id: str | None = None
    since_seq: NonNegativeInt | None = None
    as_of_seq: NonNegativeInt | None = None
class BeginRevisionInput(V2):
    parent_submission: ObjectRef
    reason: str
class SubmitInput(V2):
    decision: Literal['launch','launch_narrow','defer_with_conditions','no_go']
    products: tuple[ObjectRef,...]
    config: ObjectRef | None = None
    evidence_refs: tuple[EvidenceRefV2,...] = ()
class ReviewInput(V2):
    subjects: tuple[ObjectRef,...]
    purpose: str
    scope: tuple[str,...]
    question: str = ''
class TurnInput(V2):
    role_id: Identifier
    text: Annotated[str,Field(min_length=1,max_length=4000)]
    shares: tuple[ObjectRef,...] = ()
    task: ObjectRef | None = None
class ApprovalInput(V2):
    request: ObjectRef
    expected_request_revision: PositiveInt
class FeedbackInput(V2):
    subject: ObjectRef
    retry: bool = False
class DelegationInput(V2):
    capabilities: tuple[Literal['read','act','submit'],...] = ('read',)
    allowed_actions: tuple[str,...] | None = None
    allowed_objects: tuple[str,...] | None = None
    create_under_tasks: tuple[str,...] = ()
    expires_at: Timestamp
    agent_label: str
class DelegationRevoke(V2):
    delegation_id: Identifier
class EvidenceRead(V2):
    submission_id: Identifier
    criterion_id: Identifier
    evidence_id: Identifier
class ActionInput(V2):
    tool: Literal['apply_config','refresh_index','request_business','accept_counteroffer','pause','resume','read_material']
    config: AssistantConfig | None = None
    request: ObjectRef | None = None
    terms: dict[str,NonNegativeInt] = {}
    reason: str = ''
    evidence_refs: tuple[EvidenceRefV2,...] = ()
    material: ObjectRef | None = None


class ProductAdopt(V2):
    product_id: Identifier
    product_version: PositiveInt
    expected_head: PositiveInt
    status: Literal['unadopted','adopted','rejected']

class TaskBatch(V2):
    creates: tuple[TaskCreate,...] = ()
    updates: tuple[TaskPatch,...] = ()


class RequestResultQuery(V2):
    request_id: Identifier
