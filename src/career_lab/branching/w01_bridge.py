"""Adapter for the hash-pinned W01 r3 snapshot interface.

No public schema is redefined. Import the installed W01 remapper only when
this bridge is selected; all tests pin its immutable archived source.
"""
from pydantic import BaseModel
from career_lab.contracts.v2 import (
    ObjectRef, AssistantConfig, FileRef, Executor, LegacyProvenance,
    VersionPoint, ProtocolError, canonical, digest,
)


def identity_key(kind, oid):
    return canonical(["object",kind,oid])


def parent_prefix(snapshot):
    return digest({"state":snapshot.state.model_dump(mode="json"),
        "objects":[x.model_dump(mode="json") for x in snapshot.objects],
        "events":[x.model_dump(mode="json") for x in snapshot.events],
        "external_references":[x.model_dump(mode="json") for x in getattr(snapshot,"external_references",())]})


def verify_model_literals(original, mapped, mapping, parent, child, *, entity_ref=None):
    """Independent check of typed IDs plus every non-identity field."""
    if isinstance(original,(FileRef,Executor,LegacyProvenance)):
        if original!=mapped:raise ProtocolError("restore_opaque_provenance_changed")
        return
    if isinstance(original,BaseModel):
        if type(original) is not type(mapped):raise ProtocolError("restore_model_type_changed")
        special={}
        if isinstance(original,ObjectRef):
            special={"session_id":child,"object_id":mapping.get(identity_key(original.kind,original.object_id),original.object_id)}
        elif isinstance(original,AssistantConfig):
            special={"session_id":child,"id":mapping[identity_key("config",original.id)]}
        if entity_ref is not None:
            if "session_id" in type(original).model_fields:special["session_id"]=child
            field="product_id" if "product_id" in type(original).model_fields else "id"
            if field in type(original).model_fields:special[field]=mapping[identity_key(entity_ref.kind,entity_ref.object_id)]
        for name in type(original).model_fields:
            if name=="content_hash":continue  # Shared model revalidates the hash after typed refs change.
            a,b=getattr(original,name),getattr(mapped,name)
            if name in special:
                if b!=special[name]:raise ProtocolError("restore_identity_map_mismatch")
            else:verify_model_literals(a,b,mapping,parent,child)
    elif isinstance(original,(tuple,list)):
        if len(original)!=len(mapped):raise ProtocolError("restore_sequence_changed")
        for a,b in zip(original,mapped):verify_model_literals(a,b,mapping,parent,child)
    elif isinstance(original,dict):
        if set(original)!=set(mapped):raise ProtocolError("restore_mapping_changed")
        for key,a in original.items():
            # Plain JsonValue dictionaries remain opaque under the W01 contract.
            if isinstance(a,BaseModel):verify_model_literals(a,mapped[key],mapping,parent,child)
            elif a!=mapped[key]:raise ProtocolError("restore_business_field_changed")
    elif original!=mapped:raise ProtocolError("restore_business_field_changed")


class W01BranchPort:
    mapping_authority="provider"
    idempotent_restore=True

    def __init__(self,native,target_session,source_snapshot):
        try:
            from career_lab.storage.v2_remap import NamespaceRemapper
        except ImportError:
            raise ProtocolError("w01_remapper_not_installed",status=503) from None
        self.native=native;self.target=target_session;self.mapper=NamespaceRemapper
        self.point=VersionPoint(business_seq=source_snapshot.state.business_seq,
            workspace_revision=source_snapshot.state.workspace_revision,
            storage_revision=source_snapshot.state.storage_revision)

    def parent_digest(self,sid):return self.native.parent_digest(sid)

    def restore(self,snapshot,request_id):
        return self.native.restore(snapshot,self.target,request_id)

    def read_child(self,sid):
        current=self.native.store.view(self.native.store.research_context(sid)).state
        point=VersionPoint(business_seq=current.business_seq,workspace_revision=current.workspace_revision,
                           storage_revision=current.storage_revision)
        return self.native.read_snapshot(sid,point)

    def expected_child(self,snapshot,result):
        mapping=result.id_map
        required={identity_key(x.ref.kind,x.ref.object_id) for x in snapshot.objects}
        required.add(identity_key("cycle",snapshot.state.cycle_id))
        required.update(canonical(["event",x.id]) for x in snapshot.events)
        required.update(canonical(["transaction",x.transaction_id]) for x in snapshot.boundaries)
        if required-mapping.keys():raise ProtocolError("restore_map_incomplete")
        namespaces={}
        for key in required:
            parts=__import__("json").loads(key);namespace=tuple(parts[:-1])
            if not mapping[key] or mapping[key] in namespaces.setdefault(namespace,set()):
                raise ProtocolError("restore_map_collision")
            namespaces[namespace].add(mapping[key])
        remap=self.mapper(snapshot.session_id,result.session_id,mapping)
        objects=[]
        for obj in snapshot.objects:
            model=self.native.store.object_models.get(obj.ref.kind)
            if model is None:raise ProtocolError("w01_object_codec_missing",status=503)
            original=model.model_validate(obj.content)
            content=remap.model(original,entity_ref=obj.ref)
            verify_model_literals(original,content,mapping,snapshot.session_id,result.session_id,entity_ref=obj.ref)
            objects.append(type(obj).model_validate(obj.model_dump(mode="json")|{
                "ref":remap.model(obj.ref).model_dump(mode="json"),
                "content":content.model_dump(mode="json"),
                "dependencies":[remap.model(x).model_dump(mode="json") for x in obj.dependencies]}))
        state=remap.model(snapshot.state)
        for name in type(snapshot.state).model_fields:
            if name not in {"session_id","cycle_id"} and getattr(state,name)!=getattr(snapshot.state,name):
                raise ProtocolError("restore_business_state_changed")
        data=snapshot.model_dump(mode="json")
        data.update(session_id=result.session_id,state=state.model_dump(mode="json"),
            objects=[x.model_dump(mode="json") for x in objects],
            events=[remap.model(x).model_dump(mode="json") for x in snapshot.events],
            boundaries=[remap.model(x).model_dump(mode="json") for x in snapshot.boundaries])
        if hasattr(snapshot,"external_references"):
            data["external_references"]=[remap.model(x).model_dump(mode="json") for x in snapshot.external_references]
        data["snapshot_hash"]=digest({k:v for k,v in data.items() if k!="snapshot_hash"})
        return type(snapshot).model_validate(data)

    def verify_result_prefix(self,source,result):
        return getattr(result,"parent_session_id",None)==source.session_id and result.prefix_digest==parent_prefix(source)
