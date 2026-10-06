"""Typed, closed-prefix ID mapping. Opaque strings are never globally replaced."""
from dataclasses import dataclass
from copy import deepcopy
from typing import Callable

from pydantic import BaseModel
from career_lab.contracts.v2 import (
    ObjectRef, EvidenceRefV2, Executor, FileRef, LegacyProvenance, SnapshotExport,
    WorkProductVersion, WorkspaceTask, ProductShare, RevisionCycle, ReviewRequest,
    SubmissionV2, FeedbackV2, BusinessRequest, BusinessDecision, AssistantConfig,
    TestResultV2, EvidencePackageV2, StoredObject, StoredEvent, ActionBoundary,
    ProtocolError, VersionPoint, digest, canonical,
)


def ref_key(ref):
    return canonical([ref.session_id, ref.kind, ref.object_id, ref.version, ref.config_version])


def object_key(kind, object_id):
    return canonical(["object", kind, object_id])


@dataclass(frozen=True)
class ObjectCodec:
    model: type[BaseModel]
    id_field: str = "id"


@dataclass(frozen=True)
class EventCodec:
    """Declare all data fields. References must be typed, including empty lists."""
    reference_fields: tuple[str, ...] = ()
    reference_list_fields: tuple[str, ...] = ()
    literal_fields: tuple[str, ...] = ()


DEFAULT_OBJECT_CODECS = {
    "task": ObjectCodec(WorkspaceTask),
    "work_product": ObjectCodec(WorkProductVersion, "product_id"),
    "product": ObjectCodec(WorkProductVersion, "product_id"),
    "share": ObjectCodec(ProductShare),
    "cycle": ObjectCodec(RevisionCycle),
    "review": ObjectCodec(ReviewRequest),
    "submission": ObjectCodec(SubmissionV2),
    "feedback": ObjectCodec(FeedbackV2),
    "business_request": ObjectCodec(BusinessRequest),
    "business_decision": ObjectCodec(BusinessDecision),
    "config": ObjectCodec(AssistantConfig),
    "test": ObjectCodec(TestResultV2),
}


