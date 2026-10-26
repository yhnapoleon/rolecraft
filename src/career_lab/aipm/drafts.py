"""Agent-proposed design drafts. A draft never counts as a step record or formal feedback.

The owner adopts by saving an AipmDesign (L2) and then resolving the draft. Precheck
findings are rule output on the draft only, labelled as pending the owner's review.
"""

from functools import cache

from career_lab.contracts import v2 as C
from career_lab.storage.reference_graph import references
from career_lab.storage.v2_store import Mutation, ObjectWrite

from .progress import design_facts, enrolled, require_owner
from .projection import KIND, draft_steps, heads, project
from .types import (
    DRAFT_PRECHECK,
    AipmDesignDraft,
    DraftInput,
    DraftResolve,
    DraftSummary,
    ProcessFeedback,
    PublicAction,
)


@cache
def _rules(path):
    from career_lab.aipm.design.rules import load_rules

    return load_rules(path)


def precheck(view, auth, content, ref, draft):
    """Rule output on this draft version, recomputed on read; never stored as feedback."""
    findings = ()
    if content.design_rules is not None:
        from career_lab.aipm.design.rules import evaluate_design

        _, found = evaluate_design(
            draft.model_dump(mode="json", include={"rows"}),
            ref,
            design_facts(content)(view, auth),
            _rules(content.design_rules),
            content.work_language,
        )
        findings = tuple(ProcessFeedback.model_validate(item) for item in found)
    return {"label": DRAFT_PRECHECK, "findings": [f.model_dump(mode="json") for f in findings]}


def handlers(catalog, registry):
    def draft(view, command, auth):
        if "act" not in auth.capabilities or auth.actor_id != "learner":
            raise C.ProtocolError("capability_forbidden", status=403)
        if auth.allowed_objects is not None:
            # A draft may cite any visible object; a narrowed grant cannot prove that.
            raise C.ProtocolError("aipm_scope_incomplete", status=403)
        content = enrolled(view, auth, catalog)
        if view.state.status != "active":
            raise C.ProtocolError("aipm_practice_not_active", status=409)
        body = DraftInput.model_validate(command.payload)
        latest = heads(view.objects)
        head = latest.get((KIND, body.draft_id))
        if (head.ref.version if head else 0) != body.expected_revision:
            raise C.ProtocolError("aipm_draft_revision_conflict", status=409)
        if head is not None and head.content["status"] != "pending_owner_review":
            raise C.ProtocolError("aipm_draft_resolved", status=409)
        ref = C.ObjectRef(
            session_id=auth.session_id,
            kind=KIND,
            object_id=body.draft_id,
            version=body.expected_revision + 1,
        )
        designs = [r for r in latest.values() if r.ref.kind == "aipm_design"]
        base = max(designs, key=lambda r: r.created_storage_revision).ref if designs else None
        proposal = body.model_dump(exclude={"draft_id", "expected_revision", "schema_version"})
        record = AipmDesignDraft(
            **proposal,
            id=body.draft_id,
            session_id=auth.session_id,
            revision=ref.version,
            author=auth.executor,
            base_design_ref=base,
        )
        stored = record.model_dump(mode="json")
        for cited in references(stored):
            if cited.session_id != auth.session_id or not view.reference_allowed(cited):
                raise C.ProtocolError("object_not_found", status=404)
        write = ObjectWrite(
            ref=ref,
            expected_head=body.expected_revision,
            content=stored,
            visible_to=("learner",),
            dependencies=references(stored),
        )
        progress = project(view, auth, content, registry)
        zh = content.work_language == "zh"
        summary = DraftSummary(ref=ref, author_kind=auth.executor.kind, steps=draft_steps(stored))
        return Mutation(
            writes=(write,),
            result={
                "ref": ref.model_dump(mode="json"),
                "status": "pending_owner_review",
                "counts_toward_progress": False,
                "message": (
                    "草稿已交给本人确认；采用前不计入进度，也不产生正式过程反馈。"
                    if zh
                    else "Draft sent for the owner's review. It does not count toward "
                    "progress or formal process feedback until adopted."
                ),
                "precheck": precheck(view, auth, content, ref, record),
                "progress": {
                    "as_of": progress.as_of.model_dump(mode="json"),
                    "focus_step": progress.focus_step,
                    "suggested_step": progress.suggested_step,
                    "steps": [
                        {"id": s.id, "work_status": s.work_status, "completed": s.completed}
                        for s in progress.steps
                    ],
                    "pending_agent_drafts": [
                        d.model_dump(mode="json")
                        for d in progress.pending_agent_drafts
                        if d.ref.object_id != ref.object_id
                    ]
                    + [summary.model_dump(mode="json")],
                },
                "next_actions": [
                    PublicAction(
                        action="review_agent_draft",
                        label="请本人在网页上确认草稿" if zh else "Ask the owner to review it",
                        target=ref,
                    ).model_dump(mode="json"),
                    *[
                        a.model_dump(mode="json")
                        for s in progress.steps
                        if s.id == progress.suggested_step
                        for a in s.next_actions
                    ],
                ],
            },
        )

    def resolve(view, command, auth):
        require_owner(auth)
        enrolled(view, auth, catalog)
        body = DraftResolve.model_validate(command.payload)
        head = heads(view.objects).get((KIND, body.draft_id))
        if head is None:
            raise C.ProtocolError("object_not_found", status=404)
        if head.ref.version != body.expected_revision:
            raise C.ProtocolError("aipm_draft_revision_conflict", status=409)
        if head.content["status"] != "pending_owner_review":
            raise C.ProtocolError("aipm_draft_resolved", status=409)
        adopted = body.adopted_design_ref
        if body.status == "adopted":
            if adopted is None or adopted.kind != "aipm_design":
                raise C.ProtocolError("aipm_adopted_design_required")
            view.get(adopted)  # the owner's own saved design, exact version
        elif adopted is not None:
            raise C.ProtocolError("aipm_adopted_design_unexpected")
        record = AipmDesignDraft.model_validate(head.content).model_copy(
            update={
                "revision": head.ref.version + 1,
                "status": body.status,
                "resolved_by": auth.executor.id,
                "adopted_design_ref": adopted,
            }
        )
        stored = record.model_dump(mode="json")
        ref = head.ref.model_copy(update={"version": record.revision})
        write = ObjectWrite(
            ref=ref,
            expected_head=head.ref.version,
            content=stored,
            visible_to=("learner",),
            dependencies=references(stored),
        )
        return Mutation(
            writes=(write,), result={"ref": ref.model_dump(mode="json"), "draft": stored}
        )

    def listing(view, query, auth):
        content = enrolled(view, auth, catalog)
        rows = [r for r in heads(view.objects).values() if r.ref.kind == KIND]
        if query.status != "all":
            rows = [r for r in rows if r.content["status"] == query.status]
        rows.sort(key=lambda r: r.created_storage_revision, reverse=True)
        return {
            "items": [
                {
                    "ref": r.ref.model_dump(mode="json"),
                    "draft": r.content,
                    "precheck": precheck(
                        view, auth, content, r.ref, AipmDesignDraft.model_validate(r.content)
                    ),
                }
                for r in rows[:20]
            ]
        }

    return {
        "aipm.design.draft": draft,
        "aipm.design_drafts.resolve": resolve,
        "aipm.design_drafts.list": listing,
    }
