"""W14 integration of fixed W03 plans. Gateway and V2Store remain authoritative."""

from dataclasses import replace
from datetime import datetime, timezone
from career_lab.contracts.v2 import *
from career_lab.api.modules import Operation, V2Response
from career_lab.storage.v2_store import Mutation, ObjectWrite, references
from career_lab.workspace.extension import snapshot_from_view
from career_lab.workspace.imports import import_workspace
from career_lab.workspace.service import WorkspaceService


def _snapshot(view, auth, roles):
    if auth.actor_id != "learner":
        raise ProtocolError("workspace_actor_forbidden", status=403)
    if view.reference_allowed is None:
        raise ProtocolError("reference_view_required", status=503)
    return replace(
        snapshot_from_view(view, auth, roles, {}), reference_allowed=view.reference_allowed
    )


def preview_import(view, command, auth, *, roles, clock):
    body = WorkspaceImport.model_validate(command.payload)
    if body.mode != "preview":
        raise ProtocolError("import_mode_mismatch")
    plan = import_workspace(_snapshot(view, auth, roles), auth, command, clock())
    if plan.writes:
        raise ProtocolError("preview_has_writes", status=503)
    return ImportResult.model_validate(plan.result)


def apply_import(view, command, auth, *, roles, clock):
    body = WorkspaceImport.model_validate(command.payload)
    if body.mode != "apply":
        raise ProtocolError("import_mode_mismatch")
    now = clock()
    plan = import_workspace(_snapshot(view, auth, roles), auth, command, now)
    heads = {}
    for obj in view.objects:
        key = (obj.ref.kind, obj.ref.object_id)
        heads[key] = max(heads.get(key, 0), obj.ref.version)
    task_sources = tuple(
        ImportedTaskSource(
            task=obj.ref.model_copy(update={"kind": "task"}),
            source=LegacyProvenance.model_validate(obj.content),
        )
        for obj in plan.writes
        if obj.ref.kind == "legacy_task"
    )
    writes = []
    for obj in plan.writes:
        if obj.ref.kind == "legacy_task":
            continue
        content = obj.content
        if obj.ref.kind == "workspace_import":
            content = WorkspaceImportReceipt(
                id=obj.ref.object_id,
                session_id=auth.session_id,
                package_id=body.package_id,
                package_hash=body.package_hash,
                source_schema=body.source_schema,
                source_session_id=body.source_session_id,
                fingerprint=obj.content["fingerprint"],
                result=ImportResult.model_validate(obj.content["result"]),
                task_sources=task_sources,
                executor=auth.executor,
                created_at=now,
            ).model_dump(mode="json")
        key = (obj.ref.kind, obj.ref.object_id)
        head = heads.get(key, 0)
        if obj.ref.version != head + 1:
            raise ProtocolError("object_version_conflict", status=409)
        writes.append(
            ObjectWrite(
                ref=obj.ref,
                expected_head=head,
                content=content,
                visible_to=("learner",),
                dependencies=references(content),
            )
        )
        heads[key] = obj.ref.version
    return Mutation(writes=tuple(writes), result=plan.result)


class _ReadView:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def read(self, auth, query):
        return query(self.snapshot)


def install_workspace_recovery(registry, *, roles, clock=None):
    """Call after W03.install_workspace_operations; no route replacement or DB layer."""
    clock = clock or (lambda: datetime.now(timezone.utc))
    registry.register(
        Operation(
            "workspace_imports",
            "act",
            WorkspaceImport,
            lambda v, c, a: apply_import(v, c, a, roles=roles, clock=clock),
            response_model=ImportResult,
            preview_handler=lambda v, c, a: preview_import(v, c, a, roles=roles, clock=clock),
        )
    )

    def shares(view, page, auth):
        if not page.product_id:
            raise ProtocolError("product_required")
        service = WorkspaceService(_ReadView(_snapshot(view, auth, roles)))
        result = service.list(auth, "share", page, product_id=page.product_id)
        result["sharing_complete"] = auth.allowed_objects is None
        return V2Response(result=WorkspaceSharePage.model_validate(result).model_dump(mode="json"))

    registry.register(
        Operation(
            "work_products.shares.list",
            "read",
            ResourcePage,
            shares,
            mutates=False,
            response_model=V2Response,
        )
    )

    def imports(view, page, auth):
        _snapshot(view, auth, roles)
        rows = [
            r
            for r in view.objects
            if r.ref.kind == "workspace_import"
            and (page.import_id is None or r.ref.object_id == page.import_id)
        ]
        if page.import_id is not None and not rows:
            raise ProtocolError("object_not_found", status=404)
        rows.sort(key=lambda r: (r.created_storage_revision, r.ref.object_id))
        end = page.cursor + page.limit
        return V2Response(
            result={
                "items": [r.content for r in rows[page.cursor : end]],
                "next_cursor": end if end < len(rows) else None,
                "as_of": VersionPoint(
                    **view.state.model_dump(
                        include={"business_seq", "workspace_revision", "storage_revision"}
                    )
                ).model_dump(mode="json"),
            }
        )

    registry.register(
        Operation(
            "workspace_imports.list",
            "read",
            ResourcePage,
            imports,
            mutates=False,
            response_model=V2Response,
        )
    )
    registry.register(
        Operation(
            "workspace_imports.read",
            "read",
            ResourcePage,
            imports,
            mutates=False,
            response_model=V2Response,
        )
    )
    return registry