def typed_refs(value):
    if isinstance(value, ObjectRef):
        yield value
    elif isinstance(value, AssistantConfig):
        yield ObjectRef(session_id=value.session_id, kind="config", object_id=value.id, version=value.version, config_version=value.config_version)
    elif isinstance(value, (FileRef, Executor, LegacyProvenance)):
        return  # Historical provenance is inert; it is not an active child reference.
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from typed_refs(getattr(value, name))
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from typed_refs(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from typed_refs(item)


def parse_object(obj, codec):
    try:
        model = codec.model.model_validate(obj.content)
    except (ValueError, TypeError):
        raise ProtocolError("object_content_invalid") from None
    if getattr(model, codec.id_field) != obj.ref.object_id or model.session_id != obj.ref.session_id:
        raise ProtocolError("object_content_identity_mismatch")
    version = getattr(model, "version", getattr(model, "revision", None))
    if isinstance(model, AssistantConfig) and model.config_version != obj.ref.config_version:
        raise ProtocolError("config_version_mismatch")
    if version != obj.ref.version:
        raise ProtocolError("object_content_version_mismatch")
    return model


def event_references(event, codec):
    allowed = set(codec.reference_fields + codec.reference_list_fields + codec.literal_fields)
    if set(event.data) - allowed:
        raise ProtocolError("unsupported_event_payload")
    refs = list(event.refs)
    for key in codec.reference_fields:
        if key in event.data and event.data[key] is not None:
            refs.append(ObjectRef.model_validate(event.data[key]))
    for key in codec.reference_list_fields:
        if key in event.data:
            if not isinstance(event.data[key], list):
                raise ProtocolError("event_reference_list_invalid")
            refs.extend(ObjectRef.model_validate(x) for x in event.data[key])
    return refs


# Only semantic fields of supported DTOs are inspected; free text is untouched.
TIME_FIELDS = {
    RevisionCycle: ("opened_at",), ProductShare: ("shared_at", "revoked_at"),
    TestResultV2: ("as_of",), SubmissionV2: ("as_of",), FeedbackV2: ("as_of",),
    ReviewRequest: ("as_of",), BusinessRequest: ("as_of",), BusinessDecision: ("as_of",),
}

def object_information_window(model, obj, snapshot):
    fork = snapshot.state
    def seq_at(storage):
        return max((b.end_seq for b in snapshot.boundaries if b.storage_revision <= storage), default=0)
    created_seq = seq_at(obj.created_storage_revision)
    window = created_seq
    for name in TIME_FIELDS.get(type(model), ()):
        point = getattr(model, name)
        if point is None:
            continue
        if any(getattr(point, k) > getattr(fork, k) for k in ("business_seq", "workspace_revision", "storage_revision")):
            raise ProtocolError("object_point_after_fork")
        if point.storage_revision > obj.created_storage_revision or point.business_seq > seq_at(point.storage_revision):
            raise ProtocolError("object_point_after_creation")
        # as_of/opened_at/shared_at define what this immutable record could cite.
        if name != "revoked_at":
            window = min(window, point.business_seq)
    return window


def validate_prefix(snapshot, object_codecs, event_codecs, external_refs=()):
    # Revalidate hash and nested content even when a caller used model_copy/update.
    snapshot = SnapshotExport.model_validate_json(snapshot.model_dump_json())
    sid, point = snapshot.session_id, snapshot.state
    if point.session_id != sid:
        raise ProtocolError("snapshot_session_mismatch")
    external = {ref_key(r) for r in external_refs}
    if any(r.session_id != sid for r in external_refs):
        raise ProtocolError("external_ref_session_mismatch")
    objects = {ref_key(o.ref): o for o in snapshot.objects}
    if len(objects) != len(snapshot.objects):
        raise ProtocolError("duplicate_object_version")
    if external & objects.keys():
        raise ProtocolError("ambiguous_external_object")
    if not snapshot.boundaries:
        raise ProtocolError("missing_action_boundary")
    seq, storage = 0, -1
    requests, transactions = set(), set()
    for boundary in snapshot.boundaries:
        if (boundary.start_seq != seq or boundary.storage_revision <= storage
                or boundary.request_id in requests or boundary.transaction_id in transactions):
            raise ProtocolError("invalid_boundary_chain")
        seq, storage = boundary.end_seq, boundary.storage_revision
        requests.add(boundary.request_id); transactions.add(boundary.transaction_id)
    if seq != point.business_seq or storage != point.storage_revision:
        raise ProtocolError("prefix_not_complete_boundary")
    if [e.seq for e in snapshot.events] != list(range(1, point.business_seq + 1)):
        raise ProtocolError("event_sequence_incomplete")
    if len({e.id for e in snapshot.events}) != len(snapshot.events):
        raise ProtocolError("duplicate_event")
    by_tx = {b.transaction_id: b for b in snapshot.boundaries}
    graph = {}
    def check_ref(ref, max_storage=None, max_seq=None):
        if ref.session_id != sid or ref_key(ref) not in objects.keys() | external:
            raise ProtocolError("dangling_or_foreign_reference")
        if max_storage is not None and ref_key(ref) in objects and objects[ref_key(ref)].created_storage_revision > max_storage:
            raise ProtocolError("reference_not_yet_created")
        if isinstance(ref, EvidenceRefV2) and ref.observed_at_seq > (point.business_seq if max_seq is None else max_seq):
            raise ProtocolError("future_evidence_reference")
    for key, obj in objects.items():
        if obj.ref.session_id != sid or obj.created_storage_revision > point.storage_revision:
            raise ProtocolError("future_or_foreign_object")
        codec = object_codecs.get(obj.ref.kind)
        if codec is None:
            raise ProtocolError("unsupported_object_kind")
        model = parse_object(obj, codec)
        information_seq = object_information_window(model, obj, snapshot)
        embedded = [ref for field in type(model).model_fields for ref in typed_refs(getattr(model, field))]
        refs = (*obj.dependencies, *embedded)
        for ref in refs:
            check_ref(ref, obj.created_storage_revision, information_seq)
        graph[key] = {ref_key(r) for r in refs if ref_key(r) in objects}
    # Reject all active reference cycles. A two-phase restore may later support
    # specific cycles only after the shared protocol defines their semantics.
    order, visiting, done = [], set(), set()
    def visit(key):
        if key in visiting:
            raise ProtocolError("object_reference_cycle")
        if key in done:
            return
        visiting.add(key)
        for dep in sorted(graph[key]):
            visit(dep)
        visiting.remove(key); done.add(key); order.append(key)
    for key in sorted(graph):
        visit(key)
    for event in snapshot.events:
        boundary = by_tx.get(event.transaction_id)
        if event.session_id != sid or boundary is None or not boundary.start_seq < event.seq <= boundary.end_seq:
            raise ProtocolError("event_boundary_mismatch")
        codec = event_codecs.get(event.type)
        if codec is None:
            raise ProtocolError("unsupported_event_type")
        for ref in event_references(event, codec):
            check_ref(ref, boundary.storage_revision, event.seq)
    cycles = [o for o in snapshot.objects if o.ref.kind == "cycle" and o.ref.object_id == point.cycle_id]
    if not cycles:
        raise ProtocolError("missing_current_cycle")
    return snapshot, tuple(order)


@dataclass(frozen=True)
class MappingPlan:
    parent_session: str
    child_session: str
    ids: dict[str, str]
    refs: dict[str, ObjectRef]

    def object_id(self, kind, original):
        try:
            return self.ids[object_key(kind, original)]
        except KeyError:
            raise ProtocolError("unmapped_object_id") from None

    def reference(self, ref):
        target = self.refs.get(ref_key(ref))
        if target is None:
            raise ProtocolError("unmapped_reference")
        data = ref.model_dump(mode="json")
        data.update(session_id=target.session_id, object_id=target.object_id)
        return type(ref).model_validate(data)


def make_plan(snapshot, child_session, branch_id, external_refs=()):
    if child_session == snapshot.session_id:
        raise ProtocolError("child_cannot_equal_parent")
    ids = {}
    def add(kind, original):
        key = canonical([kind, original])
        ids[key] = digest([branch_id, child_session, kind, original])
    for obj in snapshot.objects:
        key = object_key(obj.ref.kind, obj.ref.object_id)
        ids[key] = digest([branch_id, child_session, obj.ref.kind, obj.ref.object_id])
    for event in snapshot.events:
        add("event", event.id)
    for b in snapshot.boundaries:
        add("transaction", b.transaction_id); add("request", b.request_id)
    add("snapshot", snapshot.id)
    refs = {}
    for ref in [*(o.ref for o in snapshot.objects), *external_refs]:
        oid = ids.get(object_key(ref.kind, ref.object_id), ref.object_id)
        # Immutable external scenario references retain object IDs, never parent session.
        refs[ref_key(ref)] = ref.model_copy(update={"session_id": child_session, "object_id": oid})
    return MappingPlan(snapshot.session_id, child_session, ids, refs)


def rewrite_typed(value, plan, root=False):
    if isinstance(value, ObjectRef):
        return plan.reference(value)
    if isinstance(value, (FileRef, Executor, LegacyProvenance)):
        return value.model_copy(deep=True)
    if isinstance(value, AssistantConfig) and not root:
        return value.model_copy(update={"id": plan.object_id("config", value.id), "session_id": plan.child_session})
    if isinstance(value, BaseModel):
        data = {n: rewrite_typed(getattr(value, n), plan) for n in type(value).model_fields}
        if isinstance(value, WorkProductVersion):
            payload = data["structured_payload"]
            data["content_hash"] = digest({"content": data["content"],
                "structured_payload": payload.model_dump(mode="json") if payload else None})
        if isinstance(value, EvidencePackageV2):
            # This type is not currently stored by default; requires a dedicated codec
            # if it contains untyped rule-context references.
            raise ProtocolError("evidence_package_codec_required")
        return type(value).model_validate(data)
    if isinstance(value, tuple):
        return tuple(rewrite_typed(v, plan) for v in value)
    if isinstance(value, list):
        return [rewrite_typed(v, plan) for v in value]
    if isinstance(value, dict):
        return {k: rewrite_typed(v, plan) for k, v in value.items()}
    return deepcopy(value)


def remap_snapshot(snapshot, plan, object_codecs, event_codecs, order):
    objects = {ref_key(o.ref): o for o in snapshot.objects}
    remapped = []
    for key in order:
        obj = objects[key]; codec = object_codecs[obj.ref.kind]
        model = parse_object(obj, codec)
        # Primary IDs and session identity must change together before model validation.
        data = {name: getattr(model, name) for name in type(model).model_fields}
        data[codec.id_field] = plan.object_id(obj.ref.kind, obj.ref.object_id)
        data["session_id"] = plan.child_session
        # base_state_ref/source_return_id are provenance strings in the W01 r3 contract.
        # Only typed ObjectRef fields are active references; preserve opaque anchors.
        # model_construct avoids validating cross-session refs before they are rewritten;
        # rewrite_typed performs full final validation.
        mapped_model = rewrite_typed(type(model).model_construct(**data), plan, root=True)
        remapped.append(type(obj).model_validate(obj.model_dump(mode="json") | {
            "ref": plan.reference(obj.ref).model_dump(mode="json"),
            "content": mapped_model.model_dump(mode="json"),
            "dependencies": [plan.reference(r).model_dump(mode="json") for r in obj.dependencies]}))
    events = []
    for event in snapshot.events:
        codec = event_codecs[event.type]
        data = deepcopy(event.data)
        for field in codec.reference_fields:
            if data.get(field) is not None:
                data[field] = plan.reference(ObjectRef.model_validate(data[field])).model_dump(mode="json")
        for field in codec.reference_list_fields:
            if field in data:
                data[field] = [plan.reference(ObjectRef.model_validate(r)).model_dump(mode="json") for r in data[field]]
        events.append(event.model_copy(update={
            "id": plan.ids[canonical(["event", event.id])], "session_id": plan.child_session,
            "transaction_id": plan.ids[canonical(["transaction", event.transaction_id])],
            "refs": tuple(plan.reference(r) for r in event.refs), "data": data}))
    boundaries = tuple(b.model_copy(update={
        "transaction_id": plan.ids[canonical(["transaction", b.transaction_id])],
        "request_id": plan.ids[canonical(["request", b.request_id])]}) for b in snapshot.boundaries)
    data = {name: getattr(snapshot, name) for name in type(snapshot).model_fields}
    data.update(id=plan.ids[canonical(["snapshot", snapshot.id])], session_id=plan.child_session,
        state=snapshot.state.model_copy(update={"session_id": plan.child_session,
            "cycle_id": plan.object_id("cycle", snapshot.state.cycle_id)}),
        objects=tuple(remapped), events=tuple(events), boundaries=boundaries)
    if hasattr(snapshot, "external_references"):
        data["external_references"] = tuple(rewrite_typed(x, plan) for x in snapshot.external_references)
    provisional = SnapshotExport.model_construct(**data)
    data["snapshot_hash"] = digest(provisional.model_dump(mode="json", exclude={"snapshot_hash"}))
    return SnapshotExport.model_validate(data)
