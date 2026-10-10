"""063-08: a saved preview stays as recorded; later reads name what changed and what was done."""

from typing import Any

from test_w05_http_support import WorkSession, referenced_ids
from test_w05_http_support import work_session as work_session

from career_lab.contracts import v2 as C
from career_lab.jobs.worker import Worker

NOTE = {"zh": "试点决定：先小范围试点，保留人工兜底。", "en": "Pilot decision: start small."}


def save(session: WorkSession, *, purpose: str = "commitment", text: str = "") -> dict[str, Any]:
    return session.post(
        "work-products",
        "work_products.create",
        {
            "kind": "text",
            "purpose": purpose,
            "title": "Pilot decision",
            "content": text or NOTE[session.language],
        },
    )["result"]


def revise(session: WorkSession, ref: dict[str, Any], text: str) -> dict[str, Any]:
    return session.post(
        "work-products/" + ref["object_id"] + "/versions",
        "work_products.versions.create",
        {
            "product_id": ref["object_id"],
            "expected_head": ref["version"],
            "kind": "text",
            "purpose": "commitment",
            "content": text,
        },
    )["result"]


def page(session: WorkSession, ref: dict[str, Any], **options: Any) -> dict[str, Any]:
    return session.get("work-products/" + ref["object_id"] + "/versions", **options)


def state_of(session: WorkSession, saved: dict[str, Any]) -> dict[str, Any]:
    found = page(session, saved["ref"])
    index = [row["id"] for row in found["previews"]].index(saved["preview_feedback"]["object_id"])
    return found["preview_states"][index]


def apply_config(session: WorkSession, **settings: Any) -> dict[str, Any]:
    config = session.get("timeline")["workspace"]["config"]
    base = {
        "session_id": session.sid,
        "kind": "config",
        "object_id": config["id"],
        "version": config["version"],
        "config_version": config["config_version"],
    }
    return session.post(
        "configuration", "configuration.apply", {"base": base, "settings": settings}
    )


def public_state(session: WorkSession) -> tuple:
    return (session.get()["state"], session.get("timeline")["objects"], session.get("reviews"))


def test_out_10_saved_preview_starts_current_and_reads_change_nothing(
    work_session: WorkSession,
) -> None:
    session = work_session
    saved = save(session)
    before = public_state(session)
    first = state_of(session, saved)
    for _ in range(3):
        assert state_of(session, saved) == first
        session.get("feedback-records/" + saved["preview_feedback"]["object_id"])
    assert first["status"] == "current" and first["changes"] == [] and first["actual"] == []
    assert first["feedback"] == saved["preview_feedback"]
    assert public_state(session) == before
    # A read never queues work: no model call, no second preview.
    assert Worker(session.app.state.jobs, session.app.state.handlers).run_once() is False


def test_out_10_configuration_change_marks_the_earlier_preview_stale(
    work_session: WorkSession,
) -> None:
    session = work_session
    saved = save(session)
    record = session.get("feedback-records/" + saved["preview_feedback"]["object_id"])
    assert record["preview_state"]["status"] == "current"
    stored = C.canonical(record["feedback"])
    apply_config(session, participants=30)
    state = state_of(session, saved)
    assert state["status"] == "stale"
    changes = {row["condition"]: row for row in state["changes"]}
    assert changes["configuration"]["before"] == 0
    assert changes["configuration"]["after"] == 1
    assert changes["configuration"]["ref"]["kind"] == "config"
    assert state["superseded_by"] is None
    # The preview itself is never rewritten or silently replaced.
    again = session.get("feedback-records/" + saved["preview_feedback"]["object_id"])
    assert C.canonical(again["feedback"]) == stored
    assert again["preview_state"]["status"] == "stale"
    assert [row["id"] for row in page(session, saved["ref"])["previews"]] == [
        saved["preview_feedback"]["object_id"]
    ]


def test_out_10_new_version_supersedes_while_unrelated_work_does_not(
    work_session: WorkSession,
) -> None:
    session = work_session
    saved = save(session)
    other = save(session, purpose="exploration", text="Another note")
    revise(session, other["ref"], "Another note, revised")
    assert state_of(session, saved)["status"] == "current"
    newer = revise(session, saved["ref"], "Revised decision")
    found = page(session, saved["ref"])
    old, new = found["preview_states"]
    assert old["status"] == "stale"
    assert [(row["condition"], row["before"], row["after"]) for row in old["changes"]] == [
        ("input", 1, 2)
    ]
    assert C.ObjectRef.model_validate(old["changes"][0]["ref"]) == C.ObjectRef.model_validate(
        newer["ref"]
    )
    assert old["superseded_by"] == newer["preview_feedback"]
    assert new["status"] == "current" and new["superseded_by"] is None


