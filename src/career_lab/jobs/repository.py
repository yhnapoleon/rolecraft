import json
import time
from uuid import uuid4

from sqlalchemy import Column, Float, Integer, String, Table, Text, insert, or_, select, update, func, cast, inspect

from career_lab.errors import CodedValueError
from career_lab.storage.database import job_times, metadata, utc_timestamp
from career_lab.storage.sessions import canonical, digest

jobs = Table("jobs", metadata, Column("id", String, primary_key=True), Column("request_key", String, unique=True, nullable=False),
             Column("kind", String, nullable=False), Column("payload", Text, nullable=False), Column("status", String, nullable=False),
             Column("attempt", Integer, nullable=False), Column("lease_until", Float, nullable=False), Column("lease_token", String),
             Column("worker_id", String), Column("result", Text), Column("error", String))


def v2_job_actor(conn,kind,payload):
    """Bind session-v2 queue work to its real current credential before row locks.

    Empty unbound v2 payloads retain the historical internal diagnostic behavior;
    they are not valid Gateway JobEnvelopes and gain no session authority.
    """
    if not kind.startswith('v2.'):return None
    if payload=={}:return None
    from career_lab.contracts.v2 import AuthContext,JobContextSnapshot,ProtocolError,canonical as v2_canonical
    from career_lab.storage.v2_tables import v2_credentials
    from datetime import datetime,timezone
    try:context=JobContextSnapshot.model_validate(payload['context'])
    except (KeyError,TypeError,ValueError):raise ProtocolError('job_context_invalid',status=422) from None
    if not inspect(conn).has_table('v2_credentials'):raise ProtocolError('credential_revoked_or_invalid',status=403)
    row=conn.execute(select(v2_credentials).where(v2_credentials.c.id==context.credential_id,v2_credentials.c.session_id==context.session_id).with_for_update()).mappings().first()
    if row is None or row['revoked']:raise ProtocolError('credential_revoked_or_invalid',status=403)
    auth=AuthContext.model_validate_json(row['context'])
    if auth.expires_at is not None and auth.expires_at<=datetime.now(timezone.utc):raise ProtocolError('credential_expired',status=403)
    if auth.executor!=context.actor:raise ProtocolError('executor_spoofed',status=403)
    if auth.allowed_actions is not None and context.action not in auth.allowed_actions:raise ProtocolError('action_forbidden',status=403)
    capability=payload.get('capability','act')
    if capability not in {'read','act','submit'} or capability not in auth.capabilities:raise ProtocolError('capability_forbidden',status=403)
    if 'research' in auth.capabilities:raise ProtocolError('research_read_only',status=403)
    return auth


def delegation_capacity(conn,auth):
    """One SQL count and policy shared by V2Store and the native repository."""
    if auth.executor.kind!='external_agent' and auth.executor.delegation_id is None:return None
    from career_lab.contracts.v2 import AuthContext,DelegationJobCapacity,ProtocolError,canonical as v2_canonical
    from career_lab.storage.v2_tables import v2_credentials,v2_delegation_job_limits
    from datetime import datetime,timezone
    row=conn.execute(select(v2_credentials).where(v2_credentials.c.id==auth.credential_id,v2_credentials.c.session_id==auth.session_id).with_for_update()).mappings().first()
    if row is None or row['revoked'] or v2_canonical(AuthContext.model_validate_json(row['context']))!=v2_canonical(auth):raise ProtocolError('credential_revoked_or_invalid',status=403)
    if auth.expires_at is not None and auth.expires_at<=datetime.now(timezone.utc):raise ProtocolError('credential_expired',status=403)
    limit=conn.execute(select(v2_delegation_job_limits.c.max_active_jobs).where(v2_delegation_job_limits.c.credential_id==auth.credential_id,v2_delegation_job_limits.c.session_id==auth.session_id)).scalar_one_or_none() if inspect(conn).has_table('v2_delegation_job_limits') else None
    limit=2 if limit is None else limit
    if type(limit) is not int or not 1<=limit<=2:raise ProtocolError('delegation_job_policy_invalid',status=503)
    if conn.dialect.name=='postgresql':
        from sqlalchemy.dialects.postgresql import JSONB
        credential=cast(jobs.c.payload,JSONB)['context']['credential_id'].astext
    elif conn.dialect.name=='sqlite':credential=func.json_extract(jobs.c.payload,'$.context.credential_id')
    else:raise ProtocolError('delegation_job_backend_unavailable',status=503)
    active=conn.execute(select(func.count()).select_from(jobs).where(jobs.c.kind.like('v2.%'),jobs.c.status.in_(('queued','running')),credential==auth.credential_id)).scalar_one()
    return DelegationJobCapacity(delegation_id=auth.executor.delegation_id or auth.credential_id,max_active_jobs=limit,active_jobs=active,available_slots=max(0,limit-active),observed_at=datetime.now(timezone.utc))


def require_delegation_capacity(conn,auth,additional):
    if auth is None:return
    from career_lab.contracts.v2 import ProtocolError
    capacity=delegation_capacity(conn,auth)
    if capacity is not None and capacity.active_jobs+additional>capacity.max_active_jobs:
        error=ProtocolError('delegation_job_limit_reached','委托后台任务已达到并发上限。',status=429)
        error.details={'max_active_jobs':capacity.max_active_jobs,'active_jobs':capacity.active_jobs,'requested_jobs':additional}
        raise error


class LeaseLost(ValueError):
    pass


