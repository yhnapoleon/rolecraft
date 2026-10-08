"""Native repository and public Gateway share one delegated database quota."""

from pathlib import Path
import os, json, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from career_lab.contracts import v2 as C
from career_lab.jobs.repository import JobRepository
from career_lab.storage.v2_store import V2Store
from .test_core_wiring_delegation_capacity import agent, enqueue


def payload(store, auth, key):
    point = C.VersionPoint(
        **store.view(auth).state.model_dump(
            include={"business_seq", "workspace_revision", "storage_revision"}
        )
    )
    context = C.JobContextSnapshot(
        session_id=auth.session_id,
        request_id=key,
        credential_id=auth.credential_id,
        actor=auth.executor,
        action="quota.job",
        as_of=point,
        context_hash=C.digest(key),
        sources=(),
    )
    return {"context": context.model_dump(mode="json"), "capability": "act"}


def test_native_enqueue_and_public_enqueue_share_slots_and_replay(foundation):
    store, _, *_ = foundation
    auth, _, _ = agent(foundation)
    repository = JobRepository(store.db)
    body = payload(store, auth, "native")
    jid = repository.enqueue("native", "v2.native_quota", body)
    enqueue(store, auth, "public")
    assert repository.enqueue("native", "v2.native_quota", body) == jid
    with pytest.raises(C.ProtocolError, match="委托后台任务"):
        repository.enqueue("third", "v2.native_quota", payload(store, auth, "third"))
    with pytest.raises(C.ProtocolError):
        enqueue(store, auth, "fourth")
    assert store.delegation_job_capacity(auth).active_jobs == 2


def test_native_failed_retry_checks_capacity_then_is_idempotent(foundation):
    store, _, *_ = foundation
    auth, _, _ = agent(foundation)
    repository = JobRepository(store.db)
    jid = repository.enqueue("native", "v2.native_quota", payload(store, auth, "native"))
    claimed = repository.claim_job("worker")
    repository.fail(claimed, "failed", retry=False)
    enqueue(store, auth, "full", 2)
    before = repository.get(jid)
    with pytest.raises(C.ProtocolError):
        repository.retry_failed(jid)
    assert repository.get(jid) == before
    active = repository.claim_job("worker")
    repository.complete(active["id"], active["lease_token"], {})
    retried = repository.retry_failed(jid)
    assert retried["status"] == "queued" and retried["attempt"] == 0
    assert (
        repository.retry_failed(jid) == retried
        and store.delegation_job_capacity(auth).active_jobs == 2
    )


def test_native_retry_and_new_enqueue_cannot_both_take_last_slot(foundation):
    store, _, *_ = foundation
    auth, token, _ = agent(foundation)
    repository = JobRepository(store.db)
    jid = repository.enqueue("failed", "v2.native_quota", payload(store, auth, "failed"))
    claimed = repository.claim_job("worker")
    repository.fail(claimed, "failed", retry=False)
    enqueue(store, auth, "active")
    barrier = Barrier(2)

    def run(retry):
        local = V2Store(str(store.db.engine.url))
        actor = local.authenticate(auth.session_id, token)
        repo = JobRepository(local.db)
        body = payload(local, actor, "new")
        barrier.wait(timeout=10)
        try:
            if retry:
                repo.retry_failed(jid)
            else:
                repo.enqueue("new", "v2.native_quota", body)
            return "accepted"
        except C.ProtocolError as error:
            return error.code
        finally:
            local.db.engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, (True, False)))
    assert (
        sorted(results) == ["accepted", "delegation_job_limit_reached"]
        and store.delegation_job_capacity(auth).active_jobs == 2
    )


def test_native_bound_jobs_recheck_revocation_and_actor(foundation):
    store, owner, *_ = foundation
    auth, _, grant = agent(foundation)
    repository = JobRepository(store.db)
    body = payload(store, auth, "native")
    forged = {
        **body,
        "context": {**body["context"], "actor": owner.executor.model_dump(mode="json")},
    }
    with pytest.raises(C.ProtocolError, match="executor spoofed"):
        repository.enqueue("forged", "v2.native_quota", forged)
    with pytest.raises(C.ProtocolError, match="job context invalid"):
        repository.enqueue("malformed", "v2.native_quota", {"context": {}})
    jid = repository.enqueue("native", "v2.native_quota", body)
    claimed = repository.claim_job("worker")
    repository.fail(claimed, "failed", retry=False)
    store.revoke_delegation(owner, grant.id)
    with pytest.raises(C.ProtocolError):
        repository.retry_failed(jid)
    with pytest.raises(C.ProtocolError):
        repository.enqueue("native", "v2.native_quota", body)
    assert repository.get(jid)["status"] == "failed"


def test_three_native_repository_processes_share_the_same_credential_lock(foundation, tmp_path):
    store, _, *_ = foundation
    auth, _, _ = agent(foundation)
    base = payload(store, auth, "process")
    source = tmp_path / "native.py"
    source.write_text("""import json,os,time
from pathlib import Path
from career_lab.storage.database import Database
from career_lab.jobs.repository import JobRepository
from career_lab.contracts.v2 import ProtocolError
repo=JobRepository(Database(os.environ['NATIVE_QUOTA_DB']));payload=json.loads(os.environ['NATIVE_QUOTA_PAYLOAD']);key=os.environ['NATIVE_QUOTA_KEY']
while not Path(os.environ['NATIVE_QUOTA_GO']).exists():time.sleep(.01)
try:repo.enqueue(key,'v2.native_quota',payload);print(json.dumps({'accepted':True}))
except ProtocolError as error:print(json.dumps({'accepted':False,'code':error.code}))
repo.db.engine.dispose()
""")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3] / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["NATIVE_QUOTA_DB"] = str(store.db.engine.url)
    env["NATIVE_QUOTA_PAYLOAD"] = json.dumps(base)
    env["NATIVE_QUOTA_GO"] = str(tmp_path / "go")
    processes = [
        subprocess.Popen(
            [sys.executable, str(source)],
            env=env | {"NATIVE_QUOTA_KEY": "native-process-" + str(index)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(3)
    ]
    (tmp_path / "go").touch()
    results = []
    for process in processes:
        out, err = process.communicate(timeout=20)
        assert process.returncode == 0, err
        results.append(json.loads(out))
    assert sum(result["accepted"] for result in results) == 2, results
    assert store.delegation_job_capacity(auth).active_jobs == 2
