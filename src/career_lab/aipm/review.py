"""Section review orchestration (v2 spec §6). Rules and authored coverage only: no model runs.

Order: PRD + design -> L2 rules -> coverage marks -> rubric rule items (the existing read-only
``SubmissionRuleChecks.draft``, computed before the write transaction) -> authored mentor
prompts -> status. Reviews are bound to exact inputs, so a repeated request returns the
stored review instead of recomputing.
"""

from contextvars import ContextVar
from datetime import UTC, datetime

from career_lab.contracts import v2 as C
from career_lab.storage.reference_graph import references
from career_lab.storage.v2_lifecycle import point
from career_lab.storage.v2_store import Mutation, ObjectWrite

from .projection import heads
from .types import (
    STEP_IDS,
    CoverageMark,
    MentorPrompt,
    Pointer,
    ProcessFeedback,
    ReviewDelta,
    ReviewStale,
    RubricLine,
    SectionReview,
    SectionReviewInput,
    SheetState,
)

KIND = "aipm_section_review"
ALL = (
    "R1.target",
    "R1.metrics",
    "R2.support",
    "R2.unknowns",
    "R2.failure_analysis",
    "R3.capacity",
    "R3.resources",
    "R4.functional_tests",
    "R4.staleness_test",
    "R5.impact",
    "R5.adjustment",
    "R6.alternatives",
    "R6.consistency",
    "R6.operations",
)
# Spec §5.2: formal criteria each sheet is reviewed against.
STEP_CRITERIA = {
    "business": ("R1.target", "R2.unknowns"),
    "stakeholders": ("R1.target", "R6.operations"),
    "need": ("R1.metrics", "R2.support", "R2.unknowns"),
    "boundary": (),
    "solution": ("R3.capacity", "R3.resources", "R6.alternatives", "R6.consistency"),
    "assurance": (
        "R4.functional_tests",
        "R4.staleness_test",
        "R2.failure_analysis",
        "R5.impact",
        "R5.adjustment",
        "R6.operations",
    ),
    "decision": ALL,
}
SEVERITY = {"high": 0, "medium": 1, "low": 2}
MARK = {"wrong": 0, "missing": 1, "to_check": 2, "covered": 3}
POLICY_MATERIALS = frozenset({"policy"})

# The route computes the read-only rule check outside the write transaction and hands it to
# the handler here; a request body can never supply it.
RULE_CHECK: ContextVar = ContextVar("aipm_section_rule_check", default=None)


def text(language, zh, en):
    return zh if language == "zh" else en


def material_ref(view, auth, material):
    """An exact, visible material reference at its current version, or None."""
    private = view.private_scenario_state
    if private is None or not callable(view.reference_allowed):
        return None
    version = private.source_versions.get(material)
    active = private.material_activation.get(f"{material}:{version}")
    if version is None or active is None or active > view.state.business_seq:
        return None
    ref = C.EvidenceRefV2(
        session_id=auth.session_id,
        kind="material",
        object_id=material,
        version=version,
        observed_at_seq=active,
        valid_from_seq=active,
    )
    try:
        return ref if view.reference_allowed(ref) else None
    except C.ProtocolError:
        return None


def _field(design, path):
    """Follow a dotted path; inside a list, a segment selects the element with that id."""
    value = design
    for key in path.split("."):
        if isinstance(value, list | tuple):
            value = next((x for x in value if isinstance(x, dict) and x.get("id") == key), None)
        elif isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    return value


def _rule_id(finding, input_ref):
    prefix = f"{input_ref['object_id']}-{input_ref['version']}-"
    rest = finding["id"][len(prefix) :] if finding["id"].startswith(prefix) else finding["id"]
    location = finding.get("section_or_row_id")
    return rest[: -(len(location) + 1)] if location and rest.endswith("-" + location) else rest


