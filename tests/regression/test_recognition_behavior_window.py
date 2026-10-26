"""The behaviour a feedback freezes is the live behaviour read, cut at the hand-in point.

The feedback job reads its session through a job view. That view now carries the public
history up to the job's snapshot (read with the job's authorization), so the behaviour
recognizer sees the same reads, tests and submissions the learner's live ``GET /behavior``
sees, and the frozen record names the events it was computed from.
"""

from pathlib import Path

import pytest

from .conftest import PublishedSession
from .test_submission_rule_check import as_the_submit_control_sends, run_test


@pytest.fixture
def layer_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The recognition layer on, with no weights: every recognizer uses its rule fallback."""
    monkeypatch.setenv("CAREER_LAB_RECOGNIZERS", str(tmp_path / "no-recognizers-here"))


def read_material(session: PublishedSession, material: str) -> None:
    session.send(
        "actions",
        "read-" + material,
        "read_material",
        {
            "tool": "read_material",
            "material": {
                "session_id": session.session_id,
                "kind": "material",
                "object_id": material,
                "version": 1,
            },
        },
    )


def test_the_frozen_behaviour_is_the_live_trajectory_up_to_the_hand_in(
    layer_on: None, published_session: PublishedSession
) -> None:
    session = published_session
    for material in ("brief", "technical"):
        read_material(session, material)
    run_test(session, "probe")
    payload = as_the_submit_control_sends(session, "launch_narrow")
    session.send("submissions", "submit", "submissions.create", payload)
    session.run_job()
    records = session.get("recognition").json()["result"]["result"]["records"]
    frozen = [
        row["record"]
        for row in records
        if row["carrier"]["kind"] == "feedback" and row["record"]["task"] == "behavior"
    ]
    assert frozen, records
    outputs = frozen[-1]["outputs"]
    window = outputs["window"]
    # Two reads, one test and the submission itself are events; before this fix the job
    # view had no history and the frozen behaviour counted only role turns (none here).
    assert window["events"] >= 4 and window["from_seq"] == 0
    assert outputs["length"] == len(outputs["steps"]) >= 4
    assert all(step["event_id"] for step in outputs["steps"])
    assert outputs["steps"][-1]["symbol"] == "submit"

    live = session.get("behavior").json()["result"]["result"]
    assert live["enabled"] is True
    up_to_hand_in = [
        {"seq": row["seq"], "symbol": row["symbol"], "event_id": row.get("event_id")}
        for row in live["sequence"]
        if row["seq"] <= window["to_seq"]
    ]
    assert outputs["steps"] == up_to_hand_in
    assert live["window"]["to_seq"] >= window["to_seq"]
    assert frozen[-1]["revision"] == live["record"]["revision"]


def test_with_the_layer_off_a_job_view_carries_no_history(
    published_session: PublishedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Off, job views are exactly as before: the frozen history is a recognition-layer change."""
    monkeypatch.delenv("CAREER_LAB_RECOGNIZERS", raising=False)
    store = published_session.app.state.v2_store
    sentinel = object()
    assert store._with_frozen_history(None, sentinel, None) is sentinel
