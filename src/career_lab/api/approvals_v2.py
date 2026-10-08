"""Negotiation plans using the scenario's deterministic policy and W01 store.

W02 supplies evaluate(request, view, auth) and legal candidate terms. This module
does not maintain a second approval rule set and never writes resource state.
"""
from dataclasses import dataclass
from typing import Callable, Literal

from career_lab.api.modules import Operation
from career_lab.contracts.v2 import (
    ActionInput, ApprovalInput, BusinessDecision, BusinessRequest, ObjectRef,
    ProtocolError, PublicEvent, RoleSpecV2, digest,
)
from career_lab.storage.v2_lifecycle import point
from career_lab.storage.v2_store import Mutation, EventDraft
from career_lab.storage.role_memory import object_write


@dataclass(frozen=True)
class ScenarioApprovalPort:
    evaluate: Callable
    candidates: Callable
    roles: tuple[RoleSpecV2, ...]
    decision_followup: Callable | None = None
    followup_required: bool = False
    work_language: Literal['zh','en'] = 'zh'  # Legacy package default, not a request/UI override.

    def __post_init__(self):
        from career_lab.runtime.context_v2 import require_work_language
        require_work_language(self.work_language)

    @classmethod
    def from_w02(cls, package, evaluate, *, decision_followup=None):
        """Use hash-checked W02 limits, without changing its necessity/basis rules.

        `evaluate` is the installed W02 adapter from BusinessRequest and the real
        TransactionView to its immutable scenario Snapshot. No active paths/imports.
        """
        from career_lab.runtime.context_v2 import ScenarioKnowledge
        language=ScenarioKnowledge.from_package(package).work_language
        limits = dict(package.rules["approval_limits"])

        def candidates(request, view):
            if set(request.requested) - limits.keys() or set(request.requested) - view.state.resources.keys():
                return ()
            lower = {k: min(v, limits[k]) for k, v in request.requested.items()}
            if lower == request.requested or any(v <= view.state.resources[k] for k, v in lower.items()):
                return ()
            return (lower,)

        return cls(evaluate=evaluate, candidates=candidates, roles=package.bundle.role_specs,
                   decision_followup=decision_followup, followup_required=bool(package.rules.get("business_events")), work_language=language)


def latest_request(view, ref):
    if ref.kind != "business_request" or ref.session_id != view.state.session_id:
        raise ProtocolError("object_not_found", status=404)
    record = view.get(ref)
    latest = max((r for r in view.objects if r.ref.kind == ref.kind and r.ref.object_id == ref.object_id),
                 key=lambda r: r.ref.version)
    if latest.ref != ref:
        raise ProtocolError("request_revision_conflict", status=409)
    return BusinessRequest.model_validate(record.content)


