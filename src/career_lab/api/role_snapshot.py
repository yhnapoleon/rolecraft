"""Trusted fixed-job role reads; no public route and no generation activation."""
from dataclasses import replace
from pydantic import ValidationError
from career_lab.contracts.v2 import *
from career_lab.runtime.context_v2 import RoleFrame,KnowledgeEvent,decision_memory
from career_lab.storage.role_memory import (PrivateGeneration,ReceivedShare,RoleMemory,parse_public_reply,memory_from_generation)


def _before(a,b):
    return all(getattr(a,k)<=getattr(b,k) for k in ('business_seq','workspace_revision','storage_revision'))


def activated_reference(ref,state,*,template=False):
    """Authored ledger zero is availability metadata, not session activation."""
    if ref.kind!='material':return ref
    activation=state.material_activation.get(f'{ref.object_id}:{ref.version}')
    if activation is None:return ref
    if ref.valid_from_seq not in {0,activation} or (not template and ref.observed_at_seq<activation):
        raise ProtocolError('reference_time_mismatch',status=409)
    return ref.model_copy(update={'valid_from_seq':activation,
        'observed_at_seq':max(ref.observed_at_seq,activation) if template else ref.observed_at_seq})


def activated_catalog(catalog,state):
    # Only runtime reference coordinates change. Role/version admission still
    # follows the owned projection's actual receipts and received events.
    materials=tuple(m.model_copy(update={'fragments':tuple(f.model_copy(update={'ref':activated_reference(f.ref,state,template=True)}) for f in m.fragments)}) for m in catalog.materials)
    facts=tuple(f.model_copy(update={'source':activated_reference(f.source,state,template=True)}) for f in catalog.facts)
    return replace(catalog,materials=materials,facts=facts)


class FixedRoleSnapshotPort:
    def __init__(self,store,catalog):self.store,self.catalog=store,catalog

    def project_fixed(self,view,auth,role_id):
        role=self.catalog.role(role_id)
        if view.bindings.scenario!=self.catalog.binding:raise ProtocolError('scenario_binding_mismatch',status=409)
        state,records,events=self.store.role_snapshot_records(auth,view,role_id)
        at=VersionPoint(**view.state.model_dump(include={'business_seq','workspace_revision','storage_revision'}))
        notices=[]
        materials={(m.id,m.version) for m in self.catalog.materials}
        for event in events:
            if event.type not in role.event_subscriptions:continue
            sources=[]
            for ref in event.refs:
                if ref.session_id==auth.session_id:
                    sources.append(EvidenceRefV2(**ref.model_dump(),observed_at_seq=event.seq))
            before,after=event.data.get('before_versions'),event.data.get('after_versions')
            if isinstance(before,dict) and isinstance(after,dict):
                for mid,version in after.items():
                    if (type(version) is int and before.get(mid)!=version and (mid,version) in materials
                        and state.material_activation.get(f'{mid}:{version}')==event.seq):
                        sources.append(EvidenceRefV2(session_id=auth.session_id,kind='material',object_id=mid,version=version,observed_at_seq=event.seq,valid_from_seq=event.seq))
            unique={canonical(ref):ref for ref in sources}
            notices.append(KnowledgeEvent(ObjectRef(session_id=auth.session_id,kind='event',object_id=event.id,version=1),event.type,event.seq,tuple(event.visible_to),tuple(unique.values())))
        replies={canonical(row.ref):row for row in records if row.ref.kind=='role_reply'}
        contexts=sorted((row for row in records if row.ref.kind=='role_context'),key=lambda row:(row.created_storage_revision,row.ref.object_id,row.ref.version))
        memories={};receipts={};covered=set()
        for row in contexts:
            try:context=RoleContext.model_validate(row.content)
            except (ValidationError,TypeError,ValueError):raise ProtocolError('role_private_record_invalid',status=409) from None
            if context.session_id!=auth.session_id or context.role_id!=role_id or not _before(context.as_of,at):raise ProtocolError('role_private_record_invalid',status=409)
            audit=context.generation_audit
            if audit is None:
                if context.sourced_memory or context.conversations or context.shared_products:raise ProtocolError('role_history_requires_migration',status=409)
                continue
            if audit.phase!='completed':continue
            reply_record=replies.get(canonical(audit.reply))
            if reply_record is None:raise ProtocolError('role_history_incomplete',status=409)
            reply=parse_public_reply(reply_record.content)
            if (reply.role_id!=role_id or reply.request!=audit.request or reply.executor!=audit.scope.executor
                or reply.as_of!=context.as_of or reply.session_id!=auth.session_id):raise ProtocolError('role_history_identity_invalid',status=409)
            if any(r.role_id!=role_id or not _before(r.received_at,context.as_of) for r in audit.received_shares):raise ProtocolError('role_history_identity_invalid',status=409)
            if any(m.role_id!=role_id for m in audit.memories):raise ProtocolError('role_history_identity_invalid',status=409)
            received=tuple(ReceivedShare(r.share,r.product,r.role_id,r.received_at,r.fragment) for r in audit.received_shares)
            past=tuple(RoleMemory(m.fragment,m.role_id,m.learner_refs,tuple(activated_reference(ref,state) for ref in m.provenance)) for m in audit.memories)
            generation=PrivateGeneration(role_id,audit.reply,context.model_copy(update={'generation_audit':None}),audit.prompt_messages,audit.prompt_hash,audit.history_revision,received,past,audit.refresh_count,audit.attempts,tuple(f.model_copy(update={'ref':activated_reference(f.ref,state)}) for f in audit.used_sources),work_language=self.catalog.work_language)
            memory=memory_from_generation(reply,generation)
            memories[canonical(memory.fragment.ref)]=memory;covered.add(canonical(audit.reply))
            for receipt in received:receipts.setdefault((canonical(receipt.share),canonical(receipt.product)),receipt)
        # Do not silently treat an old unverified conversation as a fresh context.
        if set(replies)-covered:raise ProtocolError('role_history_requires_migration',status=409)
        for row in records:
            if row.ref.kind=='business_decision':
                memory=decision_memory(self.catalog,role_id,row,at,tuple(notices))
                if memory is not None:memories[canonical(memory.fragment.ref)]=memory
        return RoleFrame(auth.session_id,role_id,at,self.catalog.binding,state,tuple(memories.values()),tuple(receipts.values()),tuple(notices),work_language=self.catalog.work_language)
