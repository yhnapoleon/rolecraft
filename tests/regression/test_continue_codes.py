"""Continue codes at the shipped HTTP boundary: reopening a practice from another browser."""

import logging
import re
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import MetaData, select

from .conftest import PublishedSession

GROUPED = re.compile(r"[0-9A-HJKMNP-TV-Z]{4}(?:-[0-9A-HJKMNP-TV-Z]{4}){4}")


def create_code(session: PublishedSession, expected: int = 0) -> httpx.Response:
    return session.client.post(
        session.url("continue-code"),
        headers=session.headers,
        json={"expected_generation": expected},
    )


def test_owner_creates_a_code_that_is_shown_once(published_session: PublishedSession) -> None:
    session = published_session
    before = session.get("continue-code")
    assert before.status_code == 200, before.text
    assert before.json()["result"] == {"exists": False, "generation": None, "created_at": None}

    created = create_code(session)

    assert created.status_code == 200, created.text
    assert created.headers["cache-control"] == "no-store"
    issued = created.json()["result"]
    assert GROUPED.fullmatch(issued["code"])
    assert issued["generation"] == 1
    status = session.get("continue-code")
    assert status.json()["result"]["exists"] is True
    assert status.json()["result"]["generation"] == 1
    assert status.json()["result"]["created_at"] == issued["created_at"]
    assert issued["code"] not in status.text
    assert issued["code"].replace("-", "") not in status.text


def test_replacing_needs_the_generation_the_person_saw(published_session: PublishedSession) -> None:
    session = published_session
    first = create_code(session).json()["result"]

    stale = create_code(session, expected=0)
    assert stale.status_code == 409 and stale.json()["code"] == "continue_code_changed"
    assert session.get("continue-code").json()["result"]["generation"] == 1

    replaced = create_code(session, expected=1)
    assert replaced.status_code == 200, replaced.text
    second = replaced.json()["result"]
    assert second["generation"] == 2 and second["code"] != first["code"]
    assert session.get("continue-code").json()["result"]["generation"] == 2


def agent_token(session: PublishedSession) -> str:
    command = session.command(
        "agent-grant",
        "delegations.create",
        {
            "agent_label": "Helper",
            "capabilities": ["read", "act", "submit"],
            "expires_at": (datetime.now(UTC) + timedelta(minutes=20)).isoformat(),
        },
    )
    response = session.client.post(
        session.url("delegations"), headers=session.headers, json=command
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]["result"]["token"]


def test_only_the_practices_own_person_can_see_or_create_a_code(
    published_session: PublishedSession,
) -> None:
    session = published_session
    agent = {"Authorization": "Bearer " + agent_token(session)}
    other = session.client.post(
        "/sessions",
        json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": session.language},
    ).json()
    elsewhere = {"Authorization": "Bearer " + other["token"]}
    body = {"expected_generation": 0}
    for headers, status, code in (
        ({}, 401, "token_required"),
        (agent, 403, "human_required"),
        (elsewhere, 401, "token_invalid"),
    ):
        read = session.client.get(session.url("continue-code"), headers=headers)
        made = session.client.post(session.url("continue-code"), headers=headers, json=body)
        assert (read.status_code, read.json()["code"]) == (status, code)
        assert (made.status_code, made.json()["code"]) == (status, code)
    assert session.get("continue-code").json()["result"]["exists"] is False


def stored_text(session: PublishedSession) -> str:
    engine = session.app.state.v2_store.db.engine
    tables = MetaData()
    tables.reflect(engine)
    with engine.connect() as connection:
        return "\n".join(
            repr(tuple(row))
            for table in tables.sorted_tables
            for row in connection.execute(select(table))
        )


def test_code_is_kept_only_as_a_keyed_verifier(
    published_session: PublishedSession, caplog: pytest.LogCaptureFixture
) -> None:
    session = published_session
    with caplog.at_level(logging.INFO, logger="career_lab.http"):
        code = create_code(session).json()["result"]["code"]
        replaced = create_code(session, expected=1).json()["result"]["code"]
    assert "/sessions/{session_id}/continue-code" in caplog.text  # the requests were logged
    for value in (code, replaced):
        for form in (value, value.replace("-", ""), value.lower()):
            assert form not in stored_text(session)
            assert form not in caplog.text


def test_codes_need_the_deployment_key(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = published_session
    monkeypatch.delenv("CAREER_LAB_CREDENTIAL_KEY")
    refused = create_code(session)
    assert refused.status_code == 503
    assert refused.json()["code"] == "credential_derivation_unavailable"
    assert session.get("continue-code").json()["result"]["exists"] is False
