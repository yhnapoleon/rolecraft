"""The workbench can tell whether the recognition layer is on (demo edition, outside the contract).

Off (``CAREER_LAB_RECOGNIZERS`` unset), the pre-submission check carries no sentence step, the
behaviour read computes nothing and the recognition read says so; the workbench then shows no
sentence block, no session summary and no behaviour section. On (any recognizer root, a missing
one meaning rule fallback), the rule check stays fast and marks the sentence step pending; its
own read-only route returns the sentence labels. The frozen OpenAPI does not change.
"""

import json
from pathlib import Path

import pytest

from .conftest import PublishedSession
from .test_submission_rule_check import as_the_submit_control_sends, check, stored_rows

FREEZE = Path(__file__).resolve().parents[2] / "docs/contracts/expansion-v3/openapi.json"
ROUTE = "submission-rule-check/recognition"


def sentences(session: PublishedSession, payload: dict[str, object]):
    return session.client.post(
        session.url(ROUTE),
        headers=session.headers,
        json=session.command("sentences", "submissions.rule_check", payload),
    )


@pytest.fixture
def layer_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAREER_LAB_RECOGNIZERS", str(tmp_path / "no-recognizers-here"))


@pytest.fixture
def layer_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAREER_LAB_RECOGNIZERS", raising=False)


def test_layer_off_the_check_carries_no_sentence_step(
    layer_off: None, published_session: PublishedSession
) -> None:
    session = published_session
    payload = as_the_submit_control_sends(session, "launch_narrow")
    checked = check(session, payload)
    assert checked.status_code == 200, checked.text
    assert "recognition" not in checked.json()["result"]
    step = sentences(session, payload)
    assert step.status_code == 200, step.text
    assert step.json()["result"] == {
        "session_id": session.session_id,
        "enabled": False,
        "recognition": None,
    }


def test_layer_on_the_rules_come_first_and_the_sentences_on_their_own_route(
    layer_on: None, published_session: PublishedSession
) -> None:
    session = published_session
    payload = as_the_submit_control_sends(session, "launch_narrow")
    checked = check(session, payload)
    assert checked.status_code == 200, checked.text
    assert checked.json()["result"]["recognition"] == {"status": "pending"}
    before = stored_rows(session)
    step = sentences(session, payload)
    assert step.status_code == 200, step.text
    result = step.json()["result"]
    assert (result["session_id"], result["enabled"]) == (session.session_id, True)
    units = result["recognition"]["units"]
    expected = {"index", "quote", "label", "confidence", "decision", "probabilities", "reason"}
    assert units and expected | {"expected_cost", "evidence", "source", "top"} <= set(units[0])
    assert result["recognition"]["fallback"] is True
    assert result["recognition"]["defer_cost"] == 0.5
    sourced = [u["source"] for u in units if u["source"]]
    assert sourced and all(s["kind"] and s["object_id"] and s["version"] >= 1 for s in sourced)
    assert any(s["kind"] == "material" and s["title"] for s in sourced)
    again = sentences(session, payload).json()["result"]
    assert again == result
    assert stored_rows(session) == before


def test_a_saved_submission_check_never_carries_the_sentence_step(
    layer_on: None, published_session: PublishedSession
) -> None:
    session = published_session
    payload = as_the_submit_control_sends(session, "launch_narrow")
    saved = session.send("submissions", "submit", "submissions.create", payload)
    subject = saved["result"]["submission"]["object_id"]
    again = session.get("submission-rule-check?submission_id=" + subject)
    assert again.status_code == 200, again.text
    assert "recognition" not in again.json()["result"]


def test_the_reads_say_whether_the_layer_is_on(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session = published_session
    monkeypatch.delenv("CAREER_LAB_RECOGNIZERS", raising=False)
    recognition = session.get("recognition").json()["result"]["result"]
    assert recognition["enabled"] is False and "records" in recognition
    assert session.get("behavior").json()["result"]["result"] == {"enabled": False}
    monkeypatch.setenv("CAREER_LAB_RECOGNIZERS", str(tmp_path / "missing"))
    assert session.get("recognition").json()["result"]["result"]["enabled"] is True
    behavior = session.get("behavior").json()["result"]["result"]
    assert behavior["enabled"] is True and "sequence" in behavior


def test_the_sentence_route_stays_out_of_the_public_openapi(
    published_session: PublishedSession,
) -> None:
    paths = published_session.app.openapi()["paths"]
    assert "/sessions/{session_id}/" + ROUTE not in paths
    frozen = json.loads(FREEZE.read_text())["paths"]
    assert "/sessions/{session_id}/" + ROUTE not in frozen
