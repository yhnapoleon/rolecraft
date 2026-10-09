"""Reference agents and relation models use the claim's explicit historical frame.

Open-ended validity is known only when the source adapter explicitly attests it.
An unknown frame or interval is pending, never silently converted into bad work.
The versioned context is allowed business metadata, not gold or an answer key.
"""

from career_lab.contracts.v2.core import ProtocolError

POLICY_VERSION = "historical-evidence-time-v1"
CONTEXT_KEY = "evidence_time_context"


def require_time_context(item):
    if item.task_type not in {"relation", "criterion"}:
        return None
    package = item.evidence
    context = package.rule_context.get(CONTEXT_KEY)
    if (
        not isinstance(context, dict)
        or context.get("policy") != POLICY_VERSION
        or context.get("status") != "known"
    ):
        raise ProtocolError("temporal_scope_undetermined")
    if context.get("reference_seq") != package.as_of.business_seq:
        raise ProtocolError("temporal_reference_mismatch")
    expected = {c.id for c in package.candidate_evidence}
    known = context.get("validity_known_ids")
    if not isinstance(known, list) or len(known) != len(set(known)) or set(known) != expected:
        raise ProtocolError("evidence_validity_undetermined")
    return context


def legal_evidence_ids(item):
    require_time_context(item)
    if item.task_type not in {"relation", "criterion"}:
        return None
    point = item.evidence.as_of.business_seq
    return {
        c.id
        for c in item.evidence.candidate_evidence
        if c.ref.observed_at_seq <= point
        and c.ref.valid_from_seq <= point
        and (c.ref.valid_until_seq is None or point < c.ref.valid_until_seq)
    }


def validate_time_citations(item, decision):
    allowed = legal_evidence_ids(item)
    if allowed is None:
        return
    cited = set(decision.evidence_ids)
    alternatives = decision.acceptable_evidence_sets
    if cited - allowed or any(set(group) - allowed for group in alternatives):
        raise ProtocolError("annotation_evidence_not_applicable_at_reference_time")
    if decision.evidence_evaluable and not alternatives:
        raise ProtocolError("annotation_no_legal_joint_target")
    if decision.evidence_evaluable and decision.label in {
        "SUPPORTED",
        "CONTRADICTED",
        "MET",
        "PARTIAL",
        "NOT_MET",
    }:
        if not cited or any(not group for group in alternatives):
            raise ProtocolError("positive_label_requires_nonempty_joint_evidence")
    if decision.evidence_evaluable and cited not in [set(group) for group in alternatives]:
        raise ProtocolError("final_evidence_not_an_acceptable_target")
