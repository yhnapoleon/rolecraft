"""The recorded business decisions are shown in the feedback panel line by line, as stored.

The web fixture holds the records this scenario produces; the feedback panel and the request
panel are tested against it in `business-decisions.test.ts`. This test keeps the fixture true to
the backend: one line per request with its latest decision at the feedback point, and nothing
decided afterwards. Object ids are random, so the order of the lines is not compared.
"""

import json
from pathlib import Path
from typing import Any

from test_w05_http_support import WorkSession
from test_w05_http_support import work_session as work_session

from career_lab.jobs.worker import Worker

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "apps/web/src/features/feedback-native/business-response.fixtures.json"
)
HEADING = {
    "zh": "已记录的业务决定（规则核实）：",
    "en": "Recorded business decisions (rule checked): ",
}
REASON = {
    "zh": "试点需要更多资源，依据见测试记录。",
    "en": "The pilot needs more resources; see the test record.",
}
NOTE = {"zh": "试点安排草稿。", "en": "Draft pilot plan."}


def ask(session: WorkSession, terms: dict[str, int]) -> dict[str, Any]:
    """Request resources and have the approval rules decide it."""
    made = session.post(
        "actions",
        "request_business",
        {"tool": "request_business", "terms": terms, "reason": REASON[session.language]},
    )["result"]["request"]
    return session.post(
        "approvals/resolve",
        "resolve_approval",
        {"request": made, "expected_request_revision": made["version"]},
    )["result"]


def decided(session: WorkSession) -> list[dict[str, Any]]:
    """Each request's terms and its latest decision so far."""
    rows = session.get("timeline")["objects"]
    requested = {
        row["ref"]["object_id"]: row["content"]["requested"]
        for row in rows
        if row["ref"]["kind"] == "business_request"
    }
    latest: dict[str, str] = {}
    for row in rows:
        if row["ref"]["kind"] == "business_decision":
            latest[row["content"]["request"]["object_id"]] = row["content"]["status"]
    return sorted(
        ({"requested": requested[r], "status": status} for r, status in latest.items()),
        key=json.dumps,
    )


def lines(record: str, language: str) -> list[str]:
    """The decision lines of a record, in sorted order."""
    assert record.startswith(HEADING[language]), record
    return sorted(record.removeprefix(HEADING[language]).split("\n"))


def submit(session: WorkSession, text: str) -> dict[str, Any]:
    config = session.get("timeline")["workspace"]["config"]
    submitted = session.post(
        "submissions",
        "submissions.create",
        {
            "decision": "launch_narrow",
            "products": [session.product(text)],
            "config": {
                "session_id": session.sid,
                "kind": "config",
                "object_id": config["id"],
                "version": config["version"],
                "config_version": config["config_version"],
            },
        },
    )
    assert Worker(session.app.state.jobs, session.app.state.handlers).run_once()
    return session.get("feedback/" + submitted["result"]["submission"]["object_id"])["items"][0]


def test_recorded_business_decisions_match_the_web_fixture(work_session: WorkSession) -> None:
    session = work_session
    language = session.language
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))[language]
    config = session.get("timeline")["workspace"]["config"]
    # Fifty participants need more seats than the pilot has, so the rules counter.
    session.post(
        "configuration",
        "configuration.apply",
        {
            "base": {
                "session_id": session.sid,
                "kind": "config",
                "object_id": config["id"],
                "version": config["version"],
                "config_version": config["config_version"],
            },
            "settings": {
                "participants": 50,
                "work_items": ["scope_filter", "human_fallback"],
                "fallback": "human",
            },
        },
    )

    # A counteroffer still open at the first submission.
    offered = ask(session, {"capacity": 100})
    assert offered["decision"]["status"] == "countered", offered
    first = submit(session, NOTE[language])
    assert decided(session) == expected["countered"]["decisions"]
    assert lines(first["business_response"], language) == lines(
        expected["countered"]["business_response"], language
    )

    # Revised: the counteroffer is accepted and a second request is decided.
    session.post(
        "revision-cycles",
        "begin_revision",
        {"parent_submission": first["subject"], "reason": REASON[language]},
    )
    session.post(
        "actions",
        "accept_counteroffer",
        {
            "tool": "accept_counteroffer",
            "request": offered["request"],
            "terms": offered["decision"]["countered"],
        },
    )
    ask(session, {"dev_days": 6})
    second = submit(session, NOTE[language])
    assert decided(session) == expected["decided"]["decisions"]
    assert lines(second["business_response"], language) == lines(
        expected["decided"]["business_response"], language
    )

    # Decisions after the first feedback point leave its stored record as it was.
    again = session.get("feedback/" + first["subject"]["object_id"])["items"][0]
    assert again["business_response"] == first["business_response"]
