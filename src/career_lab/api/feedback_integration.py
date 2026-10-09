"""Common persistence/recovery for factual feedback and learner follow-ups.

The evaluator supplies reports through a trusted server adapter. This module
never infers facts, completeness, actual actions or model quality from a request.
"""

from uuid import uuid4
from career_lab.contracts.v2 import *
from career_lab.api.modules import Operation, V2Response
from career_lab.storage.v2_store import Mutation, ObjectWrite, references, FeedbackReadTrace
from career_lab.storage.v2_lifecycle import point


def record_feedback_response(view, command, auth):
    body = FeedbackResponseCreate.model_validate(command.payload)
    target = ObjectRef(
        session_id=auth.session_id,
        kind="feedback",
        object_id=body.feedback_id,
        version=body.feedback_version,
    )
    feedback = FeedbackV2.model_validate(view.get(target).content)
    known = {item.criterion for item in feedback.items}
    for snapshot in feedback.historical_responsibilities or ():
        known.update(item.criterion for item in snapshot.entries)
    if body.criterion is not None and body.criterion not in known:
        raise ProtocolError("feedback_criterion_unknown")
    item = FeedbackResponseRecord(
        evidence_status="user_submitted_unverified" if body.evidence else "none_submitted",
        id=uuid4().hex,
        session_id=auth.session_id,
        feedback=target,
        kind=body.kind,
        section=body.section,
        criterion=body.criterion,
        text=body.text,
        evidence=body.evidence,
        recorded_at=point(view.state),
        executor=auth.executor,
    )
    ref = ObjectRef(
        session_id=auth.session_id, kind="feedback_response", object_id=item.id, version=1
    )
    return Mutation(
        writes=(
            ObjectWrite(
                ref=ref,
                expected_head=0,
                content=item.model_dump(mode="json"),
                dependencies=references(item.model_dump(mode="json")),
            ),
        ),
        result={
            "response": ref.model_dump(mode="json"),
            "feedback": target.model_dump(mode="json"),
            "evidence_status": item.evidence_status,
        },
        feedback_read_traces=(
            FeedbackReadTrace(
                ref,
                "/text",
                tuple(
                    {
                        canonical(r): r
                        for r in (
                            target,
                            *references([v.model_dump(mode="json") for v in body.evidence]),
                        )
                    }.values()
                ),
            ),
        ),
    )


def install_feedback_recovery(registry):
    registry.register(
        Operation(
            "feedback.responses.create", "act", FeedbackResponseCreate, record_feedback_response
        )
    )

    def read_feedback(view, page, auth):
        matches = [
            row
            for row in view.objects
            if row.ref.kind == "feedback" and row.ref.object_id == page.feedback_id
        ]
        if not matches:
            raise ProtocolError("object_not_found", status=404)
        record = max(matches, key=lambda row: row.ref.version)
        # Preserve the exact historical object; absent fields stay absent in storage and wire.
        sections = ("verified_facts", "historical_responsibilities", "rule_items", "provenance")
        return V2Response(
            result={
                "feedback": record.content,
                "sections": {
                    name: "recorded" if record.content.get(name) is not None else "not_recorded"
                    for name in sections
                },
            }
        )

    def read_responses(view, page, auth):
        if page.feedback_id is not None:
            if not any(
                row.ref.kind == "feedback" and row.ref.object_id == page.feedback_id
                for row in view.objects
            ):
                raise ProtocolError("object_not_found", status=404)
        rows = []
        for record in view.objects:
            if record.ref.kind != "feedback_response":
                continue
            item = FeedbackResponseRecord.model_validate(record.content)
            if page.response_id is not None and item.id != page.response_id:
                continue
            if page.feedback_id is not None and item.feedback.object_id != page.feedback_id:
                continue
            try:
                view.get(item.feedback)
            except ProtocolError:
                continue
            rows.append(record)
        if page.response_id is not None and not rows:
            raise ProtocolError("object_not_found", status=404)
        rows.sort(key=lambda row: (row.created_storage_revision, row.ref.object_id))
        end = page.cursor + page.limit
        return V2Response(
            result={
                "items": [row.content for row in rows[page.cursor : end]],
                "next_cursor": end if end < len(rows) else None,
                "as_of": point(view.state).model_dump(mode="json"),
            }
        )

    registry.register(
        Operation(
            "feedback.records.read",
            "read",
            ResourcePage,
            read_feedback,
            mutates=False,
            response_model=V2Response,
        )
    )
    registry.register(
        Operation(
            "feedback.responses.read",
            "read",
            ResourcePage,
            read_responses,
            mutates=False,
            response_model=V2Response,
        )
    )
    registry.register(
        Operation(
            "feedback.responses.list",
            "read",
            ResourcePage,
            read_responses,
            mutates=False,
            response_model=V2Response,
        )
    )
    return registry