def test_out_10_approved_resources_mark_the_preview_stale(work_session: WorkSession) -> None:
    session = work_session
    saved = save(session)
    apply_config(session, participants=50)
    asked = session.post(
        "actions",
        "request_business",
        {"tool": "request_business", "terms": {"capacity": 60}, "reason": "Pilot capacity"},
    )
    session.post(
        "approvals/resolve",
        "resolve_approval",
        {"request": asked["result"]["request"], "expected_request_revision": 1},
    )
    state = state_of(session, saved)
    assert state["status"] == "stale"
    resources = next(row for row in state["changes"] if row["condition"] == "resources")
    assert resources["before"] == {"capacity": 30} and resources["after"] == {"capacity": 60}
    assert resources["ref"]["kind"] == "business_decision"
    approval = next(row for row in state["actual"] if row["operation"] == "actions")
    assert approval["status"] == "approved"
    assert approval["values"]["requested"] == {"capacity": 60}
    assert approval["values"]["granted"] == {"capacity": 60}
    assert approval["at"]["business_seq"] > asked["result"]["request_data"]["as_of"]["business_seq"]


def test_out_13_actual_actions_are_listed_beside_the_unchanged_prediction(
    work_session: WorkSession,
) -> None:
    session = work_session
    saved = save(session)
    stored = C.canonical(
        session.get("feedback-records/" + saved["preview_feedback"]["object_id"])["feedback"]
    )
    apply_config(session, participants=30)
    session.post(
        "tests",
        "tests.create",
        {
            "query": "住宿上限？" if session.language == "zh" else "Hotel limit?",
            "config_version": 1,
        },
    )
    session.post(
        "work-products/" + saved["ref"]["object_id"] + "/shares",
        "work_products.shares.create",
        {
            "product_id": saved["ref"]["object_id"],
            "product_version": 1,
            "recipient_role": "supervisor",
        },
    )
    state = state_of(session, saved)
    actual = {row["operation"]: row for row in state["actual"]}
    assert list(actual) == ["configuration.apply", "tests.create", "work_products.shares.create"]
    assert actual["configuration.apply"]["status"] == "applied"
    assert actual["configuration.apply"]["values"]["config_version"] == 1
    assert actual["configuration.apply"]["values"]["changed"] == {"participants": 30}
    assert actual["tests.create"]["values"] == {
        "config_version": 1,
        "count": 1,
    }
    assert actual["tests.create"]["at"] is not None
    assert actual["work_products.shares.create"]["status"] == "shared"
    assert actual["work_products.shares.create"]["values"]["version"] == 1
    # Each actual result is its own record; the preview bytes are those saved before.
    assert {row["ref"]["kind"] for row in state["actual"]} == {"config", "test", "share"}
    assert saved["preview_feedback"]["object_id"] not in referenced_ids(state["actual"])
    assert (
        C.canonical(
            session.get("feedback-records/" + saved["preview_feedback"]["object_id"])["feedback"]
        )
        == stored
    )


def test_out_10_explicit_preview_is_marked_stale_on_its_exact_record(
    work_session: WorkSession,
) -> None:
    session = work_session
    product = save(session)["ref"]
    report = session.review(product, preview_kind="rules", purpose="commitment")
    assert report["preview_conditions"]["config_version"] == 0
    assert session.get("feedback-records/" + report["id"])["preview_state"]["status"] == "current"
    apply_config(session, participants=30)
    state = session.get("feedback-records/" + report["id"])["preview_state"]
    assert state["status"] == "stale"
    assert {row["condition"] for row in state["changes"]} >= {"configuration"}
    plain = session.review(product)
    assert "preview_state" not in session.get("feedback-records/" + plain["id"])


def test_out_14_scoped_reader_states_cite_only_what_it_can_read(
    work_session: WorkSession,
) -> None:
    session = work_session
    saved = save(session)
    product_id = saved["ref"]["object_id"]
    cycle_id = page(session, saved["ref"])["items"][0]["cycle"]["object_id"]
    apply_config(session, participants=30)
    allowed = {product_id, cycle_id, saved["preview_feedback"]["object_id"]}
    headers = session.delegate(allowed)
    scoped = page(session, saved["ref"], headers=headers)
    assert [row["id"] for row in scoped["previews"]] == [saved["preview_feedback"]["object_id"]]
    state = scoped["preview_states"][0]
    assert state["status"] == "stale"
    assert referenced_ids(state) <= allowed
    without_preview = session.delegate({product_id, cycle_id})
    assert "preview_states" not in page(session, saved["ref"], headers=without_preview)