class JobRepository:
    def __init__(self, db):
        self.db = db
        jobs.create(db.engine, checkfirst=True)
        job_times.create(db.engine, checkfirst=True)

    def _record_times(self, conn, jid, **values):
        if conn.execute(select(job_times.c.id).where(job_times.c.id == jid)).first():
            conn.execute(update(job_times).where(job_times.c.id == jid).values(**values))
        else:
            # Legacy jobs have no queued time; retain null rather than inventing one.
            conn.execute(insert(job_times).values(id=jid, **values))

    def enqueue(self, key, kind, payload, now=None):
        from sqlalchemy.exc import IntegrityError
        try:
            with self.db.transaction() as conn:
                actor=v2_job_actor(conn,kind,payload)
                row = conn.execute(select(jobs).where(jobs.c.request_key == key)).mappings().first()
                if row:
                    if row["kind"] != kind or row["payload"] != canonical(payload):
                        raise CodedValueError("job key conflict", code="request_id_reused")
                    return row["id"]
                require_delegation_capacity(conn,actor,1)
                jid = uuid4().hex
                conn.execute(insert(jobs).values(id=jid, request_key=key, kind=kind, payload=canonical(payload), status="queued", attempt=0, lease_until=0))
                self._record_times(conn, jid, queued_at=utc_timestamp(now))
                return jid
        except IntegrityError:
            return self.enqueue(key, kind, payload, now)

    def claim_job(self, worker_id, now=None, lease_seconds=60):
        now = time.time() if now is None else now
        with self.db.transaction() as conn:
            expired = conn.execute(update(jobs).where(jobs.c.status == "running", jobs.c.lease_until <= now, jobs.c.attempt >= 3).values(status="failed", error="lease_expired_after_max_attempts").returning(jobs.c.id)).scalars().all()
            for jid in expired:
                self._record_times(conn, jid, finished_at=utc_timestamp(now))
            query = select(jobs).where(or_(jobs.c.status == "queued", (jobs.c.status == "running") & (jobs.c.lease_until <= now)), jobs.c.attempt < 3).order_by(jobs.c.id).limit(1).with_for_update(skip_locked=True)
            row = conn.execute(query).mappings().first()
            if row is None:
                return None
            changes = {"status": "running", "attempt": row["attempt"] + 1, "worker_id": worker_id, "lease_token": uuid4().hex, "lease_until": now + lease_seconds}
            conn.execute(update(jobs).where(jobs.c.id == row["id"]).values(**changes))
            self._record_times(conn, row["id"], started_at=utc_timestamp(now), finished_at=None)
            return dict(row) | changes | {"payload": json.loads(row["payload"])}

    def _change_leased(self, jid, token, values, now):
        now = time.time() if now is None else now
        with self.db.transaction() as conn:
            result = conn.execute(update(jobs).where(jobs.c.id == jid, jobs.c.lease_token == token, jobs.c.status == "running", jobs.c.lease_until > now).values(**values))
            if result.rowcount != 1:
                raise LeaseLost("worker lease no longer valid")
            if values.get("status") in {"completed", "failed", "needs_context"}:
                self._record_times(conn, jid, finished_at=utc_timestamp(now))

    def heartbeat(self, jid, token, now=None, lease_seconds=60):
        now = time.time() if now is None else now
        self._change_leased(jid, token, {"lease_until": now + lease_seconds}, now)

    def complete(self, jid, token, result, now=None):
        self._change_leased(jid, token, {"status": "completed", "result": canonical({"output_hash": digest(result), "value": result})}, now)

    def fail(self, job, error, now=None, *, retry=True):
        self._change_leased(job["id"], job["lease_token"], {"status": "failed" if not retry or job["attempt"] >= 3 else "queued", "error": error}, now)

    def needs_context(self, job, error, now=None):
        """Park v2 work without spending three identical retries; explicit refresh resumes it."""
        self._change_leased(job['id'], job['lease_token'], {'status': 'needs_context', 'error': error}, now)

    def retry_failed(self, jid, now=None):
        """Explicit retries start a fresh attempt budget, fenced from prior leases."""
        with self.db.transaction() as conn:
            initial=conn.execute(select(jobs).where(jobs.c.id==jid)).mappings().first()
            if initial is None:raise KeyError("job not found")
            # Credential -> job row matches enqueue/refresh and avoids borrowing
            # an owner's budget or deadlocking a simultaneous delegated enqueue.
            actor=v2_job_actor(conn,initial['kind'],json.loads(initial['payload']))
            row = conn.execute(select(jobs).where(jobs.c.id == jid).with_for_update()).mappings().first()
            if row is None:raise KeyError("job not found")
            if row['payload']!=initial['payload'] or row['kind']!=initial['kind']:
                from career_lab.contracts.v2 import ProtocolError
                raise ProtocolError('job_identity_mismatch',status=409)
            if row["status"] == "failed":
                require_delegation_capacity(conn,actor,1)
                conn.execute(update(jobs).where(jobs.c.id == jid).values(
                    status="queued", attempt=0, error=None, result=None,
                    worker_id=None, lease_token=None, lease_until=0,
                ))
                self._record_times(conn, jid, queued_at=utc_timestamp(now), started_at=None, finished_at=None)
        return self.get(jid)

    def get(self, jid):
        with self.db.engine.connect() as conn:
            query = select(jobs, job_times.c.queued_at, job_times.c.started_at, job_times.c.finished_at).select_from(
                jobs.outerjoin(job_times, jobs.c.id == job_times.c.id)
            ).where(jobs.c.id == jid)
            row = conn.execute(query).mappings().first()
            if row is None:
                raise KeyError("job not found")
            result = dict(row)
            result["payload"] = json.loads(result["payload"])
            result["result"] = json.loads(result["result"])["value"] if result["result"] else None
            return result
