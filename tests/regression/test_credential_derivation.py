"""Credential security at the shipped HTTP boundary, using isolated test keys and DBs."""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.engine import Connection

from career_lab.contracts import v2 as C
from career_lab.security.credentials import DeploymentKey, aliases, derivations
from career_lab.storage.v2_snapshot import SnapshotService
from career_lab.storage.v2_tables import v2_credentials, v2_restores, v2_sessions

from .conftest import PublishedSession

TEST_KEY = "isolated-credential-test-key-not-for-deployment-074"


def issue(session: PublishedSession, key: str = "grant") -> tuple[httpx.Response, dict[str, Any]]:
    command = session.command(
        key,
        "delegations.create",
        {
            "agent_label": "Test helper",
            "capabilities": ["read", "act"],
            "expires_at": (datetime.now(UTC) + timedelta(minutes=20)).isoformat(),
        },
    )
    return session.client.post(
        session.url("delegations"), headers=session.headers, json=command
    ), command


def test_database_digest_cannot_derive_new_delegation(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY", TEST_KEY)
    monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY_ID", "test-key-v1")
    session = published_session
    response, _ = issue(session)
    assert response.status_code == 200, response.text
    result = response.json()["result"]["result"]
    grant = C.DelegationGrant.model_validate(result["delegation"])
    with session.app.state.v2_store.db.engine.connect() as connection:
        rows = (
            connection.execute(
                select(v2_credentials).where(v2_credentials.c.session_id == session.session_id)
            )
            .mappings()
            .all()
        )
    owner = next(
        row
        for row in rows
        if C.AuthContext.model_validate_json(row["context"]).executor.kind == "human"
    )
    reconstructed = hmac.new(
        owner["token_hash"].encode(), C.canonical(grant).encode(), hashlib.sha256
    ).hexdigest()
    assert (
        session.client.get(
            session.url(""), headers={"Authorization": "Bearer " + reconstructed}
        ).status_code
        == 401
    )
    assert (
        session.client.get(
            session.url(""), headers={"Authorization": "Bearer " + result["token"]}
        ).status_code
        == 200
    )


def test_delegation_key_drift_fails_without_record_change(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY", TEST_KEY)
    monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY_ID", "test-key-v1")
    session = published_session
    response, command = issue(session)
    assert response.status_code == 200

    def replay() -> httpx.Response:
        return session.client.post(
            session.url("delegations"), headers=session.headers, json=command
        )

    assert replay().json() == response.json()
    with session.app.state.v2_store.db.engine.connect() as connection:
        before = [dict(row) for row in connection.execute(select(v2_credentials)).mappings()]
    for key_id, secret in [
        ("test-key-v2", TEST_KEY),
        ("test-key-v1", TEST_KEY + "-changed"),
        ("", ""),
    ]:
        monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY_ID", key_id)
        monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY", secret)
        failed = replay()
        assert failed.status_code == 503
        assert failed.json()["code"] == "credential_derivation_unavailable"
        with session.app.state.v2_store.db.engine.connect() as connection:
            assert [
                dict(row) for row in connection.execute(select(v2_credentials)).mappings()
            ] == before
    token = response.json()["result"]["result"]["token"]
    assert (
        session.client.get(
            session.url(""), headers={"Authorization": "Bearer " + token}
        ).status_code
        == 200
    )


def test_legacy_delegation_replay_adds_new_token_and_keeps_old(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import delete, update

    from career_lab.security.credentials import derivations

    monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY", TEST_KEY)
    monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY_ID", "test-key-v1")
    session = published_session
    response, command = issue(session)
    assert response.status_code == 200
    result = response.json()["result"]["result"]
    grant = C.DelegationGrant.model_validate(result["delegation"])
    with session.app.state.v2_store.db.transaction() as connection:
        rows = (
            connection.execute(
                select(v2_credentials).where(v2_credentials.c.session_id == session.session_id)
            )
            .mappings()
            .all()
        )
        owner = next(
            row
            for row in rows
            if C.AuthContext.model_validate_json(row["context"]).executor.kind == "human"
        )
        legacy = hmac.new(
            owner["token_hash"].encode(), C.canonical(grant).encode(), hashlib.sha256
        ).hexdigest()
        connection.execute(
            update(v2_credentials)
            .where(v2_credentials.c.id == grant.id)
            .values(token_hash=C.digest(legacy))
        )
        connection.execute(delete(derivations).where(derivations.c.credential_id == grant.id))
    old_headers = {"Authorization": "Bearer " + legacy}
    assert session.client.get(session.url(""), headers=old_headers).status_code == 200
    changed_request = command | {"request_id": "bypass-legacy-grant"}
    assert (
        session.client.post(
            session.url("delegations"), headers=session.headers, json=changed_request
        ).status_code
        == 409
    )
    replay = session.client.post(session.url("delegations"), headers=session.headers, json=command)
    assert replay.status_code == 200, replay.text
    resigned = replay.json()["result"]["result"]
    assert resigned["delegation"] == result["delegation"]
    assert resigned["token"] != legacy
    assert session.client.get(session.url(""), headers=old_headers).status_code == 200
    assert (
        session.client.get(
            session.url(""), headers={"Authorization": "Bearer " + resigned["token"]}
        ).status_code
        == 200
    )
    assert (
        session.client.post(
            session.url("delegations"), headers=session.headers, json=command
        ).json()
        == replay.json()
    )


def test_reference_agent_uses_separate_secret_bound_derivation(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY", TEST_KEY)
    monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY_ID", "test-key-v1")
    session = published_session
    store = session.app.state.v2_store
    owner = store.authenticate(
        session.session_id, session.headers["Authorization"].split(" ", 1)[1]
    )
    token = store.reference_agent_token(owner)
    context = store.authenticate(session.session_id, token)
    with store.db.engine.connect() as connection:
        owner_digest = connection.execute(
            select(v2_credentials.c.token_hash).where(v2_credentials.c.id == owner.credential_id)
        ).scalar_one()
    unsafe = hmac.new(
        owner_digest.encode(), C.canonical(context).encode(), hashlib.sha256
    ).hexdigest()
    with pytest.raises(C.ProtocolError) as denied:
        store.authenticate(session.session_id, unsafe)
    assert denied.value.status == 401
    assert store.reference_agent_token(owner) == token
    assert context.executor.kind == "reference_agent"
    assert (
        session.client.get(
            session.url("tools"), headers={"Authorization": "Bearer " + token}
        ).status_code
        == 200
    )


def reference_headers(session: PublishedSession) -> dict[str, str]:
    store = session.app.state.v2_store
    owner = store.authenticate(
        session.session_id, session.headers["Authorization"].split(" ", 1)[1]
    )
    return {"Authorization": "Bearer " + store.reference_agent_token(owner)}


def test_reference_agent_cannot_issue_or_revoke_delegations(
    published_session: PublishedSession,
) -> None:
    session = published_session
    reference = reference_headers(session)
    issued, command = issue(session)
    assert issued.status_code == 200, issued.text
    grant = issued.json()["result"]["result"]
    created = session.client.post(
        session.url("delegations"),
        headers=reference,
        json=command | {"request_id": "reference-grant"},
    )
    assert (created.status_code, created.json()["code"]) == (403, "capability_forbidden")
    grant_id = grant["delegation"]["id"]
    revoked = session.client.request(
        "DELETE",
        session.url("delegations/" + grant_id),
        headers=reference,
        json=session.command("reference-revoke", "delegations.revoke", {"delegation_id": grant_id}),
    )
    assert (revoked.status_code, revoked.json()["code"]) == (403, "capability_forbidden")
    agent = {"Authorization": "Bearer " + grant["token"]}
    assert session.client.get(session.url(""), headers=agent).status_code == 200


def test_reference_agent_token_cannot_reach_another_session(
    published_session: PublishedSession,
) -> None:
    session = published_session
    reference = reference_headers(session)
    other = session.client.post(
        "/sessions",
        json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": session.language},
    ).json()
    route = "/sessions/" + other["session_id"]
    for path in ("", "/tools", "/observation", "/work-products"):
        assert session.client.get(route + path, headers=reference).status_code == 401
    owner = {"Authorization": "Bearer " + other["token"]}
    before = session.client.get(route, headers=owner).json()["state"]
    write = {
        "schema_version": 2,
        "request_id": "reference-cross-session",
        "expected_version": before["business_seq"],
        "expected_workspace_revision": before["workspace_revision"],
        "operation": "work_products.create",
        "payload": {
            "kind": "text",
            "purpose": "exploration",
            "title": "Cross-session note",
            "content": "Written only by the session owner.",
        },
    }
    written = session.client.post(route + "/work-products", headers=reference, json=write)
    assert written.status_code == 401
    assert session.client.get(route, headers=owner).json()["state"] == before
    # The same command is valid for the owning session, so the rejection is the credential.
    accepted = session.client.post(route + "/work-products", headers=owner, json=write)
    assert accepted.status_code == 200, accepted.text
    assert session.client.get(session.url("tools"), headers=reference).status_code == 200


def practice_request(session: PublishedSession) -> dict[str, Any]:
    product = session.work()
    saved = session.send(
        "submissions",
        "for-practice",
        "submissions.create",
        {
            "decision": "defer_with_conditions",
            "products": [product],
        },
    )
    session.run_job()
    submission = saved["result"]["submission"]["object_id"]
    shown = session.client.get(
        session.url("practice"), headers=session.headers, params={"submission_id": submission}
    ).json()["result"]
    return {
        "request_id": "practice-choice",
        "choice": "choose_other",
        "option_id": "pm_pilot_urgent-" + session.language,
        "shown": shown,
    }


def test_database_digest_cannot_derive_new_practice(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY", TEST_KEY)
    monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY_ID", "test-key-v1")
    session = published_session
    body = practice_request(session)
    response = session.client.post(
        session.url("practice/choices"), headers=session.headers, json=body
    )
    assert response.status_code == 200, response.text
    target = response.json()["result"]["session"]
    with session.app.state.v2_store.db.engine.connect() as connection:
        rows = (
            connection.execute(
                select(v2_credentials).where(v2_credentials.c.session_id == session.session_id)
            )
            .mappings()
            .all()
        )
        owner = next(
            row
            for row in rows
            if C.AuthContext.model_validate_json(row["context"]).executor.kind == "human"
        )
    unsafe = hmac.new(
        owner["token_hash"].encode(),
        ("practice-session:" + target["session_id"]).encode(),
        hashlib.sha256,
    ).hexdigest()
    endpoint = "/sessions/" + target["session_id"]
    assert (
        session.client.get(endpoint, headers={"Authorization": "Bearer " + unsafe}).status_code
        == 401
    )
    assert (
        session.client.get(
            endpoint, headers={"Authorization": "Bearer " + target["token"]}
        ).status_code
        == 200
    )
    assert (
        session.client.post(
            session.url("practice/choices"), headers=session.headers, json=body
        ).json()["result"]["session"]
        == target
    )


def test_concurrent_practice_replay_has_one_target(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from fastapi.testclient import TestClient
    from sqlalchemy import func

    from career_lab.storage.v2_tables import v2_sessions

    monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY", TEST_KEY)
    monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY_ID", "test-key-v1")
    session = published_session
    body = practice_request(session)
    start = Barrier(4)

    def send(_: int) -> httpx.Response:
        with TestClient(session.app, raise_server_exceptions=False) as client:
            start.wait(timeout=10)
            return client.post(session.url("practice/choices"), headers=session.headers, json=body)

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(send, range(4)))
    assert [response.status_code for response in responses] == [200] * 4
    targets = [response.json()["result"]["session"] for response in responses]
    assert all(target == targets[0] for target in targets)
    with session.app.state.v2_store.db.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(v2_sessions)).scalar_one() == 2


def test_legacy_practice_resigns_same_target_and_rejects_new_request_bypass(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import delete, func, update

    from career_lab.security.credentials import derivations
    from career_lab.storage.v2_tables import v2_sessions

    monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY", TEST_KEY)
    monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY_ID", "test-key-v1")
    session = published_session
    body = practice_request(session)

    def send(payload: dict[str, Any]) -> httpx.Response:
        return session.client.post(
            session.url("practice/choices"), headers=session.headers, json=payload
        )

    first = send(body)
    assert first.status_code == 200
    target = first.json()["result"]["session"]
    with session.app.state.v2_store.db.transaction() as connection:
        owner_rows = (
            connection.execute(
                select(v2_credentials).where(v2_credentials.c.session_id == session.session_id)
            )
            .mappings()
            .all()
        )
        owner = next(
            row
            for row in owner_rows
            if C.AuthContext.model_validate_json(row["context"]).executor.kind == "human"
        )
        target_row = (
            connection.execute(
                select(v2_credentials).where(v2_credentials.c.session_id == target["session_id"])
            )
            .mappings()
            .one()
        )
        legacy = hmac.new(
            owner["token_hash"].encode(),
            ("practice-session:" + target["session_id"]).encode(),
            hashlib.sha256,
        ).hexdigest()
        connection.execute(
            update(v2_credentials)
            .where(v2_credentials.c.id == target_row["id"])
            .values(token_hash=C.digest(legacy))
        )
        connection.execute(
            delete(derivations).where(derivations.c.credential_id == target_row["id"])
        )
    assert send(body | {"request_id": "different-request"}).status_code == 409
    restored = send(body)
    assert restored.status_code == 200, restored.text
    new = restored.json()["result"]["session"]
    assert new["session_id"] == target["session_id"] and new["token"] != legacy
    for token in (legacy, new["token"]):
        assert (
            session.client.get(
                "/sessions/" + new["session_id"], headers={"Authorization": "Bearer " + token}
            ).status_code
            == 200
        )
    assert send(body).json()["result"]["session"] == new
    assert send(body | {"request_id": "different-request"}).status_code == 409
    with session.app.state.v2_store.db.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(v2_sessions)).scalar_one() == 2


def test_secret_provider_failure_is_sanitized_and_does_not_write(
    published_session: PublishedSession,
) -> None:
    from sqlalchemy import func

    session = published_session

    def unavailable() -> DeploymentKey:
        raise ValueError(TEST_KEY)

    session.app.state.v2_store.credential_key_provider = unavailable
    response, _ = issue(session)
    assert response.status_code == 503
    assert response.json() == {
        "error": "credential derivation unavailable",
        "code": "credential_derivation_unavailable",
    }
    assert TEST_KEY not in response.text
    with session.app.state.v2_store.db.engine.connect() as connection:
        assert (
            connection.execute(select(func.count()).select_from(v2_credentials)).scalar_one() == 1
        )


def test_derivation_metadata_is_versioned_and_contains_no_secret(
    published_session: PublishedSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from career_lab.security.credentials import derivations

    monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY", TEST_KEY)
    monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY_ID", "test-key-v1")
    response, _ = issue(published_session)
    assert response.status_code == 200
    token = response.json()["result"]["result"]["token"]
    engine = published_session.app.state.v2_store.db.engine
    with engine.connect() as connection:
        record = connection.execute(select(derivations)).mappings().one()
        assert record.get("scheme") == "hmac-sha256-v1"
    connection = engine.raw_connection()
    try:
        dump = "\n".join(connection.driver_connection.iterdump())
    finally:
        connection.close()
    assert TEST_KEY not in dump and token not in dump
    assert TEST_KEY not in caplog.text
    assert TEST_KEY not in published_session.client.get("/openapi.json").text


@pytest.mark.parametrize("path", ["delegation", "practice"])
def test_missing_key_never_creates_credential_or_target(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    from sqlalchemy import func

    from career_lab.api.v4_extensions import practice_intents, practice_links
    from career_lab.security.credentials import aliases, derivations
    from career_lab.storage.v2_tables import v2_sessions

    session = published_session
    body = practice_request(session) if path == "practice" else None
    tables = [v2_sessions, v2_credentials, derivations, aliases, practice_links, practice_intents]

    def counts() -> list[int]:
        with session.app.state.v2_store.db.engine.connect() as connection:
            return [
                connection.execute(select(func.count()).select_from(table)).scalar_one()
                for table in tables
            ]

    before = counts()
    monkeypatch.delenv("CAREER_LAB_CREDENTIAL_KEY")
    response = (
        session.client.post(session.url("practice/choices"), headers=session.headers, json=body)
        if body
        else issue(session)[0]
    )
    assert response.status_code == 503
    assert response.json()["code"] == "credential_derivation_unavailable"
    assert counts() == before


def test_new_tokens_cannot_cross_sessions_and_revocation_still_applies(
    published_session: PublishedSession,
) -> None:
    session = published_session
    issued, command = issue(session)
    assert issued.status_code == 200
    result = issued.json()["result"]["result"]
    other = session.client.post(
        "/sessions",
        json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": session.language},
    ).json()
    auth = {"Authorization": "Bearer " + result["token"]}
    assert session.client.get("/sessions/" + other["session_id"], headers=auth).status_code == 401
    assert session.client.post(session.url("delegations"), json=command).status_code == 401
    assert (
        session.client.post(session.url("delegations"), headers=auth, json=command).status_code
        == 403
    )
    conflict = command | {"payload": command["payload"] | {"capabilities": ["read"]}}
    assert (
        session.client.post(
            session.url("delegations"), headers=session.headers, json=conflict
        ).status_code
        == 409
    )
    grant_id = result["delegation"]["id"]
    revoked = session.client.request(
        "DELETE",
        session.url("delegations/" + grant_id),
        headers=session.headers,
        json=session.command("revoke", "delegations.revoke", {"delegation_id": grant_id}),
    )
    assert revoked.status_code == 200, revoked.text
    assert session.client.get(session.url(""), headers=auth).status_code == 403
    assert (
        session.client.post(
            session.url("delegations"), headers=session.headers, json=command
        ).status_code
        == 409
    )


def test_practice_replay_key_drift_and_unauthorized_requests_do_not_mutate(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = published_session
    body = practice_request(session)
    first = session.client.post(session.url("practice/choices"), headers=session.headers, json=body)
    assert first.status_code == 200
    target = first.json()["result"]["session"]
    assert session.client.post(session.url("practice/choices"), json=body).status_code == 401
    monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY", TEST_KEY + "-changed")
    failed = session.client.post(
        session.url("practice/choices"), headers=session.headers, json=body
    )
    assert failed.status_code == 503
    assert (
        session.client.get(
            "/sessions/" + target["session_id"],
            headers={"Authorization": "Bearer " + target["token"]},
        ).status_code
        == 200
    )


def test_missing_alias_cannot_report_successful_recovery(
    published_session: PublishedSession,
) -> None:
    from sqlalchemy import delete, update

    from career_lab.security.credentials import aliases, derivations

    session = published_session
    first, command = issue(session)
    assert first.status_code == 200
    grant = first.json()["result"]["result"]["delegation"]
    with session.app.state.v2_store.db.transaction() as connection:
        connection.execute(
            update(v2_credentials)
            .where(v2_credentials.c.id == grant["id"])
            .values(token_hash=C.digest("legacy-test-token"))
        )
        connection.execute(delete(derivations).where(derivations.c.credential_id == grant["id"]))
    replay = session.client.post(session.url("delegations"), headers=session.headers, json=command)
    assert replay.status_code == 200
    with session.app.state.v2_store.db.transaction() as connection:
        connection.execute(delete(aliases).where(aliases.c.credential_id == grant["id"]))
    failed = session.client.post(session.url("delegations"), headers=session.headers, json=command)
    assert failed.status_code == 503
    assert failed.json()["code"] == "credential_derivation_unavailable"
    assert (
        session.client.get(
            session.url(""), headers={"Authorization": "Bearer legacy-test-token"}
        ).status_code
        == 200
    )


def test_failed_practice_choice_rejects_same_id_different_choice(
    published_session: PublishedSession,
) -> None:
    from sqlalchemy import event

    session = published_session
    body = practice_request(session)
    engine = session.app.state.v2_store.db.engine

    def fail_link(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().lower().startswith("insert into v4_practice_links"):
            raise OSError("controlled link storage failure")

    event.listen(engine, "before_cursor_execute", fail_link)
    try:
        failed = session.client.post(
            session.url("practice/choices"), headers=session.headers, json=body
        )
        assert failed.status_code == 500
    finally:
        event.remove(engine, "before_cursor_execute", fail_link)
    changed = body | {"choice": "decline", "option_id": None}
    assert (
        session.client.post(
            session.url("practice/choices"), headers=session.headers, json=changed
        ).status_code
        == 409
    )
    retried = session.client.post(
        session.url("practice/choices"), headers=session.headers, json=body
    )
    assert retried.status_code == 200, retried.text
    target = retried.json()["result"]["session"]
    assert (
        session.client.post(
            session.url("practice/choices"), headers=session.headers, json=body
        ).json()["result"]["session"]
        == target
    )


def test_expired_delegation_cannot_authenticate_or_recover(
    published_session: PublishedSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import career_lab.storage.v2_store as storage

    session = published_session
    response, command = issue(session)
    assert response.status_code == 200
    token = response.json()["result"]["result"]["token"]
    later = datetime.now(UTC) + timedelta(hours=2)

    class FutureClock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return later

    monkeypatch.setattr(storage, "datetime", FutureClock)
    monkeypatch.delenv("CAREER_LAB_CREDENTIAL_KEY")
    assert (
        session.client.get(
            session.url(""), headers={"Authorization": "Bearer " + token}
        ).status_code
        == 403
    )
    denied = session.client.post(session.url("delegations"), headers=session.headers, json=command)
    assert denied.status_code == 403
    assert denied.json()["code"] == "credential_expired"


def test_legacy_reference_token_survives_resigning_and_restart(
    published_session: PublishedSession,
) -> None:
    from sqlalchemy import delete, update

    from career_lab.security.credentials import derivations
    from career_lab.storage.v2_store import V2Store

    session = published_session
    store = session.app.state.v2_store
    owner = store.authenticate(
        session.session_id, session.headers["Authorization"].split(" ", 1)[1]
    )
    created = store.reference_agent_token(owner)
    target = store.authenticate(session.session_id, created)
    with store.db.transaction() as connection:
        owner_digest = connection.execute(
            select(v2_credentials.c.token_hash).where(v2_credentials.c.id == owner.credential_id)
        ).scalar_one()
        legacy = hmac.new(
            owner_digest.encode(), C.canonical(target).encode(), hashlib.sha256
        ).hexdigest()
        connection.execute(
            update(v2_credentials)
            .where(v2_credentials.c.id == target.credential_id)
            .values(token_hash=C.digest(legacy))
        )
        connection.execute(
            delete(derivations).where(derivations.c.credential_id == target.credential_id)
        )
    resigned = store.reference_agent_token(owner)
    assert resigned != legacy
    restarted = V2Store(str(store.db.engine.url))
    try:
        assert restarted.reference_agent_token(owner) == resigned
        assert restarted.authenticate(session.session_id, legacy) == target
        assert restarted.authenticate(session.session_id, resigned) == target
        with restarted.db.transaction() as connection:
            connection.execute(
                update(v2_credentials)
                .where(v2_credentials.c.id == target.credential_id)
                .values(revoked=1)
            )
        for token in (legacy, resigned):
            with pytest.raises(C.ProtocolError) as denied:
                restarted.authenticate(session.session_id, token)
            assert denied.value.status == 403
        with pytest.raises(C.ProtocolError) as denied:
            restarted.reference_agent_token(owner)
        assert denied.value.status == 403
    finally:
        restarted.db.engine.dispose()


def test_legacy_orphan_requires_original_request_for_valid_reissued_token(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CRED-05: a new request cannot recover an unlinked historical target."""
    from sqlalchemy import delete, update

    from career_lab.api.v4_extensions import practice_intents, practice_links
    from career_lab.security.credentials import aliases, derivations

    session = published_session
    body = practice_request(session)

    def send(payload: dict[str, Any]) -> httpx.Response:
        return session.client.post(
            session.url("practice/choices"), headers=session.headers, json=payload
        )

    first = send(body)
    assert first.status_code == 200, first.text
    old_target = first.json()["result"]["session"]
    endpoint = "/sessions/" + old_target["session_id"]
    # A historical digest-only row with no attribution links or new provenance.
    # Keep a fixture token as the existing owner; never reconstruct it from a digest.
    legacy_token = "isolated-historical-practice-token-kept-by-owner"
    with session.app.state.v2_store.db.transaction() as connection:
        credential_id = connection.execute(
            select(v2_credentials.c.id).where(
                v2_credentials.c.session_id == old_target["session_id"]
            )
        ).scalar_one()
        connection.execute(
            update(v2_credentials)
            .where(v2_credentials.c.id == credential_id)
            .values(token_hash=C.digest(legacy_token))
        )
        connection.execute(delete(aliases).where(aliases.c.credential_id == credential_id))
        connection.execute(delete(derivations).where(derivations.c.credential_id == credential_id))
        connection.execute(
            delete(practice_links).where(practice_links.c.source_session_id == session.session_id)
        )
        connection.execute(
            delete(practice_intents).where(
                practice_intents.c.source_session_id == session.session_id
            )
        )

    other = send(body | {"request_id": "independent-new-request"})
    assert other.status_code == 200, other.text
    new_target = other.json()["result"]["session"]
    assert new_target["session_id"] != old_target["session_id"]
    assert (
        session.client.get(
            endpoint, headers={"Authorization": "Bearer " + new_target["token"]}
        ).status_code
        == 401
    )
    assert (
        session.client.get(
            "/sessions/" + new_target["session_id"],
            headers={"Authorization": "Bearer " + new_target["token"]},
        ).status_code
        == 200
    )

    with monkeypatch.context() as missing_key:
        missing_key.delenv("CAREER_LAB_CREDENTIAL_KEY", raising=False)
        failed = send(body)
    assert failed.status_code == 503
    assert failed.json()["code"] == "credential_derivation_unavailable"
    assert (
        session.client.get(
            endpoint, headers={"Authorization": "Bearer " + legacy_token}
        ).status_code
        == 200
    )

    recovered = send(body)
    assert recovered.status_code == 200, recovered.text
    restored = recovered.json()["result"]["session"]
    assert restored["session_id"] == old_target["session_id"]
    assert restored["token"] != legacy_token
    for token in (legacy_token, restored["token"]):
        assert (
            session.client.get(endpoint, headers={"Authorization": "Bearer " + token}).status_code
            == 200
        )
    assert send(body).json()["result"]["session"] == restored


def test_delegation_same_request_rejects_changed_agent_label(
    published_session: PublishedSession,
) -> None:
    """CRED-04: a validated request field cannot disappear from idempotency."""
    session = published_session
    first, command = issue(session)
    assert first.status_code == 200, first.text
    changed = command | {"payload": command["payload"] | {"agent_label": "A different helper"}}
    conflict = session.client.post(
        session.url("delegations"), headers=session.headers, json=changed
    )
    assert conflict.status_code == 409, conflict.text
    replay = session.client.post(session.url("delegations"), headers=session.headers, json=command)
    assert replay.status_code == 200 and replay.json() == first.json()


def restore_fixture(session: PublishedSession) -> tuple[SnapshotService, C.SnapshotExport]:
    store = session.app.state.v2_store
    service = SnapshotService(store)
    snapshot = service.export(
        store.research_context(session.session_id), C.digest("restore-source")
    )
    return service, snapshot


def restore_counts(service: SnapshotService) -> list[int]:
    with service.store.db.engine.connect() as connection:
        return [
            connection.execute(select(func.count()).select_from(table)).scalar_one()
            for table in (v2_sessions, v2_credentials, v2_restores, derivations, aliases)
        ]


def child_read(session: PublishedSession, sid: str, token: str) -> httpx.Response:
    return session.client.get("/sessions/" + sid, headers={"Authorization": "Bearer " + token})


def test_snapshot_restore_rejects_database_digest_prediction(
    published_session: PublishedSession,
) -> None:
    service, snapshot = restore_fixture(published_session)
    restored, token = service.restore(snapshot, session_id="child", request_id="restore")
    with service.store.db.engine.connect() as connection:
        rows = connection.execute(
            select(v2_credentials).where(v2_credentials.c.session_id == snapshot.session_id)
        ).mappings()
        parent_digest = next(
            row["token_hash"]
            for row in rows
            if C.AuthContext.model_validate_json(row["context"]).executor.kind == "human"
        )
    # Attacker knows only the database digest and restore parameters, never the signing key.
    predicted = hmac.new(
        parent_digest.encode(),
        C.canonical(["child", "restore", snapshot.snapshot_hash]).encode(),
        hashlib.sha256,
    ).hexdigest()
    assert child_read(published_session, restored.session_id, predicted).status_code == 401
    assert child_read(published_session, restored.session_id, token).status_code == 200


def test_snapshot_restore_replay_preserves_identity_and_credential(
    published_session: PublishedSession,
) -> None:
    service, snapshot = restore_fixture(published_session)
    restored, token = service.restore(snapshot, session_id="child", request_id="restore")
    before = restore_counts(service)
    replay, replay_token = SnapshotService(service.store).restore(
        snapshot, session_id="child", request_id="restore"
    )
    assert replay.replayed and replay.model_copy(update={"replayed": False}) == restored
    assert replay_token == token
    assert restore_counts(service) == before
    assert child_read(published_session, replay.session_id, replay_token).status_code == 200


@pytest.mark.parametrize("missing", ["CAREER_LAB_CREDENTIAL_KEY_ID", "CAREER_LAB_CREDENTIAL_KEY"])
def test_snapshot_restore_missing_key_fails_without_writes(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    service, snapshot = restore_fixture(published_session)
    before = restore_counts(service)
    monkeypatch.delenv(missing)
    with pytest.raises(C.ProtocolError) as failed:
        service.restore(snapshot, session_id="child", request_id="restore")
    assert (failed.value.status, failed.value.code) == (503, "credential_derivation_unavailable")
    assert restore_counts(service) == before
    restored, token = service.restore(
        snapshot,
        session_id="explicit-child",
        request_id="explicit",
        token="isolated-explicit-token",
    )
    assert child_read(published_session, restored.session_id, token).status_code == 200
    assert (
        service.restore(snapshot, session_id="explicit-child", request_id="explicit", token=token)[
            1
        ]
        == token
    )


def test_snapshot_restore_records_provenance_without_secrets(
    published_session: PublishedSession, caplog: pytest.LogCaptureFixture
) -> None:
    service, snapshot = restore_fixture(published_session)
    restored, token = service.restore(snapshot, session_id="child", request_id="restore")
    auth = service.store.authenticate(restored.session_id, token)
    with service.store.db.engine.connect() as connection:
        record = (
            connection.execute(
                select(derivations).where(derivations.c.credential_id == auth.credential_id)
            )
            .mappings()
            .one_or_none()
        )
    assert record is not None
    assert record["purpose"] == "snapshot-restore"
    assert record["scheme"] == "hmac-sha256-v1" and record["key_id"] == "test-key-v1"
    assert len(record["fingerprint"]) == 64
    assert record["token_hash"] == C.digest(token)
    connection = service.store.db.engine.raw_connection()
    try:
        dump = "\n".join(connection.driver_connection.iterdump())
    finally:
        connection.close()
    assert TEST_KEY not in dump and token not in dump
    assert TEST_KEY not in caplog.text and token not in caplog.text
    assert TEST_KEY not in C.canonical(snapshot)


@pytest.mark.parametrize("drift", ["key", "key_id", "missing"])
def test_snapshot_restore_key_drift_preserves_existing_access(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    service, snapshot = restore_fixture(published_session)
    restored, token = service.restore(snapshot, session_id="child", request_id="restore")
    before = restore_counts(service)
    if drift == "key":
        monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY", TEST_KEY + "-changed")
    elif drift == "key_id":
        monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY_ID", "test-key-v2")
    else:
        monkeypatch.delenv("CAREER_LAB_CREDENTIAL_KEY")
    with pytest.raises(C.ProtocolError) as failed:
        service.restore(snapshot, session_id="child", request_id="restore")
    assert (failed.value.status, failed.value.code) == (503, "credential_derivation_unavailable")
    assert restore_counts(service) == before
    assert child_read(published_session, restored.session_id, token).status_code == 200


def test_snapshot_restore_legacy_token_and_explicit_replay_preserve_old_row(
    published_session: PublishedSession,
) -> None:
    service, snapshot = restore_fixture(published_session)
    # Retained historical credential fixture; no reconstruction of old plaintext.
    legacy = "isolated-historical-snapshot-token-kept-by-owner"
    restored, _ = service.restore(snapshot, session_id="child", request_id="restore", token=legacy)
    with service.store.db.engine.connect() as connection:
        before = dict(
            connection.execute(select(v2_credentials).where(v2_credentials.c.session_id == "child"))
            .mappings()
            .one()
        )
    counts = restore_counts(service)
    with pytest.raises(C.ProtocolError, match="restore token conflict"):
        service.restore(snapshot, session_id="child", request_id="restore")
    replay, token = service.restore(
        snapshot, session_id="child", request_id="restore", token=legacy
    )
    assert replay.replayed and replay.session_id == restored.session_id and token == legacy
    assert child_read(published_session, "child", legacy).status_code == 200
    assert restore_counts(service) == counts
    with service.store.db.engine.connect() as connection:
        assert (
            dict(
                connection.execute(
                    select(v2_credentials).where(v2_credentials.c.session_id == "child")
                )
                .mappings()
                .one()
            )
            == before
        )


@pytest.mark.parametrize("revoked_session", ["parent", "child"])
def test_snapshot_restore_rechecks_current_authorization(
    published_session: PublishedSession, revoked_session: str
) -> None:
    service, snapshot = restore_fixture(published_session)
    service.restore(snapshot, session_id="child", request_id="restore")
    sid = snapshot.session_id if revoked_session == "parent" else "child"
    with service.store.db.transaction() as connection:
        connection.execute(
            update(v2_credentials).where(v2_credentials.c.session_id == sid).values(revoked=1)
        )
    before = restore_counts(service)
    with pytest.raises(C.ProtocolError) as failed:
        service.restore(snapshot, session_id="child", request_id="restore")
    assert (failed.value.status, failed.value.code) == (403, "credential_revoked_or_invalid")
    assert restore_counts(service) == before


def test_snapshot_restore_rejects_missing_provenance(
    published_session: PublishedSession,
) -> None:
    service, snapshot = restore_fixture(published_session)
    _, token = service.restore(snapshot, session_id="child", request_id="restore")
    auth = service.store.authenticate("child", token)
    with service.store.db.transaction() as connection:
        connection.execute(
            delete(derivations).where(derivations.c.credential_id == auth.credential_id)
        )
    with pytest.raises(C.ProtocolError, match="restore token conflict"):
        service.restore(snapshot, session_id="child", request_id="restore")
    assert child_read(published_session, "child", token).status_code == 200


@pytest.mark.parametrize("failed_table", ["v2_credentials", "v2_restores"])
def test_snapshot_restore_rolls_back_derivation_with_target(
    published_session: PublishedSession, failed_table: str
) -> None:
    service, snapshot = restore_fixture(published_session)
    before = restore_counts(service)
    engine = service.store.db.engine

    def fail_write(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lower().startswith("insert into " + failed_table + " "):
            raise OSError("isolated storage failure")

    event.listen(engine, "before_cursor_execute", fail_write)
    try:
        with pytest.raises(OSError, match="isolated storage failure"):
            service.restore(snapshot, session_id="child", request_id="restore")
    finally:
        event.remove(engine, "before_cursor_execute", fail_write)
    assert restore_counts(service) == before
    restored, token = service.restore(snapshot, session_id="child", request_id="restore")
    assert child_read(published_session, restored.session_id, token).status_code == 200


def test_snapshot_restore_revoked_parent_cannot_create_target(
    published_session: PublishedSession,
) -> None:
    service, snapshot = restore_fixture(published_session)
    with service.store.db.transaction() as connection:
        connection.execute(
            update(v2_credentials)
            .where(v2_credentials.c.session_id == snapshot.session_id)
            .values(revoked=1)
        )
    before = restore_counts(service)
    with pytest.raises(C.ProtocolError) as failed:
        service.restore(snapshot, session_id="new-child", request_id="new-restore")
    assert (failed.value.status, failed.value.code) == (403, "credential_revoked_or_invalid")
    assert restore_counts(service) == before
