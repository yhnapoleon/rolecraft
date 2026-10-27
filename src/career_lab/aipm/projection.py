"""One server projection of the seven steps, shared by the web page and the Agent.

Only fields of authorized, learner-visible objects are read. ``recorded`` means a
completion signal exists, never mastery; quality and feedback stay separate.
"""

from collections import defaultdict

from career_lab.contracts import v2 as C
from career_lab.storage.v2_lifecycle import point

from .feedback_discovery import discover, permits
from .types import (
    STEP_IDS,
    AipmProgress,
    DraftSummary,
    FeedbackSummary,
    ProgressStep,
    Projection,
    PublicAction,
    PublicGap,
)

OPEN_FINDINGS = {"violation", "improve", "unknown"}
# Reads whose absence means some step evidence may be invisible to this caller.
EVIDENCE_READS = ("objects.read", "submissions.list", "feedback.records.read")
SUBMISSION_LIMIT = 3
KIND = "aipm_design_draft"

GAPS = {
    "business_sources": (
        "业务说明还没有关联公司来源。",
        "Business notes have no company source yet.",
    ),
    "business_audience": (
        "还没写清服务对象是内部还是外部。",
        "State whether this serves internal or external people.",
    ),
    "stakeholder_user": ("还没标出目标用户。", "No target user is marked yet."),
    "stakeholder_responsibility": (
        "还没说明一项待确认的责任。",
        "No responsibility to confirm is described yet.",
    ),
    "need_counterevidence": (
        "需求假设还缺反证或未知点。",
        "The need hypothesis lacks counterevidence or an unknown.",
    ),
    "need_next_validation": ("还没写下一步怎样验证。", "No next validation step yet."),
    "solution_alternative": (
        "方案还缺一个实质替代做法。",
        "The approach lacks a meaningful alternative.",
    ),
    "monitoring_plan": (
        "已有测试批次，但还没有监控与回退计划。",
        "A test batch exists, but no monitoring or rollback plan.",
    ),
    "recheck": ("相关输入已变化，需要重新核对。", "Related inputs changed; recheck them."),
    "projection_limited": (
        "授权范围不足，无法确认完整进度。",
        "Authorization is too narrow to confirm full progress.",
    ),
}


def gap(code, language):
    zh, en = GAPS[code]
    return PublicGap(code=code, message=zh if language == "zh" else en)


def heads(objects):
    """Latest visible version per (kind, object_id)."""
    latest = {}
    for row in objects:
        key = (row.ref.kind, row.ref.object_id)
        if key not in latest or row.ref.version > latest[key].ref.version:
            latest[key] = row
    return latest


def scoped(view, auth):
    if auth.allowed_objects is None:
        return view.objects
    return tuple(
        row
        for row in view.objects
        if row.ref.object_id in auth.allowed_objects
        or row.ref.kind in {"aipm_profile", "aipm_focus"}
    )


def complete_for(auth):
    return auth.allowed_objects is None and all(permits(auth, op) for op in EVIDENCE_READS)


def feedback_rows(objects, latest):
    """Process feedback with staleness relative to the current head of its input.

    The third value marks feedback that was superseded, not overtaken: every design save
    evaluates the rules again, so an older design's feedback gives way to the newer evaluation
    and nothing needs rechecking. Saving one section must not send the others back (QA S-1)."""
    found = []
    for row in objects:
        if row.ref.kind != "aipm_process_feedback":
            continue
        item = dict(row.content)
        source = C.ObjectRef.model_validate(item["input_ref"])
        head = latest.get((source.kind, source.object_id))
        newer = head is not None and head.ref.version > source.version
        superseded = newer and source.kind == "aipm_design" and not item.get("stale")
        item["stale"] = bool(item.get("stale")) or newer
        found.append((row, item, superseded))
    found.sort(key=lambda found: (found[0].created_storage_revision, found[0].ref.object_id))
    return found


