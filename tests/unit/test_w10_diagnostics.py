"""Diagnostic facts are not ability judgements; synthetic event records."""
from dataclasses import replace
import pytest
from career_lab.contracts.v2 import EvidenceRefV2, ProtocolError
from career_lab.diagnostics.v2.events import DiagnosticEvent, VersionChange, diagnose


def evidence(seq=1, version=1):
    return EvidenceRefV2(session_id="s",kind="document",object_id="faq",version=version,observed_at_seq=seq)


def event(seq, **changes):
    value=DiagnosticEvent(id=f"e{seq}",seq=seq,session_id="s",actor_id="learner",
        operation="test_assistant",visible_to=("learner",),outcome="success",
        evidence=(evidence(seq),),input_hash="input",visible_state_hash="state",purpose="stability")
    return replace(value,**changes)


def test_stability_repeat_is_factual_without_negative_score():
    rows=diagnose([event(1),event(2)],session_id="s",viewer_id="learner")
    assert len(rows)==1 and rows[0].kind=="repeated_input"
    assert rows[0].ability_score is None and rows[0].suggested_intervention is None
    assert "稳定性" in rows[0].uncertainty
    assert rows[0].event_ids==("e1","e2")


@pytest.mark.parametrize("changed", [{"input_hash":"different"},{"visible_state_hash":"new-state"},{"actor_id":"helper"},{"input_hash":None}])
def test_repeat_requires_same_observed_conditions(changed):
    assert diagnose([event(1),event(2,**changed)],session_id="s",viewer_id="learner")==()


@pytest.mark.parametrize("origin",["input","system","unknown"])
def test_repeated_failure_preserves_actual_origin(origin):
    events=[event(i,operation="save",outcome="failed",error_code="failure",error_origin=origin) for i in range(1,4)]
    rows=diagnose(events,session_id="s",viewer_id="learner")
    assert len(rows)==1 and rows[0].kind=="repeated_failure"
    assert origin in rows[0].observation and rows[0].ability_score is None


def test_hidden_prompt_or_private_events_cannot_establish_learner_knowledge():
    hidden=event(1,operation="prompt",visible_to=("tech",))
    change=VersionChange(object_id="faq",kind="document",version=2,seq=1,
                         source=evidence(1,2),visible_to=("tech",))
    assert diagnose([hidden,event(2)],session_id="s",viewer_id="learner",changes=[change])==()


def test_old_reference_is_not_automatically_invalidated():
    change=VersionChange(object_id="faq",kind="document",version=2,seq=2,
                         source=evidence(2,2),visible_to=("learner",))
    rows=diagnose([event(3)],session_id="s",viewer_id="learner",changes=[change])
    assert rows[0].kind=="older_evidence_version" and "历史比较" in rows[0].uncertainty
    assert rows[0].ability_score is None


@pytest.mark.parametrize("purpose",["no_go","defer_with_conditions","exploration"])
def test_submission_purpose_never_creates_mechanical_early_failure(purpose):
    assert diagnose([event(1,operation="submit",purpose=purpose)],session_id="s",viewer_id="learner")==()


def test_missing_logs_not_equivalent_to_inaction():
    rows=diagnose([event(1)],session_id="s",viewer_id="learner",logs_complete=False)
    assert rows[0].kind=="incomplete_trace" and "用户未行动" in rows[0].uncertainty


@pytest.mark.parametrize("events", [[event(2),event(1)],[event(1),event(1)],[event(1,session_id="other")]])
def test_bad_trace_identity_or_order_rejected(events):
    with pytest.raises(ProtocolError):
        diagnose(events,session_id="s",viewer_id="learner")


def test_future_evidence_is_not_used():
    change=VersionChange(object_id="faq",kind="document",version=2,seq=1,
                         source=evidence(99,2),visible_to=("learner",))
    with pytest.raises(ProtocolError):
        diagnose([event(2)],session_id="s",viewer_id="learner",changes=[change])
