"""Tests and saved work are cited with the exact reference the evaluator verifies."""

from typing import Any

from test_w05_http_support import WorkSession
from test_w05_http_support import work_session as work_session

from career_lab.contracts import v2 as C
from career_lab.jobs.worker import Worker

QUESTION = {
    "zh": "住宿报销上限是多少？",
    "en": "What is the hotel reimbursement limit per night?",
}
NOTE = {"zh": "试用记录：酒店上限已核对。", "en": "Trial notes: the hotel limit is checked."}
DECISION = {"zh": "先小范围开放，依据见引用。", "en": "Open narrowly first; see the cited basis."}


def read_material(session: WorkSession, material: str) -> None:
    session.post(
        "actions",
        "read_material",
        {
            "tool": "read_material",
            "material": {
                "session_id": session.sid,
                "kind": "material",
                "object_id": material,
                "version": 1,
            },
        },
    )


def citation(session: WorkSession, ref: dict[str, Any]) -> dict[str, Any]:
    found = session.get(f"objects/{ref['kind']}/{ref['object_id']}/{ref['version']}")
    return found["evidence_ref"]


def cited_test_and_note(session: WorkSession) -> list[dict[str, Any]]:
    """One actual test run and one saved note, cited after later business events."""
    read_material(session, "brief")
    run = session.post(
        "tests", "tests.create", {"query": QUESTION[session.language], "config_version": 0}
    )["result"]["test"]
    note = session.product(NOTE[session.language])
    # A later read moves the business clock past both creation points.
    read_material(session, "technical")
    test_ref = {"session_id": session.sid, "kind": "test", "object_id": run["id"], "version": 1}
    return [citation(session, test_ref), citation(session, note)]


def submit(session: WorkSession, product: dict[str, Any]) -> dict[str, Any]:
    config = session.get("timeline")["workspace"]["config"]
    submitted = session.post(
        "submissions",
        "submissions.create",
        {
            "decision": "launch_narrow",
            "products": [product],
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


def test_cited_test_and_work_are_verified_in_submission_feedback(
    work_session: WorkSession,
) -> None:
    session = work_session
    cited = cited_test_and_note(session)
    assert [ref["kind"] for ref in cited] == ["test", "product"]
    decision = session.product(
        DECISION[session.language], purpose="commitment", evidence_refs=cited
    )
    report = submit(session, decision)
    checks = report["verified_facts"][0]["references"]
    assert [check["status"] for check in checks] == ["exact_reference_verified"] * 2
    assert sorted(C.canonical(check["verified_ref"]) for check in checks) == sorted(
        C.canonical(ref) for ref in cited
    )


def test_requests_and_supplements_accept_cited_tests_and_work(work_session: WorkSession) -> None:
    session = work_session
    cited = cited_test_and_note(session)
    asked = session.post(
        "actions",
        "request_business",
        {
            "tool": "request_business",
            "terms": {"dev_days": 4},
            "reason": "Real-time sync" if session.language == "en" else "实时同步需要人日",
            "evidence_refs": cited,
        },
    )
    assert asked["result"]["request_data"]["evidence_refs"] == cited
    decided = session.post(
        "approvals/resolve",
        "resolve_approval",
        {"request": asked["result"]["request"], "expected_request_revision": 1},
    )
    assert decided["result"]["decision"]["reason_code"] != "request_evidence_invalid"
    report = submit(session, session.product(DECISION[session.language], purpose="commitment"))
    recorded = session.post(
        "feedback/" + report["id"] + "/responses",
        "feedback.responses.create",
        {
            "feedback_id": report["id"],
            "feedback_version": 1,
            "kind": "supplement",
            "section": "rule_items",
            "criterion": "R4.staleness_test",
            "text": "Retested after the change." if session.language == "en" else "变更后已复测。",
            "evidence": cited,
        },
    )
    assert recorded["result"]["evidence_status"] == "user_submitted_unverified"
    saved = session.get("feedback-responses/" + recorded["result"]["response"]["object_id"])
    assert saved["items"][0]["evidence"] == cited


def test_only_tests_and_work_carry_an_object_citation(work_session: WorkSession) -> None:
    session = work_session
    read_material(session, "brief")
    material = session.get("objects/material/brief/1")
    assert "evidence_ref" not in material
    assert all(fragment["ref"]["quote"] for fragment in material["content"]["fragments"])
    config = session.get("timeline")["workspace"]["config"]
    read = session.get(
        f"objects/config/{config['id']}/{config['version']}"
        f"?config_version={config['config_version']}"
    )
    assert "evidence_ref" not in read
