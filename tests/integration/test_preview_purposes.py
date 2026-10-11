"""063-08: the save-time check asks only what this purpose and task still lack."""

from typing import Any

import pytest
from test_w05_http_support import WorkSession
from test_w05_http_support import work_session as work_session

TASK = {"zh": "确认首批员工的使用需求", "en": "Confirm the first users' needs"}
OTHER_TASK = {"zh": "核对报销政策更新", "en": "Check the expense policy update"}


def task(session: WorkSession, title: str) -> dict[str, Any]:
    return session.post("work-items", "work_items.create", {"title": title})["result"]["ref"]


def save(
    session: WorkSession, purpose: str, *, parent: dict | None = None, **extra: Any
) -> dict[str, Any]:
    body = {"kind": "text", "purpose": purpose, "title": "Work", "content": "Draft", **extra}
    if parent is not None:
        body["task"] = parent
    saved = session.post("work-products", "work_products.create", body)["result"]
    found = session.get("work-products/" + saved["ref"]["object_id"] + "/versions")
    return {"saved": saved, "preview": found["previews"][0], "state": found["preview_states"][0]}


def kinds(preview: dict[str, Any]) -> list[tuple[str, str]]:
    return [(row["id"], row["kind"]) for row in preview["outcomes"]]


def operations(preview: dict[str, Any]) -> set[str]:
    return {row["operation"] for row in preview["available_actions"]}


def apply_config(session: WorkSession, **settings: Any) -> None:
    config = session.get("timeline")["workspace"]["config"]
    base = {
        "session_id": session.sid,
        "kind": "config",
        "object_id": config["id"],
        "version": config["version"],
        "config_version": config["config_version"],
    }
    session.post("configuration", "configuration.apply", {"base": base, "settings": settings})


@pytest.mark.parametrize("purpose", ["exploration", "freeform", "探索笔记"])
def test_out_01_notes_need_nothing_and_ask_nothing(work_session: WorkSession, purpose: str) -> None:
    session = work_session
    for parent in (None, task(session, TASK[session.language])):
        found = save(session, purpose, parent=parent)
        preview = found["preview"]
        assert preview["missing_inputs"] == [] and preview["clarification"] == []
        assert preview["next_options"] == []
        assert kinds(preview) == [("saved-input-1", "fact")]
        assert operations(preview) <= {"reviews.create", "work_products.shares.create"}
        assert preview["preview_conditions"] == {
            "config_version": None,
            "resources": None,
            "source_versions": None,
            "schema_version": 2,
        }


def test_out_10_a_note_is_not_staled_by_unrelated_business_conditions(
    work_session: WorkSession,
) -> None:
    session = work_session
    note = save(session, "exploration")
    decision = save(session, "commitment", parent=task(session, TASK[session.language]))
    apply_config(session, participants=30)
    pages = {
        name: session.get("work-products/" + found["saved"]["ref"]["object_id"] + "/versions")[
            "preview_states"
        ][0]
        for name, found in (("note", note), ("decision", decision))
    }
    assert pages["note"]["status"] == "current" and pages["note"]["actual"] == []
    assert pages["decision"]["status"] == "stale"
    assert "configuration" in {row["condition"] for row in pages["decision"]["changes"]}


def test_out_01_business_purposes_without_a_task_ask_for_the_task_first(
    work_session: WorkSession,
) -> None:
    session = work_session
    questions = {}
    for purpose in ("test_plan", "option", "commitment", "result"):
        preview = save(session, purpose)["preview"]
        assert preview["missing_inputs"][0] == "task"
        assert len(preview["clarification"]) == 1
        questions[purpose] = preview["clarification"][0]
    # One question per purpose; never the same fixed sentence for every save.
    assert len(set(questions.values())) == 4
    if session.language == "zh":
        assert questions["test_plan"] == "这份测试计划要支持哪件事？"
        assert questions["commitment"] == "这项试点决定针对哪件事？"
    else:
        assert questions["test_plan"] == "Which task should this test plan support?"
        assert questions["commitment"] == "Which task does this pilot decision address?"


def test_out_01_questions_name_the_current_task_and_follow_the_purpose(
    work_session: WorkSession,
) -> None:
    session = work_session
    title = TASK[session.language]
    parent = task(session, title)
    option = save(session, "option", parent=parent)["preview"]
    assert option["missing_inputs"] == ["candidate_config"]
    assert title in option["clarification"][0]
    decision = save(session, "commitment", parent=parent)["preview"]
    assert decision["missing_inputs"] == ["decision_evidence"]
    assert title in decision["clarification"][0]
    assert decision["clarification"] != option["clarification"]
    other = save(session, "commitment", parent=task(session, OTHER_TASK[session.language]))
    assert OTHER_TASK[session.language] in other["preview"]["clarification"][0]
    empty_plan = save(
        session,
        "test_plan",
        parent=parent,
        kind="test_plan",
        structured_payload={"type": "test_plan", "cases": []},
    )["preview"]
    assert empty_plan["missing_inputs"] == ["test_cases"]
    assert title in empty_plan["clarification"][0]


def test_out_01_nothing_missing_means_no_question(work_session: WorkSession) -> None:
    session = work_session
    parent = task(session, TASK[session.language])
    cited = {
        "session_id": session.sid,
        "kind": "material",
        "object_id": "brief",
        "version": 1,
        "observed_at_seq": 0,
    }
    decision = save(session, "commitment", parent=parent, evidence_refs=[cited])["preview"]
    assert decision["missing_inputs"] == [] and decision["clarification"] == []
    plan = save(session, "test_plan", parent=parent)["preview"]
    assert plan["missing_inputs"] == [] and plan["clarification"] == []


def test_out_03_purpose_predictions_name_conditions_and_link_existing_tools(
    work_session: WorkSession,
) -> None:
    session = work_session
    parent = task(session, TASK[session.language])
    before = session.get()["state"]
    timeline = session.get("timeline")
    plan = save(session, "test_plan", parent=parent)["preview"]
    assert kinds(plan) == [
        ("saved-input-1", "fact"),
        ("test-run", "conditional_prediction"),
        ("test-results", "pending_verification"),
    ]
    run = plan["outcomes"][1]
    assert run["values"] == {"config_version": 0} and len(run["conditions"]) == 2
    assert {ref["kind"] for ref in run["basis_refs"]} == {"product", "config"}
    assert {"tests.create", "configuration.apply"} <= operations(plan)
    decision = save(session, "commitment", parent=parent)["preview"]
    assert kinds(decision) == [
        ("saved-input-1", "fact"),
        ("submission", "conditional_prediction"),
        ("acceptance", "pending_verification"),
    ]
    assert decision["outcomes"][1]["values"] == {"version": 1, "config_version": 0}
    assert {"submissions.create", "actions", "configuration.apply"} <= operations(decision)
    assert decision["generation_status"] == "waiting_model"
    # Linked tools are suggestions only: no share, request, configuration, test or submission.
    after = session.get()["state"]
    assert after["business_seq"] == before["business_seq"]
    assert session.get("timeline")["workspace"] == timeline["workspace"]
    assert session.get("reviews")["items"] == []
    assert session.get("submissions")["items"] == []
    kinds_after = {row["ref"]["kind"] for row in session.get("timeline")["objects"]}
    assert not kinds_after & {"share", "business_request", "test", "submission", "review"}
