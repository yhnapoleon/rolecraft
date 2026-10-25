"""When the travel-policy change arrives (场景与训练闭环 §4.3; phase 2, step 4).

A package without ``initial_plan_trigger`` keeps the original rule: the first explicit
configuration apply brings it. A package with ``first_policy_test_or_apply`` also lets the first
policy-related test bring it, right after that test returns; the change lands once. The rule is
read from the package the session is bound to."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_engineer_session import TARGET_QUERY, Eng, build_app, make_session

OTHER = {"zh": "账号密码忘了怎么重置？", "en": "I forgot my account password. How do I reset it?"}


@pytest.fixture(params=["zh", "en"])
def eng(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[Eng]:
    app = build_app(tmp_path, monkeypatch, request.param)
    try:
        with TestClient(app) as client:
            yield make_session(app, client, request.param, tmp_path / "engineer")
    finally:
        app.state.store.close()


def new_rule(eng: Eng, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        eng.app.state.scenario_v2.package.rules,
        "initial_plan_trigger",
        "first_policy_test_or_apply",
    )


def run_test(eng: Eng, query: str, key: str) -> dict[str, Any]:
    version = eng.state().get("config_version", 0)
    return eng.ok(
        eng.call("/tests", "tests.create", {"query": query, "config_version": version}, key)
    )["test"]


def events(eng: Eng) -> list[dict[str, Any]]:
    return eng.ok(eng.read("/timeline"))["result"]["events"]


def policy_events(eng: Eng) -> list[dict[str, Any]]:
    return [e for e in events(eng) if e["type"] == "initial_plan_applied"]


def test_without_the_rule_a_policy_test_brings_no_change(eng: Eng) -> None:
    run_test(eng, TARGET_QUERY[eng.language], "t1")
    assert policy_events(eng) == []
    eng.advance_world()
    # The original rule: the change follows the first configuration apply.
    kinds = [e["type"] for e in events(eng)]
    assert kinds[-2:] == ["config_applied", "initial_plan_applied"]


def test_the_first_policy_test_brings_the_change_once(
    eng: Eng, monkeypatch: pytest.MonkeyPatch
) -> None:
    new_rule(eng, monkeypatch)
    first = run_test(eng, TARGET_QUERY[eng.language], "t1")
    # The test keeps the answer it got: it ran on the policy in force before the change.
    assert first["execution"]["source_versions"]["policy"] == 1
    assert "500" in first["answer"]
    (event,) = policy_events(eng)
    # Right after the test that brought it, in the same transaction.
    assert [e["type"] for e in events(eng)] == ["test_assistant", "initial_plan_applied"]
    assert event["data"]["before_versions"]["policy"] == 1
    assert event["data"]["after_versions"]["policy"] == 2
    second = run_test(eng, TARGET_QUERY[eng.language], "t2")
    assert second["execution"]["source_versions"]["policy"] == 2
    eng.advance_world()
    assert len(policy_events(eng)) == 1


def test_a_test_about_something_else_does_not_bring_it(
    eng: Eng, monkeypatch: pytest.MonkeyPatch
) -> None:
    new_rule(eng, monkeypatch)
    run_test(eng, OTHER[eng.language], "t1")
    assert policy_events(eng) == []
    eng.advance_world()
    assert [e["type"] for e in events(eng)][-2:] == ["config_applied", "initial_plan_applied"]


def test_an_unknown_rule_value_is_refused(eng: Eng, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(eng.app.state.scenario_v2.package.rules, "initial_plan_trigger", "soon")
    response = eng.call(
        "/tests", "tests.create", {"query": TARGET_QUERY[eng.language], "config_version": 0}, "t1"
    )
    assert response.status_code == 500 and "scenario_rule_invalid" in response.text
