"""Persisted historical reply shapes; guards preserve records and public new replies."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import importlib.util
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update
from career_lab.contracts import v2 as C
from career_lab.storage.v2_store import Mutation, ObjectWrite, TransactionResult
from career_lab.storage.v2_tables import v2_objects, v2_heads, v2_transactions, v2_request_meta
from career_lab.storage.v2_snapshot import SnapshotService
from career_lab.storage.role_memory import (
    RoleTurn,
    RoleReply,
    PublicSpokenEvidence,
    object_write,
    install_role_storage,
)
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry, Gateway, Operation
from .conftest import command

spec = importlib.util.spec_from_file_location(
    "legacy_role_privacy_fixture",
    Path(__file__).parents[2] / "expansion_v3/w04/legacy_r1_fixture.py",
)
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
SECRET = "PRIVATE_PROMPT_NEVER_UTTERED"


def forbidden(*_):
    raise AssertionError("historical recovery reentered a handler")


def state_digest(store):
    with store.db.engine.connect() as conn:
        rows = {
            table.name: [dict(row) for row in conn.execute(select(table)).mappings()]
            for table in (v2_objects, v2_heads, v2_transactions, v2_request_meta)
        }
    return C.digest(rows)


def actor(foundation, external):
    store, owner, token, *_ = foundation
    if not external:
        return owner, token
    grant = C.DelegationGrant(
        id="agent",
        session_id=owner.session_id,
        actor_id="learner",
        executor=C.Executor(id="agent", kind="external_agent", delegation_id="agent"),
        capabilities=("read", "act"),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    token = store.issue_delegation(owner, grant)
    return store.authenticate(owner.session_id, token), token


def historical(foundation, external=False, legacy_audience=("learner", "tech_lead")):
    store, owner, *_ = foundation
    install_role_storage(store)
    auth, token = actor(foundation, external)
    point = C.VersionPoint(
        **store.view(auth).state.model_dump(
            include={"business_seq", "workspace_revision", "storage_revision"}
        )
    )
    turn = RoleTurn(
        id="turn",
        session_id=auth.session_id,
        input=C.TurnInput(role_id="tech_lead", text="Question"),
        as_of=point,
        executor=auth.executor,
    )
    write = object_write("role_turn", turn)
    cmd = command(store.view(auth), "historical", "fixture").model_copy(
        update={"payload": C.V2().model_dump(mode="json")}
    )
    txn = store.execute(
        auth,
        cmd,
        lambda *_: Mutation(writes=(write,), result={"turn": write.ref.model_dump(mode="json")}),
    )
    old = legacy.RoleReply(
        id="reply",
        session_id=auth.session_id,
        role_id="tech_lead",
        request=write.ref,
        question="Question",
        text="I need to check.",
        status="completed",
        context_hash="0" * 64,
        prompt_hash="1" * 64,
        prompt_messages=(C.ProviderMessage(role="system", content=SECRET),),
        history_revision="2" * 64,
        as_of=point,
        model_revision="historical-synthetic-fixture",
        executor=auth.executor,
    )
    ref = C.ObjectRef(session_id=auth.session_id, kind="role_reply", object_id="reply", version=1)
    record = C.StoredObject(
        ref=ref,
        content=old.model_dump(mode="json"),
        visible_to=legacy_audience,
        dependencies=(write.ref,),
        created_storage_revision=txn.state.storage_revision,
    )
    # Deliberately seed the historical rows, rather than bypass the new production write guard.
    restored = txn.model_copy(
        update={
            "objects": (*txn.objects, ref),
            "result": {
                "reply": ref.model_dump(mode="json"),
                "legacy_body": old.model_dump(mode="json"),
            },
        }
    )
    with store.db.transaction() as conn:
        conn.execute(
            insert(v2_objects).values(
                session_id=auth.session_id,
                kind=ref.kind,
                id=ref.object_id,
                version=1,
                record=C.canonical(record),
                created_revision=record.created_storage_revision,
            )
        )
        conn.execute(
            insert(v2_heads).values(
                session_id=auth.session_id, kind=ref.kind, id=ref.object_id, version=1
            )
        )
        conn.execute(
            update(v2_transactions)
            .where(
                v2_transactions.c.session_id == auth.session_id,
                v2_transactions.c.request_id == cmd.request_id,
            )
            .values(result=C.canonical(restored))
        )
        conn.execute(
            update(v2_request_meta)
            .where(
                v2_request_meta.c.session_id == auth.session_id,
                v2_request_meta.c.request_id == cmd.request_id,
            )
            .values(scope_refs="[]")
        )
    return store, auth, token, cmd, record


@pytest.mark.parametrize("external", [False, True])
@pytest.mark.parametrize(
    "path", ["read", "historical_read", "view", "can_reference", "execute", "replay", "get"]
)
def test_historical_private_reply_is_closed_across_common_entrypoints(foundation, external, path):
    store, auth, token, cmd, record = historical(foundation, external)
    before = state_digest(store)
    methods = {
        "read": lambda: store.read(auth, record.ref),
        "historical_read": lambda: store.read(
            auth, record.ref, storage_revision=record.created_storage_revision
        ),
        "can_reference": lambda: store.can_reference(auth, record.ref),
        "execute": lambda: store.execute(auth, cmd, forbidden),
        "replay": lambda: store.replay(auth, cmd),
        "get": lambda: store.request_result(auth, cmd.request_id),
    }
    if path == "view":
        assert all(row.ref != record.ref for row in store.view(auth).objects)
    else:
        with pytest.raises(C.ProtocolError):
            methods[path]()
    assert state_digest(store) == before


@pytest.mark.parametrize("external", [False, True])
def test_actual_http_request_recovery_and_gateway_replay_never_return_old_body(
    foundation, external
):
    store, auth, token, cmd, record = historical(foundation, external)
    before = state_digest(store)
    registry = ExtensionRegistry()
    registry.register(Operation("turns.create", "act", C.V2, forbidden, action_name="fixture"))
    app = create_app(str(store.db.engine.url), extensions=registry)
    try:
        with TestClient(app) as client:
            header = {"Authorization": "Bearer " + token}
            for response in (
                client.get(
                    f"/sessions/{auth.session_id}/requests/{cmd.request_id}", headers=header
                ),
                client.post(
                    f"/sessions/{auth.session_id}/turns",
                    headers=header,
                    json=cmd.model_dump(mode="json"),
                ),
            ):
                assert response.status_code == 404, response.text
                assert SECRET not in response.text and "prompt_messages" not in response.text
    finally:
        app.state.store.close()
    assert state_digest(store) == before


def test_historical_audit_is_preserved_and_untrusted_exports_are_denied(foundation):
    store, auth, token, cmd, record = historical(foundation)
    before = state_digest(store)
    with pytest.raises(C.ProtocolError):
        SnapshotService(store).export(auth, C.digest("fixture"))
    trusted = store.research_context(auth.session_id)
    audit = SnapshotService(store).export(trusted, C.digest("fixture"))
    assert next(x for x in audit.objects if x.ref == record.ref) == record
    assert (
        SECRET
        in store.read(store.role_reader(auth.session_id, "tech_lead"), record.ref).model_dump_json()
    )
    with pytest.raises(C.ProtocolError):
        store.read(store.role_reader(auth.session_id, "business_lead"), record.ref)
    assert state_digest(store) == before


@pytest.mark.parametrize(
    "field",
    [
        "prompt_messages",
        "prompt_hash",
        "context_hash",
        "history_revision",
        "source_versions",
        "omitted_sources",
        "attempts",
        "actual_disclosures",
        "received_shares",
        "internal_disclosures",
        "context",
        "generation_audit",
        "scope",
        "used_sources",
        "job_attempt",
        "worker_id",
        "lease_token_hash",
        "unrecognized_meta",
        "spoken_source",
    ],
)
def test_any_legacy_private_field_blocks_new_public_reply_write(foundation, field):
    store, auth, *_ = foundation

    class LooseReply(C.V2):
        id: str
        session_id: str
        role_id: str = "tech_lead"
        version: int = 1
        model_config = {"extra": "allow"}

    store.register_object("role_reply", LooseReply)
    content = {
        "id": "new-reply",
        "session_id": auth.session_id,
        "role_id": "tech_lead",
        "version": 1,
    }
    if field == "spoken_source":
        content["spoken_evidence"] = [
            {
                "label": "fact",
                "quote": "words",
                "verification": "verified",
                "source": {"internal": "UNSAID"},
            }
        ]
    else:
        content[field] = (
            [] if field in ("prompt_messages", "source_versions", "omitted_sources") else "0" * 64
        )
    ref = C.ObjectRef(
        session_id=auth.session_id, kind="role_reply", object_id="new-reply", version=1
    )
    before = state_digest(store)
    with pytest.raises(C.ProtocolError, match="role reply private fields forbidden"):
        store.execute(
            auth,
            command(store.view(auth), "unsafe"),
            lambda *_: Mutation(
                writes=(
                    ObjectWrite(
                        ref=ref,
                        expected_head=0,
                        content=content,
                        visible_to=("learner", "tech_lead"),
                    ),
                )
            ),
        )
    assert state_digest(store) == before


@pytest.mark.parametrize("external", [False, True])
def test_new_public_reply_and_uttered_quotes_stay_readable(foundation, external):
    store, owner, *_ = foundation
    install_role_storage(store)
    auth, token = actor(foundation, external)
    point = C.VersionPoint(
        **store.view(auth).state.model_dump(
            include={"business_seq", "workspace_revision", "storage_revision"}
        )
    )
    turn = RoleTurn(
        id="turn",
        session_id=auth.session_id,
        input=C.TurnInput(role_id="tech_lead", text="Question"),
        as_of=point,
        executor=auth.executor,
    )
    reqwrite = object_write("role_turn", turn)
    reply = RoleReply(
        id="safe",
        session_id=auth.session_id,
        role_id="tech_lead",
        request=reqwrite.ref,
        question="Question",
        text="Only spoken words.",
        status="completed",
        as_of=point,
        executor=auth.executor,
        spoken_evidence=(
            PublicSpokenEvidence(label="said", quote="spoken words", verification="verified"),
        ),
    )
    write = object_write("role_reply", reply, visible_to=("learner", "tech_lead"))
    cmd = command(store.view(auth), "safe")
    result = store.execute(
        auth,
        cmd,
        lambda *_: Mutation(
            writes=(reqwrite, write), result={"reply": write.ref.model_dump(mode="json")}
        ),
    )
    assert store.read(auth, write.ref).content == reply.model_dump(mode="json")
    assert (
        store.replay(auth, cmd).replayed
        and store.request_result(auth, cmd.request_id)[1].result == result.result
    )
    assert write.ref in [r.ref for r in store.view(auth).objects]
