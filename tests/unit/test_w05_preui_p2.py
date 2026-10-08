"""Exact-source dedup and truthful hints; no model quality assertion."""

from copy import deepcopy
from test_w05_default_facts import history_payload, default_review, duty, point
from career_lab.evidence.v2.history import unique_sources
from career_lab.contracts import v2 as C
from career_lab.api.reviews_v2 import create_review_evaluator


def test_history_source_dedup_preserves_versions_spans_and_separate_actions(tmp_path):
    ref = C.EvidenceRefV2(
        session_id="s",
        kind="material",
        object_id="m",
        version=1,
        observed_at_seq=1,
        quote="a",
        span_start=0,
        span_end=1,
    ).model_dump(mode="json")
    later = {**ref, "version": 2}
    other = {**ref, "quote": "b", "span_start": 2, "span_end": 3}
    assert unique_sources([ref, deepcopy(ref), later, other, deepcopy(later)]) == [
        ref,
        later,
        other,
    ]
    raw = history_payload()
    a = duty(raw, "actual_action", facts={"actual_participants": 20, "capacity_at_action": 30})
    b = duty(raw, "actual_action", facts={"actual_participants": 25, "capacity_at_action": 30})
    a["sources"] *= 3
    raw["rule_snapshots"][0]["responsibilities"] = [a, b]
    result, _, _, _ = default_review(tmp_path, raw, decision="no_go")
    history = result["feedback"]["historical_responsibilities"][0]["entries"]
    assert len(history) == 2 and all(len(h["sources"]) == 1 for h in history)
    assert history[0]["sources"] != history[1]["sources"]


def test_hints_distinguish_unknown_purpose_missing_decision_and_declared_decision(tmp_path):
    unknown, _, _, _ = default_review(
        tmp_path, history_payload(), purpose="unspecified-purpose", name="purpose"
    )
    undecided, _, _, _ = default_review(
        tmp_path, history_payload(), purpose="commitment", name="decision"
    )
    declared, _, _, _ = default_review(
        tmp_path, history_payload(), purpose="commitment", decision="launch", name="declared"
    )
    assert any("作品用途尚未明确" in s for s in unknown["feedback"]["next_options"])
    assert any(
        "作品用途已记录，本次决定尚未声明" in s for s in undecided["feedback"]["next_options"]
    )
    assert not any("作品用途尚未明确" in s for s in undecided["feedback"]["next_options"])
    assert any(
        "你的决定声明已记录；审批与执行不会由声明自动确认" in s
        for s in declared["feedback"]["next_options"]
    )
    assert undecided["verified_facts"]["section"] == "verified_facts"


def test_followup_link_does_not_admit_supplement_quotes_or_resolve_objection(tmp_path):
    _, reader, auth, p = default_review(tmp_path, history_payload())
    prior = C.ObjectRef(
        session_id="s", kind="feedback_response", object_id="supplement-not-reverified", version=1
    )
    request = C.ReviewRequest(
        id="followup",
        session_id="s",
        subjects=(p,),
        purpose="result",
        as_of=point(5),
        scope=(),
        evaluation=reader.evaluation,
        executor=auth.executor,
        decision=None,
        followup_of=(prior,),
    )
    result = create_review_evaluator(reader).handle(auth, request, point(5))
    assert (
        result["followup_status"] == "linked_not_resolved"
        and result["followup_evidence_status"] == "not_evaluated"
    )
    assert result["reviews"][0]["verified_facts"]["declared_source_count"] == 1
    assert any("引文默认未核实" in s for s in result["reviews"][0]["feedback"]["next_options"])
