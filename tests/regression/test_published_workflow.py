"""Release-package regressions through public HTTP and the production worker."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from career_lab.contracts.v2 import digest
from career_lab.jobs.worker import Worker
from scripts.regression.published import CATALOG

from .conftest import PublishedSession


def test_submission_response_loss_recovery_and_old_feedback(
    published_session: PublishedSession,
) -> None:
    session = published_session
    work = session.work()
    command = session.command(
        "fixed-submission",
        "submissions.create",
        {"decision": "defer_with_conditions", "products": [work]},
    )
    first = session.client.post(session.url("submissions"), headers=session.headers, json=command)
    assert first.status_code == 200, first.text
    session.run_job()
    # Pretend the write response was lost. Recover by the same key, never a new command.
    recovered = session.get("requests/fixed-submission")
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "completed"
    replay = session.client.post(session.url("submissions"), headers=session.headers, json=command)
    assert replay.status_code == 200 and replay.json()["replayed"]
    subject = first.json()["result"]["submission"]["object_id"]
    before = session.get("feedback/" + subject).json()
    report = before["result"]["result"]["items"][0]
    assert len(report["items"]) == 14
    assert report["mode"] == "advisory"
    assert report["model_coverage"] == 0
    entry = next(
        row
        for row in json.loads(CATALOG.read_text())["scenarios"]
        if row["work_language"] == session.language
        and row["root"].endswith("pm_pilot" if session.language == "zh" else "pm_pilot/locales/en")
    )
    from pathlib import Path

    evaluation = json.loads((Path(entry["root"]) / "manifest.json").read_text())
    expected = next(row for row in evaluation["files"] if row["path"] == "runtime/evaluation.json")
    assert report["evaluation"]["sha256"] == expected["sha256"]
    assert report["as_of"]
    assert report["verified_facts"][0]["subject"] == work
    assert report["verified_facts"][0]["activity_window"]
    assert report["historical_responsibilities"]
    state = session.get("").json()["state"]
    session.send(
        "revision-cycles",
        "revision",
        "begin_revision",
        {
            "parent_submission": first.json()["result"]["submission"],
            "reason": "Check scope",
        },
    )
    assert session.get("").json()["state"]["status"] == "active"
    assert (
        session.get("feedback/" + subject).json()["result"]["result"]["items"]
        == before["result"]["result"]["items"]
    )
    assert digest(session.get("feedback/" + subject).json()["result"]["result"]["items"]) == digest(
        before["result"]["result"]["items"]
    )
    assert session.get("submissions").json()["result"]["result"]["items"][0]["products"] == [work]
    assert state["status"] == "submitted"
    assert not Worker(session.app.state.jobs, session.app.state.handlers).run_once()


@pytest.mark.parametrize("capacity,expected", [(100, "countered"), (1000, "rejected")])
def test_resource_choice_never_grants_unaccepted_terms(
    published_session: PublishedSession, capacity: int, expected: str
) -> None:
    session = published_session
    if expected == "countered":
        config = session.get("timeline").json()["result"]["result"]["workspace"]["config"]
        base = {
            "session_id": session.session_id,
            "kind": "config",
            "object_id": config["id"],
            "version": config["version"],
            "config_version": config["config_version"],
        }
        session.send(
            "configuration",
            "need-more",
            "configuration.apply",
            {
                "base": base,
                "settings": {
                    "participants": 50,
                    "work_items": ["scope_filter", "human_fallback"],
                    "fallback": "human",
                },
            },
        )
    requested = session.send(
        "actions",
        "request-capacity",
        "request_business",
        {
            "tool": "request_business",
            "terms": {"capacity": capacity},
            "reason": "Need a bounded pilot",
        },
    )["result"]["request"]
    decision = session.send(
        "approvals/resolve",
        "resolve-capacity",
        "resolve_approval",
        {"request": requested, "expected_request_revision": 1},
    )["result"]["decision"]
    assert decision["status"] == expected
    assert (
        session.get("timeline").json()["result"]["result"]["workspace"]["resources"]["capacity"]
        == 30
    )


def test_revoked_agent_loses_access_and_cross_session_feedback_is_private(
    published_session: PublishedSession,
) -> None:
    session = published_session
    issued = session.send(
        "delegations",
        "grant",
        "delegations.create",
        {
            "agent_label": "Controlled regression client",
            "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            "capabilities": ["read", "act"],
        },
    )["result"]["result"]
    agent_headers = {"Authorization": "Bearer " + issued["token"]}
    endpoint = session.url("work-items")
    assert session.client.get(endpoint, headers=agent_headers).status_code == 200
    revoked = session.client.request(
        "DELETE",
        session.url("delegations/" + issued["delegation"]["id"]),
        headers=session.headers,
        json=session.command(
            "revoke",
            "delegations.revoke",
            {"delegation_id": issued["delegation"]["id"]},
        ),
    )
    assert revoked.status_code == 200, revoked.text
    assert session.client.get(endpoint, headers=agent_headers).status_code in (401, 403)
    assert issued["token"] not in session.get("delegations").text
    other = session.client.post(
        "/sessions",
        json={
            "schema_version": 2,
            "scenario": "pm_pilot_v2",
            "work_language": session.language,
        },
    ).json()
    assert session.client.get(
        endpoint, headers={"Authorization": "Bearer " + other["token"]}
    ).status_code in (401, 403)
