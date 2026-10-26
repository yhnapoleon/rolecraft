"""Exact submission-to-feedback discovery in the caller's authorized read window."""

from career_lab.contracts import v2 as C
from career_lab.storage.v2_lifecycle import point

from .types import FeedbackDiscovery, ReadShortcut


def permits(auth, operation):
    return auth.allowed_actions is None or operation in auth.allowed_actions


def require_read(auth, *operations):
    if "read" not in auth.capabilities or any(not permits(auth, op) for op in operations):
        raise C.ProtocolError("action_forbidden", status=403)


def language_of(registry, bindings):
    entries = list(registry.scenarios.values())
    entries += list(getattr(registry, "language_scenarios", {}).values())
    for entry in entries:
        if entry.bindings == bindings and entry.work_language in ("zh", "en"):
            return entry.work_language
    historical = getattr(registry, "historical_identity", None)
    found = historical(bindings) if historical else None
    if found and found[1] in ("zh", "en"):
        return found[1]
    raise C.ProtocolError("work_language_unavailable", status=503)


def discover(view, auth, subject, registry, *, language=None):
    """Never use raw SQL, job state or global-latest feedback to infer readiness."""
    require_read(auth, "submissions.list")
    if subject.session_id != auth.session_id or subject.kind != "submission":
        raise C.ProtocolError("object_not_found", status=404)
    view.get(subject)
    require_read(auth, "feedback.records.read")
    reader = registry.operations.get("feedback.records.read")
    if reader is None or not reader.ready:
        raise C.ProtocolError("module_unavailable", status=503)
    language = language or language_of(registry, view.bindings)
    rows = [
        row
        for row in view.objects
        if row.ref.kind == "feedback"
        and row.content.get("preview_kind") is None
        and C.FeedbackV2.model_validate(row.content).subject == subject
    ]
    rows.sort(
        key=lambda row: (row.created_storage_revision, row.ref.version, row.ref.object_id),
        reverse=True,
    )
    for row in rows:
        # Reuse the installed pure read handler in THIS view (including read_boundaries).
        projected = reader.handler(view, C.ResourcePage(feedback_id=row.ref.object_id), auth)
        body = projected.result["feedback"]
        feedback = C.FeedbackV2.model_validate(body)
        if feedback.subject != subject or feedback.id != row.ref.object_id:
            continue
        exact = (
            ReadShortcut(
                tool="objects.read", arguments={"query": {"ref": row.ref.model_dump(mode="json")}}
            )
            if permits(auth, "objects.read")
            else None
        )
        return FeedbackDiscovery(
            subject=subject,
            status="ready",
            feedback_ref=row.ref,
            read=ReadShortcut(
                tool="feedback.records.read",
                arguments={"query": {"feedback_id": row.ref.object_id}},
            ),
            exact_read=exact,
            as_of=point(view.state),
            work_language=language,
        )
    return FeedbackDiscovery(
        subject=subject,
        status="not_ready",
        as_of=point(view.state),
        work_language=language,
        reason="尚无可读取的正式反馈。"
        if language == "zh"
        else "No readable formal feedback is available yet.",
    )
