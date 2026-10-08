# Historical ffe4cce RoleReply definitions for isolated legacy-DB regressions only.
"""Sourced dialogue memory stored by the common V2Store transaction plan.

No SQL tables, transaction manager, idempotency keys or queue live in this module.
These module-owned objects are explicitly registered through V2Store.register_object.
"""

from typing import Literal

from career_lab.contracts.v2 import (
    V2,
    Identifier,
    ObjectRef,
    TurnInput,
    VersionPoint,
    Executor,
    Hash,
    NonNegativeInt,
    PositiveInt,
    DisclosedFragment,
    EvidenceRefV2,
    PublicDisclosureRecord,
    ModelAttemptUsage,
    ProtocolError,
    BusinessDecision,
    ProviderMessage,
    canonical,
)
from career_lab.storage.v2_store import ObjectWrite, references


class RoleTurn(V2):
    id: Identifier
    session_id: Identifier
    version: PositiveInt = 1
    input: TurnInput
    as_of: VersionPoint
    executor: Executor


class SpokenEvidence(V2):
    label: Identifier
    source: EvidenceRefV2
    quote: str
    verification: Literal["verified", "model_extracted"]


class RoleReply(V2):
    id: Identifier
    session_id: Identifier
    version: PositiveInt = 1
    role_id: Identifier
    request: ObjectRef
    question: str
    text: str
    status: Literal["completed", "unavailable", "blocked"]
    error_code: str | None = None
    context_hash: Hash
    prompt_hash: Hash
    prompt_messages: tuple[ProviderMessage, ...]
    history_revision: Hash
    as_of: VersionPoint
    model_revision: str
    source_versions: tuple[ObjectRef, ...] = ()
    spoken_evidence: tuple[SpokenEvidence, ...] = ()
    omitted_sources: tuple[ObjectRef, ...] = ()
    attempts: tuple[ModelAttemptUsage, ...] = ()
    executor: Executor


class RoleDisplay(V2):
    id: Identifier
    session_id: Identifier
    version: PositiveInt = 1
    reply: ObjectRef
    as_of: VersionPoint
    executor: Executor


def install_role_storage(store):
    for kind, model in (
        ("role_turn", RoleTurn),
        ("role_reply", RoleReply),
        ("role_display", RoleDisplay),
    ):
        if kind in store.object_models:
            if store.object_models[kind] is not model:
                raise ValueError("incompatible role object registration")
        else:
            store.register_object(kind, model)


def object_write(kind, obj, *, visible_to=("learner",)):
    content = obj.model_dump(mode="json")
    ref = ObjectRef(session_id=obj.session_id, kind=kind, object_id=obj.id, version=obj.version)
    return ObjectWrite(
        ref=ref,
        expected_head=obj.version - 1,
        content=content,
        visible_to=visible_to,
        dependencies=references(content),
    )


def read_role_memory(view, role_id):
    """Historical words prove what was said, never that the claim is world truth."""
    memories = []
    for record in sorted(view.objects, key=lambda x: (x.created_storage_revision, x.ref.object_id)):
        if record.ref.kind == "business_decision":
            decision = BusinessDecision.model_validate(record.content)
            if decision.decider == role_id:
                text = canonical(
                    {
                        "record_kind": "authoritative_business_decision",
                        "status": decision.status,
                        "granted": decision.granted,
                        "countered": decision.countered,
                        "reason": decision.reason,
                        "meaning": "这是已保存的决定。approved/accepted 的 granted 已随事务生效；初始材料中的资源数字不能覆盖此结果。",
                    }
                )
                memories.append(
                    DisclosedFragment(
                        ref=EvidenceRefV2(
                            **record.ref.model_dump(), observed_at_seq=view.state.business_seq
                        ),
                        text=text,
                        channel="memory",
                        verification="verified",
                    )
                )
            continue
        if record.ref.kind != "role_reply":
            continue
        reply = RoleReply.model_validate(record.content)
        if reply.role_id != role_id or reply.status != "completed":
            continue
        if reply.session_id != view.state.session_id:
            raise ProtocolError("object_not_found", status=404)
        text = canonical(
            {
                "historical_question": reply.question,
                "historical_reply": reply.text,
                "meaning": "过去对话原文；其中意见不是新增公司事实",
                "source_versions": [
                    {"kind": r.kind, "version": r.version} for r in reply.source_versions
                ],
            }
        )
        memories.append(
            DisclosedFragment(
                ref=EvidenceRefV2(
                    **record.ref.model_dump(), observed_at_seq=reply.as_of.business_seq
                ),
                text=text,
                channel="memory",
                verification="verified",
            )
        )
    return tuple(memories)


def read_replies(view, role_id=None):
    return tuple(
        RoleReply.model_validate(r.content)
        for r in sorted(view.objects, key=lambda r: (r.created_storage_revision, r.ref.object_id))
        if r.ref.kind == "role_reply" and (role_id is None or r.content.get("role_id") == role_id)
    )
