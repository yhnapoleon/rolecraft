"""Explicit decoder: historical JSON without schema_version stays strictly v1."""

from career_lab.contracts.actions import Action, Event, WorldState
from career_lab.contracts.scenario import ScenarioSpec
from career_lab.contracts.evaluation import EvidencePackage, GoldAnnotation, CandidateEvidence
from career_lab.storage.sessions import canonical as canonical_v1, digest as digest_v1
from career_lab.contracts.v2 import (
    ProtocolError,
    LegacyAnnotation,
    digest,
    WorldStateV2,
    EvidencePackageV2,
    Command,
)

V1 = {
    "Action": Action,
    "Event": Event,
    "WorldState": WorldState,
    "ScenarioSpec": ScenarioSpec,
    "EvidencePackage": EvidencePackage,
    "GoldAnnotation": GoldAnnotation,
    "CandidateEvidence": CandidateEvidence,
}
V2 = {"Action": Command, "WorldState": WorldStateV2, "EvidencePackage": EvidencePackageV2}


def decode(name, raw):
    version = raw.get("schema_version")
    if version is None:
        if name not in V1:
            raise ProtocolError("legacy_type_unavailable")
        return V1[name].model_validate(raw)
    if version != 2 or name not in V2:
        raise ProtocolError("protocol_version_unsupported")
    return V2[name].model_validate(raw)


def preserve_legacy_annotation(raw):
    old = GoldAnnotation.model_validate(raw)
    return LegacyAnnotation(original_tier=old.label_tier, original=raw, original_hash=digest(raw))
