"""Pure mutations: writing a draft never changes resources or a milestone."""

from datetime import datetime
from dataclasses import replace

from career_lab.contracts.v2.core import AuthContext, Command, ObjectRef, ProtocolError, digest
from career_lab.contracts.v2.requests import (
    TaskCreate,
    TaskPatch,
    TaskBatch,
    ProductCreate,
    ProductEdit,
    ProductAdopt,
    ShareCreate,
    ShareUpdate,
)
from career_lab.contracts.v2.research import StoredObject
from career_lab.contracts.v2.workspace import (
    WorkspaceTask,
    WorkProductVersion,
    ProductShare,
    Adoption,
)
from .ports import Snapshot, Mutation, object_scope

OPERATIONS = (
    "work_items.create",
    "work_items.update",
    "work_items.batch",
    "work_products.create",
    "work_products.versions.create",
    "work_products.adopt",
    "work_products.shares.create",
    "work_products.shares.change",
    "workspace_imports",
)


def identity(snapshot: Snapshot, command: Command, kind: str) -> str:
    return digest([snapshot.state.session_id, command.request_id, command.operation, kind])


def reference(snapshot: Snapshot, kind: str, oid: str, version: int) -> ObjectRef:
    return ObjectRef(
        session_id=snapshot.state.session_id, kind=kind, object_id=oid, version=version
    )


def stored(
    snapshot: Snapshot,
    kind: str,
    oid: str,
    version: int,
    model,
    dependencies: tuple[ObjectRef, ...] = (),
) -> StoredObject:
    return StoredObject(
        ref=reference(snapshot, kind, oid, version),
        content=model.model_dump(mode="json") if hasattr(model, "model_dump") else model,
        visible_to=("learner",),
        dependencies=dependencies,
        created_storage_revision=snapshot.next_point.storage_revision,
    )


def validate_reference(
    snapshot: Snapshot, auth: AuthContext, ref: ObjectRef, expected_kind: str | None = None
) -> None:
    if ref.session_id != auth.session_id or (expected_kind and ref.kind != expected_kind):
        raise ProtocolError("not_found", status=404)
    object_scope(auth, ref.object_id, snapshot)
    if ref.kind in {"product", "task", "share"}:
        snapshot.get(ref.kind, ref.object_id, ref.version)
        if auth.actor_id != "learner" and ref.kind != "product":
            raise ProtocolError("not_found", status=404)
        if ref.kind == "product":
            visible_product(snapshot, auth, ref.object_id, ref.version)
    elif not snapshot.reference_allowed(ref):
        raise ProtocolError("not_found", status=404)


def visible_product(snapshot: Snapshot, auth: AuthContext, oid: str, version: int | None = None):
    """Learner lookup plus historical fixture role filtering.

    Formal role source reads use V2Store.read_shared_product; its current-share
    authorization must not be replaced with this fixture-side branch.
    """
    object_scope(auth, oid, snapshot)
    if auth.actor_id == "learner":
        return snapshot.get("product", oid, version)
    # Authorization is current even when reading a historical version. Never let
    # a historical as_of or an old share revision undo a revocation/removal.
    head = snapshot.get("product", oid)
    if head.content["removed_at"] is not None:
        raise ProtocolError("not_found", status=404)
    shares = [ProductShare.model_validate(o.content) for o in snapshot.heads("share")]
    allowed = {
        s.product.version
        for s in shares
        if s.product.object_id == oid and s.recipient_role == auth.actor_id and s.revoked_at is None
    }
    if version is None:
        version = max(allowed) if allowed else None
    if version not in allowed:
        raise ProtocolError("not_found", status=404)
    product = snapshot.get("product", oid, version)
    for dependency in product.dependencies:
        if dependency.kind == "product":
            visible_product(snapshot, auth, dependency.object_id, dependency.version)
        elif not snapshot.reference_allowed(dependency):
            # A share does not grant access to private source quotes or tests.
            # W04 may later offer an explicitly filtered excerpt instead.
            raise ProtocolError("not_found", status=404)
    return product


def product_dependencies(product):
    dependencies = list(product.evidence_refs)
    payload = product.structured_payload
    rows = getattr(payload, "cases", ()) or getattr(payload, "blocks", ())
    for row in rows:
        dependencies.extend(r for r in getattr(row, "refs", ()) if r not in dependencies)
        dependencies.extend(r for r in getattr(row, "test_refs", ()) if r not in dependencies)
        for field in ("run", "test_ref", "source_ref"):
            value = getattr(row, field, None)
            if value is not None and value not in dependencies:
                dependencies.append(value)
    return tuple(dependencies)


def _text(value: str, limit: int, *, nonempty: bool = False):
    if len(value) > limit or (nonempty and not value.strip()):
        raise ProtocolError("text_limit", "Text is empty or exceeds its limit")


