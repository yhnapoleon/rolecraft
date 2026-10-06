"""Atomic v2 storage and authentication hooks for independently installed modules."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4
import hmac
import hashlib
import json
import secrets
import time
from pydantic import ValidationError

from sqlalchemy import insert, select, update
from career_lab.storage.database import Database
from career_lab.contracts.v2 import *
from .v2_tables import *
from .v2_jobs import JobStoreMixin

OBJECT_MODELS={
    'task':WorkspaceTask,'product':WorkProductVersion,'share':ProductShare,'cycle':RevisionCycle,
    'review':ReviewRequest,'submission':SubmissionV2,'feedback':FeedbackV2,'config':AssistantConfig,
    'test':TestResultV2,'business_request':BusinessRequest,'business_decision':BusinessDecision,
    'role_context':RoleContext,'job_context':JobContextSnapshot,'scenario_state':ScenarioStateV2,
}

class ObjectWrite(V2):
    ref: ObjectRef
    expected_head: NonNegativeInt
    content: dict[str, JsonValue]
    visible_to: tuple[str, ...] = ('learner',)
    dependencies: tuple[ObjectRef, ...] = ()

class EventDraft(V2):
    type: Identifier
    visible_to: tuple[str, ...]
    refs: tuple[ObjectRef, ...] = ()
    data: dict[str, JsonValue] = {}

class JobRequest(V2):
    name: Identifier
    command: Command
    sources: tuple[ObjectRef,...] = ()
    context_hash: Hash
    head_dependencies: tuple[ObjectRef,...] = ()
    state_dependencies: tuple[Literal['config_version','resources','applied_milestones','status','cycle_id'],...] = ()

@dataclass(frozen=True)
class Mutation:
    writes: tuple[ObjectWrite, ...] = ()
    events: tuple[EventDraft, ...] = ()
    state_changes: dict = field(default_factory=dict)
    result: dict = field(default_factory=dict)
    # Resource changes can only come from an installed deterministic approval policy.
    decision: BusinessDecision | None = None
    jobs: tuple[JobRequest,...] = ()
    refresh_job: str | None = None

class TransactionResult(V2):
    transaction_id: Identifier
    boundary: ActionBoundary
    executor: Executor
    state: WorldStateV2
    objects: tuple[ObjectRef, ...]
    events: tuple[StoredEvent, ...]
    result: dict[str, JsonValue]
    replayed: bool = False

@dataclass(frozen=True)
class TransactionView:
    state: WorldStateV2
    bindings: SessionBindings
    objects: tuple[StoredObject, ...]
    private_scenario_state: ScenarioStateV2 | None = field(default=None,repr=False)
    current_cycle: StoredObject | None = field(default=None,repr=False)
    def get(self,ref: ObjectRef) -> StoredObject:
        found=next((x for x in self.objects if x.ref==ref),None)
        if found is None:raise ProtocolError('object_not_found',status=404)
        return found

class V2Store(JobStoreMixin):
    def __init__(self, url_or_db):
        self.db=url_or_db if isinstance(url_or_db,Database) else Database(url_or_db)
        # v2 table definitions are registered before this additive create_all.
        from career_lab.jobs.repository import jobs as queue
        metadata.create_all(self.db.engine)
        self.object_models=dict(OBJECT_MODELS)
        self.reference_resolvers={}
        self.contextual_reference_resolvers=set()

    def register_reference_resolver(self,kind,resolver,*,contextual=False):
        if kind in self.object_models or kind in self.reference_resolvers:raise ValueError('reference kind already registered')
        self.reference_resolvers[kind]=resolver
        if contextual:self.contextual_reference_resolvers.add(kind)

    def _external(self,c,sid,revision=None):
        q=select(v2_external_refs).where(v2_external_refs.c.session_id==sid)
        if revision is not None:q=q.where(v2_external_refs.c.created_revision<=revision)
        return tuple(ExternalReference.model_validate_json(x['record']) for x in c.execute(q).mappings())

    def register_object(self,kind,model):
        if kind in self.object_models or kind in self.reference_resolvers:raise ValueError('reference kind already registered')
        if not issubclass(model,V2):raise TypeError('object model must be v2')
        self.object_models[kind]=model

    def _row(self,c,sid):
        r=c.execute(select(v2_sessions).where(v2_sessions.c.id==sid).with_for_update()).mappings().first()
        if r is None:raise ProtocolError('session_not_found',status=404)
        return r

    def contains(self,sid):
        with self.db.engine.connect() as c:return c.execute(select(v2_sessions.c.id).where(v2_sessions.c.id==sid)).first() is not None

    def _credential(self,c,context,token):
        c.execute(insert(v2_credentials).values(id=context.credential_id,session_id=context.session_id,token_hash=digest(token),context=canonical(context),revoked=0))

    def create_session(self,bindings:SessionBindings,config:AssistantConfig,resources:dict,*,session_id=None,token=None,scenario_state=None):
        sid=session_id or uuid4().hex;token=token or secrets.token_urlsafe(32);cycle=uuid4().hex
        state=WorldStateV2(session_id=sid,business_seq=0,workspace_revision=0,storage_revision=0,cycle_id=cycle,resources=resources)
        owner=AuthContext(session_id=sid,actor_id='learner',executor=Executor(id='human:'+sid,kind='human'),capabilities=('read','act','submit','delegate'),credential_id=uuid4().hex)
        config=AssistantConfig.model_validate(config.model_dump(mode='json')|{'session_id':sid,'config_version':0,'version':1})
        cyc=RevisionCycle(id=cycle,session_id=sid,opened_at=VersionPoint(**state.model_dump(include={'business_seq','workspace_revision','storage_revision'})),base_state_ref=digest(state))
        with self.db.transaction() as c:
            c.execute(insert(v2_sessions).values(id=sid,bindings=canonical(bindings),state=canonical(state),storage_revision=0))
            self._credential(c,owner,token)
            c.execute(insert(v2_snapshots).values(session_id=sid,storage_revision=0,state=canonical(state)))
            for kind,oid,content,cv in [('config',config.id,config.model_dump(mode='json'),0),('cycle',cycle,cyc.model_dump(mode='json'),None)]:
                ref=ObjectRef(session_id=sid,kind=kind,object_id=oid,version=1,config_version=cv)
                self._put(c,StoredObject(ref=ref,content=content,visible_to=('learner',),created_storage_revision=0))
            if scenario_state is not None:
                config_ref=ObjectRef(session_id=sid,kind='config',object_id=config.id,version=1,config_version=0)
                scenario_state=ScenarioStateV2.model_validate(scenario_state.model_dump(mode='json')|{'session_id':sid,'version':1,'current_config':config_ref.model_dump(mode='json')})
                ref=ObjectRef(session_id=sid,kind='scenario_state',object_id=scenario_state.id,version=1)
                if ref.object_id in {config.id,cycle}:raise ProtocolError('object_identity_conflict')
                self._put(c,StoredObject(ref=ref,content=scenario_state.model_dump(mode='json'),visible_to=('system',),dependencies=(config_ref,),created_storage_revision=0))
        return state,token

    def _auth(self,c,auth:AuthContext,capability=None,operation=None,object_ids=()):
        r=c.execute(select(v2_credentials).where(v2_credentials.c.id==auth.credential_id,v2_credentials.c.session_id==auth.session_id).with_for_update()).mappings().first()
        if r is None or r['revoked'] or canonical(auth)!=r['context']:
            raise ProtocolError('credential_revoked_or_invalid',status=403)
        if auth.expires_at is not None and auth.expires_at<=datetime.now(timezone.utc):raise ProtocolError('credential_expired',status=403)
        if 'research' in auth.capabilities and capability not in {None,'read','research'}:raise ProtocolError('research_read_only',status=403)
        if capability and capability not in auth.capabilities:raise ProtocolError('capability_forbidden',status=403)
        if operation and auth.allowed_actions is not None and operation not in auth.allowed_actions:raise ProtocolError('action_forbidden',status=403)
        if auth.allowed_objects is not None and any(not self._object_in_scope(c,auth,x) for x in object_ids):raise ProtocolError('object_not_found',status=404)
        return auth

    def _object_in_scope(self,c,auth,object_id):
        if auth.allowed_objects is None or object_id in auth.allowed_objects:return True
        if auth.executor.delegation_id is None:return False
        rows=c.execute(select(v2_objects.c.record).where(v2_objects.c.session_id==auth.session_id,v2_objects.c.id==object_id).order_by(v2_objects.c.version)).scalars().all()
        if not rows:return False
        first_record=StoredObject.model_validate_json(rows[0]);latest=StoredObject.model_validate_json(rows[-1]).content
        if first_record.creator!=auth.executor:return False
        if first_record.ref.kind in {'test','review','submission','business_request','business_decision','feedback'}:return True
        return first_record.ref.kind=='product' and (latest.get('task') or {}).get('object_id') in auth.create_under_tasks

    def authenticate(self,sid,token):
        with self.db.engine.connect() as c:
            r=c.execute(select(v2_credentials).where(v2_credentials.c.session_id==sid,v2_credentials.c.token_hash==digest(token))).mappings().first()
            if r is None:raise ProtocolError('token_invalid',status=401)
            return self._auth(c,AuthContext.model_validate_json(r['context']))

    def authorize(self,auth,capability,operation=None,object_ids=()):
        with self.db.engine.connect() as c:return self._auth(c,auth,capability,operation,object_ids)

    def issue_delegation(self,owner:AuthContext,grant:DelegationGrant):
        with self.db.transaction() as c:
            self._auth(c,owner,'delegate')
            key=c.execute(select(v2_credentials.c.token_hash).where(v2_credentials.c.id==owner.credential_id)).scalar_one()
            token=hmac.new(key.encode(),canonical(grant).encode(),hashlib.sha256).hexdigest()
            if grant.session_id!=owner.session_id or grant.actor_id!=owner.actor_id or not set(grant.capabilities)<=set(owner.capabilities) or grant.revoked:
                raise ProtocolError('delegation_escalation',status=403)
            if grant.executor.kind!='external_agent' or grant.executor.delegation_id!=grant.id:raise ProtocolError('delegation_executor_invalid',status=403)
            if grant.expires_at<=datetime.now(timezone.utc):raise ProtocolError('credential_expired',status=403)
            for name in ('allowed_actions','allowed_objects'):
                outer=getattr(owner,name);inner=getattr(grant,name)
                if outer is not None and (inner is None or not set(inner)<=set(outer)):raise ProtocolError('delegation_escalation',status=403)
            if grant.allowed_objects is not None and not set(grant.create_under_tasks)<=set(grant.allowed_objects):raise ProtocolError('delegation_scope_invalid',status=403)
            if owner.allowed_objects is not None and not set(grant.create_under_tasks)<=set(owner.create_under_tasks):raise ProtocolError('delegation_escalation',status=403)
            if owner.expires_at and grant.expires_at>owner.expires_at:raise ProtocolError('delegation_escalation',status=403)
            context=AuthContext(session_id=owner.session_id,actor_id=grant.actor_id,executor=grant.executor,capabilities=grant.capabilities,allowed_actions=grant.allowed_actions,allowed_objects=grant.allowed_objects,create_under_tasks=grant.create_under_tasks,expires_at=grant.expires_at,credential_id=grant.id)
            previous=c.execute(select(v2_credentials).where(v2_credentials.c.id==grant.id).with_for_update()).mappings().first()
            if previous:
                if previous['revoked'] or previous['context']!=canonical(context) or previous['token_hash']!=digest(token):raise ProtocolError('delegation_id_reused',status=409)
            else:self._credential(c,context,token)
        return token

    def revoke_delegation(self,owner,credential_id):
        with self.db.transaction() as c:
            self._auth(c,owner,'delegate')
            r=c.execute(select(v2_credentials).where(v2_credentials.c.id==credential_id,v2_credentials.c.session_id==owner.session_id)).mappings().first()
            if not r or AuthContext.model_validate_json(r['context']).executor.kind!='external_agent':raise ProtocolError('object_not_found',status=404)
            c.execute(update(v2_credentials).where(v2_credentials.c.id==credential_id).values(revoked=1))

    def research_context(self,sid):
        """Internal trusted research runner only; never mounted in learner HTTP/tools."""
        token=secrets.token_urlsafe(32)
        context=AuthContext(session_id=sid,actor_id='research',executor=Executor(id='research:'+sid,kind='system'),capabilities=('read','research'),credential_id=uuid4().hex)
        with self.db.transaction() as c:self._row(c,sid);self._credential(c,context,token)
        return context

    def reference_agent_token(self,owner):
        """Internal research namespace only; never exposed as a learner delegation option."""
        with self.db.transaction() as c:
            self._auth(c,owner,'delegate')
            cid=digest(['reference-agent',owner.session_id])
            context=AuthContext(session_id=owner.session_id,actor_id='learner',executor=Executor(id='reference:'+owner.session_id,kind='reference_agent'),capabilities=('read','act','submit'),credential_id=cid)
            key=c.execute(select(v2_credentials.c.token_hash).where(v2_credentials.c.id==owner.credential_id)).scalar_one()
            token=hmac.new(key.encode(),canonical(context).encode(),hashlib.sha256).hexdigest()
            previous=c.execute(select(v2_credentials).where(v2_credentials.c.id==cid)).mappings().first()
            if previous:
                if previous['revoked'] or previous['context']!=canonical(context):raise ProtocolError('credential_revoked_or_invalid',status=403)
            else:self._credential(c,context,token)
        return token

    def role_reader(self,sid,role_id):
        """Internal context builder for an installed role; no public credential route."""
        if role_id in {'learner','system','research'}:raise ProtocolError('role_reader_reserved',status=403)
        context=AuthContext(session_id=sid,actor_id=role_id,executor=Executor(id='role:'+role_id,kind='system'),capabilities=('read',),credential_id=uuid4().hex)
        with self.db.transaction() as c:self._row(c,sid);self._credential(c,context,secrets.token_urlsafe(32))
        return context

    def _current_cycle(self,c,sid):
        state=WorldStateV2.model_validate_json(self._row(c,sid)['state'])
        cycles=[x for x in self._records(c,sid) if x.ref.kind=='cycle' and x.ref.object_id==state.cycle_id]
        return max(cycles,key=lambda x:x.ref.version) if cycles else None

    def _scenario_state(self,c,sid,revision=None):
        values=[x for x in self._records(c,sid,revision) if x.ref.kind=='scenario_state']
        return ScenarioStateV2.model_validate(max(values,key=lambda x:x.ref.version).content) if values else None

    def _records(self,c,sid,revision=None):
        q=select(v2_objects.c.record).where(v2_objects.c.session_id==sid)
        if revision is not None:q=q.where(v2_objects.c.created_revision<=revision)
        return tuple(StoredObject.model_validate_json(x) for x in c.execute(q).scalars())

    def _visible(self,record,auth):
        if 'research' in auth.capabilities:return True
        if record.ref.kind=='role_context':
            role_id=record.content['role_id']
            # Historical content cannot turn a reserved actor into a role reader.
            if role_id in {'learner','system','research'} or auth.actor_id in {'learner','system','research'}:return False
            if auth.actor_id!=role_id or auth.executor.kind!='system' or auth.executor.id!='role:'+role_id:return False
        return auth.actor_id in record.visible_to

    def view(self,auth):
        with self.db.transaction() as c:
            self._auth(c,auth,'read');r=self._row(c,auth.session_id)
            records=tuple(x for x in self._records(c,auth.session_id) if self._visible(x,auth) and (self._object_in_scope(c,auth,x.ref.object_id)))
            return TransactionView(WorldStateV2.model_validate_json(r['state']),SessionBindings.model_validate_json(r['bindings']),records,self._scenario_state(c,auth.session_id),self._current_cycle(c,auth.session_id))

    def _reference_window(self,c,sid,ceiling,ref):
        point=VersionPoint(**ceiling.model_dump(include={'business_seq','workspace_revision','storage_revision'}))
        if isinstance(ref,EvidenceRefV2):
            if ref.observed_at_seq>point.business_seq:raise ProtocolError('future_evidence')
            if ref.observed_at_seq<point.business_seq:
                # Only real completed snapshots are windows; never synthesize a
                # state from caller times or a partially emitted event batch.
                rows=c.execute(select(v2_snapshots.c.state).where(v2_snapshots.c.session_id==sid,v2_snapshots.c.storage_revision<=point.storage_revision).order_by(v2_snapshots.c.storage_revision.desc())).scalars()
                state=next((value for raw in rows if (value:=WorldStateV2.model_validate_json(raw)).business_seq==ref.observed_at_seq),None)
                if state is None:raise ProtocolError('reference_window_unavailable',status=409)
                point=VersionPoint(**state.model_dump(include={'business_seq','workspace_revision','storage_revision'}))
        return point

    def _resolve_reference(self,c,auth,ref,ceiling,bindings):
        self._auth(c,auth,'read',object_ids=(ref.object_id,))
        if ref.session_id!=auth.session_id:raise ProtocolError('object_not_found',status=404)
        resolver=self.reference_resolvers.get(ref.kind)
        if resolver is None:raise ProtocolError('reference_provider_unavailable',status=503)
        point=VersionPoint(**ceiling.model_dump(include={'business_seq','workspace_revision','storage_revision'}))
        if isinstance(ref,EvidenceRefV2) and ref.observed_at_seq>point.business_seq:raise ProtocolError('future_evidence')
        if ref.kind in self.contextual_reference_resolvers:
            point=self._reference_window(c,auth.session_id,ceiling,ref)
            scenario=self._scenario_state(c,auth.session_id,point.storage_revision)
            if scenario is None:raise ProtocolError('reference_context_required',status=503)
            resolved=resolver(auth,ref,point,bindings,scenario_state=scenario)
        else:
            resolved=resolver(auth,ref,point,bindings)
        resolved=ExternalReference.model_validate(resolved.model_dump(mode='json'))
        bare=ObjectRef.model_validate({k:v for k,v in ref.model_dump(mode='json').items() if k in ObjectRef.model_fields})
        if resolved.ref!=bare:raise ProtocolError('external_reference_mismatch')
        return resolved

    def resolve_reference(self,auth,ref:ObjectRef,*,storage_revision=None):
        """Public read-only exact-source validation, always with current credentials.

        Contextual resolvers receive only authoritative scenario state at a real
        persisted window. No resolver calls the database or caches session state.
        """
        with self.db.transaction() as c:
            self._auth(c,auth,'read',object_ids=(ref.object_id,));row=self._row(c,auth.session_id)
            state=WorldStateV2.model_validate_json(row['state'])
            if storage_revision is not None:
                if storage_revision>state.storage_revision:raise ProtocolError('reference_window_unavailable',status=409)
                raw=c.execute(select(v2_snapshots.c.state).where(v2_snapshots.c.session_id==auth.session_id,v2_snapshots.c.storage_revision==storage_revision)).scalar_one_or_none()
                if raw is None:raise ProtocolError('reference_window_unavailable',status=409)
                state=WorldStateV2.model_validate_json(raw)
            return self._resolve_reference(c,auth,ref,state,SessionBindings.model_validate_json(row['bindings']))

    def can_reference(self,auth,ref:ObjectRef):
        with self.db.transaction() as c:
            self._auth(c,auth,'read',object_ids=(ref.object_id,))
            if ref.session_id!=auth.session_id:raise ProtocolError('object_not_found',status=404)
            row=self._row(c,auth.session_id);state=WorldStateV2.model_validate_json(row['state'])
            if ref.kind in self.reference_resolvers:
                self._resolve_reference(c,auth,ref,state,SessionBindings.model_validate_json(row['bindings']))
                return True
            bare=ObjectRef.model_validate({k:v for k,v in ref.model_dump(mode='json').items() if k in ObjectRef.model_fields})
            record=next((x for x in self._records(c,auth.session_id) if x.ref==bare),None)
            if record is None or not self._visible(record,auth):raise ProtocolError('object_not_found',status=404)
            return True

    def read(self,auth,ref:ObjectRef,*,storage_revision=None):
        self.authorize(auth,'read',object_ids=(ref.object_id,))
        if ref.session_id!=auth.session_id:raise ProtocolError('object_not_found',status=404)
        with self.db.transaction() as c:
            self._auth(c,auth,'read',object_ids=(ref.object_id,))
            # A revoked credential or share cannot regain access by requesting the past.
            records=self._records(c,auth.session_id,storage_revision)
            rec=next((x for x in records if x.ref==ref),None)
            if rec is None or not self._visible(rec,auth):raise ProtocolError('object_not_found',status=404)
            return rec

    def read_shared_product(self,auth,share_ref:ObjectRef):
        with self.db.transaction() as c:
            self._auth(c,auth,'read',object_ids=(share_ref.object_id,))
            records=self._records(c,auth.session_id)
            shares=[x for x in records if x.ref.kind=='share' and x.ref.object_id==share_ref.object_id]
            if not shares:raise ProtocolError('object_not_found',status=404)
            current=max(shares,key=lambda x:x.ref.version);share=ProductShare.model_validate(current.content)
            if share_ref.session_id!=auth.session_id or share.recipient_role!=auth.actor_id or share.revoked_at is not None:raise ProtocolError('object_not_found',status=404)
            self._auth(c,auth,'read',object_ids=(share.product.object_id,))
            return next((x for x in records if x.ref==share.product),None) or self._not_found()

    def _not_found(self):raise ProtocolError('object_not_found',status=404)

    def _put(self,c,record:StoredObject):
        ref=record.ref
        c.execute(insert(v2_objects).values(session_id=ref.session_id,kind=ref.kind,id=ref.object_id,version=ref.version,record=canonical(record),created_revision=record.created_storage_revision))
        head=c.execute(select(v2_heads).where(v2_heads.c.session_id==ref.session_id,v2_heads.c.kind==ref.kind,v2_heads.c.id==ref.object_id)).first()
        if head:c.execute(update(v2_heads).where(v2_heads.c.session_id==ref.session_id,v2_heads.c.kind==ref.kind,v2_heads.c.id==ref.object_id).values(version=ref.version))
        else:c.execute(insert(v2_heads).values(session_id=ref.session_id,kind=ref.kind,id=ref.object_id,version=ref.version))
        for dep in record.dependencies:
            c.execute(insert(v2_relations).values(session_id=ref.session_id,source_kind=ref.kind,source_id=ref.object_id,source_version=ref.version,target_kind=dep.kind,target_id=dep.object_id,target_version=dep.version))

    def execute(self,auth:AuthContext,command:Command,handler,*,capability='act',fault=None,approval_policy=None,expected_storage_revision=None,worker_fence=None,derived_subject=None,job_context=None):
        # Callbacks compute a plan inside the locked transaction; no model/network IO.
        if capability=='read':raise ProtocolError('read_capability_cannot_write',status=403)
        command=Command.model_validate(command.model_dump(mode='json'))
        fp=digest({'command':command.model_dump(mode='json'),'executor':auth.executor.model_dump(mode='json'),'actor':auth.actor_id,'credential_id':auth.credential_id})
        with self.db.transaction() as c:
            self._auth(c,auth,capability,command.operation);row=self._row(c,auth.session_id)
            prior=c.execute(select(v2_transactions).where(v2_transactions.c.session_id==auth.session_id,v2_transactions.c.request_id==command.request_id)).mappings().first()
            if prior:
                if not hmac.compare_digest(prior['fingerprint'],fp):raise ProtocolError('request_id_reused',status=409)
                return TransactionResult.model_validate_json(prior['result']).model_copy(update={'replayed':True})
            state=WorldStateV2.model_validate_json(row['state'])
            if expected_storage_revision is not None and state.storage_revision!=expected_storage_revision:raise ProtocolError('context_stale',status=409)
            bindings=SessionBindings.model_validate_json(row['bindings'])
            if job_context is not None:
                self._validate_job_commit(c,auth,command,job_context,worker_fence,capability)
            elif state.business_seq!=command.expected_version or state.workspace_revision!=command.expected_workspace_revision:raise ProtocolError('version_conflict',status=409)
            records=self._records(c,auth.session_id)
            allowed=tuple(x for x in records if self._visible(x,auth) and (self._object_in_scope(c,auth,x.ref.object_id)))
            mutation=handler(TransactionView(state,bindings,allowed,self._scenario_state(c,auth.session_id),self._current_cycle(c,auth.session_id)),command,auth)
            if not isinstance(mutation,Mutation):raise TypeError('handler must return Mutation')
            if job_context is not None and (mutation.state_changes or mutation.decision or mutation.jobs or mutation.refresh_job):raise ProtocolError('async_state_change_forbidden',status=403)
            refreshing=mutation.refresh_job is not None
            if refreshing and (mutation.writes or mutation.events or mutation.state_changes or mutation.jobs or mutation.decision):raise ProtocolError('job_refresh_only',status=403)
            if set(mutation.state_changes)-{'status','cycle_id','config_version','applied_milestones'}:raise ProtocolError('state_field_forbidden',status=403)
            derived_feedback=self._derived_feedback(c,auth,mutation,derived_subject,records,bindings)
            if state.status=='submitted' and command.operation!='begin_revision' and not derived_feedback and not refreshing:raise ProtocolError('session_submitted')
            if state.status=='paused' and command.operation!='resume' and not derived_feedback and not refreshing:raise ProtocolError('session_paused')
            txn=uuid4().hex;sr=state.storage_revision+1;wr=state.workspace_revision+bool(mutation.writes);seq=state.business_seq
            planned=[]
            for write in mutation.writes:
                ref=write.ref
                parent=write.content.get('task') or {}
                scoped_creation=ref.kind=='product' and write.expected_head==0 and ref.version==1 and parent.get('kind')=='task' and parent.get('session_id')==auth.session_id and parent.get('object_id') in auth.create_under_tasks
                derived_creation=write.expected_head==0 and ref.version==1 and ref.kind in {'test','review','business_request','business_decision','feedback','submission'}
                if ref.kind=='submission' and capability!='submit':derived_creation=False
                structural_cycle=ref.kind=='cycle' and ref.object_id==state.cycle_id and capability=='submit'
                if ref.kind!='scenario_state' and not scoped_creation and not derived_creation and not structural_cycle:self._auth(c,auth,object_ids=(ref.object_id,))
                if ref.session_id!=auth.session_id:raise ProtocolError('object_not_found',status=404)
                if any(x.ref.object_id==ref.object_id and x.ref.kind!=ref.kind for x in (*records,*planned)):raise ProtocolError('object_identity_conflict',status=409)
                existing=[x for x in (*records,*planned) if x.ref.kind==ref.kind and x.ref.object_id==ref.object_id]
                head=max([x.ref.version for x in existing],default=0)
                if head!=write.expected_head or ref.version!=head+1:
                    code='job_result_identity_conflict' if job_context is not None and write.expected_head==0 and head>0 else 'object_version_conflict'
                    raise ProtocolError(code,status=409)
                if existing and ref.kind!='scenario_state' and not self._visible(max(existing,key=lambda x:x.ref.version),auth):raise ProtocolError('object_not_found',status=404)
                model=self.object_models.get(ref.kind)
                if model is None:raise ProtocolError('object_kind_unavailable',status=503)
                try:obj=model.model_validate(write.content)
                except ValidationError as exc:raise ProtocolError('module_object_invalid',status=503) from exc
                content=obj.model_dump(mode='json')
                if job_context is not None:
                    if ref.kind=='cycle':raise ProtocolError('async_cycle_write_forbidden',status=403)
                    cycle_data=content.get('cycle')
                    if ref.kind=='product' or (isinstance(cycle_data,dict) and cycle_data.get('kind')=='cycle'):
                        target_cycle=ObjectRef.model_validate(cycle_data);current_cycle=self._current_cycle(c,auth.session_id)
                        if current_cycle is None or target_cycle!=current_cycle.ref or current_cycle.content['status']!='open':raise ProtocolError('job_output_cycle_closed',status=409)
                if structural_cycle and existing:
                    original=max(existing,key=lambda x:x.ref.version).content
                    if any(content[k]!=original[k] for k in original if k not in {'version','status'}) or content['status']!='submitted':raise ProtocolError('cycle_scope_invalid',status=403)
                if ref.kind=='product' and set(write.visible_to)!={'learner'}:raise ProtocolError('product_requires_share',status=403)
                if ref.kind=='role_context':
                    if content['role_id'] in {'learner','system','research'} or not write.visible_to or not set(write.visible_to)<={'system',content['role_id']}:raise ProtocolError('role_context_private',status=403)
                    if existing and any(x.content['role_id']!=content['role_id'] for x in existing):raise ProtocolError('role_context_identity_immutable',status=409)
                if ref.kind=='config' and content['config_version']!=ref.config_version:raise ProtocolError('config_reference_mismatch')
                if ref.kind=='business_request' and existing:
                    original=min(existing,key=lambda x:x.ref.version).content
                    if content['basis']!=original['basis']:raise ProtocolError('request_basis_immutable',status=409)
                if ref.kind=='business_request' and content['basis']['config']['session_id']!=auth.session_id:raise ProtocolError('object_session_mismatch')
                if ref.kind=='share' and existing:
                    original=min(existing,key=lambda x:x.ref.version).content
                    if any(content[k]!=original[k] for k in ('product','recipient_role','shared_at','question','purpose')):raise ProtocolError('share_identity_immutable',status=409)
                if ref.kind=='scenario_state':
                    if set(write.visible_to)!={'system'}:raise ProtocolError('scenario_state_private',status=403)
                    previous=max(existing,key=lambda x:x.ref.version).content if existing else {}
                    if auth.allowed_objects is not None:
                        for name in ('source_versions','indexed_versions','material_activation'):
                            before=previous.get(name,{});after=content[name]
                            changed={k for k in set(before)|set(after) if before.get(k)!=after.get(k)}
                            changed={k.rsplit(':',1)[0] if name=='material_activation' else k for k in changed}
                            if not changed<=set(auth.allowed_objects):raise ProtocolError('object_scope_forbidden',status=403)
                validate_reference_times(content,state.business_seq)
                if content.get('session_id')!=auth.session_id:raise ProtocolError('object_session_mismatch')
                actual_id=content.get('product_id') if ref.kind=='product' else content.get('id')
                if actual_id is not None and actual_id!=ref.object_id:raise ProtocolError('object_identity_mismatch')
                if content.get('version',content.get('revision',ref.version))!=ref.version:raise ProtocolError('object_identity_mismatch')
                if content.get('executor') and content['executor']!=auth.executor.model_dump(mode='json'):raise ProtocolError('executor_spoofed',status=403)
                deps=references(content)
                if set(canonical(x) for x in deps)-set(canonical(x) for x in write.dependencies):raise ProtocolError('undeclared_object_reference')
                if ref.kind in {'submission','review'} and content.get('evaluation')!=bindings.evaluation.model_dump(mode='json'):raise ProtocolError('evaluation_binding_mismatch',status=409)
                if ref.kind=='submission' and content.get('scenario')!=bindings.scenario.model_dump(mode='json'):raise ProtocolError('scenario_binding_mismatch',status=409)
                planned.append(StoredObject(creator=auth.executor,ref=ref,content=content,visible_to=write.visible_to,dependencies=write.dependencies,created_storage_revision=sr))
            external={canonical(x.ref):x for x in self._external(c,auth.session_id)}
            # Read-only business actions may have no ObjectWrite. Their verified
            # command/result refs still need an atomic anchor for request recovery.
            validate_reference_times(mutation.result,state.business_seq)
            candidates=[*full_references(command.payload),*full_references(mutation.result)]
            for write in mutation.writes:candidates.extend(full_references(write.content))
            for ref in candidates:
                if ref.kind not in self.reference_resolvers:continue
                resolution=self._resolve_reference(c,auth,ref,state,bindings)
                bare=resolution.ref;key=canonical(bare)
                if key in external and external[key]!=resolution:raise ProtocolError('external_reference_drift',status=409)
                if key not in external:
                    c.execute(insert(v2_external_refs).values(session_id=auth.session_id,kind=bare.kind,id=bare.object_id,version=bare.version,record=canonical(resolution),created_revision=sr))
                external[key]=resolution
            all_records={canonical(x.ref):x for x in records}
            for record in planned:
                if canonical(record.ref) in all_records:raise ProtocolError('object_version_conflict',status=409)
                all_records[canonical(record.ref)]=record
            for record in planned:
                if record.ref.kind=='business_request' and record.content['basis']['mode']=='applied':
                    basis=BusinessBasis.model_validate(record.content['basis']);target=all_records.get(canonical(basis.config_ref))
                    if target is None or target.content!=basis.config.model_dump(mode='json'):raise ProtocolError('request_basis_reference_mismatch',status=409)
                for dep in record.dependencies:
                    if canonical(dep) in external:
                        if dep.kind not in self.reference_resolvers:raise ProtocolError('reference_provider_unavailable',status=503)
                        self._auth(c,auth,'read',object_ids=(dep.object_id,))
                        resolution=self._resolve_reference(c,auth,dep,state,bindings)
                        if resolution!=external[canonical(dep)]:raise ProtocolError('external_reference_drift',status=409)
                        continue
                    target=all_records.get(canonical(dep))
                    if dep.session_id!=auth.session_id or target is None or not self._visible(target,auth):raise ProtocolError('object_not_found',status=404)
                    if not ((dep.kind=='cycle' and dep.object_id==state.cycle_id) or (record.ref.kind=='cycle' and capability=='submit')):self._auth(c,auth,object_ids=(dep.object_id,))
            validate_graph(tuple(all_records.values()),external_keys=set(external))
            resources=state.resources
            if mutation.decision is not None:
                d=mutation.decision
                if approval_policy is None or approval_policy(TransactionView(state,bindings,allowed,self._scenario_state(c,auth.session_id),self._current_cycle(c,auth.session_id)),command,auth)!=d:
                    raise ProtocolError('approval_policy_required',status=403)
                if not any(x.ref.kind=='business_decision' and x.content==d.model_dump(mode='json') for x in planned):raise ProtocolError('decision_not_persisted')
                if d.status in {'approved','accepted'}:resources={**resources,**d.granted}
            # Lifecycle invariants are checked at the common boundary, not left to clients.
            changes=mutation.state_changes
            if 'config_version' in changes and not any(x.ref.kind=='config' and x.ref.config_version==changes['config_version'] for x in planned):raise ProtocolError('config_write_required')
            if changes.get('status')=='submitted':
                if capability!='submit' or not any(x.ref.kind=='submission' for x in planned):raise ProtocolError('submission_required',status=403)
            if state.status=='submitted' and not derived_feedback and not refreshing:
                cycles=[RevisionCycle.model_validate(x.content) for x in planned if x.ref.kind=='cycle']
                if len(cycles)!=1 or not cycles[0].parent_submission or changes.get('status')!='active' or changes.get('cycle_id')!=cycles[0].id:raise ProtocolError('revision_cycle_required')
            emitted=[]
            for draft in mutation.events:
                for ref in draft.refs:
                    if canonical(ref) not in all_records:raise ProtocolError('object_not_found',status=404)
                seq+=1
                emitted.append(StoredEvent(id=uuid4().hex,session_id=auth.session_id,seq=seq,transaction_id=txn,type=draft.type,executor=auth.executor,visible_to=draft.visible_to,refs=draft.refs,data=draft.data))
            new=WorldStateV2.model_validate(state.model_dump(mode='json')|changes|{'business_seq':seq,'workspace_revision':int(wr),'storage_revision':sr,'resources':resources})
            if refreshing:self._refresh_queued_job(c,auth,command,mutation.refresh_job,new)
            for record in planned:self._put(c,record)
            if fault:fault('after_objects')
            for event in emitted:c.execute(insert(v2_events).values(session_id=auth.session_id,seq=event.seq,record=canonical(event)))
            if fault:fault('after_events')
            c.execute(update(v2_sessions).where(v2_sessions.c.id==auth.session_id).values(state=canonical(new),storage_revision=sr))
            c.execute(insert(v2_snapshots).values(session_id=auth.session_id,storage_revision=sr,state=canonical(new)))
            queued=[]
            if mutation.jobs:
                from career_lab.jobs.repository import jobs as queue
                from career_lab.storage.database import job_times,utc_timestamp
                for job in mutation.jobs:
                    if not job.name.startswith('v2.'):raise ProtocolError('job_kind_invalid')
                    source_map={canonical(x):x for x in (*job.sources,*references(job.command.payload),*job.head_dependencies)}
                    sources=tuple(source_map.values())
                    for ref in sources:
                        if canonical(ref) not in all_records or not self._visible(all_records[canonical(ref)],auth):raise ProtocolError('object_not_found',status=404)
                        self._auth(c,auth,object_ids=(ref.object_id,))
                    jid=uuid4().hex
                    context=JobContextSnapshot(session_id=auth.session_id,request_id=job.command.request_id,credential_id=auth.credential_id,actor=auth.executor,action=job.command.operation,as_of=VersionPoint(**new.model_dump(include={'business_seq','workspace_revision','storage_revision'})),context_hash=job.context_hash,sources=sources,head_dependencies=job.head_dependencies,state_dependencies=job.state_dependencies)
                    job_command=Command.model_validate(job.command.model_dump(mode='json')|{'expected_version':new.business_seq,'expected_workspace_revision':new.workspace_revision})
                    payload={'schema_version':2,'context':context.model_dump(mode='json'),'command':job_command.model_dump(mode='json'),'operation':job.name,'capability':capability,'job_id':jid,'origin_request_id':command.request_id}
                    c.execute(insert(queue).values(id=jid,request_key=f'{auth.session_id}:v2:{command.request_id}:{len(queued)}',kind=job.name,payload=canonical(payload),status='queued',attempt=0,lease_until=0))
                    c.execute(insert(job_times).values(id=jid,queued_at=utc_timestamp()))
                    jobref=ObjectRef(session_id=auth.session_id,kind='job_context',object_id=jid,version=1)
                    self._put(c,StoredObject(ref=jobref,content=context.model_dump(mode='json'),visible_to=('learner',),dependencies=sources,created_storage_revision=sr))
                    queued.append(jid)
            output=mutation.result | ({'refreshed_job':mutation.refresh_job} if refreshing else {}) | ({'queued_jobs':queued} if queued else {})
            boundary=ActionBoundary(transaction_id=txn,request_id=command.request_id,start_seq=state.business_seq,end_seq=seq,storage_revision=sr)
            result=TransactionResult(transaction_id=txn,boundary=boundary,executor=auth.executor,state=new,objects=tuple(x.ref for x in planned),events=tuple(emitted),result=output)
            c.execute(insert(v2_transactions).values(session_id=auth.session_id,request_id=command.request_id,fingerprint=fp,result=canonical(result),boundary=canonical(boundary)))
            scope={canonical(r):r for r in (*references(command.payload),*references(mutation.result))}
            for record in planned:
                for r in (record.ref,*record.dependencies):scope[canonical(r)]=r
            for job in mutation.jobs:
                for r in job.sources:scope[canonical(r)]=r
            # Structural cycle/private state bookkeeping is not a grant to unrelated data.
            scope={key:r for key,r in scope.items() if r.kind not in {'cycle','scenario_state','job_context','role_context'}}
            c.execute(insert(v2_request_meta).values(session_id=auth.session_id,request_id=command.request_id,
                credential_id=auth.credential_id,executor=canonical(auth.executor),actor_id=auth.actor_id,
                operation=command.operation,scope_refs=canonical([r.model_dump(mode='json') for r in scope.values()]),job_ids=canonical(queued)))
            if worker_fence:
                from career_lab.jobs.repository import jobs as queue
                jid,lease_token=worker_fence.job_id,worker_fence.lease_token
                lease=c.execute(select(queue).where(queue.c.id==jid).with_for_update()).mappings().first()
                if lease is None or lease['status']!='running' or lease['lease_token']!=lease_token or lease['worker_id']!=worker_fence.worker_id or lease['attempt']!=worker_fence.attempt or lease['lease_until']<=time.time():raise ProtocolError('worker_lease_lost',status=409)
            if fault:fault('before_commit')
            self._auth(c,auth,capability,command.operation)
            return result

    def _derived_feedback(self,c,auth,mutation,subject,records,bindings):
        if subject is None:return False
        if subject.session_id!=auth.session_id or subject.kind not in {'submission','review'}:raise ProtocolError('derived_subject_invalid',status=403)
        self._auth(c,auth,'read',object_ids=(subject.object_id,))
        original=next((x for x in records if x.ref==subject),None)
        if original is None or not self._visible(original,auth):raise ProtocolError('object_not_found',status=404)
        if mutation.events or mutation.state_changes or mutation.decision or mutation.jobs or not mutation.writes:
            raise ProtocolError('derived_feedback_only',status=403)
        for write in mutation.writes:
            if write.ref.kind!='feedback' or write.expected_head!=0 or write.ref.version!=1:raise ProtocolError('derived_feedback_only',status=403)
            feedback=FeedbackV2.model_validate(write.content)
            if feedback.subject!=subject or feedback.session_id!=auth.session_id or feedback.evaluation.model_dump(mode='json')!=original.content['evaluation']:
                raise ProtocolError('derived_feedback_subject_mismatch',status=409)
            if subject not in write.dependencies:raise ProtocolError('derived_feedback_subject_missing')
        return True

    def request_result(self,auth,request_id):
        """Read-only authoritative lookup. Never invokes handlers, models or resolvers."""
        from career_lab.jobs.repository import jobs as queue
        with self.db.engine.connect() as c:
            self._auth(c,auth,'read');self._row(c,auth.session_id)
            def fetch(key):
                meta=c.execute(select(v2_request_meta).where(v2_request_meta.c.session_id==auth.session_id,v2_request_meta.c.request_id==key)).mappings().first()
                txn=c.execute(select(v2_transactions).where(v2_transactions.c.session_id==auth.session_id,v2_transactions.c.request_id==key)).mappings().first()
                if meta is None or txn is None:raise ProtocolError('request_not_found',status=404)
                if not (auth.executor.kind=='human' and auth.actor_id=='learner'):
                    if meta['credential_id']!=auth.credential_id or meta['executor']!=canonical(auth.executor) or meta['actor_id']!=auth.actor_id:
                        raise ProtocolError('request_not_found',status=404)
                self._auth(c,auth,'read',meta['operation'])
                refs=tuple(ObjectRef.model_validate(r) for r in json.loads(meta['scope_refs']))
                self._auth(c,auth,'read',object_ids=tuple(r.object_id for r in refs))
                records={canonical(x.ref):x for x in self._records(c,auth.session_id)}
                external={canonical(x.ref) for x in self._external(c,auth.session_id)}
                for ref in refs:
                    if ref.session_id!=auth.session_id:raise ProtocolError('request_not_found',status=404)
                    record=records.get(canonical(ref))
                    if record is not None:
                        if not self._visible(record,auth):raise ProtocolError('request_not_found',status=404)
                    elif canonical(ref) not in external:raise ProtocolError('request_not_found',status=404)
                result=TransactionResult.model_validate_json(txn['result'])
                if result.boundary.request_id!=key or canonical(result.executor)!=meta['executor']:raise ProtocolError('request_record_invalid',status=409)
                return dict(meta),result
            meta,result=fetch(request_id);links=[]
            for jid in json.loads(meta['job_ids']):
                row=c.execute(select(queue).where(queue.c.id==jid)).mappings().first()
                if row is None:raise ProtocolError('request_record_invalid',status=409)
                payload=json.loads(row['payload'])
                if payload.get('origin_request_id')!=request_id or payload.get('context',{}).get('session_id')!=auth.session_id:raise ProtocolError('request_record_invalid',status=409)
                effect_id=payload['command']['request_id'];effect=None
                try:_,effect=fetch(effect_id)
                except ProtocolError as exc:
                    if exc.code!='request_not_found':raise
                    # Missing effect metadata means unknown; an inaccessible effect must not leak through job.result.
                links.append({'job_id':jid,'origin_request_id':request_id,'effect_request_id':effect_id,'status':row['status'],'effect':effect,'error_code':row['error'],'refresh_count':payload['context'].get('refresh_count',0),'refresh_history':payload['context'].get('refresh_history',[])})
            return meta,result,links

    def replay(self,auth,command,capability='act'):
        self.authorize(auth,capability,command.operation)
        fp=digest({'command':command.model_dump(mode='json'),'executor':auth.executor.model_dump(mode='json'),'actor':auth.actor_id,'credential_id':auth.credential_id})
        with self.db.engine.connect() as c:
            prior=c.execute(select(v2_transactions).where(v2_transactions.c.session_id==auth.session_id,v2_transactions.c.request_id==command.request_id)).mappings().first()
            if prior is None:return None
            if not hmac.compare_digest(prior['fingerprint'],fp):raise ProtocolError('request_id_reused',status=409)
            return TransactionResult.model_validate_json(prior['result']).model_copy(update={'replayed':True})



def reference_values(value):
    if {'source_schema','source_session_id','original_id','original_kind','raw','original_hash'}<=value.keys():
        try:LegacyProvenance.model_validate(value)
        except ValidationError:pass
        else:return [v for k,v in value.items() if k!='raw']
    return value.values()


def references(value):
    result=[]
    if isinstance(value,dict):
        if {'session_id','kind','object_id','version'}<=value.keys():
            result.append(ObjectRef.model_validate({k:v for k,v in value.items() if k in ObjectRef.model_fields}))
        else:
            for v in reference_values(value):result.extend(references(v))
    elif isinstance(value,list):
        for v in value:result.extend(references(v))
    return tuple({canonical(x):x for x in result}.values())

def validate_graph(records,external_keys=frozenset()):
    nodes={canonical(x.ref):x for x in records};done=set();active=set()
    if len(nodes)!=len(records):raise ProtocolError('object_reference_duplicate')
    def visit(key):
        if key in active:raise ProtocolError('object_dependency_cycle')
        if key in done:return
        active.add(key)
        for dep in nodes[key].dependencies:
            k=canonical(dep)
            if k in external_keys:continue
            if k not in nodes:raise ProtocolError('object_reference_missing')
            visit(k)
        active.remove(key);done.add(key)
    for key in nodes:visit(key)


def validate_reference_times(value,business_seq):
    if isinstance(value,dict):
        if 'observed_at_seq' in value and value['observed_at_seq']>business_seq:raise ProtocolError('future_evidence')
        if 'as_of' in value and isinstance(value['as_of'],dict) and value['as_of'].get('business_seq',0)>business_seq:raise ProtocolError('future_evidence')
        for v in reference_values(value):validate_reference_times(v,business_seq)
    elif isinstance(value,list):
        for v in value:validate_reference_times(v,business_seq)


def full_references(value):
    result=[]
    if isinstance(value,dict):
        if {'session_id','kind','object_id','version'}<=value.keys():
            cls=EvidenceRefV2 if 'observed_at_seq' in value else ObjectRef
            result.append(cls.model_validate({k:v for k,v in value.items() if k in cls.model_fields}))
        else:
            for v in reference_values(value):result.extend(full_references(v))
    elif isinstance(value,list):
        for v in value:result.extend(full_references(v))
    return result
