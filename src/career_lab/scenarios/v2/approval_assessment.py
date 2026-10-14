"""Every fact behind one approval decision: terms, the bound plan's need and rule sentences.

``policy.evaluate_request`` still decides, in its own order, and keeps its reason text.
This module only records what that decision was judged against, so the learner sees
every problem at once instead of the first failed check.
"""

from career_lab.contracts.v2.world import _ApprovalAssessment, _ApprovalTermCheck

# Paragraphs of the manager's published approval rules, by position. The Chinese and
# English materials share this layout; any other layout records no clauses rather than
# citing a sentence that does not say what the decision applied.
SCOPE, LIMITS, REQUEST_FORM, SHORTFALL, SAFEGUARDS, EFFECT = range(6)
PARAGRAPHS = 6
PRIMARY = {
    "unsupported_resource_request": SCOPE,
    "request_reason_missing": REQUEST_FORM,
    "request_evidence_invalid": REQUEST_FORM,
    "request_not_needed": SHORTFALL,
    "requested_resources_insufficient": SHORTFALL,
    "approval_plan_incomplete": SAFEGUARDS,
    "within_scenario_limits": SHORTFALL,
}
ISSUE_CLAUSE = {
    "over_limit": LIMITS,
    "need_over_limit": LIMITS,
    "below_current": SHORTFALL,
    "no_increase": SHORTFALL,
    "no_shortfall": SHORTFALL,
    "insufficient": SHORTFALL,
}


def plan_demand(package, config):
    """What a configuration needs from each approvable resource."""
    costs = package.rules["work_costs"]
    return {
        "capacity": config.participants,
        "dev_days": sum(costs[w] for w in config.work_items),
        "deadline_day": config.launch_day,
    }


def term_issues(current, requested, limit, needed):
    found = {
        "over_limit": requested > limit,
        "below_current": requested < current,
        "no_increase": requested == current,
        "no_shortfall": needed <= current,
        "insufficient": requested < needed,
        "need_over_limit": needed > limit,
    }
    return tuple(issue for issue, present in found.items() if present)


def rule_clauses(package, snapshot, session_id, paragraphs):
    """Exact public sentences of the rules material that holds the published ceilings."""
    ceilings = {resource + "_limit" for resource in package.rules["approval_limits"]}
    sources = {fact.source.object_id for fact in package.facts if fact.id in ceilings}
    if len(sources) != 1:
        return ()
    material_id = sources.pop()
    version = snapshot.source_versions.get(material_id)
    activation = snapshot.material_activation.get(f"{material_id}:{version}")
    seq = snapshot.world.business_seq
    if version is None or activation is None or activation > seq:
        return ()
    material = package.material(material_id, version)
    fragments = package.project(material_id, version, "learner", seq, session_id)
    if (
        len(material.fragments) != PARAGRAPHS
        or len(fragments) != PARAGRAPHS
        or not ceilings <= set(material.fragments[LIMITS].fact_ids)
        or any(f.ref.quote is None for f in fragments)
    ):
        return ()
    return tuple(
        fragments[index].ref.model_copy(
            update={"observed_at_seq": seq, "valid_from_seq": activation}
        )
        for index in paragraphs
    )


def assess_request(package, request, snapshot, code):
    limits = package.rules["approval_limits"]
    requirements = package.rules["approval_requirements"]
    config = request.basis.config
    resources = snapshot.world.resources
    need = plan_demand(package, config)
    terms = tuple(
        _ApprovalTermCheck(
            resource=key,
            current=resources[key],
            requested=value,
            limit=limits[key],
            needed=need[key],
            issues=term_issues(resources[key], value, limits[key], need[key]),
        )
        for key, value in sorted(request.requested.items())
        if key in limits and key in resources
    )
    required = requirements["work_items_by_strategy"][config.update_strategy]
    missing = tuple(item for item in required if item not in config.work_items)
    fallback_required = config.fallback != requirements["fallback"]
    issues = [issue for term in terms for issue in term.issues]
    primary = (
        (LIMITS if "over_limit" in issues else SHORTFALL)
        if code == "request_over_limit"
        else PRIMARY.get(code, SHORTFALL)
    )
    order = [primary, *(ISSUE_CLAUSE[issue] for issue in issues)]
    if missing or fallback_required:
        order.append(SAFEGUARDS)
    if code == "within_scenario_limits":
        order.append(EFFECT)
    return _ApprovalAssessment(
        terms=terms,
        missing_work_items=missing,
        fallback_required=fallback_required,
        clauses=rule_clauses(package, snapshot, request.session_id, tuple(dict.fromkeys(order))),
    )
