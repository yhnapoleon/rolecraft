"""Result-page reads must coexist with another authorized read in SQLite WAL mode."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import event

from career_lab.api import error_boundary
from career_lab.storage.v2_lifecycle import point

from .conftest import PublishedSession
from .test_submission_rule_check import as_the_submit_control_sends, submit


@pytest.mark.parametrize("historical", [False, True], ids=["current", "historical"])
def test_result_requests_do_not_take_a_writer_lock(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch, historical: bool
) -> None:
    session = published_session
    payload = as_the_submit_control_sends(session, "launch_narrow")
    submit(session, payload)
    submission = session.get("submissions").json()["result"]["result"]["items"][-1]
    paths = ["submission-rule-check?submission_id=" + submission["id"], "work-products"]
    expected = {path: session.get(path).json() for path in paths}
    store = session.app.state.v2_store
    auth = store.authenticate(session.session_id, session.headers["Authorization"][7:])
    at = point(store.view(auth).state)
    entered, release = Event(), Event()
    errors = []
    original = error_boundary.internal_error

    def capture(request, error):
        errors.append(error)
        return original(request, error)

    monkeypatch.setattr(error_boundary, "internal_error", capture)

    def short_busy_timeout(connection, _record, _proxy):
        connection.execute("PRAGMA busy_timeout=100")

    event.listen(store.db.engine, "checkout", short_busy_timeout)

    def hold(view):
        assert view.state.session_id == session.session_id
        entered.set()
        assert release.wait(10), "the other read never completed"

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = (
            pool.submit(store.query_at, auth, at, hold)
            if historical
            else pool.submit(store.query, auth, hold)
        )
        try:
            assert entered.wait(5)
            for path in paths:
                response = session.get(path)
                assert response.status_code == 200, [(type(e).__name__, str(e)) for e in errors]
                assert response.json() == expected[path]
        finally:
            release.set()
            future.result()
            event.remove(store.db.engine, "checkout", short_busy_timeout)


def test_rule_check_reads_one_projection_per_window(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = published_session
    payload = as_the_submit_control_sends(session, "launch_narrow")
    store = session.app.state.v2_store
    calls = []
    original = store.query_at

    def counted(auth, at, reader, **kwargs):
        calls.append(at)
        return original(auth, at, reader, **kwargs)

    monkeypatch.setattr(store, "query_at", counted)
    from .test_submission_rule_check import check

    response = check(session, payload)
    assert response.status_code == 200
    assert len(calls) == len(set(p.storage_revision for p in calls)), calls


@pytest.mark.parametrize("decision", ["launch", "launch_narrow", "defer_with_conditions", "no_go"])
def test_optimized_rule_check_matches_uncached_port_field_for_field(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch, decision: str
) -> None:
    from career_lab.api import evaluation_runtime

    from .test_submission_rule_check import check, retested_before_reconfiguring, saved_check

    session = published_session
    retested_before_reconfiguring(session)
    payload = as_the_submit_control_sends(session, decision)
    optimized = check(session, payload)
    assert optimized.status_code == 200
    with monkeypatch.context() as legacy:
        legacy.setattr(
            evaluation_runtime, "RuleCheckEvidencePort", evaluation_runtime.ScenarioEvidencePort
        )
        baseline = check(session, payload)
    assert baseline.status_code == 200
    assert optimized.json() == baseline.json()
    feedback = submit(session, payload)
    submission_id = feedback["subject"]["object_id"]
    optimized = saved_check(session, submission_id)
    with monkeypatch.context() as legacy:
        legacy.setattr(
            evaluation_runtime, "RuleCheckEvidencePort", evaluation_runtime.ScenarioEvidencePort
        )
        from career_lab.api.v4_extensions import _rule_checks

        store = session.app.state.v2_store
        auth = store.authenticate(session.session_id, session.headers["Authorization"][7:])
        _rule_checks(session.app.state.gateway.registry, store, auth)._saved_cache.clear()
        baseline = saved_check(session, submission_id)
    assert baseline.status_code == optimized.status_code == 200
    assert optimized.json() == baseline.json()


def test_rule_window_rechecks_credentials_even_after_caching(
    published_session: PublishedSession,
) -> None:
    from sqlalchemy import update

    from career_lab.api.evaluation_runtime import RuleCheckEvidencePort
    from career_lab.api.v4_extensions import _rule_checks
    from career_lab.contracts import v2 as C
    from career_lab.storage.v2_tables import v2_credentials

    session = published_session
    ref = C.ObjectRef.model_validate(session.work())
    store = session.app.state.v2_store
    auth = store.authenticate(session.session_id, session.headers["Authorization"][7:])
    checks = _rule_checks(session.app.state.gateway.registry, store, auth)
    source = RuleCheckEvidencePort(store, checks.module)
    at = point(store.view(auth).state)
    assert source.record(auth, ref, at).ref == ref
    assert source.record(auth, ref, at).ref == ref
    with store.db.transaction() as connection:
        connection.execute(
            update(v2_credentials)
            .where(v2_credentials.c.id == auth.credential_id)
            .values(revoked=True)
        )
    with pytest.raises(C.ProtocolError) as error:
        source.record(auth, ref, at)
    assert error.value.code == "credential_revoked_or_invalid"


def test_saved_result_coalesces_concurrent_reads_and_invalidates_after_revision(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Barrier, Lock

    from career_lab.api.v4_extensions import _rule_checks

    session = published_session
    payload = as_the_submit_control_sends(session, "launch_narrow")
    feedback = submit(session, payload)
    subject = feedback["subject"]
    store = session.app.state.v2_store
    auth = store.authenticate(session.session_id, session.headers["Authorization"][7:])
    checks = _rule_checks(session.app.state.gateway.registry, store, auth)
    original, calls, lock = checks._check, [], Lock()

    def counted(*args):
        with lock:
            calls.append(1)
        return original(*args)

    monkeypatch.setattr(checks, "_check", counted)
    barrier = Barrier(4)

    def read(_):
        barrier.wait(timeout=10)
        return checks.saved(store, auth, subject["object_id"])

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(read, range(4)))
    assert len(calls) == 1
    assert all(result == results[0] for result in results)
    assert results[0] is not results[1]
    assert checks.saved(store, auth, subject["object_id"]) == results[0]
    assert len(calls) == 1
    session.send(
        "revision-cycles",
        "revise",
        "begin_revision",
        {"parent_submission": subject, "reason": "Retest before deciding again."},
    )
    assert checks.saved(store, auth, subject["object_id"]) == results[0]
    assert len(calls) == 2


def test_saved_cache_never_keeps_failures_or_outlives_revocation(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import update

    from career_lab.api.v4_extensions import _rule_checks
    from career_lab.contracts import v2 as C
    from career_lab.storage.v2_tables import v2_credentials

    session = published_session
    feedback = submit(session, as_the_submit_control_sends(session, "no_go"))
    store = session.app.state.v2_store
    auth = store.authenticate(session.session_id, session.headers["Authorization"][7:])
    checks = _rule_checks(session.app.state.gateway.registry, store, auth)
    original, calls = checks._saved_uncached, []

    def fail_once(*args):
        calls.append(1)
        if len(calls) == 1:
            raise C.ProtocolError("snapshot_window_unavailable", status=409)
        return original(*args)

    monkeypatch.setattr(checks, "_saved_uncached", fail_once)
    submission_id = feedback["subject"]["object_id"]
    with pytest.raises(C.ProtocolError):
        checks.saved(store, auth, submission_id)
    expected = checks.saved(store, auth, submission_id)
    assert checks.saved(store, auth, submission_id) == expected
    assert len(calls) == 2
    with store.db.transaction() as connection:
        connection.execute(
            update(v2_credentials)
            .where(v2_credentials.c.id == auth.credential_id)
            .values(revoked=True)
        )
    with pytest.raises(C.ProtocolError) as error:
        checks.saved(store, auth, submission_id)
    assert error.value.code == "credential_revoked_or_invalid"


def test_saved_rule_check_does_not_project_feedback_created_after_the_submission(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Historical checks must not pay to project later derived feedback bodies."""
    from career_lab.api.v4_extensions import _rule_checks

    session = published_session
    feedback = submit(session, as_the_submit_control_sends(session, "no_go"))
    store = session.app.state.v2_store
    auth = store.authenticate(session.session_id, session.headers["Authorization"][7:])
    checks = _rule_checks(session.app.state.gateway.registry, store, auth)
    original, projected_future = store._project_public_records, []

    def counted(connection, caller, records):
        projected_future.extend(
            row.ref
            for row in records
            if row.ref.kind == "feedback"
            and row.created_storage_revision > feedback["as_of"]["storage_revision"]
        )
        return original(connection, caller, records)

    monkeypatch.setattr(store, "_project_public_records", counted)
    result = checks.saved(store, auth, feedback["subject"]["object_id"])
    assert result.as_of.model_dump(mode="json") == feedback["as_of"]
    assert [item.model_dump(mode="json") for item in result.rule_items] == feedback["rule_items"]
    assert projected_future == []
