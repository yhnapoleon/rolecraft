from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, select, update

from career_lab.errors import CodedValueError
from career_lab.jobs.repository import JobRepository, LeaseLost, jobs
from career_lab.storage.database import job_times, utc_timestamp
from career_lab.storage.sessions import SessionStore


@pytest.fixture
def repository(tmp_path):
    return JobRepository(SessionStore(f"sqlite:///{tmp_path / 'jobs.db'}").db)


def exhaust(repository):
    jid = repository.enqueue("feedback", "feedback", {"session_id": "s"}, now=0)
    job = None
    for attempt in range(3):
        job = repository.claim_job("worker", now=attempt + 1)
        repository.fail(job, "generation_failed", now=attempt + 1.5)
    return jid, job


def test_explicit_failed_retry_resets_budget_and_times_and_fences_old_worker(repository):
    jid, old_claim = exhaust(repository)
    failed = repository.get(jid)
    assert failed["status"] == "failed"
    assert failed["finished_at"] == utc_timestamp(3.5)
    # Even stale result content must be removed when explicitly retrying.
    with repository.db.transaction() as conn:
        conn.execute(
            update(jobs).where(jobs.c.id == jid).values(result='{"value": {"stale": true}}')
        )
    queued = repository.retry_failed(jid, now=10)
    assert queued["status"] == "queued"
    assert queued["attempt"] == 0
    assert queued["queued_at"] == utc_timestamp(10)
    assert queued["started_at"] is None
    assert queued["finished_at"] is None
    assert queued["lease_until"] == 0
    for field in ("error", "result", "lease_token", "worker_id"):
        assert queued[field] is None
    assert repository.enqueue("feedback", "feedback", {"session_id": "s"}, now=11) == jid
    assert repository.get(jid)["queued_at"] == utc_timestamp(10)
    fresh_claim = repository.claim_job("new-worker", now=12)
    assert fresh_claim["attempt"] == 1
    with pytest.raises(LeaseLost):
        repository.complete(jid, old_claim["lease_token"], {"old": True}, now=13)
    assert repository.get(jid)["finished_at"] is None
    repository.complete(jid, fresh_claim["lease_token"], {"feedback": "ready"}, now=14)
    result = repository.get(jid)
    assert result["status"] == "completed"
    assert result["result"] == {"feedback": "ready"}
    assert result["queued_at"] == utc_timestamp(10)
    assert result["started_at"] == utc_timestamp(12)
    assert result["finished_at"] == utc_timestamp(14)


@pytest.mark.parametrize("status", ["queued", "running", "completed"])
def test_explicit_retry_leaves_non_failed_jobs_unchanged(repository, status):
    jid = repository.enqueue("feedback", "feedback", {}, now=0)
    if status != "queued":
        claim = repository.claim_job("worker", now=1)
    if status == "completed":
        repository.complete(jid, claim["lease_token"], {"ok": True}, now=2)
    before = repository.get(jid)
    assert repository.retry_failed(jid, now=10) == before
    assert repository.get(jid) == before


def test_enqueue_conflict_preserves_message_and_has_stable_code(repository):
    jid = repository.enqueue("same", "feedback", {}, now=0)
    assert repository.enqueue("same", "feedback", {}, now=20) == jid
    assert repository.get(jid)["queued_at"] == utc_timestamp(0)
    with pytest.raises(CodedValueError, match="^job key conflict$") as error:
        repository.enqueue("same", "feedback", {"other": True}, now=30)
    assert error.value.code == "request_id_reused"


def test_last_lease_expiry_finishes_job_and_reclaim_updates_start_time(repository):
    jid = repository.enqueue("feedback", "feedback", {}, now=0)
    for now in (1, 12, 23):
        repository.claim_job("worker", now=now, lease_seconds=10)
        current = repository.get(jid)
        assert current["queued_at"] == utc_timestamp(0)
        assert current["started_at"] == utc_timestamp(now)
        assert current["finished_at"] is None
    assert repository.claim_job("worker", now=34) is None
    failed = repository.get(jid)
    assert failed["status"] == "failed"
    assert failed["finished_at"] == utc_timestamp(34)
    assert repository.claim_job("worker", now=50) is None
    assert repository.get(jid)["finished_at"] == utc_timestamp(34)


def test_automatic_retry_and_heartbeat_do_not_invent_terminal_times(repository):
    jid = repository.enqueue("feedback", "feedback", {}, now=0)
    claimed = repository.claim_job("worker", now=1)
    repository.heartbeat(jid, claimed["lease_token"], now=2)
    assert repository.get(jid)["started_at"] == utc_timestamp(1)
    repository.fail(claimed, "temporary", now=3)
    result = repository.get(jid)
    assert result["status"] == "queued"
    assert result["finished_at"] is None
    assert result["queued_at"] == utc_timestamp(0)


def test_concurrent_retry_only_refreshes_timestamp_once(repository):
    jid, _ = exhaust(repository)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda now: repository.retry_failed(jid, now=now), (10, 20)))
    after = repository.get(jid)
    assert after["queued_at"] in {utc_timestamp(10), utc_timestamp(20)}
    assert repository.retry_failed(jid, now=30) == after
    assert repository.claim_job("worker", now=31)["attempt"] == 1
    assert repository.claim_job("other-worker", now=32) is None


@pytest.mark.parametrize("operation", ["enqueue", "complete", "retry"])
def test_job_state_and_times_roll_back_together(repository, operation):
    if operation == "complete":
        jid = repository.enqueue("feedback", "feedback", {}, now=0)
        claimed = repository.claim_job("worker", now=1)
        before = repository.get(jid)
    elif operation == "retry":
        jid, _ = exhaust(repository)
        before = repository.get(jid)

    def fail_write(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith(("INSERT INTO job_times ", "UPDATE job_times ")):
            raise RuntimeError("injected metadata failure")

    event.listen(repository.db.engine, "before_cursor_execute", fail_write)
    with pytest.raises(RuntimeError, match="injected"):
        if operation == "enqueue":
            repository.enqueue("feedback", "feedback", {}, now=0)
        elif operation == "complete":
            repository.complete(jid, claimed["lease_token"], {"ok": True}, now=2)
        else:
            repository.retry_failed(jid, now=10)
    event.remove(repository.db.engine, "before_cursor_execute", fail_write)
    if operation == "enqueue":
        with repository.db.engine.connect() as conn:
            assert conn.execute(select(jobs)).first() is None
            assert conn.execute(select(job_times)).first() is None
    else:
        assert repository.get(jid) == before


def test_retry_missing_job_is_not_found(repository):
    with pytest.raises(KeyError, match="job not found"):
        repository.retry_failed("missing")
