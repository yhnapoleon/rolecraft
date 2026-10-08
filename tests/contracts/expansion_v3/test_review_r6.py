"""C-W01-04 lifecycle/cost recovery; synthetic handlers, real storage and Worker."""

from dataclasses import replace
import pytest
from sqlalchemy import update
from career_lab.contracts import v2 as C
from career_lab.storage.v2_store import Mutation, ObjectWrite, JobRequest
from career_lab.storage.v2_lifecycle import record_submission, begin_revision
from career_lab.storage.v2_tables import v2_credentials
from career_lab.api.modules import ExtensionRegistry, Gateway
from career_lab.jobs.repository import JobRepository
from career_lab.jobs.worker import Worker, WorkerClaim, ClaimedHandler
from .conftest import command, product_plan
from .test_review_r4 import submit_jobs, worker_for


def ask(store, auth, *, deps=(), handler=None):
    registry = ExtensionRegistry()
    g = Gateway(store, registry)
    calls = []

    def answer(v, e, a):
        calls.append((v.state.cycle_id, e.command.payload["question"]))
        return product_plan(v, e.command, a, oid="reply")

    registry.register_job("v2.reply", handler or answer)
    cmd = command(store.view(auth), "question", "turns.create").model_copy(
        update={"payload": {"question": "What should I investigate next?"}}
    )
    job = JobRequest(
        name="v2.reply",
        command=cmd.model_copy(update={"request_id": "answer"}),
        context_hash="0" * 64,
        state_dependencies=deps,
    )
    queued = store.execute(auth, cmd, lambda *_: Mutation(jobs=(job,)))
    q, w = worker_for(store, registry, g, "v2.reply")
    return g, q, w, queued.result["queued_jobs"][0], calls


def submit(store, auth):
    cmd = command(store.view(auth), "submit", "submit").model_copy(
        update={"payload": C.SubmitInput(decision="no_go", products=()).model_dump(mode="json")}
    )
    return store.execute(auth, cmd, record_submission, capability="submit")


def revise(store, auth, submitted):
    cmd = command(store.view(auth), "revise", "begin_revision").model_copy(
        update={
            "payload": C.BeginRevisionInput(
                parent_submission=submitted.result["submission"], reason="Continue investigation"
            ).model_dump(mode="json")
        }
    )
    return store.execute(auth, cmd, begin_revision)


def refresh(store, auth, g, jid, key="refresh"):
    cmd = command(store.view(auth), key, "jobs.refresh").model_copy(
        update={"payload": {"job_id": jid}}
    )
    return g.dispatch(auth, "jobs.refresh", cmd.model_dump(mode="json"), {"job_id": jid})


@pytest.mark.parametrize("deps", [(), ("status",)])
def test_N2_N2b_submitted_reply_calls_no_model_and_refresh_waits_for_open_cycle(foundation, deps):
    store, auth, *_ = foundation
    g, q, w, jid, calls = ask(store, auth, deps=deps)
    queued = q.get(jid)["payload"]
    s = submit(store, auth)
    subject = C.ObjectRef.model_validate(s.result["submission"])
    original = store.read(auth, subject)
    assert w.run_once() and not w.run_once()
    parked = q.get(jid)
    assert (
        parked["status"] == "needs_context"
        and parked["error"] == "job_session_inactive"
        and parked["attempt"] == 1
        and calls == []
    )
    result = g.request_result(auth, "question")
    assert result.status == "needs_context" and result.jobs[0].error_code == "job_session_inactive"
    before = store.view(auth).state
    with pytest.raises(C.ProtocolError, match="job session inactive"):
        refresh(store, auth, g, jid)
    assert store.view(auth).state == before and q.get(jid) == parked
    new = revise(store, auth, s)
    refresh(store, auth, g, jid)
    updated = q.get(jid)["payload"]
    assert updated["command"] == queued["command"]
    assert updated["context"]["sources"] == queued["context"]["sources"]
    assert updated["context"]["refresh_history"][0]["reason"] == "job_session_inactive"
    assert updated["context"]["refresh_history"][0]["attempt"] == 1
    assert updated["context"]["refresh_history"][0]["parked_at"] is not None
    assert w.run_once() and not w.run_once() and q.get(jid)["status"] == "completed"
    assert calls == [(new.state.cycle_id, "What should I investigate next?")]
    reply = next(x for x in store.view(auth).objects if x.ref.object_id == "reply")
    assert reply.content["cycle"]["object_id"] == new.state.cycle_id
    assert store.read(auth, subject) == original
    result = g.request_result(auth, "question")
    assert result.status == "completed" and result.jobs[0].refresh_count == 1
    assert result.jobs[0].refresh_history[0].reason == "job_session_inactive"


