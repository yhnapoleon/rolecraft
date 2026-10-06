"""Public dialogue records and private, sourced generation data.

PrivateGeneration is an in-process plan, never a registered storage kind. Only a
future W01 protected audit port may persist it. Public objects contain no prompt,
private provenance, context hashes or internal fact keys.
"""
from dataclasses import dataclass
from typing import Literal, Protocol
from pydantic import model_validator, ValidationError

from career_lab.contracts.v2 import (
    V2, Identifier, ObjectRef, TurnInput, VersionPoint, Executor, PositiveInt,
    DisclosedFragment, EvidenceRefV2, PublicDisclosureRecord, ModelAttemptUsage,
    ProtocolError, RoleContext, ProviderMessage, DisclosureRecord, WorkProductVersion,
)
from career_lab.storage.v2_store import ObjectWrite, references


class RoleTurn(V2):
    id: Identifier
    session_id: Identifier
    version: PositiveInt = 1
    input: TurnInput
    as_of: VersionPoint
    executor: Executor
    origin_cycle: ObjectRef | None = None  # legacy r1 stays unknown, never current


class PublicSpokenEvidence(V2):
    label: Identifier
    quote: str
    verification: Literal["verified", "model_extracted"]


class RoleReply(V2):
    """Learner-visible utterance. Do not add internal generation fields here."""
    id: Identifier
    session_id: Identifier
    version: PositiveInt = 1
    role_id: Identifier
    request: ObjectRef
    question: str
    text: str
    status: Literal["completed", "unavailable", "blocked"]
    error_code: str | None = None
    as_of: VersionPoint
    executor: Executor
    origin_cycle: ObjectRef | None = None
    generation_cycle: ObjectRef | None = None
    # These record only uttered text; the source is the public reply, not a private
    # material. Internal fact/source mapping lives in PrivateGeneration.context.
    spoken_evidence: tuple[PublicSpokenEvidence, ...] = ()
    omission_count: int = 0

    @model_validator(mode="after")
    def uttered_evidence_only(self):
        if any(not item.quote or item.quote not in self.text for item in self.spoken_evidence):
            raise ValueError("public disclosure must quote the actual utterance")
        return self


class RoleDisplay(V2):
    id: Identifier
    session_id: Identifier
    version: PositiveInt = 1
    reply: ObjectRef
    as_of: VersionPoint
    executor: Executor


@dataclass(frozen=True)
class ReceivedShare:
    """An immutable receipt of what this role actually read, not a live re-read."""
    share: ObjectRef
    product: ObjectRef
    role_id: str
    received_at: VersionPoint
    fragment: DisclosedFragment

    def __post_init__(self):
        if self.share.kind != "share" or self.product.kind != "product" or self.fragment.ref.kind != "product":
            raise ProtocolError("role_memory_source_invalid")
        if self.share.session_id != self.product.session_id or self.fragment.ref.session_id != self.product.session_id:
            raise ProtocolError("role_memory_source_invalid")
        if (self.fragment.ref.object_id, self.fragment.ref.version) != (self.product.object_id, self.product.version):
            raise ProtocolError("role_memory_source_invalid")
        if self.fragment.verification != "verified":
            raise ProtocolError("role_memory_source_invalid")
        if self.fragment.ref.observed_at_seq != self.received_at.business_seq:
            raise ProtocolError("role_memory_time_invalid")


@dataclass(frozen=True)
class RoleMemory:
    fragment: DisclosedFragment
    role_id: str
    # Empty for intrinsic role knowledge. Learner object excerpts retain their
    # precise provenance, so a scoped caller cannot recover them through a role.
    learner_refs: tuple[ObjectRef, ...] = ()
    provenance: tuple[EvidenceRefV2, ...] = ()


