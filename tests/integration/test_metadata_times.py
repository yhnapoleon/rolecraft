from datetime import datetime, timezone

import pytest
from sqlalchemy import MetaData, create_engine, event, insert, inspect, select

from career_lab.contracts.actions import Action
from career_lab.jobs.repository import JobRepository, jobs
from career_lab.scenarios.reducer import VersionConflict, apply_action, initial_state
from career_lab.storage.database import (
    actions,
    events,
    event_times,
    objects,
    object_times,
    sessions,
    snapshots,
)
from career_lab.storage.sessions import IdempotencyConflict, SessionStore, canonical, digest


def read_action(key, version):
    return Action(
        id=key,
        idempotency_key=key,
        expected_version=version,
        actor_id="learner",
        tool="read_material",
        arguments={"material_id": "brief"},
    )


def assert_utc(value):
    assert value.endswith("Z")
    assert datetime.fromisoformat(value).tzinfo == timezone.utc


def test_event_and_object_times_are_atomic_immutable_metadata(tmp_path, spec):
    store = SessionStore(f"sqlite:///{tmp_path / 'times.db'}")
    store.create_session(spec, "s")
    for index in range(2):
        store.commit_action("s", read_action(f"read-{index}", index))
    action = Action(
        id="turn",
        idempotency_key="turn",
        expected_version=2,
        actor_id="learner",
        tool="record_turn",
        arguments={"object_id": "turn"},
    )
    content = {"answer": "unchanged evidence"}
    original = apply_action(store.get_state("s"), action, spec)
    result = store.commit_action(
        "s", action, object_record={"id": "turn", "kind": "turn", "content": content}
    )
    # Includes the policy-update event; metadata does not change any world output.
    assert result == original
    created_at = store.object_created_at("s", "turn")
    assert_utc(created_at)
    assert all(store.event_created_at("s", event.seq) == created_at for event in result.events)
    assert all(store.event_created_at("s", event.seq) for event in store.events("s"))
    assert store.get_object("s", "turn") == content
    assert store.list_objects("s", "turn") == [{"id": "turn", **content}]
    assert store.object_created_at("other", "turn") is None
    assert store.event_created_at("other", 1) is None
    assert store.commit_action(
        "s", action, object_record={"id": "turn", "kind": "turn", "content": content}
    ).replayed
    assert store.object_created_at("s", "turn") == created_at
    assert all(store.event_created_at("s", event.seq) == created_at for event in result.events)
    with store.db.engine.connect() as conn:
        assert conn.execute(
            select(objects.c.content).where(objects.c.id == "turn")
        ).scalar_one() == canonical(content)
        assert conn.execute(
            select(actions.c.request_hash).where(actions.c.key == "turn")
        ).scalar_one() == digest(
            {
                "action": action.model_dump(mode="json"),
                "object": {"id": "turn", "kind": "turn", "content": content},
            }
        )
    store.close()
    reopened = SessionStore(f"sqlite:///{tmp_path / 'times.db'}")
    assert reopened.object_created_at("s", "turn") == created_at


@pytest.mark.parametrize(
    "kind", ["test", "artifact", "submission", "turn", "approval", "approval_denied"]
)
def test_derived_records_have_times_without_advancing_world(tmp_path, spec, kind):
    store = SessionStore(f"sqlite:///{tmp_path / 'derived.db'}")
    state = store.create_session(spec, "s")
    content = {"value": kind}
    metadata = {"request_hash": "hash", "error": "original error"}
    assert (
        store.save_derived("s", "record", kind, content, metadata=metadata, expected_version=0)
        == content
    )
    created_at = store.object_created_at("s", "record")
    assert_utc(created_at)
    assert store.get_object_metadata("s", "record") == metadata
    assert store.get_object_metadata("other", "record") == {}
    assert store.get_state("s") == state
    assert store.events("s") == ()
    store.commit_action("s", read_action("read", 0))
    assert (
        store.save_derived("s", "record", kind, content, metadata=metadata, expected_version=0)
        == content
    )
    assert store.object_created_at("s", "record") == created_at
    with pytest.raises(IdempotencyConflict):
        store.save_derived("s", "record", kind, content, metadata={"request_hash": "other"})
    with pytest.raises(VersionConflict, match="approval state changed"):
        store.save_derived("s", "stale", kind, content, expected_version=0)
    assert store.object_created_at("s", "stale") is None


