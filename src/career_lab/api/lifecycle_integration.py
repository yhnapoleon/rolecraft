"""Public lifecycle and queue assembly. evaluation supplies the evidence/feedback plan."""

from dataclasses import replace
from functools import partial

from career_lab.contracts.v2 import (
    BeginRevisionInput,
    Command,
    FeedbackInput,
    ObjectRef,
    ProtocolError,
    ResourcePage,
    ReviewInput,
    SubmitInput,
    digest,
)
from career_lab.api.modules import Operation, StoreJobHandler, V2Response
from career_lab.storage.v2_lifecycle import begin_revision, point, record_submission
from career_lab.api.reviews_v2 import record_review_request as record_review
from career_lab.storage.v2_store import JobRequest, Mutation


def feedback_job(command, subject, source, *, key):
    effect = Command(
        schema_version=2,
        request_id="feedback-effect-"
        + digest([command.request_id, subject.model_dump(mode="json")])[:24],
        expected_version=command.expected_version,
        expected_workspace_revision=command.expected_workspace_revision,
        operation="feedback.create",
        payload={"subject": subject.model_dump(mode="json")},
    )
    return JobRequest(
        name="v2.feedback", command=effect, sources=(subject, *source), context_hash=digest(key)
    )


def install_lifecycle(registry, *, feedback_handler=None):
    """A missing evidence adapter is explicit; saving a submission remains usable."""

    def save(plan_fn, kind):
        def handler(view, command, auth):
            plan = plan_fn(view, command, auth)
            if feedback_handler is None:
                return replace(plan, result={**plan.result, "feedback_status": "not_installed"})
            subject = ObjectRef.model_validate(plan.result[kind])
            record = next(write for write in plan.writes if write.ref == subject)
            sources = tuple(
                ObjectRef.model_validate(r)
                for r in record.content.get("products", record.content.get("subjects", ()))
            )
            return replace(
                plan,
                jobs=(feedback_job(command, subject, sources, key=record.content),),
                result={**plan.result, "feedback_status": "queued"},
            )

        return handler

    def request_feedback(view, command, auth):
        body = FeedbackInput.model_validate(command.payload)
        if body.subject.kind not in {"review", "submission"}:
            raise ProtocolError("feedback_subject_invalid")
        if body.retry:
            raise ProtocolError(
                "use_job_refresh", "Use the recorded job refresh action for an explicit retry", 409
            )
        record = view.get(body.subject)
        source = tuple(
            ObjectRef.model_validate(r)
            for r in record.content.get("products", record.content.get("subjects", ()))
        )
        return Mutation(
            jobs=(feedback_job(command, body.subject, source, key=record.content),),
            result={"subject": body.subject.model_dump(mode="json"), "status": "queued"},
        )

    def read_kind(kind, *, selected=None):
        def reader(view, page, auth):
            target = getattr(page, selected) if selected else None
            rows = [
                r
                for r in view.objects
                if r.ref.kind == kind and (target is None or r.ref.object_id == target)
            ]
            if target is not None and not rows:
                raise ProtocolError("object_not_found", status=404)
            rows.sort(key=lambda r: (r.created_storage_revision, r.ref.object_id, r.ref.version))
            end = page.cursor + page.limit
            return V2Response(
                result={
                    "items": [r.content for r in rows[page.cursor : end]],
                    "next_cursor": end if end < len(rows) else None,
                    "as_of": point(view.state).model_dump(mode="json"),
                }
            )

        return reader

    def feedbacks(view, page, auth):
        subjects = {r.ref.object_id for r in view.objects if r.ref.kind in {"review", "submission"}}
        if page.submission_id not in subjects:
            raise ProtocolError("object_not_found", status=404)
        rows = [
            r
            for r in view.objects
            if r.ref.kind == "feedback" and r.content["subject"]["object_id"] == page.submission_id
        ]
        return V2Response(
            result={
                "items": [r.content for r in rows],
                "as_of": point(view.state).model_dump(mode="json"),
            }
        )

    registry.register(
        Operation(
            "submissions.create", "submit", SubmitInput, save(record_submission, "submission")
        )
    )
    registry.register(
        Operation(
            "submissions.list",
            "read",
            ResourcePage,
            read_kind("submission"),
            mutates=False,
            response_model=V2Response,
        )
    )
    registry.register(
        Operation(
            "reviews.create",
            "act",
            ReviewInput,
            save(partial(record_review, registry=registry), "review"),
        )
    )
    registry.register(
        Operation(
            "reviews.read",
            "read",
            ResourcePage,
            read_kind("review", selected="review_id"),
            mutates=False,
            response_model=V2Response,
        )
    )
    registry.register(
        Operation(
            "revision_cycles",
            "act",
            BeginRevisionInput,
            begin_revision,
            action_name="begin_revision",
        )
    )
    registry.register(
        Operation(
            "feedback.create",
            "act",
            FeedbackInput,
            request_feedback,
            ready=feedback_handler is not None,
            unavailable_code=None if feedback_handler else "feedback_reader_not_installed",
        )
    )
    registry.register(
        Operation(
            "feedback.read",
            "read",
            ResourcePage,
            feedbacks,
            mutates=False,
            response_model=V2Response,
        )
    )
    if feedback_handler is not None:
        registry.register_job(
            "v2.feedback", StoreJobHandler(feedback_handler, retry_on_error=False)
        )
    return registry