def _new_scope(auth: AuthContext, parent: ObjectRef | None = None):
    if auth.allowed_objects is not None:
        # Only the formal explicit create_under_tasks grant permits creation.
        if (
            parent is None
            or parent.kind != "task"
            or parent.object_id not in auth.create_under_tasks
        ):
            raise ProtocolError("object_scope_denied", status=403)
        object_scope(auth, parent.object_id)


def _task_refs(snapshot, auth, parent, relations, own_id=None, previous=None):
    old_refs = (
        (([previous.parent] if previous.parent else []) + list(previous.relations))
        if previous
        else []
    )
    for ref in ([parent] if parent else []) + list(relations):
        if ref in old_refs:
            continue
        validate_reference(snapshot, auth, ref, "task")
        if snapshot.get("task", ref.object_id).content["status"] == "removed":
            raise ProtocolError("task_removed")
    if previous and parent == previous.parent:
        return
    seen = {own_id} if own_id else set()
    while parent:
        if parent.object_id in seen:
            raise ProtocolError("task_cycle")
        seen.add(parent.object_id)
        parent = WorkspaceTask.model_validate(snapshot.get("task", parent.object_id).content).parent


def _product_refs(snapshot, auth, payload, previous=None):
    if payload.task and (previous is None or payload.task != previous.task):
        validate_reference(snapshot, auth, payload.task, "task")
        if snapshot.get("task", payload.task.object_id).content["status"] == "removed":
            raise ProtocolError("task_removed")
    for ref in payload.evidence_refs:
        if previous and ref in previous.evidence_refs:
            continue
        if (
            ref.observed_at_seq > snapshot.state.business_seq
            or ref.valid_from_seq > snapshot.state.business_seq
        ):
            raise ProtocolError("future_reference")
        validate_reference(snapshot, auth, ref)
    structured = payload.structured_payload
    if structured:
        if structured.type != payload.kind:
            raise ProtocolError("payload_kind_mismatch")
        rows = (
            structured.cases
            if structured.type == "test_plan"
            else structured.blocks
            if structured.type == "investigation"
            else ()
        )
        if len({r.id for r in rows}) != len(rows):
            raise ProtocolError("duplicate_child_id")
        if len(rows) > (20 if structured.type == "test_plan" else 8):
            raise ProtocolError("too_many_children")
        for row in rows:
            old_dependencies = product_dependencies(previous) if previous else ()
            for ref in (*getattr(row, "refs", ()), *getattr(row, "test_refs", ())):
                if ref not in old_dependencies:
                    validate_reference(snapshot, auth, ref)
            for name in ("run", "test_ref", "source_ref"):
                ref = getattr(row, name, None)
                if ref and ref not in old_dependencies:
                    validate_reference(snapshot, auth, ref)
    _text(payload.title, 160)
    _text(payload.purpose, 200)
    _text(payload.content, 50000)


def _product(snapshot, auth, payload, oid, version, now, previous=None):
    _product_refs(snapshot, auth, payload, previous)
    if payload.legacy is not None and previous is None:
        raise ProtocolError(
            "use_import_preview", "Browser provenance must pass import preview/apply"
        )
    if previous and payload.legacy != previous.legacy:
        raise ProtocolError("immutable_provenance")
    if previous and previous.kind != payload.kind:
        raise ProtocolError("kind_immutable")
    if (
        previous
        and payload.source_return_id is not None
        and payload.source_return_id != previous.source_return_id
    ):
        raise ProtocolError("immutable_provenance")
    if auth.executor.kind != "human" and payload.kind == "investigation":
        before = previous.structured_payload if previous else None
        after = payload.structured_payload
        old_judgment = (
            (before.review_note, before.review_direction, before.review_focus)
            if before
            else ("", "unknown", "uncertain")
        )
        new_judgment = (
            (after.review_note, after.review_direction, after.review_focus)
            if after
            else ("", "unknown", "uncertain")
        )
        if old_judgment != new_judgment:
            raise ProtocolError("human_judgment_only", status=403)
    if payload.structured_payload and payload.kind in {"test_plan", "investigation"}:
        field = "cases" if payload.kind == "test_plan" else "blocks"
        previous_payload = previous.structured_payload if previous else None
        old_rows = {r.id: r for r in getattr(previous_payload, field, ())}
        rows = []
        for index, row in enumerate(getattr(payload.structured_payload, field)):
            old = old_rows.get(row.id)
            content = row.model_dump(mode="json", exclude={"id", "revision"})
            changed = old is None or content != old.model_dump(
                mode="json", exclude={"id", "revision"}
            )
            rows.append(
                row.model_copy(
                    update={
                        "id": old.id if old else digest([oid, version, field, index, row.id]),
                        "revision": old.revision + int(changed) if old else 1,
                    }
                )
            )
        payload = payload.model_copy(
            update={
                "structured_payload": payload.structured_payload.model_copy(
                    update={field: tuple(rows)}
                )
            }
        )
    structure = (
        payload.structured_payload.model_dump(mode="json") if payload.structured_payload else None
    )
    return WorkProductVersion(
        product_id=oid,
        session_id=auth.session_id,
        version=version,
        cycle=reference(snapshot, "cycle", snapshot.state.cycle_id, 1),
        task=payload.task,
        kind=payload.kind,
        purpose=payload.purpose,
        title=payload.title,
        content=payload.content,
        structured_payload=payload.structured_payload,
        evidence_refs=payload.evidence_refs,
        author=previous.author if previous else auth.executor,
        executor=auth.executor,
        source_return_id=previous.source_return_id if previous else payload.source_return_id,
        adoption=Adoption(),
        content_hash=digest({"content": payload.content, "structured_payload": structure}),
        created_at=now,
        legacy=previous.legacy if previous else None,
    )