@dataclass(frozen=True)
class PrivateGeneration:
    role_id: str
    reply_ref: ObjectRef
    context: RoleContext
    prompt_messages: tuple[ProviderMessage, ...]
    prompt_hash: str
    history_revision: str
    received_shares: tuple[ReceivedShare, ...]
    memories: tuple[RoleMemory, ...]
    refresh_count: int
    attempts: tuple[ModelAttemptUsage, ...]
    used_sources: tuple[DisclosedFragment, ...]


class PrivateGenerationPort(Protocol):
    """Implemented by the fixed W01 protected carrier, never by a user DTO.

    prepare returns official protected ObjectWrite(s) for the same Mutation as
    the public reply. The audit may reference the reply; reverse edges are banned.
    """
    def require_available(self) -> None: ...
    def prepare(self, view, envelope, auth, generation: PrivateGeneration) -> tuple[ObjectWrite, ...]: ...
    def record_attempt(self, envelope, auth, attempt: ModelAttemptUsage, error_code: str | None) -> None: ...


PRIVATE_REPLY_FIELDS = frozenset({
    "prompt_messages", "prompt_hash", "context_hash", "source_versions",
    "history_revision", "attempts", "omitted_sources", "actual_disclosures",
    "received_shares", "internal_disclosures", "context",
})


def parse_public_reply(content):
    """Fail closed on r1 raw records until W01 installs a trusted legacy projection."""
    if PRIVATE_REPLY_FIELDS.intersection(content):
        raise ProtocolError("role_legacy_reply_requires_projection", status=409)
    try:
        return RoleReply.model_validate(content)
    except (ValidationError,TypeError,ValueError):
        raise ProtocolError("role_reply_record_invalid",status=409) from None


def install_role_storage(store):
    for kind, model in (("role_turn", RoleTurn), ("role_reply", RoleReply), ("role_display", RoleDisplay)):
        if kind in store.object_models:
            if store.object_models[kind] is not model:
                raise ValueError("incompatible role object registration")
        else:
            store.register_object(kind, model)
    # No private kind is registered here. Missing W01 protected persistence blocks
    # generation before model invocation, rather than changing a DTO's visibility.


def object_write(kind, obj, *, visible_to=("learner",)):
    content = obj.model_dump(mode="json")
    ref = ObjectRef(session_id=obj.session_id, kind=kind, object_id=obj.id, version=obj.version)
    # Public disclosure self-links are metadata, so they are returned at display
    # time; do not persist a circular dependency in a public reply.
    return ObjectWrite(ref=ref, expected_head=obj.version - 1, content=content,
                       visible_to=visible_to, dependencies=references(content))


def read_replies(view, role_id=None):
    return tuple(parse_public_reply(r.content) for r in sorted(view.objects, key=lambda r: (r.created_storage_revision, r.ref.object_id))
                 if r.ref.kind == "role_reply" and (role_id is None or r.content.get("role_id") == role_id))


def memory_from_generation(reply, generation):
    """Retain exact provenance without requiring the model to echo attachments."""
    from career_lab.contracts.v2 import canonical
    selected={canonical(ObjectRef.model_validate({k:v for k,v in s.ref.model_dump().items() if k in ObjectRef.model_fields})) for s in generation.used_sources}
    learner=[]
    for r in generation.received_shares:
        if canonical(r.product) in selected:learner.append(r.product)
    for m in generation.memories:
        ref=ObjectRef.model_validate({k:v for k,v in m.fragment.ref.model_dump().items() if k in ObjectRef.model_fields})
        if canonical(ref) in selected:learner.extend(m.learner_refs)
    provenance=tuple(s.ref for s in generation.used_sources)
    text=canonical({"historical_question":reply.question,"historical_reply":reply.text,
                    "meaning":"过去对话原文，保留其时点；意见不自动成为公司事实"})
    fragment=DisclosedFragment(ref=EvidenceRefV2(**generation.reply_ref.model_dump(),observed_at_seq=reply.as_of.business_seq),
                              text=text,channel="memory",verification="verified")
    return RoleMemory(fragment,reply.role_id,tuple({canonical(r):r for r in learner}.values()),provenance)