def _design_findings(view, auth, content, design_row, step):
    if design_row is None or content.design_rules is None:
        return [], set(), set()
    from career_lab.aipm.design.rules import evaluate_design

    from .drafts import _rules
    from .progress import design_facts

    _, findings = evaluate_design(
        design_row.content,
        design_row.ref,
        design_facts(content)(view, auth),
        _rules(content.design_rules),
        content.work_language,
    )
    mine = [f for f in findings if f["step_id"] == step]
    fired = {_rule_id(f, f["input_ref"]) for f in mine if f["finding"] in {"violation", "improve"}}
    unknown = {_rule_id(f, f["input_ref"]) for f in mine if f["finding"] == "unknown"}
    return [f for f in mine if f["finding"] in {"violation", "improve"}], fired, unknown


def _coverage(view, auth, content, design, step, fired, unknown, rubric_items):
    language = content.work_language
    refs = (design or {}).get("section_refs", {}).get(step, ())
    cited = {r["object_id"] for r in refs if r.get("kind") == "material"}
    marks = []
    for rule in content.coverage_rules:
        if rule.step_id != step:
            continue
        predicate, mark, source = rule.predicate, "to_check", "model_suggestion"
        if rule.check == "choice":
            source = "choice"
            value = _field(design or {}, predicate.get("field", ""))
            if value in (None, "", [], (), "unknown"):
                mark = "missing"
            elif value in predicate.get("conflicts_with", ()):
                mark = "wrong"
            else:
                mark = "covered"
        elif rule.check == "citation":
            source = "citation"
            mark = "covered" if cited & set(predicate.get("materials", ())) else "missing"
        elif rule.check == "rule":
            source = "rule"
            name = predicate.get("rule")
            mark = "wrong" if name in fired else "to_check" if name in unknown else "covered"
        elif rule.check == "rubric_rule":
            source = "rubric_rule"
            item = rubric_items.get(predicate.get("criterion"))
            if item is None or item.source != "verified_rule":
                mark = "to_check"
            elif item.label == "MET":
                mark = "covered"
            elif item.label in {"NOT_MET", "PARTIAL"}:
                mark = "missing"
            else:
                mark = "to_check"
        elif rule.check == "self":
            source = "learner_assessment"
        found = [r for m in rule.look_again_materials if (r := material_ref(view, auth, m))]
        marks.append(
            CoverageMark(
                id=rule.id,
                label=rule.label[language],
                check=rule.check,
                severity=rule.severity,
                mark=mark,
                # Only where to look again; covered items need no pointer.
                pointer=None
                if mark == "covered"
                else Pointer(text=rule.look_again[language], refs=tuple(found)),
                owner=rule.owner,
                source=source,
            )
        )
    marks.sort(key=lambda m: (MARK[m.mark], SEVERITY[m.severity], m.id))
    return tuple(marks)


def _rubric(content, step, rule_check):
    wanted = STEP_CRITERIA[step]
    if not wanted:
        return (), {}
    language = content.work_language
    if rule_check is None:
        hint = text(
            language,
            "到「上线决策」选一个拟定决定后，可以核对这一项。",
            "Pick an intended decision on the launch-decision sheet to check this item.",
        )
        return tuple(
            RubricLine(criterion=c, label="PENDING", source="pending", explanation=hint)
            for c in wanted
        ), {}
    items = {item.criterion: item for item in rule_check.rule_items}
    pending = text(language, "交付时由正式反馈判断。", "Judged by formal feedback at delivery.")
    lines = []
    for criterion in wanted:
        item = items.get(criterion)
        if item is None:
            continue
        verified = item.source == "verified_rule"
        lines.append(
            RubricLine(
                criterion=criterion,
                label=item.label if verified else "PENDING",
                source="verified_rule" if verified else "pending",
                explanation=item.explanation if verified else pending,
                citations=item.citations if verified else (),
            )
        )
    return tuple(lines), items


def _mentor(view, auth, content, step, fired, coverage):
    marks = {m.id: m.mark for m in coverage}
    prompts = []
    for rule in content.mentor_rules:
        if rule.step_id != step:
            continue
        hit = next((r for r in rule.when_rule if r in fired), None)
        if hit is None:
            hit = next((i for i, want in rule.when_coverage.items() if marks.get(i) in want), None)
        if hit is None:
            continue
        found = [r for m in rule.materials if (r := material_ref(view, auth, m))]
        prompts.append(
            MentorPrompt(
                colleague=rule.colleague,
                question=rule.question[content.work_language],
                pointer=Pointer(text="", refs=tuple(found)) if found else None,
                trigger_id=hit,
            )
        )
    return tuple(prompts)


