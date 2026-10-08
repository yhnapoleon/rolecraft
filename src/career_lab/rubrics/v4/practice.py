"""Pure optional next-practice selection; W14 owns authorization and new sessions.

Inputs are an authorized FeedbackV2 projection and a trusted independently
reviewed W02 catalog. This module neither approves variants nor creates sessions.
"""

from dataclasses import dataclass
from career_lab.contracts import v2 as C


@dataclass(frozen=True)
class ReviewedPractice:
    id: str
    title_zh: str
    title_en: str
    work_language: str
    bindings: C.SessionBindings
    criteria: tuple[str, ...]
    review_status: str
    review: C.FileRef | None
    component_id: str


def suggestions(auth, feedback_ref, feedback, catalog, *, work_language):
    """Caller reauthorizes feedback/candidates before each display and choice."""
    if work_language not in {"zh", "en"}:
        raise ValueError("fixed language required")
    if (
        feedback_ref.kind != "feedback"
        or feedback_ref.session_id != auth.session_id
        or feedback.session_id != auth.session_id
        or feedback_ref.object_id != feedback.id
        or feedback_ref.version != 1
    ):
        raise C.ProtocolError("practice_feedback_scope_mismatch", status=404)
    source_hash = C.digest(feedback)
    english = work_language == "en"
    options = []
    findings = {}
    for item in feedback.rule_items or feedback.items:
        if item.applicability != "applicable":
            continue
        if (
            item.source == "verified_rule"
            and item.rule_bound
            and item.citations
            and (item.rule_bound.upper != "MET" or item.rule_bound.lower != item.rule_bound.upper)
        ):
            findings[item.criterion] = ("rule_followup", item)
        elif item.source == "pending" and item.label == "INSUFFICIENT":
            findings[item.criterion] = ("pending_verification", item)
    seen = set()
    for option in catalog:
        if option.id in seen:
            raise C.ProtocolError("duplicate_practice_option")
        seen.add(option.id)
        if (
            option.work_language != work_language
            or option.review_status != "approved"
            or option.review is None
        ):
            continue
        matches = [(cid, *findings[cid]) for cid in option.criteria if cid in findings]
        if not matches:
            continue
        reason_code = (
            "rule_followup"
            if any(code == "rule_followup" for _, code, _ in matches)
            else "pending_verification"
        )
        explanation = (
            (
                "This optional scenario lets you revisit a recorded rule finding under changed conditions."
                if reason_code == "rule_followup"
                else "This optional scenario gives you another opportunity to collect evidence for an unresolved feedback item."
            )
            if english
            else (
                "可以在变化后的条件中，再核对这轮已有的规则发现。"
                if reason_code == "rule_followup"
                else "可以换一个情境，为这轮尚待核验的事项补充可观察记录。"
            )
        )
        identity = {
            "id": option.id,
            "bindings": option.bindings.model_dump(mode="json"),
            "work_language": option.work_language,
            "review": option.review.model_dump(mode="json"),
            "component_id": option.component_id,
        }
        options.append(
            {
                **identity,
                "candidate_hash": C.digest(identity),
                "title": option.title_en if english else option.title_zh,
                "reason_code": reason_code,
                "reason": explanation,
                "basis": [
                    {
                        "criterion": cid,
                        "explanation": item.explanation,
                        "source": item.source,
                        "citations": [r.model_dump(mode="json") for r in item.citations],
                    }
                    for cid, _, item in matches
                ],
            }
        )
    data = {
        "source_feedback": feedback_ref.model_dump(mode="json"),
        "source_feedback_hash": source_hash,
        "work_language": work_language,
        "options": options,
        "can_decline": True,
        "can_choose_other": True,
        "learning_gain": "not_established",
        "note": (
            "You may decline, choose another reviewed scenario, or continue revising. Any new feedback must use the new actions and evidence; no learning gain is assumed."
            if english
            else "可以拒绝、自选其他已审核情境，或继续原修订。下一轮反馈只依据新行动和证据，不预先认定已有学习收益。"
        ),
    }
    return {**data, "suggestion_hash": C.digest(data)}


def selection_plan(auth, feedback_ref, feedback, catalog, shown, *, choice, option_id=None):
    """Validate an explicit choice against fresh authorized inputs; no mutation.

    W14 must atomically create the new session and persist this source/target
    relation. Calling this function or accepting a choice is not session creation.
    """
    fresh = suggestions(auth, feedback_ref, feedback, catalog, work_language=shown["work_language"])
    if (
        fresh["source_feedback"] != shown["source_feedback"]
        or fresh["source_feedback_hash"] != shown["source_feedback_hash"]
    ):
        raise C.ProtocolError("practice_feedback_changed", status=409)
    if choice == "choose" and fresh["suggestion_hash"] != shown["suggestion_hash"]:
        raise C.ProtocolError("practice_suggestion_changed", status=409)
    if choice not in {"decline", "continue_revision", "choose"}:
        raise C.ProtocolError("explicit_practice_choice_required")
    target = None
    if choice == "choose":
        target = next((x for x in fresh["options"] if x["id"] == option_id), None)
        if target is None:
            raise C.ProtocolError("reviewed_practice_option_required")
    elif option_id is not None:
        raise C.ProtocolError("unexpected_practice_option")
    return {
        "source_feedback": fresh["source_feedback"],
        "source_feedback_hash": fresh["source_feedback_hash"],
        "suggestion_hash": shown["suggestion_hash"],
        "choice": choice,
        "target": target,
        "creates_session": False,
        "new_session_id": None,
        "help_source": "optional_feedback_suggestion",
        "learning_gain": "not_established",
    }
