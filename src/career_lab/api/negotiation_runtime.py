"""W04 negotiation over the actual W02 policy and business follow-up reducer."""

from dataclasses import replace
from career_lab.api.approvals_v2 import NegotiationService, ScenarioApprovalPort
from career_lab.scenarios.v2.policy import evaluate_request
from career_lab.contracts.v2 import ProtocolError
from career_lab.storage.v2_lifecycle import point
from career_lab.storage.v2_store import EventDraft


def install_negotiation(registry, module):
    def evaluate(request, view, auth):
        def checked(ref):
            try:
                return module.check_evidence(view, auth, ref)
            except ProtocolError:
                return False

        return evaluate_request(module.package, request, module.snapshot(view), checked).model_copy(
            update={"as_of": point(view.state)}
        )

    def followup(view, request, decision, plan):
        snapshot = module.snapshot(view)
        snapshot = replace(
            snapshot,
            world=snapshot.world.model_copy(
                update={
                    "business_seq": view.state.business_seq + 1,
                    "resources": {**view.state.resources, **decision.granted},
                }
            ),
        )
        following, notices = module.engine.business_followups(snapshot, "capacity_approved")
        if not notices:
            return plan
        current = view.private_scenario_state
        private = current.model_copy(
            update={
                "version": current.version + 1,
                "source_versions": following.source_versions,
                "indexed_versions": following.indexed_versions,
                "material_activation": following.material_activation,
            }
        )
        write = module.write(private, "scenario_state", current.version, visible_to=("system",))
        events = tuple(
            EventDraft(type=n["event_type"], visible_to=tuple(n["visible_to"]), data=n["payload"])
            for n in notices
        )
        return replace(
            plan,
            writes=(*plan.writes, write),
            events=(*plan.events, *events),
            state_changes={
                **plan.state_changes,
                "applied_milestones": following.world.applied_milestones,
            },
        )

    service = NegotiationService(
        ScenarioApprovalPort.from_w02(module.package, evaluate, decision_followup=followup)
    )
    old = registry.operations.pop("actions")
    approval = registry.operations.pop("approvals.resolve")
    registry.register(replace(service.operation(), action_name=approval.action_name))
    registry.register(
        service.action_operation(
            old.handler,
            downstream_policy=old.approval_policy,
            downstream_projector=old.event_projector,
        )
    )
