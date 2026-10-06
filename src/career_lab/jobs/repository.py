import json
import time
from uuid import uuid4

from sqlalchemy import Column, Float, Integer, String, Table, Text, insert, or_, select, update

from career_lab.errors import CodedValueError
from career_lab.storage.database import job_times, metadata, utc_timestamp
from career_lab.storage.sessions import canonical, digest

jobs = Table("jobs", metadata, Column("id", String, primary_key=True), Column("request_key", String, unique=True, nullable=False),
             Column("kind", String, nullable=False), Column("payload", Text, nullable=False), Column("status", String, nullable=False),
             Column("attempt", Integer, nullable=False), Column("lease_until", Float, nullable=False), Column("lease_token", String),
             Column("worker_id", String), Column("result", Text), Column("error", String))


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
                row = conn.execute(select(jobs).where(jobs.c.request_key == key)).mappings().first()
                if row:
                    if row["kind"] != kind or row["payload"] != canonical(payload):
                        raise CodedValueError("job key conflict", code="request_id_reused")
                    return row["id"]
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
            if values.get("status") in {"completed", "failed"}:
                self._record_times(conn, jid, finished_at=utc_timestamp(now))

    def heartbeat(self, jid, token, now=None, lease_seconds=60):
        now = time.time() if now is None else now
        self._change_leased(jid, token, {"lease_until": now + lease_seconds}, now)

    def complete(self, jid, token, result, now=None):
        self._change_leased(jid, token, {"status": "completed", "result": canonical({"output_hash": digest(result), "value": result})}, now)

    def fail(self, job, error, now=None):
        self._change_leased(job["id"], job["lease_token"], {"status": "failed" if job["attempt"] >= 3 else "queued", "error": error}, now)

    def needs_context(self, job, error, now=None):
        """Park v2 work without spending three identical retries; explicit refresh resumes it."""
        self._change_leased(job['id'], job['lease_token'], {'status': 'needs_context', 'error': error}, now)

    def retry_failed(self, jid, now=None):
        """Explicit retries start a fresh attempt budget, fenced from prior leases."""
        with self.db.transaction() as conn:
            row = conn.execute(select(jobs).where(jobs.c.id == jid).with_for_update()).mappings().first()
            if row is None:
                raise KeyError("job not found")
            if row["status"] == "failed":
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
