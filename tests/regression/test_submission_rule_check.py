"""Pre-submission rule check: read-only, rules only, the same rule items as the formal feedback.

The person checks what submitting the chosen versions and decision would give, before
submitting. Nothing is saved and no model runs; once the same inputs are submitted, the
feedback records exactly the rule items the check showed.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, table

from career_lab.api import evaluation_runtime, vertical_runtime
from career_lab.contracts.v2 import ProtocolError
from career_lab.runtime.model_adapter import LocalModel
from career_lab.runtime.model_slots import ModelSlots
from career_lab.runtime.roles_v2 import LocalRoleModel
from scripts.regression.published import write_catalog

from .conftest import PublishedSession

QUESTION = {
    "zh": "住宿报销上限是多少？",
    "en": "What is the hotel reimbursement limit per night?",
}


def workspace_config(session: PublishedSession) -> dict[str, object]:
    return session.get("timeline").json()["result"]["result"]["workspace"]["config"]


def config_ref(session: PublishedSession) -> dict[str, object]:
    config = workspace_config(session)
    return {
        "session_id": session.session_id,
        "kind": "config",
        "object_id": config["id"],
        "version": config["version"],
        "config_version": config["config_version"],
    }


def run_test(session: PublishedSession, key: str) -> dict[str, object]:
    version = workspace_config(session)["config_version"]
    return session.send(
        "tests",
        key,
        "tests.create",
        {"query": QUESTION[session.language], "config_version": version},
    )


def apply(session: PublishedSession, key: str, **changes: object) -> None:
    config = workspace_config(session)
    body = (
        config
        | changes
        | {
            "version": config["version"] + 1,
            "config_version": config["config_version"] + 1,
        }
    )
    session.send("actions", key, "apply_config", {"tool": "apply_config", "config": body})


def as_the_submit_control_sends(session: PublishedSession, decision: str) -> dict[str, object]:
    return {"decision": decision, "products": [session.work()], "config": config_ref(session)}


def check(session: PublishedSession, payload: dict[str, object]):
    return session.client.post(
        session.url("submission-rule-check"),
        headers=session.headers,
        json=session.command("rule-check", "submissions.rule_check", payload),
    )


def submit(session: PublishedSession, payload: dict[str, object]) -> dict[str, object]:
    saved = session.send("submissions", "submit", "submissions.create", payload)
    session.run_job()
    subject = saved["result"]["submission"]["object_id"]
    return session.get("feedback/" + subject).json()["result"]["result"]["items"][0]


def fresh_launch(session: PublishedSession) -> str:
    return "launch"


def retested_before_reconfiguring(session: PublishedSession) -> str:
    """164 F17: retested after the policy update on v1, then changed the settings to v2."""
    run_test(session, "before-update")
    apply(session, "update", freshness_guard="warn")
    run_test(session, "retest")
    apply(session, "reconfigure", fallback="none")
    return "launch_narrow"


def beyond_capacity_and_resources(session: PublishedSession) -> str:
    apply(
        session,
        "too-much",
        participants=40,
        work_items=["scope_filter", "human_fallback", "realtime_sync"],
        launch_day=9,
    )
    return "launch"


def deferred_after_retesting(session: PublishedSession) -> str:
    retested_before_reconfiguring(session)
    return "defer_with_conditions"


def stopped_after_retesting(session: PublishedSession) -> str:
    retested_before_reconfiguring(session)
    return "no_go"


SITUATIONS = (
    fresh_launch,
    retested_before_reconfiguring,
    beyond_capacity_and_resources,
    deferred_after_retesting,
    stopped_after_retesting,
)


@pytest.mark.parametrize("situation", SITUATIONS, ids=lambda f: f.__name__)
def test_checked_rule_items_are_the_rule_items_of_the_feedback_once_submitted(
    published_session: PublishedSession, situation: Callable[[PublishedSession], str]
) -> None:
    session = published_session
    payload = as_the_submit_control_sends(session, situation(session))
    response = check(session, payload)
    assert response.status_code == 200, response.text
    checked = response.json()["result"]
    assert (checked["basis"], checked["mode"]) == ("draft", "rules_only")
    feedback = submit(session, payload)
    assert checked["as_of"] == feedback["as_of"]
    assert checked["rule_items"] == feedback["rule_items"]


def test_the_check_names_the_verified_facts_behind_its_rule_items(
    published_session: PublishedSession,
) -> None:
    session = published_session
    payload = as_the_submit_control_sends(session, retested_before_reconfiguring(session))
    facts = check(session, payload).json()["result"]["facts"]
    # Capacity 30, 3 developer-days and day 7 are the brief's starting constraints; the
    # default 20 participants and two one-day work items fit them. Configuration v2 was never
    # tested: v0 ran before the policy update, v1 after it.
    assert facts == {
        "schema_version": 2,
        "participants": 20,
        "capacity": 30,
        "required_dev_days": 2,
        "available_dev_days": 3,
        "requested_launch_day": 7,
        "deadline_day": 7,
        "unapproved_resource_excess": False,
        "config_version": 2,
        "policy_version": 2,
        "adjustment_actions": 1,
        "test_runs": [
            {"schema_version": 2, "config_version": 0, "runs": 1, "retests": 0},
            {"schema_version": 2, "config_version": 1, "runs": 1, "retests": 1},
        ],
    }


def stored_rows(session: PublishedSession) -> dict[str, int]:
    engine = session.app.state.v2_store.db.engine
    with engine.connect() as connection:
        return {
            name: connection.execute(select(func.count()).select_from(table(name))).scalar_one()
            for name in inspect(engine).get_table_names()
        }


def test_a_check_writes_nothing_and_moves_no_state(published_session: PublishedSession) -> None:
    session = published_session
    payload = as_the_submit_control_sends(session, retested_before_reconfiguring(session))
    before = (stored_rows(session), session.get("").json()["state"])
    first = check(session, payload)
    second = check(session, payload)
    assert (first.status_code, second.status_code) == (200, 200)
    assert (stored_rows(session), session.get("").json()["state"]) == before
    assert first.json() == second.json()


class CountingModel:
    """A configured Judge and support model that only counts calls (and always fails)."""

    revision = "counting-model"
    retries = 0

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages: list[dict], tools: list[dict]) -> None:
        self.calls += 1
        raise RuntimeError("counting model")


@pytest.fixture
def judged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[PublishedSession, CountingModel]]:
    model = CountingModel()
    monkeypatch.setenv("CAREER_LAB_SCENARIO_CATALOG", str(write_catalog(tmp_path / "catalog.json")))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    monkeypatch.setattr(
        vertical_runtime,
        "configured_slots",
        lambda provider: ModelSlots(LocalRoleModel(), model, model, None, LocalModel()),
    )
    app = vertical_runtime.create_runtime_app("sqlite:///" + str(tmp_path / "s.db"))
    with TestClient(app) as client:
        created = client.post(
            "/sessions",
            json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": "zh"},
        ).json()
        headers = {"Authorization": "Bearer " + created["token"]}
        yield PublishedSession(app, client, created["session_id"], headers, "zh"), model
    app.state.store.close()
    app.state.v2_store.db.engine.dispose()


def test_a_check_runs_no_model_even_where_feedback_uses_one(
    judged: tuple[PublishedSession, CountingModel],
) -> None:
    session, model = judged
    payload = as_the_submit_control_sends(session, retested_before_reconfiguring(session))
    assert check(session, payload).status_code == 200
    assert model.calls == 0
    submit(session, payload)
    assert model.calls > 0


def test_only_the_person_of_this_practice_can_check(published_session: PublishedSession) -> None:
    session = published_session
    payload = as_the_submit_control_sends(session, "launch")
    issued = session.send(
        "delegations",
        "grant",
        "delegations.create",
        {
            "agent_label": "Rule check boundary",
            "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            "capabilities": ["read", "act", "submit"],
        },
    )["result"]["result"]
    other = session.client.post(
        "/sessions",
        json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": session.language},
    ).json()
    url = session.url("submission-rule-check")
    body = session.command("rule-check", "submissions.rule_check", payload)

    def status(headers: dict[str, str]) -> tuple[int, str]:
        response = session.client.post(url, headers=headers, json=body)
        return response.status_code, response.json()["code"]

    assert status({}) == (401, "token_required")
    assert status({"Authorization": "Bearer " + issued["token"]}) == (403, "human_required")
    assert status({"Authorization": "Bearer " + other["token"]})[0] == 401
    assert check(session, payload).status_code == 200


def test_a_check_needs_saved_versions_the_current_state_and_an_open_practice(
    published_session: PublishedSession,
) -> None:
    session = published_session
    payload = as_the_submit_control_sends(session, "launch")
    work = payload["products"][0]
    missing = {**payload, "products": [{**work, "version": work["version"] + 1}]}
    assert check(session, missing).status_code == 404
    stale = session.command("rule-check", "submissions.rule_check", payload)
    stale["expected_version"] += 1
    response = session.client.post(
        session.url("submission-rule-check"), headers=session.headers, json=stale
    )
    assert (response.status_code, response.json()["code"]) == (409, "version_conflict")
    other = session.command("rule-check", "submissions.create", payload)
    response = session.client.post(
        session.url("submission-rule-check"), headers=session.headers, json=other
    )
    assert response.status_code == 422
    submit(session, payload)
    response = check(session, payload)
    assert (response.status_code, response.json()["code"]) == (422, "session_submitted")


def saved_check(session: PublishedSession, submission_id: str):
    return session.client.get(
        session.url("submission-rule-check"),
        headers=session.headers,
        params={"submission_id": submission_id},
    )


def test_a_saved_submission_is_checked_again_at_its_own_point(
    published_session: PublishedSession,
) -> None:
    session = published_session
    payload = as_the_submit_control_sends(session, retested_before_reconfiguring(session))
    feedback = submit(session, payload)
    subject = feedback["subject"]
    response = saved_check(session, subject["object_id"])
    assert response.status_code == 200, response.text
    checked = response.json()["result"]
    assert (checked["basis"], checked["submission"]) == ("saved", subject)
    assert checked["as_of"] == feedback["as_of"]
    assert checked["rule_items"] == feedback["rule_items"]
    # Later work does not change what held at submission.
    session.send(
        "revision-cycles",
        "revise",
        "begin_revision",
        {"parent_submission": subject, "reason": "Retest on the current settings."},
    )
    run_test(session, "after-revision")
    assert saved_check(session, subject["object_id"]).json() == response.json()
    assert saved_check(session, "missing").status_code == 404


def test_no_check_where_this_service_runs_no_evaluation_for_the_package(
    published_session: PublishedSession,
) -> None:
    session = published_session
    payload = as_the_submit_control_sends(session, "launch")
    registry = session.app.state.gateway.registry
    # The package is served, but installs no evaluation.
    registry.rule_checks.clear()
    response = check(session, payload)
    assert (response.status_code, response.json()["code"]) == (
        503,
        "evaluation_runtime_unavailable",
    )
    # The package is no longer served at all (an archived practice).
    registry.active_bindings = ()
    response = check(session, payload)
    assert (response.status_code, response.json()["code"]) == (409, "scenario_read_only")


def test_an_unusable_evaluation_package_starts_without_a_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unusable(module: object) -> None:
        raise ProtocolError("evaluation_runtime_unavailable", status=503)

    monkeypatch.setenv("CAREER_LAB_SCENARIO_CATALOG", str(write_catalog(tmp_path / "catalog.json")))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    monkeypatch.setattr(evaluation_runtime, "installed_evaluation", unusable)
    app = vertical_runtime.create_runtime_app(
        "sqlite:///" + str(tmp_path / "s.db"), feedback_handler=lambda *args: None
    )
    try:
        with TestClient(app) as client:
            created = client.post(
                "/sessions",
                json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": "zh"},
            ).json()
            headers = {"Authorization": "Bearer " + created["token"]}
            session = PublishedSession(app, client, created["session_id"], headers, "zh")
            response = check(session, as_the_submit_control_sends(session, "launch"))
            assert (response.status_code, response.json()["code"]) == (
                503,
                "evaluation_runtime_unavailable",
            )
    finally:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()
