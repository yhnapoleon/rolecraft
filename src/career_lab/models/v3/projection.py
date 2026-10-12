"""Model inputs from fixed evidence packages, shared by product inference and data export.

Rule derivations, evaluator labels and private context never become model features.
"""

from career_lab.contracts.v2.core import EvidenceRefV2, ObjectRef, canonical, digest
from career_lab.contracts.v2.data import CriterionInput, RelationInput
from career_lab.contracts.v2.evaluation import EvidencePackageV2


def relation_input(package: EvidencePackageV2) -> RelationInput:
    """Use exact learner work, excluding it from its own supporting evidence.

    The criterion package claim describes evaluation responsibility; it is never
    substituted for the learner's statement. Whole source text preserves its
    conditions, negation and sequence, without claiming atomic decomposition.
    """
    subjects = {_object_key(ref) for ref in package.subjects}
    claim = "\n\n".join(text for _, text in subject_texts(package))
    candidates = tuple(
        candidate
        for candidate in package.candidate_evidence
        if _object_key(candidate.ref) not in subjects
    )
    raw = package.model_dump(mode="json", exclude={"input_hash"})
    raw.update(
        task_type="relation",
        criterion=None,
        claim=claim,
        rule_bound=None,
        candidate_evidence=[candidate.model_dump(mode="json") for candidate in candidates],
        rule_context={
            "evidence_time_context": {
                "policy": "historical-evidence-time-v1",
                "status": "known",
                "reference_seq": package.as_of.business_seq,
                "validity_known_ids": [candidate.id for candidate in candidates],
            }
        },
    )
    return RelationInput(
        evidence=EvidencePackageV2.model_validate(raw | {"input_hash": digest(raw)})
    )


def subject_texts(package: EvidencePackageV2) -> tuple[tuple[EvidenceRefV2, str], ...]:
    """Each work subject with its exact text (empty when the package carries none)."""
    claims = {
        canonical(candidate.ref): candidate.text
        for candidate in package.candidate_evidence
        if canonical(candidate.ref) in {canonical(ref) for ref in package.subjects}
    }
    return tuple((ref, claims.get(canonical(ref), "")) for ref in package.subjects)


def sentence_input(whole: RelationInput, subject: EvidenceRefV2, claim: str) -> RelationInput:
    """One sentence of the work as a relation input.

    Only the claim (the sentence) and the subject (its span in the work) differ from the
    whole-work input; candidates, purpose, time point and time-validity context are the same.
    """
    raw = whole.evidence.model_dump(mode="json", exclude={"input_hash"})
    raw.update(claim=claim, subjects=[subject.model_dump(mode="json")])
    return RelationInput(
        evidence=EvidencePackageV2.model_validate(raw | {"input_hash": digest(raw)})
    )


def _object_key(ref: EvidenceRefV2) -> str:
    return canonical(ref.model_dump(mode="json", include=set(ObjectRef.model_fields)))


def without_rule_context(package: EvidencePackageV2) -> EvidencePackageV2:
    """The same package with its rule context and rule bound removed."""
    body = package.model_dump(mode="json", exclude={"input_hash"})
    body.update(rule_context={}, rule_bound=None)
    return EvidencePackageV2(**body, input_hash=digest(body))


def criterion_input(package: EvidencePackageV2) -> CriterionInput:
    """A criterion package as a model sees it: no rule context and no rule bound."""
    return CriterionInput(evidence=without_rule_context(package))
