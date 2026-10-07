"""Snapshot-bound asynchronous work, with current authorization and explicit refresh.

All mutations run inside V2Store's common transaction. This module owns no queue,
credential or idempotency namespace of its own.
"""
import json
import time
from datetime import datetime, timezone
from sqlalchemy import select, update
from career_lab.contracts.v2 import *
from .v2_tables import v2_credentials, v2_snapshots, v2_transactions


class JobStoreMixin:
    def _job_auth(self, c, context, capability):
        raw=c.execute(select(v2_credentials.c.context).where(v2_credentials.c.id==context.credential_id,v2_credentials.c.session_id==context.session_id)).scalar_one_or_none()
        if raw is None:raise ProtocolError('credential_revoked_or_invalid',status=403)
        auth=self._auth(c,AuthContext.model_validate_json(raw),capability,context.action,[r.object_id for r in (*context.sources,*context.head_dependencies)])
        if auth.executor!=context.actor:raise ProtocolError('executor_spoofed',status=403)
        records=self._records(c,context.session_id)
        for ref in (*context.sources,*context.head_dependencies):
            target=next((x for x in records if x.ref==ref),None)
            if target is None or ref.session_id!=context.session_id or not self._visible(target,auth):raise ProtocolError('object_not_found',status=404)
            if ref.kind in {'feedback','feedback_response'}:
                project,_,_=self._record_projection(c,auth,records)
                if project(target) is None:raise ProtocolError('object_not_found',status=404)
        return auth

    def _job_snapshot(self,c,context):
        raw=c.execute(select(v2_snapshots.c.state).where(v2_snapshots.c.session_id==context.session_id,v2_snapshots.c.storage_revision==context.as_of.storage_revision)).scalar_one_or_none()
        if raw is None:raise ProtocolError('job_snapshot_missing',status=409)
        state=WorldStateV2.model_validate_json(raw)
        if VersionPoint(**state.model_dump(include={'business_seq','workspace_revision','storage_revision'}))!=context.as_of:raise ProtocolError('job_snapshot_mismatch',status=409)
        return state

    def fixed_feedback_subject(self,command):
        if command is None or command.operation!='feedback.create' or 'subject' not in command.payload:return None
        subject=ObjectRef.model_validate(command.payload['subject'])
        return subject if subject.kind in {'submission','review'} else None

    def _check_job_lifecycle(self,c,context,command=None,*,refresh=False):
        # Only fixed-subject feedback may finish after submission or a new cycle.
        subject=self.fixed_feedback_subject(command)
        if subject is not None:
            if subject.session_id!=context.session_id:raise ProtocolError('object_not_found',status=404)
            auth=self._job_auth(c,context,'read')
            self._auth(c,auth,'read',object_ids=(subject.object_id,))
            record=next((x for x in self._records(c,context.session_id) if x.ref==subject),None)
            if record is None or not self._visible(record,auth):raise ProtocolError('object_not_found',status=404)
            return
        records=self._records(c,context.session_id)
        for source in (*context.sources,*context.head_dependencies):
            if source.kind!='share':continue
            shares=[x for x in records if x.ref.kind=='share' and x.ref.object_id==source.object_id]
            if not shares:raise ProtocolError('job_share_unavailable',status=403)
            share=ProductShare.model_validate(max(shares,key=lambda x:x.ref.version).content)
            products=[x for x in records if x.ref.kind=='product' and x.ref.object_id==share.product.object_id]
            if share.revoked_at is not None or not products or max(products,key=lambda x:x.ref.version).content.get('removed_at') is not None:raise ProtocolError('job_share_unavailable',status=403)
        current=WorldStateV2.model_validate_json(self._row(c,context.session_id)['state'])
        if current.status!='active':raise ProtocolError('job_session_inactive',status=409)
        cycle=self._current_cycle(c,context.session_id)
        if cycle is None or cycle.content['status']!='open':raise ProtocolError('job_cycle_closed',status=409)
        if not refresh and current.cycle_id!=self._job_snapshot(c,context).cycle_id:raise ProtocolError('job_cycle_changed',status=409)

    def _check_job_context(self,c,context,command=None):
        self._check_job_lifecycle(c,context,command)
        original=self._job_snapshot(c,context)
        current=WorldStateV2.model_validate_json(self._row(c,context.session_id)['state'])
        if any(getattr(current,key)!=getattr(original,key) for key in context.state_dependencies):raise ProtocolError('context_stale',status=409)
        records=self._records(c,context.session_id)
        for ref in context.head_dependencies:
            versions=[x.ref for x in records if x.ref.kind==ref.kind and x.ref.object_id==ref.object_id]
            if not versions or max(versions,key=lambda x:x.version)!=ref:raise ProtocolError('context_stale',status=409)

    def guard_job(self,context,capability='act',check_context=True,*,command=None):
        with self.db.transaction() as c:
            auth=self._job_auth(c,context,capability)
            if check_context:self._check_job_context(c,context,command)
            return auth

    def job_view(self,auth,context,*,command=None):
        """Read the exact queued/refreshed snapshot, filtered by current permission."""
        from .v2_store import TransactionView
        with self.db.transaction() as c:
            current_auth=self._job_auth(c,context,'read')
            if current_auth!=auth:raise ProtocolError('credential_revoked_or_invalid',status=403)
            self._check_job_context(c,context,command)
            state=self._job_snapshot(c,context)
            row=self._row(c,auth.session_id)
            records=self._records(c,auth.session_id,context.as_of.storage_revision)
            visible=self._project_public_records(c,auth,records)
            scenarios=[x for x in records if x.ref.kind=='scenario_state']
            cycles=[x for x in records if x.ref.kind=='cycle' and x.ref.object_id==state.cycle_id]
            private=ScenarioStateV2.model_validate(max(scenarios,key=lambda x:x.ref.version).content) if scenarios else None
            cycle=max(cycles,key=lambda x:x.ref.version) if cycles else None
            return TransactionView(state,SessionBindings.model_validate_json(row['bindings']),visible,private,cycle,job_context=context)

    def _validate_job_commit(self,c,auth,command,context,claim,capability):
        from career_lab.jobs.repository import jobs
        from career_lab.jobs.worker import WorkerClaim
        if not isinstance(claim,WorkerClaim):raise ProtocolError('worker_claim_required',status=409)
        row=c.execute(select(jobs).where(jobs.c.id==claim.job_id).with_for_update()).mappings().first()
        if row is None or row['status']!='running' or row['lease_until']<=time.time() or (row['lease_token'],row['worker_id'],row['attempt'])!=(claim.lease_token,claim.worker_id,claim.attempt):raise ProtocolError('worker_lease_lost',status=409)
        payload=json.loads(row['payload'])
        if JobContextSnapshot.model_validate(payload['context'])!=context or payload['command']!=command.model_dump(mode='json') or payload['capability']!=capability:raise ProtocolError('job_identity_mismatch',status=409)
        if self._job_auth(c,context,capability)!=auth:raise ProtocolError('credential_revoked_or_invalid',status=403)
        self._check_job_context(c,context,command)

    def refresh_job(self,auth,command,job_id):
        from .v2_store import Mutation
        if command.operation!='jobs.refresh' or command.payload!={'job_id':job_id}:raise ProtocolError('operation_route_mismatch',status=403)
        return self.execute(auth,command,lambda *_:Mutation(refresh_job=job_id))

    def _refresh_queued_job(self,c,auth,command,job_id,new_state):
        from career_lab.jobs.repository import jobs
        from career_lab.storage.database import job_times,utc_timestamp
        row=c.execute(select(jobs).where(jobs.c.id==job_id).with_for_update()).mappings().first()
        if row is None or not row['kind'].startswith('v2.'):raise ProtocolError('job_not_found',status=404)
        payload=json.loads(row['payload']);context=JobContextSnapshot.model_validate(payload['context'])
        if context.session_id!=auth.session_id or (context.credential_id!=auth.credential_id and not (auth.actor_id=='learner' and auth.executor.kind=='human')):raise ProtocolError('job_not_found',status=404)
        original_auth=self._job_auth(c,context,payload['capability'])
        # Caller permission never grants a revoked/narrowed original actor new authority.
        self._auth(c,auth,'act',context.action,[x.object_id for x in context.sources])
        if row['status']!='needs_context':raise ProtocolError('job_refresh_not_available',status=409)
        self._check_job_lifecycle(c,context,Command.model_validate(payload['command']),refresh=True)
        if c.execute(select(v2_transactions.c.request_id).where(v2_transactions.c.session_id==auth.session_id,v2_transactions.c.request_id==context.request_id)).first():raise ProtocolError('job_effect_already_committed',status=409)
        records=self._records(c,auth.session_id)
        heads=[]
        for ref in context.head_dependencies:
            latest=max((x for x in records if x.ref.kind==ref.kind and x.ref.object_id==ref.object_id),key=lambda x:x.ref.version)
            if not self._visible(latest,original_auth):raise ProtocolError('object_not_found',status=404)
            heads.append(latest.ref)
        # Explicit source refs, subject, evaluation and logical command remain unchanged.
        # Only the declared current-context guards and snapshot move forward.
        timestamps=c.execute(select(job_times).where(job_times.c.id==job_id)).mappings().first() or {}
        history=JobRefreshRecord(previous_as_of=context.as_of,reason=row['error'] or 'context_refresh',attempt=row['attempt'],
            queued_at=timestamps.get('queued_at'),started_at=timestamps.get('started_at'),parked_at=timestamps.get('finished_at'),refreshed_at=datetime.now(timezone.utc))
        refreshed=context.model_copy(update={'refresh_history':(*context.refresh_history,history),'as_of':VersionPoint(**new_state.model_dump(include={'business_seq','workspace_revision','storage_revision'})), 'head_dependencies':tuple(heads),'refresh_count':context.refresh_count+1})
        payload['context']=refreshed.model_dump(mode='json')
        prior=[x for x in records if x.ref.kind=='job_context' and x.ref.object_id==job_id]
        version=max(x.ref.version for x in prior)+1
        ref=ObjectRef(session_id=auth.session_id,kind='job_context',object_id=job_id,version=version)
        deps=tuple({canonical(x):x for x in (*refreshed.sources,*refreshed.head_dependencies)}.values())
        self._put(c,StoredObject(ref=ref,content=refreshed.model_dump(mode='json'),visible_to=('learner',),dependencies=deps,created_storage_revision=new_state.storage_revision))
        c.execute(update(jobs).where(jobs.c.id==job_id).values(payload=canonical(payload),status='queued',attempt=0,lease_token=None,lease_until=0,worker_id=None,error=None,result=None))
        c.execute(update(job_times).where(job_times.c.id==job_id).values(queued_at=utc_timestamp(),started_at=None,finished_at=None))
