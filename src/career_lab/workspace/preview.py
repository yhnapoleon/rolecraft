"""One cheap private rule check in the successful save transaction; no job or model."""

import os
from dataclasses import replace

from career_lab.api.modules import ExtensionRegistry
from career_lab.api.reviews_v2 import permitted_preview_operations
from career_lab.contracts import v2 as C
from career_lab.contracts.v2.evaluation import _OutcomeAction as OutcomeAction
from career_lab.evidence.v2.preview import (
    clarification_questions,
    configuration_missing,
    pending_configuration,
    saved_input_outcome,
)
from career_lab.storage.v2_store import (
    FeedbackReadTrace,
    Mutation,
    ObjectWrite,
    TransactionView,
    references,
)


def after_saved_version(
    registry: ExtensionRegistry,
    view: TransactionView,
    command: C.Command,
    auth: C.AuthContext,
    plan: Mutation,
) -> Mutation:
    if command.operation not in {"work_products.create", "work_products.versions.create"}:
        return plan
    if os.environ.get("CAREER_LAB_PREVIEW_ON_SAVE", "1").lower() in {"0", "false", "off"}:
        return plan
    if not registry.availability("feedback.create").ready:
        return plan
    if auth.allowed_objects is not None:
        # Scoped saves must not create inaccessible derived records or infer owner preferences.
        return replace(plan, result={**plan.result, "preview_status": "explicit_review_required"})
    preferences = [
        row
        for row in view.objects
        if row.ref.kind == "review"
        and row.content.get("preview_on_save") is not None
        and row.content["executor"]["kind"] == "human"
    ]
    if (
        preferences
        and not max(preferences, key=lambda row: row.created_storage_revision).content[
            "preview_on_save"
        ]
    ):
        return plan
    languages = {
        row.work_language for row in registry.scenarios.values() if row.bindings == view.bindings
    }
    if len(languages) != 1 or not languages <= {"zh", "en"}:
        return plan
    language = next(iter(languages))
    assert language is not None
    writes = []
    traces = []
    review_ref = feedback_ref = None
    for write in plan.writes:
        if write.ref.kind != "product":
            continue
        request, report = saved_version_check(
            view, command, auth, write, language, permitted_preview_operations(registry, auth)
        )
        review_ref = C.ObjectRef(
            session_id=auth.session_id, kind="review", object_id=request.id, version=1
        )
        feedback_ref = C.ObjectRef(
            session_id=auth.session_id, kind="feedback", object_id=report.id, version=1
        )
        for ref, model in ((review_ref, request), (feedback_ref, report)):
            content = model.model_dump(mode="json")
            writes.append(
                ObjectWrite(
                    ref=ref, expected_head=0, content=content, dependencies=references(content)
                )
            )
        for index, _ in enumerate(report.outcomes or ()):
            traces.append(
                FeedbackReadTrace(feedback_ref, f"/outcomes/{index}", (write.ref, review_ref))
            )
    if not writes:
        return plan
    assert review_ref is not None and feedback_ref is not None
    return replace(
        plan,
        writes=(*plan.writes, *writes),
        feedback_read_traces=(*plan.feedback_read_traces, *traces),
        result={
            **plan.result,
            "preview_review": review_ref.model_dump(mode="json"),
            "preview_feedback": feedback_ref.model_dump(mode="json"),
        },
    )


def saved_version_check(
    view: TransactionView,
    command: C.Command,
    auth: C.AuthContext,
    write: ObjectWrite,
    language: str,
    operations: tuple[str, ...],
) -> tuple[C.ReviewRequest, C.FeedbackV2]:
    product = C.WorkProductVersion.model_validate(write.content)
    # The common core advances these two clocks once for this atomic write set.
    at = C.VersionPoint(
        business_seq=view.state.business_seq,
        workspace_revision=view.state.workspace_revision + 1,
        storage_revision=view.state.storage_revision + 1,
    )
    request = C.ReviewRequest(
        id=C.digest([command.request_id, write.ref.model_dump(mode="json"), "saved-rule-check"]),
        session_id=auth.session_id,
        subjects=(write.ref,),
        purpose=product.purpose,
        scope=(),
        as_of=at,
        evaluation=view.bindings.evaluation,
        executor=auth.executor,
        preview_kind="rules",
        available_operations=operations,
    )
    ref = C.ObjectRef(session_id=auth.session_id, kind="review", object_id=request.id, version=1)
    proof = C.EvidenceRefV2(**write.ref.model_dump(), observed_at_seq=at.business_seq)
    missing = configuration_missing(product.purpose, None)
    questions = clarification_questions(missing, language)
    report = C.FeedbackV2(
        id=C.digest([request.id, "saved-rule-feedback"]),
        session_id=auth.session_id,
        subject=ref,
        evaluation=view.bindings.evaluation,
        as_of=at,
        items=(),
        business_response="No business action was executed."
        if language == "en"
        else "未执行业务动作。",
        next_options=questions,
        verified_coverage=0,
        model_coverage=0,
        preview_kind="rules",
        preview_language=language,
        input_refs=(write.ref,),
        evaluation_as_of=at,
        basis_refs=(write.ref,),
        conditions=(),
        missing_inputs=missing,
        clarification=questions,
        available_actions=tuple(
            OutcomeAction(operation=name, objects=(write.ref,))
            for name in operations
            if name in {"reviews.create", "work_products.shares.create"}
        ),
        generation_status="waiting_model",
        outcomes=(
            saved_input_outcome(write.ref, proof, 1, language),
            pending_configuration(missing, language),
        ),
    )
    return request, report
