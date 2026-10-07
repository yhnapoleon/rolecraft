"""English explanations of the same deterministic approval decisions."""
REASONS={
 'unsupported_resource_request':'Only capacity, developer-days and the pilot deadline can be requested here. Other suggestions may be discussed but do not count as executed changes.',
 'request_reason_missing':'State the resource shortfall and the proposed work.',
 'request_evidence_invalid':'The citation is not available at this point, does not exist, or is outside the current permissions. Check the exact version before resubmitting.',
 'request_over_limit':'The request exceeds an approval ceiling or would reduce an existing allocation. Check the published approval rules.',
 'request_not_needed':'The requested terms do not demonstrate an additional shortfall. Recheck the target participants, work-item costs and date.',
 'requested_resources_insufficient':'The requested amount is still insufficient for the corresponding proposed configuration.',
 'approval_plan_incomplete':"Approval requires human fallback and the strategy-specific work items. Complete the safeguards in Manager's published resource-approval rules before resubmitting.",
}


def reason(code,requested,resources,demand):
    value=REASONS.get(code,'The request has a genuine shortfall and is within the approval ceilings. Resources change only after the decision commits successfully.')
    if code=='request_not_needed':
        labels={'capacity':'Capacity','dev_days':'Developer-days','deadline_day':'Pilot deadline day'}
        value+=' '+'; '.join(f'{labels[k]}: allocated {resources[k]}, proposed need {demand[k]}, requested {amount}' for k,amount in requested.items() if k in labels)
    return value
