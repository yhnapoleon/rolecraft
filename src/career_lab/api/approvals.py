"""Deterministic simulated supervisor decisions; never exposed as an LLM tool."""
from career_lab.contracts.actions import Action
from career_lab.contracts.scenario import PilotPlan
from career_lab.scenarios.reducer import InvalidAction, VersionConflict
from career_lab.storage.sessions import IdempotencyConflict, digest


class ApprovalDenied(InvalidAction):
    """A persisted supervisor denial, distinct from a stale request."""


def _decision_response(store, session_id, oid, decision, state=None):
    from career_lab.api.presentation import learner_state

    if state is None:
        # Existing approval objects predate the response state. The transaction's
        # snapshots still preserve the exact state, including any triggered event.
        seq = max(event.seq for event in store.events(session_id) if event.id.startswith(oid + ":"))
        state = store.get_state(session_id, seq)
    return {**decision, "state": learner_state(store, session_id, state),
            "created_at": store.object_created_at(session_id, oid)}


def _previous_result(store, session_id, oid, fingerprint):
    try:
        previous = store.get_object(session_id, oid)
    except KeyError:
        return None
    if previous.get("approved"):
        saved_hash = previous["request_hash"]
    else:
        saved_hash = store.get_object_metadata(session_id, oid).get("request_hash")
    if saved_hash != fingerprint:
        raise IdempotencyConflict("approval request ID reused with different content")
    if previous.get("approved"):
        return _decision_response(store, session_id, oid, previous)
    metadata = store.get_object_metadata(session_id, oid)
    raise ApprovalDenied(metadata["error"], code=previous["code"], details=previous["details"])


def resolve_approval(store, session_id, rule_id, request_id, expected_version):
    request = dict(rule_id=rule_id, request_id=request_id, expected_version=expected_version)
    fingerprint = digest(request)
    oid = digest([session_id, "approval", request_id])
    previous = _previous_result(store, session_id, oid, fingerprint)
    if previous:
        return previous
    state, spec = store.get_state(session_id), store.get_spec(session_id)
    if state.version != expected_version:
        # A concurrent identical request may just have finished successfully.
        previous = _previous_result(store, session_id, oid, fingerprint)
        if previous:
            return previous
        raise VersionConflict("approval state changed; reload before resolving")

    def deny(message, code, details=None):
        content = {"rule_id": rule_id, "request_id": request_id, "code": code, "details": details or {}}
        try:
            store.save_derived(session_id, oid, "approval_denied", content,
                               metadata={"request_hash": fingerprint, "error": message},
                               expected_version=expected_version)
        except (IdempotencyConflict, VersionConflict):
            previous = _previous_result(store, session_id, oid, fingerprint)
            if previous:
                return previous
            raise
        raise ApprovalDenied(message, code=code, details=content["details"])

    rule = next((r for r in spec.event_rules if r.id == rule_id), None)
    if not rule or rule.trigger.kind != "approved_request" or rule.trigger.authorized_role != "supervisor" or rule_id not in state.pending_requests:
        return deny("supervisor approval requires a pending scenario request", "approval_no_pending_request")
    if not state.configs.get("pilot"):
        return deny("configure the requested pilot before supervisor review", "approval_needs_config")
    plan = PilotPlan.model_validate(state.configs["pilot"])
    costs = {w.id: w.dev_days for w in spec.work_items}
    required = {"realtime_sync" if plan.update_strategy == "realtime" else "scope_filter", "human_fallback"}
    work = set(plan.work_items)
    if not required <= work or work - costs.keys() or plan.fallback != "human" or plan.participants < spec.constraints.minimum_participants:
        return deny("requested plan lacks necessary work or human fallback", "approval_plan_incomplete", {
            "missing": {"work_items": sorted(required - work), "human_fallback": plan.fallback != "human",
                        "minimum_participants": plan.participants < spec.constraints.minimum_participants},
            "participants": plan.participants, "minimum_participants": spec.constraints.minimum_participants,
            "unknown_work_items": sorted(work - costs.keys()),
        })
    if rule.trigger.request_tool == "request_capacity":
        approved = rule.effects.capacity is not None and state.resources["capacity"] < plan.participants <= rule.effects.capacity
        reason = "申请人数超过当前额度且处于场景允许扩容上限内。"
        limits = {"requested": {"capacity": plan.participants}, "current": {"capacity": state.resources["capacity"]},
                  "limit": {"capacity": rule.effects.capacity}}
    elif rule.trigger.request_tool == "request_resources":
        total = sum(costs[w] for w in work)
        approved = (total > state.resources["dev_days"] or plan.launch_day > state.resources["deadline_day"]) and total <= (rule.effects.dev_days if rule.effects.dev_days is not None else state.resources["dev_days"]) and plan.launch_day <= (rule.effects.deadline_day or state.resources["deadline_day"])
        reason = "工作项或上线日需要新增资源，且未超过场景允许的追加资源与延期上限。"
        limits = {"requested": {"dev_days": total, "deadline_day": plan.launch_day},
                  "current": {key: state.resources[key] for key in ("dev_days", "deadline_day")},
                  "limit": {"dev_days": rule.effects.dev_days if rule.effects.dev_days is not None else state.resources["dev_days"],
                            "deadline_day": rule.effects.deadline_day or state.resources["deadline_day"]}}
    else:
        return deny("unsupported supervisor approval rule", "approval_unsupported_rule")
    if not approved:
        return deny("request is unnecessary or exceeds the scenario approval limits", "approval_not_needed_or_over_limit", limits)
    decision = dict(approved=True, rule_id=rule_id, request_hash=fingerprint,
                    authority="scenario-supervisor-policy-v1", reason=reason)
    action = Action(id=oid, idempotency_key="approval:" + request_id, expected_version=expected_version,
                    actor_id="supervisor", tool="approve_request", arguments={"rule_id": rule_id})
    try:
        result = store.commit_action(session_id, action, object_record={"id": oid, "kind": "approval_decision", "content": decision})
    except (IdempotencyConflict, VersionConflict):
        previous = _previous_result(store, session_id, oid, fingerprint)
        if previous:
            return previous
        raise
    return _decision_response(store, session_id, oid, decision, result.state)