def test_N1_new_revision_parks_old_question_until_explicit_refresh(foundation):
    store, auth, *_ = foundation
    g, q, w, jid, calls = ask(store, auth)
    s = submit(store, auth)
    new = revise(store, auth, s)
    assert w.run_once() and calls == [] and q.get(jid)["error"] == "job_cycle_changed"
    old = q.get(jid)
    refresh(store, auth, g, jid)
    with pytest.raises(C.ProtocolError, match="worker lease lost"):
        g.run_job(
            "v2.reply",
            old["payload"],
            claim=WorkerClaim(old["id"], old["lease_token"], old["worker_id"], old["attempt"]),
        )
    assert calls == [] and w.run_once() and calls[0][0] == new.state.cycle_id
    assert q.get(jid)["status"] == "completed"


def test_pause_parks_before_model_and_only_resumed_session_can_refresh(foundation):
    store, auth, *_ = foundation
    g, q, w, jid, calls = ask(store, auth)
    store.execute(
        auth,
        command(store.view(auth), "pause", "pause"),
        lambda *_: Mutation(state_changes={"status": "paused"}),
    )
    assert w.run_once() and calls == [] and q.get(jid)["error"] == "job_session_inactive"
    with pytest.raises(C.ProtocolError, match="job session inactive"):
        refresh(store, auth, g, jid)
    store.execute(
        auth,
        command(store.view(auth), "resume", "resume"),
        lambda *_: Mutation(state_changes={"status": "active"}),
    )
    refresh(store, auth, g, jid)
    assert w.run_once() and len(calls) == 1 and q.get(jid)["status"] == "completed"


def test_lifecycle_changed_during_model_has_one_call_no_old_write_then_recovers(foundation):
    store, auth, *_ = foundation
    calls = []

    def answer(v, e, a):
        calls.append(v.state.cycle_id)
        if len(calls) == 1:
            revise(store, auth, submit(store, auth))
        return product_plan(v, e.command, a, oid="reply")

    g, q, w, jid, _ = ask(store, auth, handler=answer)
    assert (
        w.run_once()
        and q.get(jid)["status"] == "needs_context"
        and q.get(jid)["error"] == "job_cycle_changed"
    )
    assert not any(x.ref.object_id == "reply" for x in store.view(auth).objects)
    refresh(store, auth, g, jid)
    assert w.run_once() and len(calls) == 2 and calls[0] != calls[1]
    assert q.get(jid)["status"] == "completed"


def test_refreshed_handler_cannot_write_a_product_into_old_closed_cycle(foundation):
    store, auth, *_ = foundation
    old_cycle = store.view(auth).current_cycle.ref
    calls = []

    def bad(v, e, a):
        calls.append(1)
        plan = product_plan(v, e.command, a, oid="reply")
        write = plan.writes[0]
        write = write.model_copy(
            update={
                "content": write.content | {"cycle": old_cycle.model_dump(mode="json")},
                "dependencies": (old_cycle,),
            }
        )
        return replace(plan, writes=(write,))

    g, q, w, jid, _ = ask(store, auth, handler=bad)
    revise(store, auth, submit(store, auth))
    assert w.run_once() and calls == []
    refresh(store, auth, g, jid)
    assert w.run_once() and not w.run_once() and calls == [1]
    assert q.get(jid)["status"] == "failed" and q.get(jid)["error"] == "job_output_cycle_closed"
    assert not any(x.ref.object_id == "reply" for x in store.view(auth).objects)
    with pytest.raises(C.ProtocolError, match="job refresh not available"):
        refresh(store, auth, g, jid, "impossible-refresh")


