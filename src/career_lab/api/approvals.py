"""Deterministic simulated supervisor decisions; never exposed as an LLM tool."""
from career_lab.contracts.actions import Action
from career_lab.contracts.scenario import PilotPlan
from career_lab.scenarios.reducer import InvalidAction, VersionConflict
from career_lab.storage.sessions import IdempotencyConflict, digest


def resolve_approval(store, session_id, rule_id, request_id, expected_version):
    request = dict(rule_id=rule_id, request_id=request_id, expected_version=expected_version)
    fingerprint = digest(request)
    oid = digest([session_id, "approval", request_id])
    try:
        previous = store.get_object(session_id, oid, "approval_decision")
    except KeyError:
        previous = None
    if previous:
        if previous["request_hash"] != fingerprint:
            raise IdempotencyConflict("approval request ID reused with different content")
        return previous
    state, spec = store.get_state(session_id), store.get_spec(session_id)
    if state.version != expected_version:
        raise VersionConflict("approval state changed; reload before resolving")
    rule = next((r for r in spec.event_rules if r.id == rule_id), None)
    if not rule or rule.trigger.kind != "approved_request" or rule.trigger.authorized_role != "supervisor" or rule_id not in state.pending_requests:
        raise InvalidAction("supervisor approval requires a pending scenario request")
    if not state.configs.get("pilot"):
        raise InvalidAction("configure the requested pilot before supervisor review")
    plan = PilotPlan.model_validate(state.configs["pilot"])
    costs = {w.id: w.dev_days for w in spec.work_items}
    required = {"realtime_sync" if plan.update_strategy == "realtime" else "scope_filter", "human_fallback"}
    work = set(plan.work_items)
    if not required <= work or work - costs.keys() or plan.fallback != "human" or plan.participants < spec.constraints.minimum_participants:
        raise InvalidAction("requested plan lacks necessary work or human fallback")
    if rule.trigger.request_tool == "request_capacity":
        approved = rule.effects.capacity is not None and state.resources["capacity"] < plan.participants <= rule.effects.capacity
        reason = "申请人数超过当前额度且处于场景允许扩容上限内。"
    elif rule.trigger.request_tool == "request_resources":
        total = sum(costs[w] for w in work)
        approved = (total > state.resources["dev_days"] or plan.launch_day > state.resources["deadline_day"]) and total <= (rule.effects.dev_days if rule.effects.dev_days is not None else state.resources["dev_days"]) and plan.launch_day <= (rule.effects.deadline_day or state.resources["deadline_day"])
        reason = "工作项或上线日需要新增资源，且未超过场景允许的追加资源与延期上限。"
    else:
        raise InvalidAction("unsupported supervisor approval rule")
    if not approved:
        raise InvalidAction("request is unnecessary or exceeds the scenario approval limits")
    decision = dict(approved=True, rule_id=rule_id, request_hash=fingerprint,
                    authority="scenario-supervisor-policy-v1", reason=reason)
    action = Action(id=oid, idempotency_key="approval:" + request_id, expected_version=expected_version,
                    actor_id="supervisor", tool="approve_request", arguments={"rule_id": rule_id})
    store.commit_action(session_id, action, object_record={"id": oid, "kind": "approval_decision", "content": decision})
    return decision
