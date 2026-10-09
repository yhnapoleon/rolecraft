"""Normalize incoming alternatives without rewriting archived annotation bytes."""

from career_lab.contracts.v2.core import ProtocolError
from career_lab.contracts.v2.data import AnnotationDecision, AnnotationV2, DatasetRecordV2

from .attestation import rebuild_annotation, verify_annotation_artifacts, verify_attempt


def minimal_decision(decision: AnnotationDecision) -> AnnotationDecision:
    """Project fully validated evidence alternatives onto their minimal antichain.

    Public consensus still uses semantic_decision_key. Raw requests, passes and
    old annotations keep their exact bytes; this projection is review-only.
    """
    groups = {frozenset(group) for group in decision.acceptable_evidence_sets}
    minimal = sorted(tuple(sorted(group)) for group in groups if not any(s < group for s in groups))
    selected = set(decision.evidence_ids)
    representatives = [group for group in minimal if set(group) <= selected]
    representative = representatives[0] if representatives else tuple(sorted(selected))
    return AnnotationDecision.model_validate(
        decision.model_dump(mode="json")
        | {"acceptable_evidence_sets": minimal, "evidence_ids": representative}
    )


def verify_handoff_annotation(
    record: DatasetRecordV2, annotation: AnnotationV2, artifacts: dict[str, bytes], tier: str
) -> AnnotationV2:
    verified = verify_annotation_artifacts(record, annotation, artifacts)
    for decision in [verified.final, *[item.decision for item in verified.passes]]:
        if decision is not None:
            require_acceptable_selection(decision)
    if verified.status != "disputed" or tier != "G2v":
        return verified
    # Verify original raw/parsed bindings first, then review their canonical forms.
    normalized = []
    for declared in verified.passes:
        raw = artifacts[f"labels/passes/{declared.id}.json"]
        stored, parsed = verify_attempt(record, verified.annotation_version, raw)
        if parsed.decision is not None:
            parsed = parsed.model_copy(update={"decision": minimal_decision(parsed.decision)})
        normalized.append((stored, parsed, raw))
    return rebuild_annotation(record, verified.annotation_version, normalized)


def require_acceptable_selection(decision: AnnotationDecision) -> None:
    if decision.evidence_evaluable and set(decision.evidence_ids) not in [
        set(group) for group in decision.acceptable_evidence_sets
    ]:
        raise ProtocolError("final_evidence_not_an_acceptable_target")
