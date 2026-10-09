"""Pure workspace operations for the frozen Gateway; no database or private clock.

The application assembles public app/CLI entry points. Import persistence registration is
installed only when its formal receipt contract is available.
"""

from datetime import datetime, timezone

from career_lab.api.modules import Operation, V2Response
from career_lab.contracts.v2 import (
    ObjectRef,
    ResourcePage,
    TaskCreate,
    TaskPatch,
    TaskBatch,
    ProductCreate,
    ProductEdit,
    ProductAdopt,
    ShareCreate,
    ShareUpdate,
    ProtocolError,
    canonical,
)
from career_lab.storage.v2_store import ObjectWrite, Mutation, references
from .domain import handle, product_dependencies
from .ports import Snapshot
from .service import WorkspaceService


WRITE_MODELS = {
    "work_items.create": TaskCreate,
    "work_items.update": TaskPatch,
    "work_items.batch": TaskBatch,
    "work_products.create": ProductCreate,
    "work_products.versions.create": ProductEdit,
    "work_products.adopt": ProductAdopt,
    "work_products.shares.create": ShareCreate,
    "work_products.shares.change": ShareUpdate,
}


def snapshot_from_view(view, auth, roles, resolvers):
    objects = list(view.objects)
    if view.current_cycle and not any(r.ref == view.current_cycle.ref for r in objects):
        objects.append(view.current_cycle)
    permitted_ids = {r.ref.object_id for r in view.objects}

    def permitted(oid):
        return auth.allowed_objects is None or oid in permitted_ids or oid in auth.allowed_objects

    def can_reference(reference):
        if reference.session_id != auth.session_id:
            return False
        predicate = view.reference_allowed
        if predicate is None:
            raise ProtocolError("reference_view_required", status=503)
        # The public predicate supplies contextual resolver authority and expires
        # with this transaction. Never call standalone resolvers or retain it.
        return predicate(reference)

    return Snapshot(
        view.state,
        tuple(objects),
        can_reference,
        tuple(roles),
        permitted,
        auth.allowed_objects is None,
        view.removal_cascade,
    )


def workspace_plan(view, command, auth, *, roles, resolvers, clock=None):
    if command.operation not in WRITE_MODELS:
        raise ProtocolError("module_unavailable", status=503)
    payload = (
        WRITE_MODELS[command.operation]
        .model_validate(command.payload)
        .model_dump(mode="json", exclude_none=command.operation == "work_items.update")
    )
    command = command.model_copy(update={"payload": payload})
    snapshot = snapshot_from_view(view, auth, roles, resolvers)
    plan = handle(snapshot, auth, command, (clock or (lambda: datetime.now(timezone.utc)))())
    heads = {}
    for record in view.objects:
        key = (record.ref.kind, record.ref.object_id)
        heads[key] = max(heads.get(key, 0), record.ref.version)
    writes = []
    for record in plan.writes:
        key = (record.ref.kind, record.ref.object_id)
        head = heads.get(key, 0)
        if record.ref.version != head + 1:
            raise ProtocolError("object_version_conflict", status=409)
        visible = (
            ("learner", record.content["recipient_role"])
            if record.ref.kind == "share"
            else ("learner",)
        )
        writes.append(
            ObjectWrite(
                ref=record.ref,
                expected_head=head,
                content=record.content,
                dependencies=references(record.content),
                visible_to=visible,
            )
        )
        heads[key] = record.ref.version
    return Mutation(writes=tuple(writes), result=plan.result)


class _ReadView:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def read(self, auth, query):
        return query(self.snapshot)


def install_workspace_operations(registry, *, roles, clock=None):
    """Register only verified pure slots; callers keep create_app/Gateway intact."""
    resolvers = dict(registry.reference_resolvers)
    for name, model in WRITE_MODELS.items():

        def handler(view, command, auth):
            plan = workspace_plan(
                view, command, auth, roles=roles, resolvers=resolvers, clock=clock
            )
            from .preview import after_saved_version

            return after_saved_version(registry, view, command, auth, plan)

        registry.register(Operation(name, "act", model, handler))
    for name, kind in [
        ("work_items.list", "task"),
        ("work_products.list", "product"),
        ("work_products.versions.list", "versions"),
    ]:

        def make_reader(resource_kind):
            def reader(view, payload, auth):
                snapshot = snapshot_from_view(view, auth, roles, resolvers)
                service = WorkspaceService(_ReadView(snapshot))
                return V2Response(
                    result=service.list(auth, resource_kind, payload, product_id=payload.product_id)
                )

            return reader

        registry.register(
            Operation(
                name,
                "read",
                ResourcePage,
                make_reader(kind),
                mutates=False,
                response_model=V2Response,
            )
        )
    return registry