def _design_signals(design, language):
    status, refs, missing = {}, {}, defaultdict(list)
    if design is None:
        return status, refs, missing
    content, ref = design.content, design.ref
    business = content.get("business")
    if business:
        refs["business"] = [ref]
        if not business.get("source_refs"):
            missing["business"].append(gap("business_sources", language))
        if business.get("audience") == "unknown":
            missing["business"].append(gap("business_audience", language))
        status["business"] = "working" if missing["business"] else "recorded"
    people = content.get("stakeholders") or ()
    if people:
        refs["stakeholders"] = [ref]
        if not any("user" in person.get("relationships", ()) for person in people):
            missing["stakeholders"].append(gap("stakeholder_user", language))
        if not any(person.get("responsibility", "").strip() for person in people):
            missing["stakeholders"].append(gap("stakeholder_responsibility", language))
        status["stakeholders"] = "working" if missing["stakeholders"] else "recorded"
    needs = content.get("needs") or ()
    if needs:
        refs["need"] = [ref]
        if not any(need.get("counterevidence_or_unknown", "").strip() for need in needs):
            missing["need"].append(gap("need_counterevidence", language))
        if not any(need.get("next_validation", "").strip() for need in needs):
            missing["need"].append(gap("need_next_validation", language))
        status["need"] = "working" if missing["need"] else "recorded"
    if content.get("rows"):
        refs["boundary"] = [ref]
        status["boundary"] = "recorded"
    solution = content.get("solution")
    if solution:
        refs["solution"] = [ref]
        if not solution.get("alternative", "").strip():
            missing["solution"].append(gap("solution_alternative", language))
        status["solution"] = "working" if missing["solution"] else "recorded"
    return status, refs, missing


def draft_steps(draft):
    steps = []
    for step, present in (
        ("business", draft.get("business")),
        ("stakeholders", draft.get("stakeholders")),
        ("need", draft.get("needs")),
        ("boundary", draft.get("rows")),
        ("solution", draft.get("solution")),
    ):
        if present:
            steps.append(step)
    for step in draft.get("prd_sections") or {}:
        if step not in steps:
            steps.append(step)
    return tuple(steps)


def pending(objects):
    rows = [r for r in heads(objects).values() if r.ref.kind == KIND]
    rows.sort(key=lambda r: (r.created_storage_revision, r.ref.object_id))
    return [
        DraftSummary(
            ref=r.ref,
            author_kind=r.content["author"]["kind"],
            steps=draft_steps(r.content),
        )
        for r in rows
        if r.content["status"] == "pending_owner_review"
    ]


