from concurrent.futures import ThreadPoolExecutor

import pytest

from career_lab.contracts.actions import Action
from career_lab.storage.sessions import SessionStore, IdempotencyConflict
from career_lab.scenarios.reducer import VersionConflict


def test_idempotency_restart_and_historical_view(tmp_path, spec):
    url = f"sqlite:///{tmp_path / 'state.db'}"
    store = SessionStore(url)
    state = store.create_session(spec, "s")
    first = Action(
        id="a",
        idempotency_key="k",
        expected_version=0,
        actor_id="learner",
        tool="read_material",
        arguments={"material_id": "brief"},
    )
    result = store.commit_action("s", first)
    assert store.commit_action("s", first).replayed
    assert len(store.events("s")) == 1
    with pytest.raises(IdempotencyConflict):
        store.commit_action("s", first.model_copy(update={"arguments": {"material_id": "faq"}}))
    with pytest.raises(VersionConflict):
        store.commit_action("s", first.model_copy(update={"id": "b", "idempotency_key": "new"}))
    for i in range(2):
        state = store.get_state("s")
        store.commit_action(
            "s",
            first.model_copy(
                update={"id": str(i), "idempotency_key": str(i), "expected_version": state.version}
            ),
        )
    store.close()
    reopened = SessionStore(url)
    assert reopened.get_state("s").material_versions["policy"] == 2
    assert (
        next(
            m.version
            for m in reopened.project_view("s", "learner", 1).permitted_materials
            if m.id == "policy"
        )
        == 1
    )
    assert (
        next(
            m.version
            for m in reopened.project_view("s", "learner").permitted_materials
            if m.id == "policy"
        )
        == 2
    )
    assert reopened.commit_action("s", first).state == result.state


def test_concurrent_duplicate_commits_once(tmp_path, spec):
    store = SessionStore(f"sqlite:///{tmp_path / 'parallel.db'}")
    store.create_session(spec, "s")
    action = Action(
        id="a",
        idempotency_key="k",
        expected_version=0,
        actor_id="learner",
        tool="read_material",
        arguments={"material_id": "brief"},
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: store.commit_action("s", action), range(2)))
    assert sum(r.replayed for r in results) == 1
    assert len(store.events("s")) == 1
