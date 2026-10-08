"""Six shipped packages and their practice transitions; no runtime generation."""

import json
from pathlib import Path

import pytest

from career_lab.jobs.worker import Worker
from career_lab.scenarios.v2.module import ScenarioModule
from scripts.regression.published import CATALOG, ROOT

from .conftest import PublishedSession

ENTRIES = json.loads(CATALOG.read_text())["scenarios"]


@pytest.mark.parametrize("entry", ENTRIES, ids=[row["root"].split("2.9.6/")[1] for row in ENTRIES])
def test_installed_package_is_valid_as_published(entry: dict[str, str]) -> None:
    module = ScenarioModule(ROOT / entry["root"])
    assert module.bindings.scenario.sha256 == entry["scenario_hash"]
    assert module.work_language == entry["work_language"]


def submit(session: PublishedSession) -> tuple[str, dict[str, object]]:
    work = session.work()
    saved = session.send(
        "submissions",
        "submit",
        "submissions.create",
        {
            "decision": "defer_with_conditions",
            "products": [work],
        },
    )
    session.run_job()
    subject = saved["result"]["submission"]["object_id"]
    feedback = session.get("feedback/" + subject).json()["result"]["result"]["items"][0]
    return subject, feedback


@pytest.mark.parametrize("variant", ["pm_pilot_urgent", "pm_pilot_capacity15"])
def test_published_practice_starts_once_and_preserves_feedback(
    published_session: PublishedSession,
    variant: str,
) -> None:
    session = published_session
    subject, feedback = submit(session)
    shown = session.get("practice?submission_id=" + subject)
    assert shown.status_code == 200, shown.text
    options = shown.json()["result"]
    assert len(options["catalog"]) == 2
    assert options["work_language"] == session.language
    choice = {
        "request_id": "choose-once",
        "shown": options,
        "choice": "choose_other",
        "option_id": variant + "-" + session.language,
    }
    selected = session.client.post(
        session.url("practice/choices"), headers=session.headers, json=choice
    )
    assert selected.status_code == 200, selected.text
    replay = session.client.post(
        session.url("practice/choices"), headers=session.headers, json=choice
    )
    assert replay.status_code == 200, replay.text
    assert selected.json()["result"]["session"] == replay.json()["result"]["session"]
    assert replay.json()["result"]["duplicate"] is True
    created = selected.json()["result"]["session"]
    expected = next(
        row
        for row in ENTRIES
        if Path(row["root"]).parts[-1 if session.language == "zh" else -3] == variant
        and row["work_language"] == session.language
    )
    assert created["binding"]["scenarioHash"] == expected["scenario_hash"]
    assert session.get("feedback/" + subject).json()["result"]["result"]["items"][0] == feedback
    assert not Worker(session.app.state.jobs, session.app.state.handlers).run_once()


def test_saved_feedback_is_private_and_history_reads_never_regenerate(
    published_session: PublishedSession,
) -> None:
    session = published_session
    _, feedback = submit(session)
    url = session.url("feedback-records/" + feedback["id"])
    before = session.client.get(url, headers=session.headers)
    assert before.status_code == 200
    created = session.client.post(
        "/sessions",
        json={
            "schema_version": 2,
            "scenario": "pm_pilot_v2",
            "work_language": session.language,
        },
    ).json()
    foreign = session.client.get(url, headers={"Authorization": "Bearer " + created["token"]})
    assert foreign.status_code in (401, 403)
    assert session.client.get(url).status_code == 401
    # A reader must not need the producer, even if every job handler is unavailable.
    session.app.state.handlers.clear()
    assert session.client.get(url, headers=session.headers).json() == before.json()
    assert session.client.get(url, headers=session.headers).json() == before.json()
