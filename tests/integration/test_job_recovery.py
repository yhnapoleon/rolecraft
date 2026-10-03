import pytest

from career_lab.jobs.repository import JobRepository, LeaseLost
from career_lab.jobs.worker import Worker
from career_lab.storage.sessions import SessionStore


def test_leases_reclaim_and_stale_worker_fenced(tmp_path):
    store = SessionStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    jobs = JobRepository(store.db)
    jid = jobs.enqueue("k", "echo", {"value": 1}, now=0)
    a = jobs.claim_job("a", now=0, lease_seconds=10)
    assert jobs.claim_job("b", now=5) is None
    b = jobs.claim_job("b", now=11)
    assert b["attempt"] == 2
    with pytest.raises(LeaseLost):
        jobs.complete(jid, a["lease_token"], {"old": 1}, now=12)
    jobs.complete(jid, b["lease_token"], {"ok": 1}, now=12)
    assert jobs.get(jid)["result"] == {"ok": 1}
    assert jobs.enqueue("k", "echo", {"value": 1}) == jid
    with pytest.raises(ValueError):
        jobs.enqueue("k", "echo", {"value": 2})


def test_worker_failure_retry(tmp_path):
    store = SessionStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    jobs = JobRepository(store.db)
    jid = jobs.enqueue("x", "echo", {"value": 2})
    Worker(jobs, {"echo": lambda p: p}).run_once()
    assert jobs.get(jid)["status"] == "completed"


def test_last_attempt_expiry_is_terminal(tmp_path):
    store = SessionStore(f"sqlite:///{tmp_path / 'expiry.db'}")
    jobs = JobRepository(store.db)
    jid = jobs.enqueue("x", "echo", {})
    for now in (0, 11, 22):
        assert jobs.claim_job("worker", now=now, lease_seconds=10)
    assert jobs.claim_job("worker", now=33) is None
    assert jobs.get(jid)["status"] == "failed"
