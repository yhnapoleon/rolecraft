"""Controlled catalog tests, not independent approval of actual W02 variants."""

from dataclasses import replace
import pytest
from career_lab.contracts import v2 as C
from career_lab.rubrics.v4.practice import ReviewedPractice, suggestions, selection_plan


def fixture(language="zh"):
    auth = C.AuthContext(
        session_id="s",
        actor_id="learner",
        executor=C.Executor(id="human", kind="human"),
        credential_id="controlled",
        capabilities=("read",),
    )
    ref = C.ObjectRef(session_id="s", kind="feedback", object_id="f", version=1)
    source = C.EvidenceRefV2(
        session_id="s", kind="test", object_id="t", version=1, observed_at_seq=0
    )
    item = C.FeedbackItem(
        criterion="R4.staleness_test",
        label="PARTIAL",
        applicability="applicable",
        source="verified_rule",
        explanation="Observed an older version.",
        citations=(source,),
        rule_bound=C.RuleBound(lower="PARTIAL", upper="PARTIAL"),
    )
    file = C.FileRef(path="controlled.json", sha256="1" * 64)
    feedback = C.FeedbackV2(
        id="f",
        session_id="s",
        subject=C.ObjectRef(session_id="s", kind="submission", object_id="s1", version=1),
        evaluation=file,
        as_of=C.VersionPoint(business_seq=0, workspace_revision=0, storage_revision=0),
        items=(item,),
        rule_items=(item,),
        business_response="",
        next_options=(),
        verified_coverage=1,
        model_coverage=0,
        mode="advisory",
    )
    option = ReviewedPractice(
        "capacity15",
        "更紧的容量",
        "Tighter capacity",
        language,
        C.SessionBindings(scenario=file, runtime=file, evaluation=file),
        ("R4.staleness_test",),
        "approved",
        file,
        "same-family",
    )
    return auth, ref, feedback, option


@pytest.mark.parametrize("language", ["zh", "en"])
def test_optional_suggestion_is_grounded_without_learning_claim(language):
    auth, ref, feedback, option = fixture(language)
    before = C.digest(feedback)
    shown = suggestions(auth, ref, feedback, (option,), work_language=language)
    assert len(shown["options"]) == 1 and shown["options"][0]["basis"][0]["citations"]
    assert shown["can_decline"] and shown["learning_gain"] == "not_established"
    for choice in ("decline", "continue_revision", "choose"):
        plan = selection_plan(
            auth,
            ref,
            feedback,
            (option,),
            shown,
            choice=choice,
            option_id=option.id if choice == "choose" else None,
        )
        assert (
            not plan["creates_session"]
            and plan["new_session_id"] is None
            and plan["choice"] == choice
        )
    assert C.digest(feedback) == before


@pytest.mark.parametrize(
    "kind",
    [
        "pending_review",
        "missing_review",
        "other_language",
        "not_applicable",
        "model_advice",
        "complete_met",
    ],
)
def test_unreviewed_or_unobserved_basis_never_becomes_a_recommendation(kind):
    auth, ref, feedback, option = fixture()
    if kind == "pending_review":
        option = replace(option, review_status="pending")
    elif kind == "missing_review":
        option = replace(option, review=None)
    elif kind == "other_language":
        option = replace(option, work_language="en")
    else:
        item = feedback.rule_items[0]
        updates = {
            "not_applicable": {
                "label": "NOT_APPLICABLE",
                "applicability": "not_applicable",
                "rule_bound": None,
            },
            "model_advice": {"source": "model_advice", "rule_bound": None},
            "complete_met": {"label": "MET", "rule_bound": C.RuleBound(lower="MET", upper="MET")},
        }[kind]
        item = C.FeedbackItem.model_validate(item.model_dump(mode="json") | updates)
        feedback = feedback.model_copy(update={"items": (item,), "rule_items": (item,)})
    assert suggestions(auth, ref, feedback, (option,), work_language="zh")["options"] == []


def test_pending_is_an_unresolved_item_not_a_skill_deficit():
    auth, ref, feedback, option = fixture()
    item = feedback.items[0].model_copy(
        update={"label": "INSUFFICIENT", "source": "pending", "rule_bound": None, "citations": ()}
    )
    feedback = feedback.model_copy(update={"items": (item,), "rule_items": (item,)})
    shown = suggestions(auth, ref, feedback, (option,), work_language="en")
    assert shown["options"] == []
    shown = suggestions(auth, ref, feedback, (option,), work_language="zh")
    assert shown["options"][0]["reason_code"] == "pending_verification"


def test_choice_rechecks_feedback_and_reviewed_candidate_identity():
    auth, ref, feedback, option = fixture()
    shown = suggestions(auth, ref, feedback, (option,), work_language="zh")
    changed = replace(option, review=C.FileRef(path="review2.json", sha256="2" * 64))
    with pytest.raises(C.ProtocolError):
        selection_plan(auth, ref, feedback, (changed,), shown, choice="choose", option_id=option.id)
    with pytest.raises(C.ProtocolError):
        suggestions(
            auth.model_copy(update={"session_id": "other"}),
            ref,
            feedback,
            (option,),
            work_language="zh",
        )


def test_declining_remains_possible_when_a_candidate_is_withdrawn():
    auth, ref, feedback, option = fixture()
    shown = suggestions(auth, ref, feedback, (option,), work_language="zh")
    withdrawn = replace(option, review_status="withdrawn")
    plan = selection_plan(auth, ref, feedback, (withdrawn,), shown, choice="decline")
    assert plan["target"] is None and plan["suggestion_hash"] == shown["suggestion_hash"]
