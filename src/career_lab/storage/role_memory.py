"""Public dialogue records and private, sourced generation data.

PrivateGeneration is an in-process plan, never a registered storage kind. Only a
future W01 protected audit port may persist it. Public objects contain no prompt,
private provenance, context hashes or internal fact keys.
"""
from dataclasses import dataclass
from typing import Literal, Protocol
from pydantic import model_validator, ValidationError

from career_lab.contracts.v2 import (
    V2, Identifier, ObjectRef, FileRef, TurnInput, VersionPoint, Executor, PositiveInt,
    DisclosedFragment, EvidenceRefV2, ModelAttemptUsage,
    ProtocolError, RoleContext, ProviderMessage, canonical,
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
class RoleStanceEvidence:
    role_id: str
    reply_ref: ObjectRef
    source_binding: FileRef
    source_field: str
    source_index: int
    quote: str
    assertion_type: Literal["role_opinion"] = "role_opinion"
    verification: Literal["verbatim_match_only"] = "verbatim_match_only"


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
    opinions: tuple[RoleStanceEvidence, ...] = ()
    source_aliases: tuple[tuple[ObjectRef,str], ...] = ()
    stance_state: "RoleStanceState | None" = None
    stance_resolutions: tuple["StanceResolution", ...] = ()
    work_language: Literal["zh", "en"] | None = None
    prompt_template_revision: str | None = None
    language_consistency: Literal["unverified"] = "unverified"
    learner_penalty_allowed: Literal[False] = False


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
    from career_lab.runtime.context_v2 import role_text
    # Existing Chinese c7 audits predate explicit owned language metadata.
    language=generation.work_language if generation.work_language is not None else 'zh'
    text=canonical({"historical_question":reply.question,"historical_reply":reply.text,
                    "meaning":role_text(language,'history_meaning')})
    fragment=DisclosedFragment(ref=EvidenceRefV2(**generation.reply_ref.model_dump(),observed_at_seq=reply.as_of.business_seq),
                              text=text,channel="memory",verification="verified")
    return RoleMemory(fragment,reply.role_id,tuple({canonical(r):r for r in learner}.values()),provenance)


VERSION_AXES=('business_seq','workspace_revision','storage_revision')


def version_point_relation(left,right):
    """Partial order; never lexicographically compare independent revision axes."""
    if not isinstance(left,VersionPoint) or not isinstance(right,VersionPoint):return 'unknown'
    try:
        left=VersionPoint.model_validate(left.model_dump(mode='json'))
        right=VersionPoint.model_validate(right.model_dump(mode='json'))
    except (ValidationError,TypeError,ValueError):return 'unknown'
    a=tuple(getattr(left,k) for k in VERSION_AXES);b=tuple(getattr(right,k) for k in VERSION_AXES)
    if a==b:return 'equal'
    if all(x<=y for x,y in zip(a,b)):return 'before'
    if all(x>=y for x,y in zip(a,b)):return 'after'
    return 'incomparable'


def point_at_or_before(left,right):return version_point_relation(left,right) in {'before','equal'}


@dataclass(frozen=True)
class StanceFactReceipt:
    """Verified receipt of a ledger entry, not a claim of G0 or semantic support."""
    fact_id: str
    semantic_hash: str
    source: EvidenceRefV2
    acquired_at_seq: int
    verification: Literal['source_verified'] = 'source_verified'
    acquired_at: VersionPoint | None = None

    @property
    def key(self):return self.fact_id,self.semantic_hash


@dataclass(frozen=True)
class StancePosition:
    key: str
    text: str


@dataclass(frozen=True)
class RoleStanceState:
    session_id: str
    role_id: str
    source_binding: FileRef
    revision: int
    positions: tuple[StancePosition,...]
    established_at: VersionPoint
    considered_facts: tuple[tuple[str,str],...] = ()


@dataclass(frozen=True)
class StanceBasisRef:
    fact_id: str
    source: ObjectRef


@dataclass(frozen=True)
class StanceProposal:
    id: str
    session_id: str
    role_id: str
    parent_revision: int
    position_key: str
    proposed_text: str
    basis: tuple[StanceBasisRef,...]
    proposed_at: VersionPoint
    reason: str = ''  # inert model/user explanation; never an approval signal


@dataclass(frozen=True)
class StanceSupport:
    decision: Literal['supported','unsupported','undetermined']
    semantic_novelty: bool | None
    previous_state_hash: str
    proposal_hash: str
    basis_hash: str
    checked_at: VersionPoint
    verification_ref: FileRef | None
    method: str  # only a server-installed rule or independent review is accepted


class StanceVerifier(Protocol):
    """Server-installed verifier, not a field accepted from the model/caller."""
    def check(self,state,proposal,basis:tuple[StanceFactReceipt,...]) -> StanceSupport: ...


@dataclass(frozen=True)
class StanceChange:
    previous_revision: int
    resulting_revision: int
    position_key: str
    previous_text: str
    new_text: str
    basis: tuple[StanceFactReceipt,...]
    changed_at: VersionPoint
    support: StanceSupport
    effect: Literal['role_stance_only'] = 'role_stance_only'


@dataclass(frozen=True)
class StanceResolution:
    previous_state: RoleStanceState
    proposal: StanceProposal
    state: RoleStanceState
    status: Literal['unchanged','rejected','pending','changed']
    reason_code: str
    basis: tuple[StanceFactReceipt,...] = ()
    support: StanceSupport | None = None
    change: StanceChange | None = None
    learner_penalty_allowed: Literal[False] = False
    language_consistency: Literal['unverified'] = 'unverified'


def _stance_json(value):
    """Internal canonical data for binding a support decision to exact inputs."""
    from dataclasses import is_dataclass,fields
    if hasattr(value,'model_dump'):return value.model_dump(mode='json')
    if is_dataclass(value):return {field.name:_stance_json(getattr(value,field.name)) for field in fields(value)}
    if isinstance(value,(tuple,list)):return [_stance_json(x) for x in value]
    if isinstance(value,dict):return {k:_stance_json(v) for k,v in value.items()}
    return value


def stance_digest(value):
    from career_lab.contracts.v2 import digest
    return digest(_stance_json(value))


def initial_stance(session_id,role,binding,as_of,facts):
    # Declared concerns seed private stance only. They are not claims that the role
    # has said these words, and do not change approval authority or scenario rules.
    positions=tuple(StancePosition(f'{name}:{i}',text) for name in
        ('goals','acceptable_conditions','unacceptable_conditions') for i,text in enumerate(getattr(role,name)))
    return RoleStanceState(session_id,role.id,binding,1,positions,as_of,tuple(sorted({f.key for f in facts})))


def resolve_stance(state,proposal,known_facts,as_of,verifier=None):
    """Mechanical guard. With no trusted semantic support, a proposal stays pending.

    Caller pressure, quoted rationale, duplicate refs and newer version numbers
    never themselves authorize a change. The default runtime has no verifier.
    """
    from dataclasses import replace
    def result(status,code,basis=(),support=None,new=None,change=None):
        return StanceResolution(state,proposal,new or state,status,code,tuple(basis),support,change)
    if ((proposal.session_id,proposal.role_id)!=(state.session_id,state.role_id)
        or proposal.parent_revision!=state.revision):return result('rejected','stance_identity_or_revision_mismatch')
    proposal_order=version_point_relation(proposal.proposed_at,as_of)
    established_order=version_point_relation(state.established_at,proposal.proposed_at)
    if proposal_order=='after':return result('rejected','stance_future_proposal')
    if proposal_order not in {'before','equal'} or established_order not in {'before','equal'}:
        return result('pending','stance_time_unverified')
    old=next((p for p in state.positions if p.key==proposal.position_key),None)
    if old is None or not proposal.proposed_text.strip():return result('rejected','stance_position_invalid')
    if proposal.proposed_text==old.text:return result('unchanged','same_stance')
    receipts={}
    for fact in known_facts:
        if (fact.verification!='source_verified' or fact.source.kind not in {'material','test','business_decision'} or fact.source.session_id!=state.session_id
            or fact.acquired_at_seq!=fact.source.observed_at_seq):continue
        key=(fact.fact_id,canonical(ObjectRef.model_validate({k:v for k,v in fact.source.model_dump(mode='json').items() if k in ObjectRef.model_fields})))
        if key in receipts and receipts[key]!=fact:return result('rejected','stance_ambiguous_basis')
        receipts[key]=fact
    resolved=[]
    for ref in proposal.basis:
        fact=receipts.get((ref.fact_id,canonical(ref.source)))
        if fact is None:return result('rejected','stance_basis_not_known')
        if fact not in resolved:resolved.append(fact)
    if not resolved:return result('rejected','stance_new_fact_required')
    # Content fingerprints exclude version, receipt time and citation ordering.
    novel=[f for f in resolved if f.key not in set(state.considered_facts)]
    if not novel:return result('rejected','stance_new_fact_required',resolved)
    for fact in resolved:
        if (not isinstance(fact.acquired_at,VersionPoint) or fact.acquired_at.business_seq!=fact.acquired_at_seq
            or not point_at_or_before(fact.acquired_at,proposal.proposed_at)):
            return result('pending','stance_acquisition_time_unverified',resolved)
    novelty_orders=[version_point_relation(f.acquired_at,state.established_at) for f in novel]
    if any(order in {'unknown','incomparable'} for order in novelty_orders):
        return result('pending','stance_acquisition_time_unverified',resolved)
    if not any(order=='after' for order in novelty_orders):
        return result('rejected','stance_new_fact_required',resolved)
    if verifier is None:return result('pending','stance_support_unverified',resolved)
    try:support=verifier.check(state,proposal,tuple(resolved))
    except Exception:return result('pending','stance_support_unavailable',resolved)
    if (not isinstance(support,StanceSupport) or not isinstance(support.method,str)
        or support.method not in {'deterministic_rule','independent_review'}
        or not isinstance(support.verification_ref,FileRef) or support.previous_state_hash!=stance_digest(state)
        or support.proposal_hash!=stance_digest(proposal) or support.basis_hash!=stance_digest(tuple(resolved))):
        return result('pending','stance_support_unverified',resolved)
    if not point_at_or_before(proposal.proposed_at,support.checked_at) or not point_at_or_before(support.checked_at,as_of):
        return result('pending','stance_support_time_unverified',resolved,support)
    if support.decision=='unsupported' or support.semantic_novelty is False:
        return result('rejected','stance_support_rejected',resolved,support)
    if support.decision!='supported' or support.semantic_novelty is not True:
        return result('pending','stance_support_unverified',resolved,support)
    positions=tuple(StancePosition(p.key,proposal.proposed_text) if p.key==old.key else p for p in state.positions)
    new=replace(state,revision=state.revision+1,positions=positions,established_at=as_of,
                considered_facts=tuple(sorted(set(state.considered_facts)|{f.key for f in known_facts
                    if f.source.session_id==state.session_id and f.verification=='source_verified' and f.acquired_at_seq==f.source.observed_at_seq and f.acquired_at is not None and point_at_or_before(f.acquired_at,as_of)})))
    change=StanceChange(state.revision,new.revision,old.key,old.text,proposal.proposed_text,tuple(resolved),as_of,support)
    return result('changed','stance_change_supported',resolved,support,new,change)
