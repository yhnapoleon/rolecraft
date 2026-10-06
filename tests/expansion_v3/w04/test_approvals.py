"""Common store atomicity around an explicit controlled scenario-policy fixture.

Full acceptance still requires W02's frozen production policy adapter.
"""
from types import SimpleNamespace

import pytest
from career_lab.api.approvals_v2 import ScenarioApprovalPort, NegotiationService
from career_lab.api.modules import Operation
from career_lab.contracts.v2 import (
    ActionInput, ApprovalInput, AssistantConfig, BusinessBasis, BusinessDecision,
    BusinessRequest, Command, ObjectRef, ProtocolError, assistant_config_content_hash,
    digest, TurnInput,
)
from career_lab.storage.role_memory import object_write
from career_lab.storage.v2_lifecycle import point
from career_lab.storage.v2_store import Mutation
from test_runtime import build_runtime, session, send


def evaluate(request, view, auth):
    # Controlled boundary policy only. The production service receives W02's callable.
    demand=request.basis.config.participants;need=view.state.resources["capacity"]
    value=request.requested.get("capacity",0)
    code = "over_limit" if value>60 else ("insufficient" if value<demand else ("not_needed" if demand<=need else None))
    return BusinessDecision(id="d-"+digest(request)[:24],session_id=request.session_id,version=1,
        request=ObjectRef(session_id=request.session_id,kind="business_request",object_id=request.id,version=request.version),
        status="rejected" if code else "approved",decider="supervisor",rule_revision="fixture-only",
        granted={} if code else dict(request.requested),reason_code=code or "eligible",reason=code or "eligible",
        as_of=point(view.state))


def setup(tmp_path):
    rt=build_runtime("sqlite:///"+str(tmp_path/"negotiation.db"));auth,token=session(rt)
    policy=ScenarioApprovalPort.from_w02(SimpleNamespace(rules={"approval_limits":{"capacity":60}}),evaluate)
    service=NegotiationService(policy);rt[1].register(service.operation())
    rt[1].register(Operation("actions","act",ActionInput,service.accept,action_field="tool",
                            approval_policy=service.acceptance_decision))
    return rt,auth,service


def request(rt,auth,key,amount,demand=50,previous=None):
    view=rt[0].view(auth)
    config=AssistantConfig(id="proposal-"+key,session_id=auth.session_id,domains=("faq",),participants=demand)
    req=BusinessRequest(id=key,session_id=auth.session_id,version=1,requested={"capacity":amount},reason="新增用户有明确需求",
        basis=BusinessBasis(mode="proposed",config=config,content_hash=assistant_config_content_hash(config)),
        as_of=point(view.state),executor=auth.executor,previous_request=previous)
    write=object_write("business_request",req)
    cmd=Command(schema_version=2,request_id="request-"+key,operation="fixture_request",expected_version=view.state.business_seq,
                expected_workspace_revision=view.state.workspace_revision)
    result=rt[0].execute(auth,cmd,lambda *_:Mutation(writes=(write,)))
    return write.ref


def resolve(rt,auth,key,ref):
    return send(rt,auth,"approvals.resolve",key,{"request":ref.model_dump(mode="json"),"expected_request_revision":ref.version})


def test_counter_accept_and_successful_resource_commit_have_separate_evidence(tmp_path):
    rt,auth,service=setup(tmp_path);ref=request(rt,auth,"too-large",100)
    offered,_=resolve(rt,auth,"offer",ref)
    assert offered["result"]["decision"]["status"]=="countered"
    assert offered["result"]["decision"]["countered"]=={"capacity":60}
    assert rt[0].view(auth).state.resources["capacity"]==30
    pending=ObjectRef.model_validate(offered["result"]["request"])
    state=rt[0].view(auth).state
    body={"schema_version":2,"request_id":"accept","operation":"accept_counteroffer",
          "expected_version":state.business_seq,"expected_workspace_revision":state.workspace_revision,
          "payload":{"tool":"accept_counteroffer","request":pending.model_dump(mode="json")}}
    result=rt[2].dispatch(auth,"actions",body)
    assert result["result"]["decision"]["status"]=="accepted"
    assert [e["type"] for e in result["events"]]==["resource_counteroffer_accepted","resource_grant_committed"]
    assert rt[0].view(auth).state.resources["capacity"]==60
    assert rt[2].dispatch(auth,"actions",body)["replayed"]
    assert len([o for o in rt[0].view(auth).objects if o.ref.kind=="business_decision"])==2
    manager=rt[4].port.capture(auth,TurnInput(role_id="supervisor",text="资源到底是否到位"))
    assert any('"granted":{"capacity":60}' in m.text for m in manager.context.sourced_memory)
    assert any('"status":"countered"' in m.text for m in manager.context.sourced_memory)
    tech=rt[4].port.capture(auth,TurnInput(role_id="tech_lead",text="有没有经理新决定"))
    assert not any("authoritative_business_decision" in m.text for m in tech.context.sourced_memory)


