"""Internal snapshot/restore: never queue a job, call a model, or reuse credentials."""
from uuid import uuid4, uuid5, NAMESPACE_URL
from sqlalchemy import insert, select
from career_lab.contracts.v2 import *
from .v2_store import V2Store, validate_graph
from .v2_remap import NamespaceRemapper, identity_key, event_key, transaction_key
from .v2_tables import *
import json
import secrets
import hashlib
import hmac
from datetime import datetime, timezone

class SnapshotService:
    def __init__(self,store:V2Store):self.store=store

    def export(self,auth:AuthContext,source_digest:str,*,storage_revision=None,fork_seq=None):
        with self.store.db.transaction() as c:
            self.store._auth(c,auth,'research');row=self.store._row(c,auth.session_id)
            current=WorldStateV2.model_validate_json(row['state'])
            sr=current.storage_revision if storage_revision is None else storage_revision
            raw=c.execute(select(v2_snapshots.c.state).where(v2_snapshots.c.session_id==auth.session_id,v2_snapshots.c.storage_revision==sr)).scalar_one_or_none()
            if raw is None:raise ProtocolError('snapshot_revision_unavailable',status=404)
            state=WorldStateV2.model_validate_json(raw)
            boundaries=tuple(ActionBoundary.model_validate_json(x) for x in c.execute(select(v2_transactions.c.boundary).where(v2_transactions.c.session_id==auth.session_id)).scalars())
            boundaries=tuple(sorted((b for b in boundaries if b.storage_revision<=sr),key=lambda x:x.storage_revision))
            if fork_seq is not None and fork_seq!=state.business_seq:raise ProtocolError('not_action_boundary',status=409)
            if sr and (not boundaries or boundaries[-1].storage_revision!=sr or boundaries[-1].end_seq!=state.business_seq):raise ProtocolError('not_action_boundary',status=409)
            records=tuple(sorted(self.store._records(c,auth.session_id,sr),key=lambda x:(x.ref.kind,x.ref.object_id,x.ref.version)))
            external=self.store._external(c,auth.session_id,sr)
            validate_graph(records,external_keys={canonical(x.ref) for x in external}|self.store._event_keys(c,auth.session_id,state))
            events=tuple(StoredEvent.model_validate_json(x) for x in c.execute(select(v2_events.c.record).where(v2_events.c.session_id==auth.session_id,v2_events.c.seq<=state.business_seq).order_by(v2_events.c.seq)).scalars())
            if [x.seq for x in events]!=list(range(1,state.business_seq+1)):raise ProtocolError('snapshot_log_gap',status=409)
            value={'schema_version':2,'id':digest([auth.session_id,sr,source_digest]),'session_id':auth.session_id,'bindings':json.loads(row['bindings']),'state':state.model_dump(mode='json'),'objects':[x.model_dump(mode='json') for x in records],'events':[x.model_dump(mode='json') for x in events],'boundaries':[x.model_dump(mode='json') for x in boundaries],'external_references':[x.model_dump(mode='json') for x in sorted(external,key=lambda x:canonical(x.ref))],'source_digest':source_digest}
            return SnapshotExport.model_validate(value|{'snapshot_hash':digest(value)})

    def restore(self,snapshot:SnapshotExport,*,session_id=None,token=None,request_id=None):
        # Revalidate rather than trust callers' model_copy(update=...) values.
        snapshot=SnapshotExport.model_validate(snapshot.model_dump(mode='json'))
        validate_graph(snapshot.objects,external_keys={canonical(x.ref) for x in snapshot.external_references}|{canonical(ObjectRef(session_id=snapshot.session_id,kind='event',object_id=e.id,version=1)) for e in snapshot.events})
        validate_snapshot_structure(snapshot)
        if any(x.ref.session_id!=snapshot.session_id or x.created_storage_revision>snapshot.state.storage_revision for x in snapshot.objects):raise ProtocolError('snapshot_object_scope')
        if snapshot.state.session_id!=snapshot.session_id:raise ProtocolError('snapshot_session_mismatch')
        sid=session_id or uuid4().hex
        if request_id and token is None:
            with self.store.db.engine.connect() as c:
                rows=c.execute(select(v2_credentials).where(v2_credentials.c.session_id==snapshot.session_id)).mappings().all()
                parent=next((r for r in rows if AuthContext.model_validate_json(r['context']).executor.kind=='human'),None)
                if parent is None:raise ProtocolError('restore_parent_auth_missing',status=403)
                token=hmac.new(parent['token_hash'].encode(),canonical([sid,request_id,snapshot.snapshot_hash]).encode(),hashlib.sha256).hexdigest()
        token=token or secrets.token_urlsafe(32)
        if sid==snapshot.session_id:raise ProtocolError('restore_requires_new_session',status=409)
        local_keys={identity_key(x.ref.kind,x.ref.object_id) for x in snapshot.objects}
        local_keys.add(identity_key('cycle',snapshot.state.cycle_id))
        local_keys.update(transaction_key(x.transaction_id) for x in snapshot.boundaries)
        local_keys.update(event_key(x.id) for x in snapshot.events)
        mapping={key:uuid5(NAMESPACE_URL,canonical([snapshot.snapshot_hash,sid,key])).hex for key in local_keys}
        # Immutable scenario-file IDs live in their own kind/namespace and remain canonical.
        for external in snapshot.external_references:
            key=identity_key(external.ref.kind,external.ref.object_id)
            if key in mapping:raise ProtocolError('snapshot_namespace_collision')
            mapping[key]=external.ref.object_id
        remapper=NamespaceRemapper(snapshot.session_id,sid,mapping)
        restored=[]
        for original in snapshot.objects:
            model=self.store.object_models.get(original.ref.kind)
            if model is None:raise ProtocolError('object_kind_unavailable',status=503)
            content=remapper.model(model.model_validate(original.content),entity_ref=original.ref)
            restored.append(StoredObject.model_validate(original.model_dump(mode='json')|{
                'ref':remapper.model(original.ref).model_dump(mode='json'),
                'content':content.model_dump(mode='json'),
                'dependencies':[remapper.model(r).model_dump(mode='json') for r in original.dependencies],
            }))
        objects=tuple(restored)
        state=remapper.model(snapshot.state)
        events=tuple(remapper.model(x) for x in snapshot.events)
        boundaries=tuple(remapper.model(x) for x in snapshot.boundaries)
        external_references=tuple(remapper.model(x) for x in snapshot.external_references)
        validate_graph(objects,external_keys={canonical(x.ref) for x in external_references}|{canonical(ObjectRef(session_id=sid,kind='event',object_id=e.id,version=1)) for e in events})
        valid_refs={canonical(x.ref) for x in objects}|{canonical(x.ref) for x in external_references}|{canonical(ObjectRef(session_id=sid,kind='event',object_id=e.id,version=1)) for e in events}
        for event in events:
            if event.session_id!=sid or any(canonical(r) not in valid_refs for r in event.refs):raise ProtocolError('snapshot_event_reference_missing')
        if any(x.ref.session_id!=sid or any(r.session_id!=sid for r in x.dependencies) for x in objects):raise ProtocolError('snapshot_object_scope')
        if [x.seq for x in events]!=list(range(1,state.business_seq+1)):raise ProtocolError('snapshot_log_gap')
        owner=AuthContext(session_id=sid,actor_id='learner',executor=Executor(id='human:'+sid,kind='human'),capabilities=('read','act','submit','delegate'),credential_id=uuid4().hex)
        normalized={'state':snapshot.state.model_dump(mode='json'),'objects':[x.model_dump(mode='json') for x in snapshot.objects],'events':[x.model_dump(mode='json') for x in snapshot.events],'external_references':[x.model_dump(mode='json') for x in snapshot.external_references]}
        result=RestoreResult(parent_session_id=snapshot.session_id,session_id=sid,source_snapshot_hash=snapshot.snapshot_hash,id_map=mapping,state=state,prefix_digest=digest(normalized))
        from sqlalchemy.exc import IntegrityError
        try:
            with self.store.db.transaction() as c:
                previous=c.execute(select(v2_restores).where(v2_restores.c.target_session_id==sid)).mappings().first()
                if previous:
                    if not request_id or previous['request_id']!=request_id or previous['snapshot_hash']!=snapshot.snapshot_hash:raise ProtocolError('restore_id_reused',status=409)
                    credentials=c.execute(select(v2_credentials).where(v2_credentials.c.session_id==sid,v2_credentials.c.token_hash==digest(token),v2_credentials.c.revoked==0)).mappings().all()
                    if not any(AuthContext.model_validate_json(r['context']).executor.kind=='human' and (AuthContext.model_validate_json(r['context']).expires_at is None or AuthContext.model_validate_json(r['context']).expires_at>datetime.now(timezone.utc)) for r in credentials):raise ProtocolError('restore_token_conflict',status=409)
                    return RestoreResult.model_validate_json(previous['result']).model_copy(update={'replayed':True}),token
                if c.execute(select(v2_sessions.c.id).where(v2_sessions.c.id==sid)).first():raise ProtocolError('restore_target_exists',status=409)
                from .record_invariants import validate_history

                validate_history(objects)
                c.execute(insert(v2_sessions).values(id=sid,bindings=canonical(snapshot.bindings),state=canonical(state),storage_revision=state.storage_revision))
                self.store._credential(c,owner,token)
                for item in external_references:
                    c.execute(insert(v2_external_refs).values(session_id=sid,kind=item.ref.kind,id=item.ref.object_id,version=item.ref.version,record=canonical(item),created_revision=0))
                # Historical provenance is data; no parent's queued jobs or credentials are copied.
                for record in sorted(objects,key=lambda x:(x.ref.kind,x.ref.object_id,x.ref.version)):self.store._put(c,record)
                for event in events:c.execute(insert(v2_events).values(session_id=sid,seq=event.seq,record=canonical(event)))
                c.execute(insert(v2_snapshots).values(session_id=sid,storage_revision=state.storage_revision,state=canonical(state)))
                # Preserve transaction boundaries without making parent requests replayable.
                for boundary in boundaries:
                    key='restored:'+boundary.transaction_id
                    c.execute(insert(v2_transactions).values(session_id=sid,request_id=key,fingerprint='restored-prefix-not-replayable',result='{}',boundary=canonical(boundary)))
                if request_id:c.execute(insert(v2_restores).values(target_session_id=sid,request_id=request_id,snapshot_hash=snapshot.snapshot_hash,result=canonical(result)))
        except IntegrityError as exc:
            raise ProtocolError('restore_target_exists',status=409) from exc
        return result,token


