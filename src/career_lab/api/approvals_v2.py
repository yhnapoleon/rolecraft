"""Negotiation plans using the scenario's deterministic policy and W01 store.

W02 supplies evaluate(request, view, auth) and legal candidate terms. This module
does not maintain a second approval rule set and never writes resource state.
"""
from dataclasses import dataclass, replace
from typing import Callable

from career_lab.api.modules import Operation
from career_lab.contracts.v2 import (
    ActionInput, ApprovalInput, BusinessDecision, BusinessRequest, ObjectRef,
    ProtocolError, digest,
)
from career_lab.storage.v2_lifecycle import point
from career_lab.storage.v2_store import Mutation, EventDraft
from career_lab.storage.role_memory import object_write


@dataclass(frozen=True)
class ScenarioApprovalPort:
    evaluate: Callable
    candidates: Callable

    @classmethod
    def from_w02(cls, package, evaluate):
        """Use hash-checked W02 limits, without changing its necessity/basis rules.

        `evaluate` is the installed W02 adapter from BusinessRequest and the real
        TransactionView to its immutable scenario Snapshot. No active paths/imports.
        """
        limits = dict(package.rules["approval_limits"])

        def candidates(request, view):
            if set(request.requested) - limits.keys():
                return ()
            lower = {k: min(v, limits[k]) for k, v in request.requested.items()}
            if lower == request.requested or any(v <= view.state.resources[k] for k, v in lower.items()):
                return ()
            return (lower,)

        return cls(evaluate=evaluate, candidates=candidates)


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
        decision = self.policy.evaluate(request, view, auth)
        decision = BusinessDecision.model_validate(decision.model_dump(mode="json"))
        expected = ObjectRef(session_id=request.session_id, kind="business_request",
                             object_id=request.id, version=request.version)
        if decision.request != expected or decision.session_id != request.session_id:
            raise ProtocolError("approval_policy_identity_invalid", status=503)
        if decision.status not in {"approved", "rejected"}:
            raise ProtocolError("approval_policy_result_invalid", status=503)
        if decision.status == "approved" and decision.granted != request.requested:
            raise ProtocolError("approval_policy_terms_invalid", status=503)
        return decision

    def resolve_decision(self, view, command, auth):
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
                    "reason": "当前申请超出可批档位；这些较低条件已通过同一场景规则。接受成功前资源不变。"})
        return decision

    def resolve(self, view, command, auth):
        decision = self.resolve_decision(view, command, auth)
        request = latest_request(view, decision.request)
        return self._plan(request, decision, view, accepted=False)

    def acceptance_decision(self, view, command, auth):
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
            "reason": "已接受还价；资源仅随本决定的原子提交生效。"})

    def accept(self, view, command, auth):
        decision = self.acceptance_decision(view, command, auth)
        request = latest_request(view, decision.request)
        return self._plan(request, decision, view, accepted=True)

    def _plan(self, request, decision, view, *, accepted):
        updated = BusinessRequest.model_validate(request.model_dump(mode="json") | {
            "version": request.version + 1, "status": decision.status})
        request_write = object_write("business_request", updated)
        decision_write = object_write("business_decision", decision, visible_to=("learner", decision.decider))
        events = [EventDraft(type="resource_counteroffer_accepted" if accepted else "resource_" + decision.status,
                            visible_to=("learner", "supervisor"), refs=(decision_write.ref, request_write.ref))]
        if decision.status in {"approved", "accepted"}:
            events.append(EventDraft(type="resource_grant_committed", visible_to=("learner", "supervisor"),
                                     refs=(decision_write.ref,), data={"granted": decision.granted}))
        return Mutation(writes=(request_write, decision_write), events=tuple(events), decision=decision,
                        result={"decision": decision.model_dump(mode="json"),
                                "request": request_write.ref.model_dump(mode="json"),
                                "resources_changed": decision.status in {"approved", "accepted"}})

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
                         approval_policy=self.resolve_decision)