def _status(coverage, misconceptions):
    if misconceptions or any(m.mark == "wrong" for m in coverage):
        return "draft"
    cited = any(m.check == "citation" and m.mark == "covered" for m in coverage)
    if not cited or any(m.mark == "missing" and m.severity == "high" for m in coverage):
        return "draft"
    if any(m.mark == "missing" and m.severity == "medium" for m in coverage):
        return "based"
    return "solid"


def counts(review):
    coverage = review.get("coverage") or ()
    return (
        sum(1 for m in coverage if m["check"] == "citation" and m["mark"] == "covered"),
        sum(1 for m in coverage if m["mark"] == "missing"),
        sum(1 for m in coverage if m["mark"] == "wrong") + len(review.get("misconceptions") or ()),
    )


def _basis(view, content, step, design, coverage_rules, mentor_rules):
    """Exact versions this review depended on, for later staleness."""
    materials = set()
    for ref in (design or {}).get("section_refs", {}).get(step, ()):
        if ref.get("kind") == "material":
            materials.add(ref["object_id"])
    for rule in coverage_rules:
        if rule.step_id == step:
            materials.update(rule.look_again_materials)
            materials.update(rule.predicate.get("materials", ()))
    for rule in mentor_rules:
        if rule.step_id == step:
            materials.update(rule.materials)
    materials.update((content.design_public or {}).get("source_requirements", {}).values())
    private = view.private_scenario_state
    basis = {"content_revision": content.content_revision}
    for material in sorted(materials):
        version = private.source_versions.get(material) if private else None
        if version is not None:
            basis["material:" + material] = str(version)
    return basis


def reviews_of(objects, step=None):
    rows = [r for r in heads(objects).values() if r.ref.kind == KIND]
    if step is not None:
        rows = [r for r in rows if r.content["step_id"] == step]
    rows.sort(key=lambda r: (r.created_storage_revision, r.ref.object_id), reverse=True)
    return rows


def stale(view, review, latest):
    """Why a stored review no longer matches the current inputs, if it does not."""
    private = view.private_scenario_state
    for key, version in sorted(review.get("basis", {}).items()):
        if not key.startswith("material:") or private is None:
            continue
        material = key.removeprefix("material:")
        current = private.source_versions.get(material)
        if current is not None and str(current) != version:
            reason = "policy_changed" if material in POLICY_MATERIALS else "source_changed"
            return ReviewStale(reason=reason, detail=f"{material} v{version} -> v{current}")
    prd = review["prd_ref"]
    head = latest.get(("product", prd["object_id"]))
    if head is not None and head.ref.version > prd["version"]:
        return ReviewStale(reason="edited", detail=f"v{prd['version']} -> v{head.ref.version}")
    return None


