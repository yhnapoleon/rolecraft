"""Consumer of W07 historical-evidence-time-v1; no current-clock substitution.

The same versioned rule is exercised across the serialized W07→W08 boundary.
Reference time is the evaluated claim/behavior horizon, not export capture time.
"""
from career_lab.contracts.v2.core import ProtocolError
POLICY_VERSION="historical-evidence-time-v1"
CONTEXT_KEY="evidence_time_context"


def legal_evidence_ids(item):
    package=item.evidence;context=package.rule_context.get(CONTEXT_KEY)
    if not isinstance(context,dict) or context.get("policy")!=POLICY_VERSION or context.get("status")!="known":raise ProtocolError("temporal_scope_undetermined")
    if context.get("reference_seq")!=package.as_of.business_seq:raise ProtocolError("temporal_reference_mismatch")
    expected={c.id for c in package.candidate_evidence};known=context.get("validity_known_ids")
    if not isinstance(known,list) or len(known)!=len(set(known)) or set(known)!=expected:raise ProtocolError("evidence_validity_undetermined")
    point=package.as_of.business_seq
    return {c.id for c in package.candidate_evidence if c.ref.observed_at_seq<=point and c.ref.valid_from_seq<=point
            and (c.ref.valid_until_seq is None or point<c.ref.valid_until_seq)}


def validate_gold_time(item,decision):
    allowed=legal_evidence_ids(item)
    if set(decision.evidence_ids)-allowed or any(set(group)-allowed for group in decision.acceptable_evidence_sets):
        raise ProtocolError("gold_has_inapplicable_time_reference")
    if decision.evidence_evaluable and not decision.acceptable_evidence_sets:raise ProtocolError("gold_has_no_legal_joint_target")


def temporal_text(item,candidate=None):
    p=item.evidence
    if candidate is None:return f"reference time {p.as_of.business_seq}; temporal scope {p.rule_context.get(CONTEXT_KEY,{}).get('status','undetermined')}"
    r=candidate.ref
    return f"observed {r.observed_at_seq}; valid from {r.valid_from_seq}; valid until {r.valid_until_seq if r.valid_until_seq is not None else 'open'}"
