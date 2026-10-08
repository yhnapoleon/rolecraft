"""Pure object construction from the transaction's fixed, authorized context."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, JsonValue, ValidationError

from career_lab.contracts.v2 import (
    AuthContext,
    FeedbackReadBoundary,
    FeedbackV2,
    ObjectRef,
    ProtocolError,
    SessionBindings,
    StoredObject,
    WorldStateV2,
    canonical,
    digest,
)

from .reference_graph import references, validate_reference_times

if TYPE_CHECKING:
    from .v2_store import FeedbackReadTrace, ObjectWrite

ROLE_REPLY_PRIVATE_FIELDS = frozenset(
    {
        "prompt_messages",
        "prompt_hash",
        "context_hash",
        "history_revision",
        "source_versions",
        "omitted_sources",
        "attempts",
        "actual_disclosures",
        "received_shares",
        "internal_disclosures",
        "context",
    }
)


def role_reply_has_private_fields(content: object) -> bool:
    from career_lab.storage.role_memory import RoleReply

    if not isinstance(content, dict) or ROLE_REPLY_PRIVATE_FIELDS.intersection(content):
        return True
    try:
        # JSON round-trip prevents a preconstructed nested model from avoiding
        # recursive validation. Never return the private validation input.
        RoleReply.model_validate_json(canonical(content))
    except (ValidationError, TypeError, ValueError):
        return True
    return False


@dataclass(frozen=True)
class ObjectPlanContext:
    auth: AuthContext
    state: WorldStateV2
    bindings: SessionBindings
    existing: tuple[StoredObject, ...]
    current_cycle: StoredObject | None
    storage_revision: int
    structural_cycle: bool
    asynchronous: bool
    private_role: bool
    feedback_response: bool


def _trace_boundaries(
    write: ObjectWrite,
    content: dict[str, JsonValue],
    auth: AuthContext,
    traces: Sequence[FeedbackReadTrace],
) -> tuple[ObjectRef, ...]:
    from career_lab.contracts.v2.projection import feedback_segment

    if write.ref.kind not in {"feedback", "feedback_response"}:
        return ()
    if content.get("read_boundaries") is not None:
        raise ProtocolError("feedback_boundary_requires_server_trace", status=403)
    selected = [trace for trace in traces if trace.record == write.ref]
    if not selected:
        return ()
    if len({trace.path for trace in selected}) != len(selected):
        raise ProtocolError("feedback_trace_invalid", status=403)
    boundaries = []
    for trace in selected:
        if not trace.dependencies or any(
            dep.session_id != auth.session_id for dep in trace.dependencies
        ):
            raise ProtocolError("feedback_trace_invalid", status=403)
        value = feedback_segment(content, trace.path)
        deps = tuple(
            {canonical(dep): dep for dep in (*trace.dependencies, *references(value))}.values()
        )
        boundaries.append(
            FeedbackReadBoundary(path=trace.path, content_hash=digest(value), dependencies=deps)
        )
    content["read_boundaries"] = [boundary.model_dump(mode="json") for boundary in boundaries]
    return tuple(
        {canonical(dep): dep for boundary in boundaries for dep in boundary.dependencies}.values()
    )


def _cycle_channels(
    write: ObjectWrite, content: dict[str, JsonValue], context: ObjectPlanContext
) -> None:
    kind, existing = write.ref.kind, context.existing
    if (
        kind not in {"cycle", "scenario_state", "job_context", "role_context"}
        and context.auth.actor_id not in write.visible_to
    ):
        raise ProtocolError("private_object_channel_required", status=403)
    if context.asynchronous:
        if kind == "cycle":
            raise ProtocolError("async_cycle_write_forbidden", status=403)
        cycle = content.get("cycle")
        if kind == "product" or (isinstance(cycle, dict) and cycle.get("kind") == "cycle"):
            target = ObjectRef.model_validate(cycle)
            current = context.current_cycle
            if current is None or target != current.ref or current.content["status"] != "open":
                raise ProtocolError("job_output_cycle_closed", status=409)
    if context.structural_cycle and existing:
        original = max(existing, key=lambda row: row.ref.version).content
        if (
            any(
                content[key] != original[key]
                for key in original
                if key not in {"version", "status"}
            )
            or content["status"] != "submitted"
        ):
            raise ProtocolError("cycle_scope_invalid", status=403)
    if kind == "product" and set(write.visible_to) != {"learner"}:
        raise ProtocolError("product_requires_share", status=403)


def _feedback_channels(
    write: ObjectWrite, content: dict[str, JsonValue], context: ObjectPlanContext
) -> None:
    kind = write.ref.kind
    if kind in {"feedback", "feedback_response"}:
        if content.get("read_projection") is not None:
            raise ProtocolError("feedback_projection_not_persistable", status=403)
        if context.existing or write.ref.version != 1:
            raise ProtocolError("feedback_record_immutable", status=409)
    if kind == "feedback" and context.auth.allowed_objects is not None:
        report = FeedbackV2.model_validate(content)
        complete = any(
            total.status == "complete"
            for facts in report.verified_facts or ()
            for total in facts.activity_totals.values()
        )
        if complete or any(
            history.completeness == "complete"
            for history in report.historical_responsibilities or ()
        ):
            raise ProtocolError("feedback_completeness_scope_unknown", status=403)
    if kind == "feedback_response" and (
        not context.feedback_response or set(write.visible_to) != {"learner"}
    ):
        raise ProtocolError("feedback_response_operation_required", status=403)
    if kind == "workspace_import" and (context.existing or set(write.visible_to) != {"learner"}):
        raise ProtocolError("import_receipt_immutable", status=403)


def _role_channels(
    write: ObjectWrite, content: dict[str, JsonValue], context: ObjectPlanContext
) -> None:
    if write.ref.kind == "role_reply" and role_reply_has_private_fields(content):
        raise ProtocolError("role_reply_private_fields_forbidden", status=403)
    if write.ref.kind != "role_context":
        return
    if content.get("generation_audit") is not None and not context.private_role:
        raise ProtocolError("role_private_authority_required", status=403)
    role = content["role_id"]
    if (
        role in {"learner", "system", "research"}
        or not write.visible_to
        or not set(write.visible_to) <= {"system", role}
    ):
        raise ProtocolError("role_context_private", status=403)
    if any(row.content["role_id"] != role for row in context.existing):
        raise ProtocolError("role_context_identity_immutable", status=409)


def _business_identity(
    write: ObjectWrite, content: dict[str, JsonValue], context: ObjectPlanContext
) -> None:
    kind, existing = write.ref.kind, context.existing
    if kind == "config" and content["config_version"] != write.ref.config_version:
        raise ProtocolError("config_reference_mismatch")
    if kind == "business_request":
        if (
            existing
            and content["basis"] != min(existing, key=lambda row: row.ref.version).content["basis"]
        ):
            raise ProtocolError("request_basis_immutable", status=409)
        if content["basis"]["config"]["session_id"] != context.auth.session_id:
            raise ProtocolError("object_session_mismatch")
    if kind == "share" and existing:
        original = min(existing, key=lambda row: row.ref.version).content
        if any(
            content[key] != original[key]
            for key in ("product", "recipient_role", "shared_at", "question", "purpose")
        ):
            raise ProtocolError("share_identity_immutable", status=409)
    if kind == "scenario_state":
        _scenario_scope(write, content, context)


def _scenario_scope(
    write: ObjectWrite, content: dict[str, JsonValue], context: ObjectPlanContext
) -> None:
    if set(write.visible_to) != {"system"}:
        raise ProtocolError("scenario_state_private", status=403)
    if context.auth.allowed_objects is None:
        return
    previous = (
        max(context.existing, key=lambda row: row.ref.version).content if context.existing else {}
    )
    for name in ("source_versions", "indexed_versions", "material_activation"):
        before, after = previous.get(name, {}), content[name]
        changed = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
        changed = {
            key.rsplit(":", 1)[0] if name == "material_activation" else key for key in changed
        }
        if not changed <= set(context.auth.allowed_objects):
            raise ProtocolError("object_scope_forbidden", status=403)


def _object_identity(
    write: ObjectWrite, content: dict[str, JsonValue], context: ObjectPlanContext
) -> None:
    validate_reference_times(content, context.state.business_seq)
    if content.get("session_id") != context.auth.session_id:
        raise ProtocolError("object_session_mismatch")
    identity = content.get("product_id") if write.ref.kind == "product" else content.get("id")
    if identity is not None and identity != write.ref.object_id:
        raise ProtocolError("object_identity_mismatch")
    if content.get("version", content.get("revision", write.ref.version)) != write.ref.version:
        raise ProtocolError("object_identity_mismatch")
    if content.get("executor") and content["executor"] != context.auth.executor.model_dump(
        mode="json"
    ):
        raise ProtocolError("executor_spoofed", status=403)


def _dependencies(
    write: ObjectWrite,
    content: dict[str, JsonValue],
    traced: tuple[ObjectRef, ...],
    bindings: SessionBindings,
) -> tuple[ObjectRef, ...]:
    declared = tuple({canonical(dep): dep for dep in (*write.dependencies, *traced)}.values())
    if {canonical(ref) for ref in references(content)} - {canonical(ref) for ref in declared}:
        raise ProtocolError("undeclared_object_reference")
    if write.ref.kind in {"submission", "review"} and content.get(
        "evaluation"
    ) != bindings.evaluation.model_dump(mode="json"):
        raise ProtocolError("evaluation_binding_mismatch", status=409)
    if write.ref.kind == "submission" and content.get("scenario") != bindings.scenario.model_dump(
        mode="json"
    ):
        raise ProtocolError("scenario_binding_mismatch", status=409)
    return declared


def plan_object(
    write: ObjectWrite,
    model: type[BaseModel],
    context: ObjectPlanContext,
    traces: Sequence[FeedbackReadTrace],
) -> StoredObject:
    try:
        obj = model.model_validate(write.content)
    except ValidationError as error:
        raise ProtocolError("module_object_invalid", status=503) from error
    content = obj.model_dump(mode="json")
    traced = _trace_boundaries(write, content, context.auth, traces)
    _cycle_channels(write, content, context)
    _feedback_channels(write, content, context)
    _role_channels(write, content, context)
    _business_identity(write, content, context)
    _object_identity(write, content, context)
    dependencies = _dependencies(write, content, traced, context.bindings)
    return StoredObject(
        creator=context.auth.executor,
        ref=write.ref,
        content=content,
        visible_to=write.visible_to,
        dependencies=dependencies,
        created_storage_revision=context.storage_revision,
    )