def validate_snapshot_structure(snapshot):
    previous_seq=0;previous_revision=0;covered=set()
    for b in snapshot.boundaries:
        if b.start_seq!=previous_seq or b.storage_revision<=previous_revision:raise ProtocolError('snapshot_boundary_invalid')
        group=[e for e in snapshot.events if b.start_seq<e.seq<=b.end_seq]
        if len(group)!=b.end_seq-b.start_seq or any(e.transaction_id!=b.transaction_id for e in group):raise ProtocolError('snapshot_boundary_invalid')
        covered.update(e.seq for e in group);previous_seq=b.end_seq;previous_revision=b.storage_revision
    if previous_seq!=snapshot.state.business_seq or previous_revision!=snapshot.state.storage_revision:raise ProtocolError('snapshot_boundary_invalid')
    if covered!=set(range(1,snapshot.state.business_seq+1)):raise ProtocolError('snapshot_log_gap')
    if any(e.session_id!=snapshot.session_id for e in snapshot.events):raise ProtocolError('snapshot_event_scope')


class SnapshotPortAdapter:
    """Trusted research driver adapter; policy code receives only its environment port."""
    def __init__(self,store,source_digest,environment_factory=None,action_models=None):
        self.store=store;self.source_digest=source_digest;self.service=SnapshotService(store)
        self.environment_factory=environment_factory;self._auth={};self._tokens={}
        from career_lab.contracts.v2.discovery import REQUEST_MODELS, public_models
        models=public_models()
        self.action_models={name:models[model] for name,model in REQUEST_MODELS.items()}
        self.action_models.update(action_models or {})
    def _research(self,sid):
        if sid not in self._auth:self._auth[sid]=self.store.research_context(sid)
        return self._auth[sid]
    def export(self,session_id,as_of:VersionPoint):
        snapshot=self.service.export(self._research(session_id),self.source_digest,storage_revision=as_of.storage_revision,fork_seq=as_of.business_seq)
        if snapshot.state.workspace_revision!=as_of.workspace_revision:raise ProtocolError('snapshot_revision_mismatch',status=409)
        return snapshot
    def read_snapshot(self,session_id,as_of):return self.export(session_id,as_of)
    def restore(self,snapshot,session_id,request_id):
        if not request_id:raise ProtocolError('restore_request_id_required')
        result,root_token=self.service.restore(snapshot,session_id=session_id,request_id=request_id)
        if result.session_id!=session_id:raise ProtocolError('restore_target_mismatch',status=409)
        owner=self.store.authenticate(session_id,root_token)
        self._tokens[session_id]=self.store.reference_agent_token(owner)
        return result
    def parent_digest(self,session_id):
        return self.service.export(self._research(session_id),self.source_digest).snapshot_hash
    def remap_action(self,action:ActionProposal,restored:RestoreResult):
        model=self.action_models.get(action.tool)
        if model is None:raise ProtocolError('action_remap_schema_required',status=503)
        typed=model.model_validate(action.arguments)
        mapped=NamespaceRemapper(restored.parent_session_id,restored.session_id,restored.id_map).model(typed)
        return ActionProposal.model_validate(action.model_dump(mode='json')|{'arguments':mapped.model_dump(mode='json')})
    def environment(self,restored):
        if self.environment_factory is None:raise ProtocolError('environment_adapter_unavailable',status=503)
        if restored.session_id not in self._tokens:raise ProtocolError('restore_context_missing',status=409)
        return self.environment_factory(restored,self._tokens[restored.session_id])
