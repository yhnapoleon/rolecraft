"""Authoring checks for feasible alternatives, not runtime approvals or rubric scores."""

from career_lab.contracts.scenario import PilotPlan, ScenarioSpec, ValidationIssue


def check_solution(
    spec: ScenarioSpec, plan: PilotPlan, *, approved_event_ids: tuple[str, ...] = ()
) -> list[ValidationIssue]:
    """Probe a hypothetical path. Task 2 must derive real approvals from stored events."""
    issues: list[ValidationIssue] = []

    def issue(code: str, message: str):
        issues.append(ValidationIssue(code=code, location="plan", message=message))

    limits = spec.constraints.model_dump()
    events = {e.id: e for e in spec.event_rules}
    for event_id in approved_event_ids:
        event = events.get(event_id)
        if event is None or event.trigger.kind != "approved_request":
            raise ValueError(f"unknown approval: {event_id}")
        for key in ("capacity", "dev_days", "deadline_day"):
            value = getattr(event.effects, key)
            if value is not None:
                limits[key] = value

    if plan.participants < limits["minimum_participants"] or not plan.knowledge_domains:
        issue("no_pilot", "必须提供有实际用户和知识范围的试点。")
    if plan.participants > limits["capacity"]:
        issue("capacity_exceeded", "人数超过当前获批上限。")
    if plan.launch_day > limits["deadline_day"]:
        issue("deadline_exceeded", "上线时间超过当前获批期限。")

    domains = {d.id: d for d in spec.domains}
    if set(plan.knowledge_domains) - domains.keys():
        issue("unknown_domain", "方案包含未定义知识域。")
    work = {w.id: w.dev_days for w in spec.work_items}
    if set(plan.work_items) - work.keys():
        issue("unknown_work_item", "方案包含未定义工作项。")
    if sum(work.get(w, 0) for w in plan.work_items) > limits["dev_days"]:
        issue("budget_exceeded", "工作项总成本超过当前获批开发资源。")

    required = {"realtime_sync"} if plan.update_strategy == "realtime" else {"scope_filter"}
    if plan.fallback == "human":
        required.add("human_fallback")
    if required - set(plan.work_items):
        issue("missing_work_item", "配置依赖的工作项没有纳入开发计划。")
    if plan.fallback != "human":
        issue("missing_fallback", "无法回答和高风险问题需要转人工。")
    mutable = any(domains[d].mutable for d in plan.knowledge_domains if d in domains)
    if mutable and plan.update_strategy == "daily":
        issue("stale_policy_risk", "动态政策每日更新仍有过期风险，需实时同步或政策转人工。")
    return issues
