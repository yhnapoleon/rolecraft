"""Continue codes at the shipped HTTP boundary: reopening a practice from another browser."""

import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, select

from career_lab.api import continue_codes
from career_lab.api.vertical_runtime import create_runtime_app
from scripts.regression.published import write_catalog

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


def test_codes_and_new_tokens_never_reach_storage_or_logs(
    published_session: PublishedSession, caplog: pytest.LogCaptureFixture
) -> None:
    session = published_session
    with caplog.at_level(logging.INFO, logger="career_lab.http"):
        code = create_code(session).json()["result"]["code"]
        token = exchange(session, code.lower()).json()["result"]["session"]["token"]
        replaced = create_code(session, expected=1).json()["result"]["code"]
        assert exchange(session, code).status_code == 404
        assert exchange(session, "my code is " + replaced).status_code == 422
    assert "/sessions/{session_id}/continue-code" in caplog.text  # the requests were logged
    assert "/continue-codes/exchange" in caplog.text
    stored = stored_text(session)
    for value in (code, replaced):
        for form in (value, value.replace("-", ""), value.lower()):
            assert form not in stored
            assert form not in caplog.text
    assert token not in stored and token not in caplog.text


def test_codes_need_the_deployment_key(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = published_session
    monkeypatch.delenv("CAREER_LAB_CREDENTIAL_KEY")
    refused = create_code(session)
    assert refused.status_code == 503
    assert refused.json()["code"] == "credential_derivation_unavailable"
    assert session.get("continue-code").json()["result"]["exists"] is False


def exchange(session: PublishedSession, code: str, request_id: str = "restore-1") -> httpx.Response:
    return session.client.post(
        "/continue-codes/exchange", json={"code": code, "request_id": request_id}
    )


def test_another_browser_opens_the_same_practice_with_the_code(
    published_session: PublishedSession,
) -> None:
    session = published_session
    code = create_code(session).json()["result"]["code"]

    opened = exchange(session, code)

    assert opened.status_code == 200, opened.text
    assert opened.headers["cache-control"] == "no-store"
    result = opened.json()["result"]
    assert result["scenario"] == "pm_pilot_v2"
    restored = result["session"]
    assert restored["session_id"] == session.session_id
    assert restored["binding"] == {
        "protocol": 2,
        "sessionId": session.session_id,
        "workLanguage": session.language,
        "scenarioHash": session.get("workbench").json()["result"]["result"]["session"][
            "scenarioHash"
        ],
    }
    assert restored["token"] != session.headers["Authorization"].removeprefix("Bearer ")
    headers = {"Authorization": "Bearer " + restored["token"]}
    workbench = session.client.get(session.url("workbench"), headers=headers)
    assert workbench.status_code == 200, workbench.text
    assert (
        workbench.json()["result"]["result"] == session.get("workbench").json()["result"]["result"]
    )


def readable(session: PublishedSession, headers: dict[str, str], submission: str) -> dict:
    def result(path: str) -> dict:
        response = session.client.get(session.url(path), headers=headers)
        assert response.status_code == 200, response.text
        return response.json()["result"]["result"]

    return {
        "records": result("workbench")["timeline"]["objects"],
        "tasks": result("work-items?limit=100")["items"],
        "work": result("work-products?limit=100")["items"],
        "submissions": result("submissions")["items"],
        "feedback": result("feedback/" + submission)["items"],
    }


def test_the_new_browser_reads_the_same_work_tests_conversation_and_feedback(
    published_session: PublishedSession,
) -> None:
    session = published_session
    session.send("work-items", "task", "work_items.create", {"title": "Scope", "goal": "Who first"})
    work = session.work()
    config = session.get("").json()["state"]["config_version"]
    session.send(
        "tests", "probe", "tests.create", {"query": "Hotel limit?", "config_version": config}
    )
    session.send(
        "turns",
        "ask",
        "turns.create",
        {"role_id": "supervisor", "text": "Who first?", "shares": []},
    )
    session.run_job()
    submitted = session.send(
        "submissions",
        "deliver",
        "submissions.create",
        {"decision": "defer_with_conditions", "products": [work]},
    )
    session.run_job()
    submission = submitted["result"]["submission"]["object_id"]
    code = create_code(session).json()["result"]["code"]

    token = exchange(session, code).json()["result"]["session"]["token"]

    seen = readable(session, {"Authorization": "Bearer " + token}, submission)
    assert seen == readable(session, session.headers, submission)
    kinds = {row["ref"]["kind"] for row in seen["records"]}
    assert {"test", "role_turn", "role_reply", "submission"} <= kinds
    assert [task["title"] for task in seen["tasks"]] == ["Scope"]
    assert [row["product_id"] for row in seen["work"]] == [work["object_id"]]
    assert len(seen["submissions"]) == 1 and len(seen["feedback"]) == 1


def test_queued_work_and_the_original_browser_survive_exchange_and_replacement(
    published_session: PublishedSession,
) -> None:
    session = published_session
    work = session.work()
    submitted = session.send(
        "submissions",
        "deliver",
        "submissions.create",
        {"decision": "defer_with_conditions", "products": [work]},
    )
    assert submitted["result"]["feedback_status"] == "queued"
    code = create_code(session).json()["result"]["code"]
    assert exchange(session, code).status_code == 200
    assert create_code(session, expected=1).status_code == 200

    session.run_job()

    recovered = session.get("requests/deliver").json()
    assert recovered["status"] == "completed", recovered
    subject = submitted["result"]["submission"]["object_id"]
    assert len(session.get("feedback/" + subject).json()["result"]["result"]["items"]) == 1


def test_a_replaced_code_stops_working_at_once(published_session: PublishedSession) -> None:
    session = published_session
    old = create_code(session).json()["result"]["code"]
    assert exchange(session, old, "first").status_code == 200
    new = create_code(session, expected=1).json()["result"]["code"]

    for request_id in ("first", "second"):
        refused = exchange(session, old, request_id)
        assert refused.status_code == 404
        assert refused.json()["code"] == "continue_code_invalid"
        assert "token" not in refused.text
    assert exchange(session, new, "second").status_code == 200


def test_retrying_the_same_request_returns_the_same_access(
    published_session: PublishedSession,
) -> None:
    session = published_session
    code = create_code(session).json()["result"]["code"]

    first = exchange(session, code, "lost-response").json()["result"]["session"]["token"]
    again = exchange(session, code, "lost-response").json()["result"]["session"]["token"]
    other = exchange(session, code, "another-browser").json()["result"]["session"]["token"]

    assert first == again
    assert other != first
    for token in (first, other):
        headers = {"Authorization": "Bearer " + token}
        assert session.client.get(session.url(""), headers=headers).status_code == 200


def test_text_that_cannot_be_a_code_is_refused_without_echo(
    published_session: PublishedSession,
) -> None:
    session = published_session
    refused = exchange(session, "my code is 7K3Q")
    assert refused.status_code == 422
    assert refused.json()["code"] == "continue_code_malformed"
    assert "7K3Q" not in refused.text


def test_ten_tries_per_source_every_fifteen_minutes(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = published_session
    now = [1_800_000_000.0]
    monkeypatch.setattr(continue_codes, "clock", lambda: now[0])
    code = create_code(session).json()["result"]["code"]
    assert exchange(session, code).status_code == 200
    for attempt in range(9):
        assert exchange(session, "0000-0000-0000-0000-000" + str(attempt)).status_code == 404

    now[0] += 60
    limited = exchange(session, code)

    assert limited.status_code == 429
    assert limited.json()["code"] == "continue_code_rate_limited"
    assert limited.json()["details"] == {"retry_after_seconds": 840}
    assert "token" not in limited.text
    now[0] += 840
    assert exchange(session, code).status_code == 200


def test_new_access_reaches_only_its_own_practice(published_session: PublishedSession) -> None:
    session = published_session
    other = session.client.post(
        "/sessions",
        json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": session.language},
    ).json()
    code = create_code(session).json()["result"]["code"]
    token = exchange(session, code).json()["result"]["session"]["token"]

    refused = session.client.get(
        "/sessions/" + other["session_id"], headers={"Authorization": "Bearer " + token}
    )

    assert (refused.status_code, refused.json()["code"]) == (401, "token_invalid")


def test_exchange_needs_the_key_the_code_was_made_with(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = published_session
    code = create_code(session).json()["result"]["code"]

    monkeypatch.delenv("CAREER_LAB_CREDENTIAL_KEY")
    missing = exchange(session, code)
    assert (missing.status_code, missing.json()["code"]) == (
        503,
        "credential_derivation_unavailable",
    )
    monkeypatch.setenv("CAREER_LAB_CREDENTIAL_KEY", "another-deployment-key-of-sufficient-length-0")
    rotated = exchange(session, code)
    assert (rotated.status_code, rotated.json()["code"]) == (404, "continue_code_invalid")


@contextmanager
def served(url: str) -> Iterator[TestClient]:
    app = create_runtime_app(url, provider="local")
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()


def test_a_practice_from_an_earlier_release_reopens_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "sqlite:///" + str(tmp_path / "practice.db")
    monkeypatch.setenv("CAREER_LAB_SCENARIO_CATALOG", str(write_catalog(tmp_path / "catalog.json")))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    with served(url) as client:
        created = client.post(
            "/sessions",
            json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": "en"},
        ).json()
        sid = created["session_id"]
        code = client.post(
            f"/sessions/{sid}/continue-code",
            headers={"Authorization": "Bearer " + created["token"]},
            json={"expected_generation": 0},
        ).json()["result"]["code"]
    # A later deployment runs only the Chinese main package; the English one is archived.
    monkeypatch.delenv("CAREER_LAB_SCENARIO_CATALOG")
    with served(url) as client:
        opened = client.post("/continue-codes/exchange", json={"code": code, "request_id": "a"})
        assert opened.status_code == 200, opened.text
        result = opened.json()["result"]
        assert result["scenario"] == "pm_pilot_v2"
        assert result["session"]["binding"]["workLanguage"] == "en"
        workbench = client.get(
            f"/sessions/{sid}/workbench",
            headers={"Authorization": "Bearer " + result["session"]["token"]},
        )
        assert workbench.json()["result"]["result"]["read_only"] is True


def test_a_practice_this_deployment_cannot_show_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "sqlite:///" + str(tmp_path / "practice.db")
    monkeypatch.setenv("CAREER_LAB_SCENARIO_CATALOG", str(write_catalog(tmp_path / "catalog.json")))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    with served(url) as client:
        created = client.post(
            "/sessions",
            json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": "en"},
        ).json()
        code = client.post(
            f"/sessions/{created['session_id']}/continue-code",
            headers={"Authorization": "Bearer " + created["token"]},
            json={"expected_generation": 0},
        ).json()["result"]["code"]
    monkeypatch.delenv("CAREER_LAB_SCENARIO_CATALOG")
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "another-archive"))
    with served(url) as client:
        refused = client.post("/continue-codes/exchange", json={"code": code, "request_id": "a"})
    assert (refused.status_code, refused.json()["code"]) == (
        409,
        "continue_code_scenario_unavailable",
    )
    assert "token" not in refused.text


def test_a_followup_practice_reopened_by_code_still_replays_its_original_choice(
    published_session: PublishedSession,
) -> None:
    session = published_session
    work = session.work()
    submitted = session.send(
        "submissions",
        "deliver",
        "submissions.create",
        {"decision": "defer_with_conditions", "products": [work]},
    )
    session.run_job()
    shown = session.get(
        "practice?submission_id=" + submitted["result"]["submission"]["object_id"]
    ).json()["result"]
    choice = {
        "request_id": "pick",
        "shown": shown,
        "choice": "choose_other",
        "option_id": "pm_pilot_urgent-" + session.language,
    }
    chosen = session.client.post(
        session.url("practice/choices"), headers=session.headers, json=choice
    )
    assert chosen.status_code == 200, chosen.text
    practice = chosen.json()["result"]["session"]
    followup = PublishedSession(
        session.app,
        session.client,
        practice["session_id"],
        {"Authorization": "Bearer " + practice["token"]},
        session.language,
    )
    code = create_code(followup).json()["result"]["code"]
    assert exchange(followup, code).status_code == 200

    replayed = session.client.post(
        session.url("practice/choices"), headers=session.headers, json=choice
    )

    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["result"]["session"]["session_id"] == practice["session_id"]
    assert replayed.json()["result"]["session"]["token"] == practice["token"]
