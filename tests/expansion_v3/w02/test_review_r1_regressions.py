"""Regression cases for coordinator findings W02-R1/R2/R3."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import pytest

from career_lab.contracts.v2.core import ObjectRef, ProtocolError
from career_lab.contracts.v2.world import TestRequestV2 as AssistantTestRequest
from career_lab.assistant.v2 import Assistant, RetrievalTuning
from .conftest import auth, command, apply
from .test_engine import approve


def resolve(engine, transition, key="resolve"):
    req = transition.result
    ref = ObjectRef(session_id=req.session_id, kind="business_request", object_id=req.id, version=req.version)
    return engine.plan(transition.snapshot,
        command(transition.snapshot, "resolve_approval", key,
                request=ref.model_dump(mode="json"), expected_request_revision=req.version),
        auth(req.session_id, actor="supervisor", capabilities=("approve",)))


@pytest.mark.parametrize("objects", [(), ("faq",), ("faq", "pilot")])
def test_limited_refresh_cannot_change_ungranted_policy(engine, objects):
    s = apply(engine, engine.initial("session")).snapshot
    before = deepcopy(s)
    assert s.source_versions["policy"] == 2 and s.indexed_versions["policy"] == 1
    with pytest.raises(ProtocolError) as error:
        engine.plan(s, command(s, "refresh_index", "restricted"), auth(objects=objects))
    assert error.value.code == "object_forbidden" and error.value.status == 403
    assert s == before


@pytest.mark.parametrize("tool,payload", [
    ("request_business", {"terms":{"dev_days":6}, "reason":"more"}),
    ("pause", {}),
    ("apply_config", None),
])
def test_object_grants_do_not_authorize_session_mutations(engine, tool, payload):
    s = engine.initial("session")
    if payload is None:
        cfg = s.config.model_copy(update={"version":2, "config_version":1})
        payload = {"config":cfg.model_dump(mode="json")}
    with pytest.raises(ProtocolError, match="object forbidden"):
        engine.plan(s, command(s, tool, "limited", **payload), auth(objects=("pilot","faq")))
    assert s.world.business_seq == 0 and s.source_versions["policy"] == 1


def test_scoped_system_decider_cannot_grant_session_resources(engine):
    s = apply(engine, engine.initial("session"), participants=50).snapshot
    request = engine.plan(s, command(s,"request_business","r",terms={"capacity":60},reason="scope"),auth())
    ref = ObjectRef(session_id="session",kind="business_request",object_id=request.result.id,version=1)
    decider = auth(actor="supervisor",capabilities=("approve",),objects=(ref.object_id,))
    with pytest.raises(ProtocolError,match="object forbidden"):
        engine.plan(request.snapshot, command(request.snapshot,"resolve_approval","a",
            request=ref.model_dump(mode="json"),expected_request_revision=1),decider)


def test_event_projection_preserves_full_auth_scope(engine):
    t = apply(engine,engine.initial("session"))
    refreshed = engine.plan(t.snapshot,command(t.snapshot,"refresh_index","r"),auth())
    event = refreshed.events[0]
    assert engine.public_event(event,refreshed.snapshot,auth(objects=("faq",))) is None
    scoped = engine.public_event(event,refreshed.snapshot,auth(objects=("policy",)))
    assert scoped["payload"] == {"before_versions":{"policy":1}, "after_versions":{"policy":2}}
    assert "tech_private" not in str(scoped) and "brief" not in str(scoped)
    config_event = t.events[0]
    assert engine.public_event(config_event,t.snapshot,auth(objects=("faq",))) is None
    assert engine.public_event(config_event,t.snapshot,auth(objects=("pilot",)))["payload"]["config_id"] == "pilot"
    assert engine.public_event(config_event,t.snapshot,auth(actor="tech_lead")) is None


def test_event_projection_rejects_wrong_expired_and_missing_read_authority(engine):
    t = apply(engine,engine.initial("session"))
    for caller in [
        auth("foreign"),
        auth(capabilities=("act",)),
        auth().model_copy(update={"expires_at":datetime.now(timezone.utc)-timedelta(seconds=1)}),
        "learner",
    ]:
        with pytest.raises(ProtocolError):
            engine.public_event(t.events[-1],t.snapshot,caller)
    foreign = {**t.events[-1],"session_id":"foreign"}
    with pytest.raises(ProtocolError,match="event session mismatch"):
        engine.public_event(foreign,t.snapshot,auth())
    with pytest.raises(ProtocolError,match="event unavailable"):
        engine.public_event(t.events[-1],engine.initial("session"),auth())


def test_scoped_test_requires_config_read_grant(package,engine):
    s = engine.initial("session")
    request = AssistantTestRequest(query="会议室预约",config_version=0)
    with pytest.raises(ProtocolError) as denied:
        Assistant(package).run(s,request,auth(objects=("faq",)),"t")
    assert denied.value.code == "config_forbidden"
    allowed = Assistant(package).run(s,request,auth(objects=("faq","pilot")),"t")
    assert allowed.result.status == "answered"
    assert {ref.object_id for ref in allowed.result.citations} == {"faq"}
    assert allowed.provenance["source_versions"] == {"faq":1}
    assert allowed.provenance["indexed_versions"] == {"faq":1}
    assert allowed.result.config.requested.id == "pilot"
    with pytest.raises(ProtocolError,match="action forbidden"):
        Assistant(package).run(s,request,auth(capabilities=("act",)),"t")
    whole = Assistant(package).run(s,request,auth(),"t")
    assert whole.result.id != allowed.result.id


@pytest.mark.parametrize("terms", [
    {"dev_days":6}, {"deadline_day":10}, {"capacity":60},
    {"dev_days":6,"deadline_day":10},
])
def test_unnecessary_requests_rejected_with_optional_empty_evidence(engine,terms):
    s = engine.initial("session")
    result = approve(engine,s,terms)
    assert result.result.status == "rejected"
    assert result.result.reason_code == "request_not_needed"
    assert result.snapshot.world.resources == s.world.resources
    assert result.result.evidence_refs == ()


@pytest.mark.parametrize("config,terms", [
    ({"update_strategy":"realtime","work_items":("realtime_sync","human_fallback")},{"dev_days":6}),
    ({"launch_day":10},{"deadline_day":10}),
    ({"participants":50},{"capacity":60}),
    ({"update_strategy":"realtime","work_items":("realtime_sync","human_fallback"),"launch_day":10},
     {"dev_days":6,"deadline_day":10}),
])
def test_real_per_resource_shortfalls_are_approved(engine,config,terms):
    s = apply(engine,engine.initial("session"),**config).snapshot
    result = approve(engine,s,terms)
    assert result.result.status == "approved"
    assert result.result.granted == terms
    assert not result.result.evidence_refs


@pytest.mark.parametrize("config,terms,necessary", [
    ({"launch_day":10},{"dev_days":6,"deadline_day":10},{"deadline_day":10}),
    ({"participants":50},{"capacity":60,"dev_days":6},{"capacity":60}),
    ({"update_strategy":"realtime","work_items":("realtime_sync","human_fallback")},
     {"dev_days":6,"deadline_day":10},{"dev_days":6}),
])
def test_mixed_unnecessary_terms_reject_atomically_then_allow_revised_request(engine,config,terms,necessary):
    s = apply(engine,engine.initial("session"),**config).snapshot
    denied = approve(engine,s,terms)
    assert denied.result.status == "rejected"
    assert denied.snapshot.world.resources == s.world.resources
    fixed = approve(engine,denied.snapshot,necessary,key="necessary-only")
    assert fixed.result.status == "approved" and fixed.result.granted == necessary


def test_proposal_can_request_resources_before_applying_configuration(engine,package):
    s = engine.initial("session")
    proposed = s.config.model_copy(update={"version":2,"config_version":1,"update_strategy":"realtime",
        "work_items":("realtime_sync","human_fallback"),"launch_day":10})
    request = engine.plan(s,command(s,"request_business","proposal",
        config=proposed.model_dump(mode="json"),terms={"dev_days":6,"deadline_day":10},
        reason="先申请同步与人工接管资源，再决定应用方案"),auth())
    assert request.snapshot.config == s.config
    assert "initial_plan_applied" not in request.snapshot.world.applied_milestones and request.snapshot.source_versions["policy"] == 1
    assert request.snapshot.request_targets[request.result.id] == proposed
    granted = resolve(engine,request)
    assert granted.result.status == "approved"
    assert granted.snapshot.config.config_version == 0
    assert granted.snapshot.source_versions["policy"] == 1
    applied = engine.plan(granted.snapshot,command(granted.snapshot,"apply_config","apply",
        config=proposed.model_dump(mode="json")),auth())
    result = Assistant(package).run(applied.snapshot,
        AssistantTestRequest(query="住宿报销上限",config_version=1),auth(),"after")
    assert result.result.config.effective.update_strategy == "realtime"
    assert "400" in result.result.answer


def test_request_basis_is_pinned_and_reasons_do_not_invent_resource_need(engine):
    s = apply(engine,engine.initial("session"),launch_day=10).snapshot
    request = engine.plan(s,command(s,"request_business","r",terms={"deadline_day":10},reason="计划需要延期"),auth())
    changed = apply(engine,request.snapshot,launch_day=7).snapshot
    from dataclasses import replace
    result = resolve(engine,replace(request,snapshot=changed))
    assert result.result.status == "approved"
    assert result.snapshot.request_targets[request.result.id].launch_day == 10
    # Conversely, natural-language assertion alone does not create a shortfall.
    initial = engine.initial("session")
    claim = engine.plan(initial,command(initial,"request_business","claim",
        terms={"dev_days":6},reason="我说需要六人日"),auth())
    assert resolve(engine,claim).result.reason_code == "request_not_needed"


@pytest.mark.parametrize("changes", [{"session_id":"foreign"},{"id":"different"},{"version":99},{"work_items":("magic",)}])
def test_invalid_proposed_basis_is_rejected_without_applying(engine,changes):
    s = engine.initial("session")
    proposed = s.config.model_copy(update={"version":2,"config_version":1,**changes})
    with pytest.raises(ProtocolError):
        engine.plan(s,command(s,"request_business","bad",config=proposed.model_dump(mode="json"),
            terms={"dev_days":6},reason="proposal"),auth())
    assert not s.requests and s.world.business_seq == 0


@pytest.mark.parametrize("guard,status,code,warning,has_citation", [
    ("none","answered",None,False,True),
    ("warn","answered_with_warning",None,True,True),
    ("fallback","fallback","stale_source_guard",False,False),
])
def test_stale_source_three_guard_states(package,engine,guard,status,code,warning,has_citation):
    s = apply(engine,engine.initial("session")).snapshot
    s=replace(s,config=s.config.model_copy(update={"freshness_guard":guard}))
    result = Assistant(package).run(s,AssistantTestRequest(query="住宿报销上限是多少？",config_version=1),
        auth(),"guard",tuning=RetrievalTuning(freshness_guard=guard))
    assert result.result.status == status and result.result.error_code == code
    assert ("来源索引版本落后" in result.result.answer) == warning
    assert bool(result.result.citations) == has_citation
    if has_citation:
        assert "500" in result.result.answer and result.result.citations[0].version == 1
    else:
        assert "500" not in result.result.answer
    assert result.provenance["source_versions"]["policy"] == 2
    assert result.provenance["used_versions"]["policy"] == 1
    assert result.provenance["retrieved_source_stale"] is True


@pytest.mark.parametrize("invalid", [False,True,None,0,1,"","WARN","invalid",[],{}])
def test_guard_values_are_explicitly_validated(invalid):
    with pytest.raises(ValueError,match="freshness_guard"):
        RetrievalTuning(freshness_guard=invalid)


@pytest.mark.parametrize("guard", ["none","warn","fallback"])
def test_fresh_source_is_answered_in_all_guard_modes(package,engine,guard):
    s = apply(engine,engine.initial("session")).snapshot
    s = engine.plan(s,command(s,"refresh_index","fresh"),auth()).snapshot
    s=replace(s,config=s.config.model_copy(update={"freshness_guard":guard}))
    result = Assistant(package).run(s,AssistantTestRequest(query="住宿报销上限",config_version=1),
        auth(),"fresh",tuning=RetrievalTuning(freshness_guard=guard))
    assert result.result.status == "answered" and "400" in result.result.answer
    assert result.result.error_code is None and not result.provenance["retrieved_source_stale"]


def test_lost_request_basis_cannot_silently_fall_back_to_active_plan(engine):
    from dataclasses import replace
    s = apply(engine,engine.initial("session"),participants=50).snapshot
    request = engine.plan(s,command(s,"request_business","r",terms={"capacity":60},reason="scope"),auth())
    missing = replace(request,snapshot=replace(request.snapshot,request_targets={}))
    resolved=resolve(engine,missing)
    assert resolved.result.status=="approved"
    assert resolved.snapshot.world.resources["capacity"]==60
    assert resolved.result.request.object_id==request.result.id
    # The formal BusinessRequest carries its immutable basis across reconstruction.