def test_fixed_subject_feedback_still_finishes_when_new_cycle_is_paused(foundation):
    store, auth, *_ = foundation
    registry = ExtensionRegistry()
    g = Gateway(store, registry)
    s = submit_jobs(store, auth, registry, 2)
    revise(store, auth, s)
    store.execute(
        auth,
        command(store.view(auth), "pause", "pause"),
        lambda *_: Mutation(state_changes={"status": "paused"}),
    )
    before = store.view(auth).state
    q, w = worker_for(store, registry, g, "v2.feedback")
    assert w.run_once() and w.run_once() and not w.run_once()
    assert all(q.get(j)["status"] == "completed" for j in s.result["queued_jobs"])
    after = store.view(auth).state
    assert (after.status, after.cycle_id, after.business_seq) == (
        before.status,
        before.cycle_id,
        before.business_seq,
    )


def test_permanent_output_id_conflict_stops_once_and_cannot_refresh(foundation):
    store, auth, *_ = foundation
    g, q, w, jid, calls = ask(store, auth)
    store.execute(
        auth,
        command(store.view(auth), "occupied"),
        lambda v, c, a: product_plan(v, c, a, oid="reply"),
    )
    assert w.run_once() and not w.run_once() and len(calls) == 1
    assert (
        q.get(jid)["status"] == "failed" and q.get(jid)["error"] == "job_result_identity_conflict"
    )
    with pytest.raises(C.ProtocolError, match="job refresh not available"):
        refresh(store, auth, g, jid)


def test_protocol_deterministic_errors_stop_and_library_codes_are_not_public(foundation):
    store, auth, *_ = foundation

    def rejected(*_):
        raise C.ProtocolError("synthetic_module_rejected", status=422)

    g, q, w, jid, _ = ask(store, auth, handler=rejected)
    assert w.run_once() and not w.run_once() and q.get(jid)["error"] == "synthetic_module_rejected"
    assert q.get(jid)["status"] == "failed" and q.get(jid)["attempt"] == 1
    from career_lab.jobs.repository import JobRepository
    from career_lab.jobs.worker import Worker

    class LibraryFailure(Exception):
        code = "e3q8"

    def broken(*_):
        raise LibraryFailure("not public")

    another = q.enqueue("library", "v2.library", {})
    worker = Worker(q, {"v2.library": ClaimedHandler(broken)})
    assert worker.run_once() and q.get(another)["error"] == "job_execution_failed"


@pytest.mark.parametrize("legacy", [False, True])
def test_live_research_is_read_only_including_previously_issued_writable_credentials(
    foundation, legacy
):
    store, owner, *_ = foundation
    audit = store.research_context(owner.session_id)
    if legacy:
        audit = audit.model_copy(update={"capabilities": ("read", "act", "research")})
        with store.db.transaction() as c:
            c.execute(
                update(v2_credentials)
                .where(v2_credentials.c.id == audit.credential_id)
                .values(context=C.canonical(audit))
            )
    assert store.view(audit).state.session_id == owner.session_id
    called = []
    with pytest.raises(C.ProtocolError, match="research read only"):
        store.execute(audit, command(store.view(audit)), lambda *_: called.append(True))
    assert called == []


@pytest.mark.parametrize("failure", [None, "gap", "after_objects"])
def test_same_transaction_multiple_versions_are_ordered_atomic_and_replayable(foundation, failure):
    store, auth, *_ = foundation
    v = store.view(auth)
    cmd = command(v, "import-versions")
    first = product_plan(v, cmd, auth, expected_head=0).writes[0]
    second = product_plan(v, cmd, auth, expected_head=1).writes[0]
    if failure == "gap":
        second = second.model_copy(update={"expected_head": 2})

    def crash(stage):
        if stage == "after_objects":
            raise RuntimeError("injected rollback")

    def run():
        return store.execute(
            auth,
            cmd,
            lambda *_: Mutation(writes=(first, second)),
            fault=crash if failure == "after_objects" else None,
        )

    if failure:
        with pytest.raises((C.ProtocolError, RuntimeError)):
            run()
        assert store.view(auth).state == v.state and not any(
            x.ref.kind == "product" for x in store.view(auth).objects
        )
    else:
        result = run()
        assert [x.version for x in result.objects] == [1, 2]
        assert (
            store.read(auth, first.ref).content["version"] == 1
            and store.read(auth, second.ref).content["version"] == 2
        )
        assert run().replayed and store.view(auth).state.workspace_revision == 1