def test_failed_accept_is_atomic_and_counteroffer_remains_recoverable(tmp_path):
    rt,auth,service=setup(tmp_path);ref=request(rt,auth,"large",100)
    offered,_=resolve(rt,auth,"offer",ref);pending=ObjectRef.model_validate(offered["result"]["request"])
    view=rt[0].view(auth)
    cmd=Command(schema_version=2,request_id="accept",operation="accept_counteroffer",expected_version=view.state.business_seq,
        expected_workspace_revision=view.state.workspace_revision,payload={"tool":"accept_counteroffer","request":pending.model_dump(mode="json")})
    def fault(stage):
        if stage=="after_objects":raise RuntimeError("injected commit failure")
    with pytest.raises(RuntimeError):
        rt[0].execute(auth,cmd,service.accept,approval_policy=service.acceptance_decision,fault=fault)
    after=rt[0].view(auth)
    assert after.state==view.state
    assert after.get(pending).content["status"]=="countered"
    good=rt[0].execute(auth,cmd,service.accept,approval_policy=service.acceptance_decision)
    assert good.state.resources["capacity"]==60


def test_reject_allows_revised_request_and_infeasible_lower_offer_is_not_invented(tmp_path):
    rt,auth,service=setup(tmp_path);ref=request(rt,auth,"impossible",100,demand=90)
    rejected,_=resolve(rt,auth,"reject",ref)
    assert rejected["result"]["decision"]["status"]=="rejected"
    assert not rejected["result"]["decision"]["countered"]
    previous=ObjectRef.model_validate(rejected["result"]["request"])
    new=request(rt,auth,"revised",50,demand=50,previous=previous)
    approved,_=resolve(rt,auth,"approve-revised",new)
    assert approved["result"]["decision"]["status"]=="approved"
    assert rt[0].read(auth,previous).content["status"]=="rejected"


def test_chat_does_not_resolve_and_accepting_modified_terms_is_rejected(tmp_path):
    rt,auth,service=setup(tmp_path);ref=request(rt,auth,"large",100)
    offered,_=resolve(rt,auth,"offer",ref);pending=ObjectRef.model_validate(offered["result"]["request"])
    with pytest.raises(ProtocolError,match="counteroffer terms conflict"):
        state=rt[0].view(auth).state
        rt[2].dispatch(auth,"actions",{"schema_version":2,"request_id":"bad-accept","operation":"accept_counteroffer",
            "expected_version":state.business_seq,"expected_workspace_revision":state.workspace_revision,
            "payload":{"tool":"accept_counteroffer","request":pending.model_dump(mode="json"),"terms":{"capacity":80}}})
    assert rt[0].view(auth).state.resources["capacity"]==30


def test_common_store_rejects_decision_without_trusted_policy(tmp_path):
    rt,auth,service=setup(tmp_path);ref=request(rt,auth,"fine",50)
    view=rt[0].view(auth);cmd=Command(schema_version=2,request_id="untrusted",operation="approvals.resolve",
        expected_version=view.state.business_seq,expected_workspace_revision=view.state.workspace_revision,
        payload={"request":ref.model_dump(mode="json"),"expected_request_revision":1})
    with pytest.raises(ProtocolError,match="approval policy required"):
        rt[0].execute(auth,cmd,service.resolve)
    assert rt[0].view(auth).state==view.state
