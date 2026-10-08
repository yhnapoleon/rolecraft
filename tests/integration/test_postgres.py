import os
from uuid import uuid4

import pytest

from career_lab.contracts.actions import Action
from career_lab.storage.sessions import SessionStore


@pytest.mark.skipif(
    not os.getenv("CAREER_LAB_TEST_PG"), reason="set CAREER_LAB_TEST_PG for PostgreSQL integration"
)
def test_postgres_persists_and_replays(spec):
    url = os.environ["CAREER_LAB_TEST_PG"]
    store = SessionStore(url)
    sid = "test-" + uuid4().hex
    store.create_session(spec, sid)
    action = Action(
        id="a",
        idempotency_key="k",
        expected_version=0,
        actor_id="learner",
        tool="read_material",
        arguments={"material_id": "brief"},
    )
    store.commit_action(sid, action)
    store.close()
    store = SessionStore(url)
    assert store.get_state(sid).version == 1
    assert store.commit_action(sid, action).replayed
    assert len(store.events(sid)) == 1
    store.close()