def project(view, auth, content, registry, *, focus_default="business"):
    language = content.work_language
    objects = scoped(view, auth)
    latest = heads(objects)
    by_kind = defaultdict(list)
    for row in latest.values():
        by_kind[row.ref.kind].append(row)
    newest = lambda kind: max(  # noqa: E731
        by_kind[kind], key=lambda r: (r.created_storage_revision, r.ref.version), default=None
    )

    focus_row = newest("aipm_focus")
    focus = focus_row.content["step_id"] if focus_row else focus_default
    status, refs, missing = _design_signals(newest("aipm_design"), language)
    refs = defaultdict(list, refs)

    batches = by_kind["aipm_batch"]
    if batches:
        batch = max(batches, key=lambda r: (r.created_storage_revision, r.ref.version))
        refs["assurance"].append(batch.ref)
        if batch.content.get("monitoring"):
            status["assurance"] = "recorded"
        else:
            status["assurance"] = "working"
            missing["assurance"].append(gap("monitoring_plan", language))
        if batch.content.get("pause_reason"):
            status["assurance"] = "recheck"
            missing["assurance"].append(gap("recheck", language))

    submissions = sorted(
        (row for row in objects if row.ref.kind == "submission"),
        key=lambda r: (r.created_storage_revision, r.ref.version),
        reverse=True,
    )
    if submissions:
        refs["decision"].append(submissions[0].ref)
        status["decision"] = "recorded"

    for link in by_kind["aipm_step_link"]:
        step = link.content["step_id"]
        refs[step].append(C.ObjectRef.model_validate(link.content["product_ref"]))
        # A learner's own link is a recorded signal awaiting review, not verified quality.
        status.setdefault(step, "recorded")

    feedback = defaultdict(list)
    overtaken = set()
    for _row, item, superseded in feedback_rows(objects, latest):
        feedback[item["step_id"]].append(item)
        if item["stale"] and not superseded:
            overtaken.add(item["step_id"])

    guide = {step.id: step for step in content.guide.steps}
    from .review import sheets

    drafts = pending(objects)
    pending_steps = {step for draft in drafts for step in draft.steps}
    latest_design = newest("aipm_design")
    sheet_states, prd = sheets(
        view, objects, latest_design.content if latest_design else None, pending_steps
    )
    steps = []
    for step_id in STEP_IDS:
        items = feedback[step_id]
        live = [item for item in items if not item["stale"]]
        work = status.get(step_id, "not_started")
        if work in {"recorded", "working"} and step_id in overtaken:
            work = "recheck"
            missing[step_id].append(gap("recheck", language))
        if work == "not_started" and submissions:
            work = "uncovered"
        open_items = [item for item in live if item["finding"] in OPEN_FINDINGS]
        if any(item["finding"] in {"violation", "improve"} for item in live):
            quality = "has_findings"
        elif live and all(item["finding"] == "supported_for_scope" for item in live):
            quality = "checked_for_declared_scope"
        else:
            quality = "unverified"
        base = guide[step_id]
        actions = []
        if work != "recorded" or open_items:
            direction = next((h for h in base.help if h.get("level") == "direction"), {})
            label = (direction.get("primary_action") or {}).get("label") or base.label
            actions.append(PublicAction(action="open_step", label=label, step_id=step_id))
        if open_items:
            actions.append(
                PublicAction(
                    action="open_feedback",
                    label="查看过程反馈" if language == "zh" else "Review process feedback",
                    step_id=step_id,
                )
            )
        unique = {C.canonical(ref): ref for ref in refs[step_id]}
        sheet = sheet_states.get(step_id)
        steps.append(
            ProgressStep(
                id=step_id,
                order=base.order,
                label=base.label,
                goal=base.goal,
                expected_outputs=base.expected_outputs,
                segment=base.segment,
                icon=base.icon,
                work_status=work,
                completed=work == "recorded",
                evidence_refs=tuple(
                    C.ObjectRef.model_validate(
                        {k: v for k, v in ref.model_dump().items() if k in C.ObjectRef.model_fields}
                    )
                    for ref in unique.values()
                ),
                missing=tuple(missing[step_id]),
                quality_status=quality,
                open_feedback=tuple(
                    FeedbackSummary(
                        id=item["id"],
                        source=item["source"],
                        finding=item["finding"],
                        message=item["message"],
                        input_ref=C.ObjectRef.model_validate(item["input_ref"]),
                    )
                    for item in open_items[-3:]
                ),
                next_actions=tuple(actions),
                **({"sheet": sheet} if sheet is not None else {}),
            )
        )

    suggested = _suggest(steps, focus)
    discoveries = []
    can_discover = permits(auth, "submissions.list") and permits(auth, "feedback.records.read")
    if can_discover:
        seen = set()
        for row in submissions:
            if row.ref.object_id in seen:
                continue
            seen.add(row.ref.object_id)
            discoveries.append(discover(view, auth, row.ref, registry, language=language))
            if len(discoveries) == SUBMISSION_LIMIT:
                break

    unresolved = []
    design = newest("aipm_design")
    if design is not None:
        for need in design.content.get("needs") or ():
            if need.get("claim_status") == "unresolved":
                unresolved.append(PublicGap(code="need_unresolved", message=need["problem"][:200]))
    complete = complete_for(auth)
    return AipmProgress(
        session_id=auth.session_id,
        content_revision=content.content_revision,
        work_language=language,
        as_of=point(view.state),
        focus_step=focus,
        suggested_step=suggested,
        projection=Projection(
            complete=complete,
            reason=None if complete else gap("projection_limited", language).message,
        ),
        steps=tuple(steps),
        submission_feedback=tuple(discoveries),
        unresolved_business_items=tuple(unresolved[:5]),
        pending_agent_drafts=tuple(drafts[-5:]),
        prd_ref=prd,
    )


def _suggest(steps, focus):
    """Current step's explicit problem first, then the earliest step without a record."""
    by_id = {step.id: step for step in steps}
    current = by_id[focus]
    if current.quality_status == "has_findings" or current.work_status in {"working", "recheck"}:
        return focus
    for step in steps:
        if step.quality_status == "has_findings" or step.work_status == "recheck":
            return step.id
    for step in steps:
        if step.work_status in {"not_started", "working"}:
            return step.id
    return "decision"


def feedback_page(view, auth, *, cursor=0, limit=20, step_id=None):
    objects = scoped(view, auth)
    rows = [item for _, item, _ in feedback_rows(objects, heads(objects))]
    if step_id is not None:
        rows = [item for item in rows if item["step_id"] == step_id]
    rows.reverse()  # newest first
    page = rows[cursor : cursor + limit]
    more = cursor + limit < len(rows)
    return {
        "items": page,
        "as_of": point(view.state).model_dump(mode="json"),
        "next_cursor": cursor + limit if more else None,
        "complete": complete_for(auth),
    }