def test_legacy_schema_adds_tables_without_backfilling_or_changing_content(tmp_path, spec):
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(url)
    old_metadata = MetaData()
    original_tables = (sessions, snapshots, events, actions, objects, jobs)
    for table in original_tables:
        table.to_metadata(old_metadata)
    old_metadata.create_all(engine)
    before_columns = {
        table.name: [column["name"] for column in inspect(engine).get_columns(table.name)]
        for table in original_tables
    }
    initial = initial_state("s", spec)
    action = read_action("legacy", 0)
    transition = apply_action(initial, action, spec)
    content = {"old": "payload"}
    with engine.begin() as conn:
        conn.execute(
            insert(sessions).values(
                id="s",
                state=transition.state.model_dump_json(),
                spec=spec.model_dump_json(),
                token_hash=digest(""),
            )
        )
        for state in (initial, *transition.snapshots):
            conn.execute(
                insert(snapshots).values(
                    session_id="s", seq=state.version, state=state.model_dump_json()
                )
            )
        conn.execute(
            insert(events).values(
                session_id="s", seq=1, content=transition.events[0].model_dump_json()
            )
        )
        conn.execute(
            insert(objects).values(
                id="old", session_id="s", kind="test", content=canonical(content)
            )
        )
        conn.execute(
            insert(actions).values(
                session_id="s",
                key="legacy",
                request_hash=digest({"action": action.model_dump(mode="json"), "object": None}),
                result=transition.model_dump_json(),
            )
        )
        conn.execute(
            insert(jobs).values(
                id="old-job",
                request_key="legacy",
                kind="feedback",
                payload="{}",
                status="queued",
                attempt=0,
                lease_until=0,
            )
        )
    engine.dispose()
    store = SessionStore(url)
    repository = JobRepository(store.db)
    assert {
        table.name: [column["name"] for column in inspect(store.db.engine).get_columns(table.name)]
        for table in original_tables
    } == before_columns
    assert store.event_created_at("s", 1) is None
    assert store.object_created_at("s", "old") is None
    assert store.get_object_metadata("s", "old") == {}
    assert store.get_object("s", "old") == content
    assert store.commit_action("s", action).replayed
    assert store.event_created_at("s", 1) is None
    assert repository.enqueue("legacy", "feedback", {}, now=100) == "old-job"
    assert {
        field: repository.get("old-job")[field]
        for field in ("queued_at", "started_at", "finished_at")
    } == {"queued_at": None, "started_at": None, "finished_at": None}
    claimed = repository.claim_job("worker", now=101)
    assert repository.get("old-job")["queued_at"] is None
    assert_utc(repository.get("old-job")["started_at"])
    repository.complete("old-job", claimed["lease_token"], {"ok": True}, now=102)
    assert_utc(repository.get("old-job")["finished_at"])
    store.commit_action("s", read_action("new", 1))
    assert_utc(store.event_created_at("s", 2))
    assert store.event_created_at("s", 1) is None


@pytest.mark.parametrize("failing_table", ["event_times", "object_times", "actions"])
def test_action_and_metadata_roll_back_together(tmp_path, spec, failing_table):
    store = SessionStore(f"sqlite:///{tmp_path / 'rollback.db'}")
    original = store.create_session(spec, "s")
    action = Action(
        id="turn",
        idempotency_key="turn",
        expected_version=0,
        actor_id="learner",
        tool="record_turn",
        arguments={"object_id": "turn"},
    )

    def fail_write(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith(f"INSERT INTO {failing_table} "):
            raise RuntimeError("injected persistence failure")

    event.listen(store.db.engine, "before_cursor_execute", fail_write)
    with pytest.raises(RuntimeError, match="injected"):
        store.commit_action(
            "s", action, object_record={"id": "turn", "kind": "turn", "content": {"text": "hello"}}
        )
    event.remove(store.db.engine, "before_cursor_execute", fail_write)
    assert store.get_state("s") == original
    assert store.events("s") == ()
    assert store.list_objects("s", "turn") == []
    assert store.object_created_at("s", "turn") is None
    assert store.event_created_at("s", 1) is None
    with store.db.engine.connect() as conn:
        for table in (events, event_times, objects, object_times, actions):
            assert conn.execute(select(table)).first() is None


def test_derived_metadata_failure_rolls_back_object_and_time(tmp_path, spec):
    store = SessionStore(f"sqlite:///{tmp_path / 'derived-rollback.db'}")
    store.create_session(spec, "s")

    def fail_write(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO object_metadata "):
            raise RuntimeError("injected metadata failure")

    event.listen(store.db.engine, "before_cursor_execute", fail_write)
    with pytest.raises(RuntimeError, match="injected"):
        store.save_derived(
            "s", "denial", "approval_denied", {"code": "no"}, metadata={"error": "no"}
        )
    event.remove(store.db.engine, "before_cursor_execute", fail_write)
    assert store.list_objects("s", "approval_denied") == []
    assert store.object_created_at("s", "denial") is None
    assert store.get_object_metadata("s", "denial") == {}


def test_existing_derived_object_conflict_does_not_advance_state(tmp_path, spec):
    store = SessionStore(f"sqlite:///{tmp_path / 'conflict.db'}")
    original = store.create_session(spec, "s")
    store.save_derived("s", "shared", "approval_denied", {"code": "denied"})
    with pytest.raises(IdempotencyConflict):
        store.commit_action(
            "s",
            read_action("conflict", 0),
            object_record={"id": "shared", "kind": "approval", "content": {"approved": True}},
        )
    assert store.get_state("s") == original