def handle(snapshot: Snapshot, auth: AuthContext, command: Command, now: datetime) -> Mutation:
    op, data = command.operation, command.payload
    if op == "workspace_imports":
        from .imports import import_workspace

        return import_workspace(snapshot, auth, command, now)
    if op == "work_items.batch":
        batch = TaskBatch.model_validate(data)
        if not batch.creates and not batch.updates:
            raise ProtocolError("empty_task_batch")
        if len(batch.creates) + len(batch.updates) > 100:
            raise ProtocolError("task_batch_limit")
        if len({p.item_id for p in batch.updates}) != len(batch.updates):
            raise ProtocolError("duplicate_task_update")
        writes = []
        objects = []
        view = snapshot
        for name, items in [
            ("work_items.create", batch.creates),
            ("work_items.update", batch.updates),
        ]:
            for index, payload in enumerate(items):
                nested = Command(
                    schema_version=2,
                    request_id=digest([command.request_id, name, index]),
                    expected_version=command.expected_version,
                    expected_workspace_revision=command.expected_workspace_revision,
                    operation=name,
                    payload=payload.model_dump(
                        mode="json", exclude_none=name == "work_items.update"
                    ),
                )
                plan = handle(view, auth, nested, now)
                writes.extend(plan.writes)
                objects.append(plan.result["object"])
                view = replace(view, objects=(*view.objects, *plan.writes))
        return Mutation(
            tuple(writes),
            {
                "objects": objects,
                "refs": [w.ref.model_dump(mode="json") for w in writes],
                "as_of": snapshot.next_point.model_dump(mode="json"),
            },
            op,
        )
    if op == "work_items.create":
        p = TaskCreate.model_validate(data)
        _new_scope(auth)
        _text(p.title, 120, nonempty=True)
        _text(p.goal, 5000)
        _task_refs(snapshot, auth, p.parent, p.relations)
        oid = identity(snapshot, command, "task")
        task = WorkspaceTask(
            id=oid,
            session_id=auth.session_id,
            revision=1,
            created_at=now,
            updated_at=now,
            **p.model_dump(exclude={"schema_version"}),
        )
        writes = (stored(snapshot, "task", oid, 1, task),)
    elif op == "work_items.update":
        p = TaskPatch.model_validate(data)
        object_scope(auth, p.item_id, snapshot)
        old = WorkspaceTask.model_validate(snapshot.get("task", p.item_id).content)
        if old.revision != p.expected_revision:
            raise ProtocolError("object_version_conflict", status=409)
        patch = p.model_dump(
            exclude_unset=True,
            exclude={"schema_version", "item_id", "expected_revision", "clear_parent"},
        )
        if any(value is None for key, value in patch.items() if key != "parent"):
            raise ProtocolError("null_field")
        if p.clear_parent:
            if p.parent:
                raise ProtocolError("ambiguous_parent")
            patch["parent"] = None
        task = WorkspaceTask.model_validate(
            {
                **old.model_dump(mode="json"),
                **patch,
                "revision": old.revision + 1,
                "updated_at": now,
            }
        )
        _text(task.title, 120, nonempty=True)
        _text(task.goal, 5000)
        _task_refs(snapshot, auth, task.parent, task.relations, task.id, old)
        writes = (stored(snapshot, "task", task.id, task.revision, task),)
    elif op == "work_products.create":
        p = ProductCreate.model_validate(data)
        _new_scope(auth, p.task)
        product = _product(snapshot, auth, p, identity(snapshot, command, "product"), 1, now)
        writes = (
            stored(
                snapshot, "product", product.product_id, 1, product, product_dependencies(product)
            ),
        )
    elif op == "work_products.adopt":
        p = ProductAdopt.model_validate(data)
        object_scope(auth, p.product_id, snapshot)
        old = WorkProductVersion.model_validate(snapshot.get("product", p.product_id).content)
        if old.version != p.expected_head or p.product_version != old.version:
            raise ProtocolError("object_version_conflict", status=409)
        if old.removed_at:
            raise ProtocolError("product_removed")
        if auth.executor.kind != "human":
            raise ProtocolError("human_adoption_only", status=403)
        adoption = Adoption(
            status=p.status,
            adopter=auth.executor if p.status == "adopted" else None,
            adopted_at=now if p.status == "adopted" else None,
        )
        product = old.model_copy(
            update={
                "version": old.version + 1,
                "executor": auth.executor,
                "created_at": now,
                "adoption": adoption,
            }
        )
        writes = (
            stored(
                snapshot,
                "product",
                product.product_id,
                product.version,
                product,
                product_dependencies(product),
            ),
        )
    elif op == "work_products.versions.create":
        p = ProductEdit.model_validate(data)
        object_scope(auth, p.product_id, snapshot)
        old = WorkProductVersion.model_validate(snapshot.get("product", p.product_id).content)
        if old.version != p.expected_head:
            raise ProtocolError("object_version_conflict", status=409)
        product = _product(snapshot, auth, p, old.product_id, old.version + 1, now, old)
        lifecycle_only = all(
            getattr(product, key) == getattr(old, key)
            for key in (
                "title",
                "purpose",
                "content",
                "structured_payload",
                "evidence_refs",
                "task",
            )
        )
        if old.removed_at and not lifecycle_only:
            raise ProtocolError("product_removed", "Restore this work before editing")
        if lifecycle_only:
            product = product.model_copy(update={"adoption": old.adoption})
        product = product.model_copy(
            update={"removed_at": (old.removed_at or now) if p.removed else None}
        )
        writes = (
            stored(
                snapshot,
                "product",
                product.product_id,
                product.version,
                product,
                product_dependencies(product),
            ),
        )
        if p.removed and snapshot.removal_cascade != "current_product_only":
            # Without the trusted transaction cascade, a filtered view cannot
            # prove every share was revoked. Legacy fixture behavior stays local.
            # A filtered view cannot prove that every active share was revoked.
            # shares_complete is never upgraded by a removal authorization.
            if not snapshot.shares_complete:
                raise ProtocolError("share_scope_incomplete", status=403)
            for record in snapshot.heads("share"):
                share = ProductShare.model_validate(record.content)
                if share.product.object_id != product.product_id or share.revoked_at is not None:
                    continue
                revoked = share.model_copy(
                    update={"version": share.version + 1, "revoked_at": snapshot.next_point}
                )
                writes += (
                    stored(snapshot, "share", share.id, revoked.version, revoked, (share.product,)),
                )
    elif op == "work_products.shares.create":
        p = ShareCreate.model_validate(data)
        object_scope(auth, p.product_id, snapshot)
        if p.recipient_role not in snapshot.roles:
            raise ProtocolError("unknown_role")
        head = snapshot.get("product", p.product_id)
        if head.content["removed_at"]:
            raise ProtocolError("product_removed")
        product = snapshot.get("product", p.product_id, p.product_version)
        if product.content["removed_at"]:
            raise ProtocolError("product_removed")
        _text(p.question, 4000)
        _text(p.purpose, 200)
        share = ProductShare(
            id=identity(snapshot, command, "share"),
            session_id=auth.session_id,
            version=1,
            product=product.ref,
            recipient_role=p.recipient_role,
            question=p.question,
            purpose=p.purpose,
            shared_at=snapshot.next_point,
        )
        writes = (stored(snapshot, "share", share.id, 1, share, (product.ref,)),)
    elif op == "work_products.shares.change":
        p = ShareUpdate.model_validate(data)
        object_scope(auth, p.product_id, snapshot)
        old = ProductShare.model_validate(snapshot.get("share", p.share_id).content)
        if old.product.object_id != p.product_id:
            raise ProtocolError("not_found", status=404)
        if old.version != p.expected_revision:
            raise ProtocolError("object_version_conflict", status=409)
        if p.operation == "restore" and snapshot.get("product", p.product_id).content["removed_at"]:
            raise ProtocolError("product_removed")
        share = old.model_copy(
            update={
                "version": old.version + 1,
                "revoked_at": snapshot.next_point if p.operation == "revoke" else None,
            }
        )
        writes = (stored(snapshot, "share", share.id, share.version, share, (share.product,)),)
    else:
        raise ProtocolError("capability_not_installed", status=503)
    return Mutation(
        writes,
        {
            "object": writes[0].content,
            "ref": writes[0].ref.model_dump(mode="json"),
            "as_of": snapshot.next_point.model_dump(mode="json"),
        },
        op,
    )