class NegotiationService:
    def __init__(self, policy: ScenarioApprovalPort):
        self.policy = policy

    def _assess(self, request, view, auth):
        if getattr(view.bindings,'work_language',self.policy.work_language)!=self.policy.work_language:
            raise ProtocolError('approval_language_binding_mismatch',status=409)
        if set(request.requested) - view.state.resources.keys():
            raise ProtocolError("unsupported_resource_request", status=422)
        decision = self.policy.evaluate(request, view, auth)
        decision = BusinessDecision.model_validate(decision.model_dump(mode="json"))
        expected = ObjectRef(session_id=request.session_id, kind="business_request",
                             object_id=request.id, version=request.version)
        if decision.request != expected or decision.session_id != request.session_id:
            raise ProtocolError("approval_policy_identity_invalid", status=503)
        role = next((r for r in self.policy.roles if r.id == decision.decider), None)
        if role is None or "approve_business" not in role.approval_authority:
            raise ProtocolError("approval_authority_forbidden", status=403)
        if decision.status not in {"approved", "rejected"}:
            raise ProtocolError("approval_policy_result_invalid", status=503)
        if decision.status == "approved" and decision.granted != request.requested:
            raise ProtocolError("approval_policy_terms_invalid", status=503)
        return decision

    def resolve_decision(self, view, command, auth):
        from career_lab.runtime.context_v2 import role_text
        body = ApprovalInput.model_validate(command.payload)
        request = latest_request(view, body.request)
        if request.version != body.expected_request_revision or request.status != "pending":
            raise ProtocolError("request_not_pending", status=409)
        decision = self._assess(request, view, auth)
        if decision.status == "approved":
            return decision
        for terms in self.policy.candidates(request, view):
            # A counteroffer must satisfy exactly the same deterministic policy and
            # immutable proposed/applied plan. A smaller but infeasible offer fails.
            candidate = BusinessRequest.model_validate(request.model_dump(mode="json") | {"requested": terms})
            checked = self._assess(candidate, view, auth)
            if checked.status == "approved":
                return BusinessDecision.model_validate(decision.model_dump(mode="json") | {
                    "id": "counter-" + digest([decision.id, terms])[:24], "status": "countered",
                    "granted": {}, "countered": terms, "reason_code": "lower_terms_available",
                    "reason": role_text(self.policy.work_language,"counteroffer")})
        return decision

    def resolve(self, view, command, auth):
        decision = self.resolve_decision(view, command, auth)
        request = latest_request(view, decision.request)
        return self._plan(request, decision, view, accepted=False)

    def acceptance_decision(self, view, command, auth):
        from career_lab.runtime.context_v2 import role_text
        body = ActionInput.model_validate(command.payload)
        if body.tool != "accept_counteroffer" or body.request is None:
            raise ProtocolError("counteroffer_request_required")
        request = latest_request(view, body.request)
        if request.status != "countered":
            raise ProtocolError("counteroffer_not_pending", status=409)
        offers = [BusinessDecision.model_validate(r.content) for r in view.objects
                  if r.ref.kind == "business_decision" and r.content["request"]["object_id"] == request.id
                  and r.content["status"] == "countered"]
        # Counteroffer corresponds to the immediately preceding pending request.
        offers = [d for d in offers if d.request.version == request.version - 1]
        if len(offers) != 1 or (body.terms and body.terms != offers[0].countered):
            raise ProtocolError("counteroffer_terms_conflict", status=409)
        offer = offers[0]
        candidate = BusinessRequest.model_validate(request.model_dump(mode="json") | {
            "status": "pending", "requested": offer.countered, "as_of": point(view.state).model_dump(mode="json")})
        checked = self._assess(candidate, view, auth)
        # Revalidate against the current resources and scenario, never the model.
        if checked.status != "approved":
            raise ProtocolError("counteroffer_no_longer_valid", status=409)
        return BusinessDecision.model_validate(checked.model_dump(mode="json") | {
            "id": "accepted-" + digest([offer.id, command.request_id])[:24],
            "status": "accepted", "countered": {}, "reason_code": "counteroffer_accepted",
            "reason": role_text(self.policy.work_language,"counteroffer_accepted")})

    def accept(self, view, command, auth):
        decision = self.acceptance_decision(view, command, auth)
        request = latest_request(view, decision.request)
        return self._plan(request, decision, view, accepted=True)

    def _plan(self, request, decision, view, *, accepted):
        updated = BusinessRequest.model_validate(request.model_dump(mode="json") | {
            "version": request.version + 1, "status": decision.status})
        request_write = object_write("business_request", updated)
        decision_write = object_write("business_decision", decision, visible_to=("learner", decision.decider))
        audience = tuple(dict.fromkeys(("learner", decision.decider, *(r.id for r in self.policy.roles if "business_decided" in r.event_subscriptions))))
        events = [EventDraft(type="business_decided", visible_to=audience,
                    refs=(decision_write.ref, request_write.ref), data={"decision_id":decision.id,
                    "request_id":request.id, "status":decision.status, "reason_code":decision.reason_code,
                    "granted":decision.granted, "countered":decision.countered})]
        if accepted:
            events.append(EventDraft(type="business_counteroffer_accepted",visible_to=audience,refs=(decision_write.ref,)))
        if decision.status in {"approved", "accepted"}:
            events.append(EventDraft(type="resource_grant_committed", visible_to=audience,
                                     refs=(decision_write.ref,), data={"granted": decision.granted}))
        plan = Mutation(writes=(request_write, decision_write), events=tuple(events), decision=decision,
                        result={"decision":decision.model_dump(mode="json"),
                                "request":request_write.ref.model_dump(mode="json"),
                                "resources_changed":decision.status in {"approved","accepted"}})
        if decision.status in {"approved", "accepted"} and "capacity" in decision.granted:
            if self.policy.decision_followup is not None:
                return self.policy.decision_followup(view,request,decision,plan)
            if self.policy.followup_required:
                # Do not silently skip W02's capacity-approved business event or
                # manufacture a parallel scenario state transition in W04.
                raise ProtocolError("role_decision_followup_unavailable",status=409)
        return plan

    def actions(self, downstream_handler):
        def handle(view, command, auth):
            return self.accept(view, command, auth) if command.payload.get("tool") == "accept_counteroffer" else downstream_handler(view, command, auth)
        return handle

    def approval_policy(self, downstream_policy=None):
        def policy(view, command, auth):
            if command.payload.get("tool") == "accept_counteroffer":
                return self.acceptance_decision(view, command, auth)
            if command.operation == "approvals.resolve":
                return self.resolve_decision(view, command, auth)
            if downstream_policy is not None:
                return downstream_policy(view, command, auth)
            raise ProtocolError("approval_policy_required", status=403)
        return policy

    def operation(self):
        return Operation("approvals.resolve", "act", ApprovalInput, self.resolve,
                         approval_policy=self.resolve_decision, event_projector=self.event_projector())

    def event_projector(self, downstream=None):
        def project(event, auth):
            if event.type not in {"business_decided","business_counteroffer_accepted","resource_grant_committed"}:
                return downstream(event,auth) if downstream else None
            if event.session_id!=auth.session_id or auth.actor_id not in event.visible_to or "read" not in auth.capabilities:
                return None
            allowed={"decision_id","request_id","status","reason_code","granted","countered"}
            return PublicEvent.model_validate(event.model_dump(mode="json",exclude={"visible_to","data"}) |
                       {"data":{k:v for k,v in event.data.items() if k in allowed}})
        return project

    def action_operation(self, downstream_handler, *, downstream_policy=None, downstream_projector=None):
        # ActionInput.tool is Literal, so W01 can recover this projector from the
        # persisted action on job results, request replays and historical reads.
        return Operation("actions","act",ActionInput,self.actions(downstream_handler),action_field="tool",
                         approval_policy=self.approval_policy(downstream_policy),
                         event_projector=self.event_projector(downstream_projector))