def create(view, auth, content, body: SectionReviewInput, rule_check, registry=None):
    step = body.step_id
    prd = view.get(body.prd_ref)  # exact visible version
    if prd.ref.kind != "product":
        raise C.ProtocolError("aipm_prd_product_required")
    design_row = view.get(body.design_ref) if body.design_ref is not None else None
    if design_row is not None and design_row.ref.kind != "aipm_design":
        raise C.ProtocolError("aipm_design_required")
    design = design_row.content if design_row else None
    decision = (design or {}).get("intended_decision")
    if rule_check is not None:
        if rule_check.as_of != point(view.state) or rule_check.decision != decision:
            raise C.ProtocolError("aipm_review_window_changed", status=409)
    basis = _basis(view, content, step, design, content.coverage_rules, content.mentor_rules)
    identity = C.digest(
        [
            "aipm-section-review-v1",
            step,
            prd.ref.model_dump(mode="json"),
            design_row.ref.model_dump(mode="json") if design_row else None,
            decision,
            basis,
            content.coverage_revision,
            content.mentor_revision,
        ]
    )[:32]
    latest = heads(view.objects)
    existing = latest.get((KIND, "review-" + identity))
    if existing is not None:
        return Mutation(
            result={"ref": existing.ref.model_dump(mode="json"), "review": existing.content}
        )
    misconceptions, fired, unknown = _design_findings(view, auth, content, design_row, step)
    rubric, items = _rubric(content, step, rule_check)
    coverage = _coverage(view, auth, content, design, step, fired, unknown, items)
    feedback = tuple(ProcessFeedback.model_validate(f) for f in misconceptions)
    previous = next(iter(reviews_of(view.objects, step)), None)
    review = SectionReview(
        id="review-" + identity,
        session_id=auth.session_id,
        step_id=step,
        prd_ref=prd.ref,
        design_ref=design_row.ref if design_row else None,
        as_of=point(view.state),
        created_at=datetime.now(UTC),
        status=_status(coverage, feedback),
        previous_review_ref=previous.ref if previous else None,
        misconceptions=feedback,
        coverage=coverage,
        rubric=rubric,
        mentor_prompts=_mentor(view, auth, content, step, fired, coverage),
        decision_used=decision if rule_check is not None else None,
        basis=basis,
    )
    stored = review.model_dump(mode="json")
    if previous is not None:
        before, after = counts(previous.content), counts(stored)
        stored["delta"] = ReviewDelta(
            citations=(before[0], after[0]), gaps=(before[1], after[1]), wrong=(before[2], after[2])
        ).model_dump(mode="json")
    ref = C.ObjectRef(session_id=auth.session_id, kind=KIND, object_id=review.id, version=1)
    write = ObjectWrite(
        ref=ref,
        expected_head=0,
        content=stored,
        visible_to=("learner",),
        dependencies=references(stored),
    )
    return Mutation(writes=(write,), result={"ref": ref.model_dump(mode="json"), "review": stored})


def page(view, auth, step=None, cursor=0, limit=10):
    from .projection import scoped

    objects = scoped(view, auth)
    latest = heads(objects)
    rows = reviews_of(objects, step)
    items = []
    for row in rows[cursor : cursor + limit]:
        current = stale(view, row.content, latest)
        review = dict(row.content, stale=current.model_dump(mode="json") if current else None)
        items.append({"ref": row.ref.model_dump(mode="json"), "review": review})
    more = cursor + limit < len(rows)
    return {"items": items, "next_cursor": cursor + limit if more else None}


def prd_ref(latest, design):
    """The pilot PRD: the latest visible version of the product the latest design names."""
    named = (design or {}).get("prd_ref")
    if not named:
        return None
    head = latest.get(("product", named["object_id"]))
    return head.ref if head is not None else None


def sheets(view, objects, design, pending_steps):
    """Sheet state per step from the latest review against the current PRD."""
    latest = heads(objects)
    prd = prd_ref(latest, design)
    sections = {}
    if prd is not None:
        payload = latest[("product", prd.object_id)].content.get("structured_payload") or {}
        sections = payload.get("sections") or {}
    result = {}
    for step in STEP_IDS:
        row = next(iter(reviews_of(objects, step)), None)
        written = bool(str(sections.get(step, "")).strip())
        state = {
            "status": "draft" if written else "not_started",
            "prd_version": prd.version if prd else None,
            "agent_draft_pending": step in pending_steps,
        }
        if row is not None:
            review = row.content
            current = stale(view, review, latest)
            worst = next(
                (m["message"] for m in review.get("misconceptions") or ()),
                next(
                    (m["label"] for m in review.get("coverage") or () if m["mark"] != "covered"),
                    None,
                ),
            )
            state.update(review_ref=row.ref, gap_hint=worst)
            if current is not None and current.reason != "edited":
                state.update(status="recheck", recheck_reason=current.reason)
            elif current is not None:
                state.update(status="draft", edited_since_review=True)
            else:
                state.update(status=review["status"])
        result[step] = SheetState(**state)
    return result, prd
