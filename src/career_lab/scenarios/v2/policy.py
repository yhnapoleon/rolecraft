"""Deterministic scenario policy. Evaluating a request never writes resources."""
from career_lab.contracts.v2.core import ObjectRef, ProtocolError, digest
from career_lab.contracts.v2.world import BusinessDecision, EffectiveConfig


def validate_config(package, config, session_id):
    if config.session_id != session_id:
        raise ProtocolError("config_session_mismatch", status=403)
    if len(set(config.domains)) != len(config.domains) or len(set(config.work_items)) != len(config.work_items):
        raise ProtocolError("duplicate_config_item")
    if set(config.domains) - package.bundle.domains.keys():
        raise ProtocolError("unknown_domain")
    if set(config.work_items) - package.rules["work_costs"].keys():
        raise ProtocolError("unknown_work_item")
    if config.chunk_size > 4000 or config.retrieval_limit > 20:
        raise ProtocolError("retrieval_limit_exceeded")


def effective_config(package, config, resources):
    validate_config(package, config, config.session_id)
    changes, reasons = {}, {}
    costs = package.rules["work_costs"]
    works = set(config.work_items)
    total = sum(costs[w] for w in works)
    # Smaller independently deliverable safeguards have deterministic priority.
    human = "human_fallback" in works and resources["dev_days"] >= costs["human_fallback"]
    remaining = resources["dev_days"] - (costs["human_fallback"] if human else 0)
    realtime = "realtime_sync" in works and remaining >= costs["realtime_sync"]
    remaining -= costs["realtime_sync"] if realtime else 0
    scope_work = "scope_filter" in works and remaining >= costs["scope_filter"]
    scoped = realtime or scope_work
    delivered = tuple(w for w in config.work_items if (w == "human_fallback" and human) or (w == "realtime_sync" and realtime) or (w == "scope_filter" and scope_work))
    if delivered != config.work_items:
        changes["work_items"] = delivered
        reasons["work_items"] = "requested_work_not_fully_provisioned"
    if config.update_strategy == "realtime" and not realtime:
        changes["update_strategy"] = "daily"
        reasons["update_strategy"] = "realtime_sync_not_provisioned"
    if config.scope_filter and not scoped:
        changes["scope_filter"] = False
        reasons["scope_filter"] = "scope_filter_not_provisioned"
    if config.fallback == "human" and not human:
        changes["fallback"] = "none"
        reasons["fallback"] = "human_fallback_not_provisioned"
    if config.update_strategy == "manual_policy" and not (human and scoped):
        changes["update_strategy"] = "daily"
        reasons["update_strategy"] = "manual_policy_not_provisioned"
    # Feasibility diagnostics don't silently replace the learner's plan.
    if config.participants > resources["capacity"]:
        reasons["participants"] = "requested_participants_exceed_approved_capacity"
    if config.launch_day > resources["deadline_day"]:
        reasons["launch_day"] = "requested_launch_exceeds_approved_deadline"
    if total > resources["dev_days"]:
        reasons["work_items"] = "requested_work_exceeds_approved_budget"
    return EffectiveConfig(requested=config, effective=config.model_copy(update=changes), differences=reasons)


def evaluate_request(package, request, snapshot, evidence_check):
    """Must be invoked by a trusted approval adapter; returns a proposal only."""
    if request.session_id != snapshot.world.session_id:
        raise ProtocolError("request_session_mismatch", status=403)
    if request.status != "pending":
        raise ProtocolError("request_not_pending", status=409)
    requested, resources = request.requested, snapshot.world.resources
    limits, work_costs = package.rules["approval_limits"], package.rules["work_costs"]
    cfg = snapshot.request_targets.get(request.id)
    if cfg is None:
        raise ProtocolError("request_basis_unavailable", status=503)
    validate_config(package, cfg, snapshot.world.session_id)
    code = None
    if not requested or set(requested) - limits.keys():
        code = "unsupported_resource_request"
    elif not request.reason.strip():
        code = "request_reason_missing"
    elif any(not evidence_check(ref) for ref in request.evidence_refs):
        code = "request_evidence_invalid"
    elif any(value > limits[key] or value < resources[key] for key, value in requested.items()):
        code = "request_over_limit"
    else:
        demand = {"capacity":cfg.participants,
                  "dev_days":sum(work_costs[w] for w in cfg.work_items),
                  "deadline_day":cfg.launch_day}
        unnecessary = [key for key, value in requested.items()
                       if demand[key] <= resources[key] or value <= resources[key]]
        insufficient = [key for key, value in requested.items() if value < demand[key]]
        needed = {"human_fallback", "realtime_sync" if cfg.update_strategy == "realtime" else "scope_filter"}
        if not needed <= set(cfg.work_items) or cfg.fallback != "human":
            code = "approval_plan_incomplete"
        elif unnecessary:
            # No partial grants hidden inside a mixed request. The caller can
            # revise and resubmit just the terms with an actual shortfall.
            code = "request_not_needed"
        elif insufficient:
            code = "requested_resources_insufficient"
    return BusinessDecision(
        id=digest(["w02-decision", request.model_dump(mode="json"), cfg.model_dump(mode="json"), snapshot.world.model_dump(mode="json")]),
        session_id=request.session_id, version=1,
        request=ObjectRef(session_id=request.session_id, kind="business_request", object_id=request.id, version=request.version),
        status="rejected" if code else "approved", decider="supervisor",
        rule_revision=package.rules["approval_rule_revision"],
        granted={} if code else dict(requested), reason_code=code or "within_scenario_limits",
        reason=("申请未满足当前确定性规则：" + code) if code else "申请在场景档位内；此决定须经可信事务入口写入后生效。",
        evidence_refs=request.evidence_refs, as_of=request.as_of)
