"""evaluation production integration boundary, awaiting coordinator-pinned shared protocol input.

The evidence assembler and advisory evaluator are usable pure modules. HTTP,
lifecycle transitions, idempotency, and jobs must be registered on the shared
Gateway/V2Store. Never mount the historical test router as a production fallback.
"""

from dataclasses import replace

from career_lab.api.modules import ExtensionRegistry
from career_lab.contracts import v2 as C
from career_lab.contracts.v2.core import ProtocolError
from career_lab.storage.v2_lifecycle import record_review
from career_lab.storage.v2_store import Mutation, TransactionView


def create_service(*args, **kwargs):
    raise ProtocolError(
        "module_unavailable", "W05 requires the fixed public lifecycle and worker input", status=503
    )


def create_router(*args, **kwargs):
    raise ProtocolError(
        "module_unavailable", "Install W05 operations on the shared Gateway", status=503
    )


def create_review_evaluator(reader, *, engine=None, model_bytes=16000, work_language="zh"):
    """Default read-only factual/semantic handler; no provider required.

    Reader must supply an immutable authorized snapshot, frozen policies and the
    exact-version formation point. Persistence/worker/objections remain external.
    """
    from career_lab.evidence.v2.review_evaluator import ReviewEvaluator

    return ReviewEvaluator(
        reader, engine=engine, model_bytes=model_bytes, work_language=work_language
    )


def prepare_review_feedback(evaluator, auth, request):
    """Evaluate a caller-authorized saved ReviewRequest outside transactions.

    Returns one immutable report per exact work version. It does not invent an
    aggregate grade across works, close objections or start a worker/queue.
    """
    from career_lab.contracts import v2 as C

    if not isinstance(request, C.ReviewRequest):
        raise C.ProtocolError("saved_review_required")
    result = evaluator.handle(auth, request, request.as_of)
    subject = C.ObjectRef(
        session_id=request.session_id, kind="review", object_id=request.id, version=request.version
    )
    reports = []
    for entry in result["reviews"]:
        if entry["feedback"] is None:
            raise C.ProtocolError("subject_point_unknown")
        raw = entry["feedback"]
        raw.update(
            subject=subject.model_dump(mode="json"),
            id=C.digest(
                [
                    subject.model_dump(mode="json"),
                    entry["subject"],
                    request.evaluation.model_dump(mode="json"),
                    "w05-c8-feedback",
                ]
            ),
        )
        reports.append(C.FeedbackV2.model_validate(raw))
    return {
        "request": request,
        "request_hash": C.digest(request),
        "reports": tuple(reports),
        "work_language": evaluator.work_language,
        "followup_of": request.followup_of,
        "followup_status": result["followup_status"],
        "followup_evidence_status": result["followup_evidence_status"],
    }


def review_feedback_plan(view, command, auth, prepared):
    """Commit only prepared public feedback through the single shared store.

    The worker must supply the actual claim/derived_subject to V2Store. Internal
    evidence snapshots/diagnostics are never retagged learner-visible here.
    """
    from career_lab.contracts import v2 as C
    from career_lab.storage.v2_store import Mutation, ObjectWrite, references

    request = prepared["request"]
    subject = C.ObjectRef(
        session_id=auth.session_id, kind="review", object_id=request.id, version=request.version
    )
    if (
        request.session_id != auth.session_id
        or C.digest(C.ReviewRequest.model_validate(view.get(subject).content))
        != prepared["request_hash"]
    ):
        raise C.ProtocolError("review_input_changed", status=409)
    body = C.FeedbackInput.model_validate(command.payload)
    if body.subject != subject:
        raise C.ProtocolError("feedback_subject_mismatch")
    for product in request.subjects:
        view.get(product)
    writes = []
    for report in prepared["reports"]:
        if report.subject != subject or report.evaluation != request.evaluation:
            raise C.ProtocolError("feedback_subject_mismatch")
        ref = C.ObjectRef(
            session_id=auth.session_id, kind="feedback", object_id=report.id, version=1
        )
        content = report.model_dump(mode="json")
        writes.append(
            ObjectWrite(ref=ref, expected_head=0, content=content, dependencies=references(content))
        )
    return Mutation(
        writes=tuple(writes),
        result={
            "feedbacks": [w.ref.model_dump(mode="json") for w in writes],
            "followup_of": [r.model_dump(mode="json") for r in request.followup_of],
            "followup_status": prepared["followup_status"],
            "followup_evidence_status": prepared["followup_evidence_status"],
        },
    )


def record_review_request(
    view: TransactionView, command: C.Command, auth: C.AuthContext, *, registry: ExtensionRegistry
) -> Mutation:
    """Dispatch opt-in previews; legacy reviews retain their original plan and bytes."""
    body = C.ReviewInput.model_validate(command.payload)
    plan = record_review(view, command, auth)
    if body.preview_kind is None:
        if any(
            value is not None
            for value in (body.preview_on_save, body.candidate_config, body.requested_outcomes)
        ):
            raise C.ProtocolError("preview_kind_required")
        return plan
    if body.preview_on_save is not None and auth.executor.kind != "human":
        raise C.ProtocolError("human_preference_required", status=403)
    if not body.subjects or any(ref.kind != "product" for ref in body.subjects):
        raise C.ProtocolError("preview_subject_required")
    if view.current_cycle is None or view.current_cycle.content["status"] != "open":
        raise C.ProtocolError("preview_cycle_closed", status=409)
    for ref in body.subjects:
        view.get(ref)
    if body.candidate_config is not None and body.candidate_config.session_id != auth.session_id:
        raise C.ProtocolError("config_session_mismatch", status=403)
    operations = permitted_preview_operations(registry, auth)
    writes = tuple(
        write.model_copy(
            update={
                "content": C.ReviewRequest.model_validate(
                    {
                        **write.content,
                        "preview_kind": body.preview_kind,
                        "candidate_config": body.candidate_config,
                        "requested_outcomes": body.requested_outcomes,
                        "preview_on_save": body.preview_on_save,
                        "available_operations": operations,
                    }
                ).model_dump(mode="json")
            }
        )
        for write in plan.writes
    )
    return replace(plan, writes=writes)


def permitted_preview_operations(
    registry: ExtensionRegistry, auth: C.AuthContext
) -> tuple[str, ...]:
    """Finite installed capabilities only; this is a suggestion, never an authorization grant."""
    return tuple(
        name
        for name in (
            "reviews.create",
            "work_products.shares.create",
            "configuration.apply",
            "tests.create",
        )
        if registry.availability(name).ready
        and registry.availability(name).capability in auth.capabilities
        and (auth.allowed_actions is None or name in auth.allowed_actions)
    )
