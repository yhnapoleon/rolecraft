"""The preview must enter through normal reviews.create, never a test-only router."""

from datetime import UTC, datetime, timedelta

from test_w05_http_support import WorkSession, referenced_ids
from test_w05_http_support import work_session as work_session

from career_lab.contracts import v2 as C


def test_out_01_saved_input_can_request_specific_clarification(work_session: WorkSession) -> None:
    session = work_session
    product = session.product(
        "稍后补充用途和条件。" * 200
        if session.language == "zh"
        else "Purpose and conditions to follow. " * 200,
        purpose="",
    )
    report = session.review(product, purpose="", preview_kind="rules")
    assert report["preview_kind"] == "rules"
    assert report["missing_inputs"]
    assert report["clarification"]


def test_out_02_unknown_decision_keeps_facts_without_launch(work_session: WorkSession) -> None:
    session = work_session
    product = session.product("待决定" if session.language == "zh" else "Still deciding")
    report = session.review(product, preview_kind="rules")
    request = session.get("reviews/" + report["subject"]["object_id"])["items"][0]
    assert request["decision"] is None
    facts = [item for item in report["outcomes"] if item["kind"] == "fact"]
    assert facts and facts[0]["basis_refs"][0]["object_id"] == product["object_id"]
    pending = next(item for item in report["outcomes"] if item["id"] == "decision")
    assert pending["kind"] == "pending_verification" and "decision" in pending["missing_inputs"]


def test_wire_03_legacy_review_request_bytes_stay_fixed() -> None:
    request = C.ReviewInput(
        subjects=(
            C.ObjectRef(session_id="fixed-session", kind="product", object_id="draft", version=1),
        ),
        purpose="exploration",
        scope=(),
    )
    expected = (
        '{"decision":null,"followup_of":[],"purpose":"exploration","question":"","schema_'
        'version":2,"scope":[],"subjects":[{"config_version":null,"kind":"product","objec'
        't_id":"draft","schema_version":2,"session_id":"fixed-session","version":1}]}'
    )
    assert C.canonical(request) == expected
    assert C.digest(request) == "90fdcf05640017390f5d1e6a90922b19e041d75c065129e99703ba8926fee496"


def test_out_03_conditional_configuration_is_not_approval_or_execution(
    work_session: WorkSession,
) -> None:
    session = work_session
    current = session.get("timeline")["workspace"]["config"]
    candidate = {
        **current,
        "participants": 50,
        "update_strategy": "realtime",
        "work_items": ["realtime_sync", "human_fallback"],
    }
    product = session.product(
        "待批准方案" if session.language == "zh" else "Proposal awaiting approval", purpose="plan"
    )
    report = session.review(
        product, purpose="plan", preview_kind="rules", candidate_config=candidate
    )
    outcome = next(row for row in report["outcomes"] if row["id"] == "configuration")
    assert outcome["kind"] == "conditional_prediction" and outcome["conditions"]
    assert outcome["values"]["requested"]["participants"] == 50
    assert outcome["values"]["effective"]["update_strategy"] == "daily"
    assert (
        outcome["values"]["differences"]["participants"]
        == "requested_participants_exceed_approved_capacity"
    )
    assert outcome["basis_refs"]
    assert report["available_actions"]
    assert session.get("timeline")["workspace"]["config"] == current


def test_out_04_preview_changes_no_business_state_or_shares(work_session: WorkSession) -> None:
    session = work_session
    product = session.product("私人方案" if session.language == "zh" else "Private proposal")
    before = session.get()
    timeline = session.get("timeline")
    shares = session.get("work-products/" + product["object_id"] + "/shares")
    report = session.review(product, preview_kind="rules")
    after = session.get()
    for key in before["state"].keys() - {"workspace_revision", "storage_revision"}:
        assert after["state"][key] == before["state"][key]
    assert session.get("timeline")["workspace"] == timeline["workspace"]
    assert session.get("timeline")["objects"] == timeline["objects"]
    assert (
        session.get("work-products/" + product["object_id"] + "/shares")["items"] == shares["items"]
    )
    assert report["preview_kind"] == "rules"


def test_out_05_private_preview_is_unavailable_without_its_work(work_session: WorkSession) -> None:
    session = work_session
    secret = "PRIVATE_DRAFT_NOT_SHARED_9ac4"
    product = session.product(secret, title=secret)
    report = session.review(product, preview_kind="rules")
    allowed = referenced_ids(report) | {report["id"]}
    allowed.discard(product["object_id"])
    headers = session.delegate(allowed)
    response = session.client.get(
        f"/sessions/{session.sid}/feedback-records/{report['id']}", headers=headers
    )
    assert response.status_code in {200, 404}
    assert secret not in response.text
    versions = session.client.get(
        f"/sessions/{session.sid}/work-products/{product['object_id']}/versions", headers=headers
    )
    assert secret not in versions.text
    assert session.get("work-products/" + product["object_id"] + "/shares")["items"] == []


def test_out_06_unmodelled_outcomes_remain_unsupported_and_original_is_saved(
    work_session: WorkSession,
) -> None:
    session = work_session
    text = (
        "预测真实企业长期ROI和个人能力。"
        if session.language == "zh"
        else "Predict long-term enterprise ROI and personal ability."
    )
    product = session.product(text)
    report = session.review(
        product, preview_kind="rules", requested_outcomes=["long_term_roi", "personal_ability"]
    )
    unsupported = [row for row in report["outcomes"] if row["kind"] == "unsupported"]
    assert {row["values"]["requested_outcome"] for row in unsupported} == {
        "long_term_roi",
        "personal_ability",
    }
    assert all(not row["basis_refs"] and not row["conditions"] for row in unsupported)
    versions = session.get("work-products/" + product["object_id"] + "/versions")["items"]
    assert any(
        row.get("content", row).get("content") == text
        if isinstance(row.get("content"), dict)
        else row.get("content") == text
        for row in versions
    )


def test_out_07_historical_work_and_current_preview_have_distinct_windows(
    work_session: WorkSession,
) -> None:
    session = work_session
    product = session.product("旧时点判断" if session.language == "zh" else "Earlier judgment")
    original = session.review(product, preview_kind="rules")
    old_bytes = C.canonical(original)
    for _ in range(3):
        session.post(
            "tests",
            "tests.create",
            {
                "query": "住宿上限？" if session.language == "zh" else "Hotel limit?",
                "config_version": 0,
            },
        )
    current = session.review(product, preview_kind="rules")
    assert current["input_refs"] == original["input_refs"]
    assert current["verified_facts"][0]["as_of"] == original["verified_facts"][0]["as_of"]
    assert (
        current["evaluation_as_of"]["business_seq"] > original["evaluation_as_of"]["business_seq"]
    )
    assert C.canonical(session.get("feedback-records/" + original["id"])["feedback"]) == old_bytes


def test_out_01_save_checks_once_and_can_be_disabled(
    work_session: WorkSession, monkeypatch
) -> None:
    session = work_session
    saved = session.post(
        "work-products",
        "work_products.create",
        {
            "kind": "text",
            "purpose": "",
            "content": "待补充" if session.language == "zh" else "To clarify",
        },
    )
    feedback_ref = saved["result"]["preview_feedback"]
    report = session.get("feedback-records/" + feedback_ref["object_id"])["feedback"]
    assert report["input_refs"] == [saved["result"]["ref"]]
    assert "purpose" in report["missing_inputs"]
    assert saved["result"].get("queued_jobs", []) == []
    recovered = session.get("requests/http-request-" + str(session.sequence))
    assert recovered["response"]["result"]["preview_feedback"] == feedback_ref
    monkeypatch.setenv("CAREER_LAB_PREVIEW_ON_SAVE", "0")
    disabled = session.post(
        "work-products", "work_products.create", {"kind": "text", "content": "Disabled check"}
    )
    assert "preview_feedback" not in disabled["result"]


def test_out_01_natural_purpose_preserves_deterministic_checks(work_session: WorkSession) -> None:
    session = work_session
    candidate = session.get("timeline")["workspace"]["config"]
    product = session.product("试点方案" if session.language == "zh" else "Pilot proposal")
    purpose = (
        "评估50人试点的资源可行性"
        if session.language == "zh"
        else "Check resource feasibility for a 50-person pilot"
    )
    report = session.review(
        product,
        preview_kind="rules",
        purpose=purpose,
        candidate_config={**candidate, "participants": 50},
    )
    configuration = next(row for row in report["outcomes"] if row["id"] == "configuration")
    assert configuration["kind"] == "conditional_prediction"
    assert "purpose" not in configuration["missing_inputs"]
    assert report["generation_status"] == "waiting_model"


def test_out_01_user_can_disable_checks_for_their_session(work_session: WorkSession) -> None:
    session = work_session
    product = session.product("先记笔记" if session.language == "zh" else "Notes first")
    session.review(product, preview_kind="rules", preview_on_save=False)
    saved = session.post(
        "work-products",
        "work_products.create",
        {"kind": "text", "content": "My checks are disabled"},
    )
    assert "preview_feedback" not in saved["result"]
    other = WorkSession(session.app, session.client, session.language)
    enabled = other.post(
        "work-products", "work_products.create", {"kind": "text", "content": "Another session"}
    )
    assert "preview_feedback" in enabled["result"]
    session.review(product, preview_kind="rules", preview_on_save=True)
    restored = session.post(
        "work-products", "work_products.create", {"kind": "text", "content": "Checks restored"}
    )
    assert "preview_feedback" in restored["result"]


def test_out_01_saved_request_replay_has_one_private_check(work_session: WorkSession) -> None:
    session = work_session
    before = session.get()["state"]
    payload = {"kind": "text", "content": "Saved once"}
    saved = session.post("work-products", "work_products.create", payload)
    body = {
        "schema_version": 2,
        "request_id": "http-request-" + str(session.sequence),
        "operation": "work_products.create",
        "payload": payload,
        "expected_version": before["business_seq"],
        "expected_workspace_revision": before["workspace_revision"],
    }
    replay = session.client.post(
        f"/sessions/{session.sid}/work-products", headers=session.headers, json=body
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True
    assert replay.json()["result"]["preview_feedback"] == saved["result"]["preview_feedback"]
    assert session.get()["state"] == saved["state"]


def test_out_05_scoped_agent_save_is_not_blocked_by_private_checks(
    work_session: WorkSession,
) -> None:
    session = work_session
    product = session.product(
        "授权修改的作品" if session.language == "zh" else "Work the agent may edit"
    )
    versions = session.get("work-products/" + product["object_id"] + "/versions")["items"]
    cycle_id = versions[0]["cycle"]["object_id"]
    session.review(product, preview_kind="rules", preview_on_save=False)
    delegated = session.post(
        "delegations",
        "delegations.create",
        {
            "capabilities": ["read", "act"],
            "allowed_objects": [product["object_id"], cycle_id],
            "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
            "agent_label": "Scoped editor",
        },
    )
    while isinstance(delegated.get("result"), dict):
        delegated = delegated["result"]
    headers = {"Authorization": "Bearer " + delegated["token"]}
    for version, enabled in ((1, False), (2, True)):
        if enabled:
            session.review(product, preview_kind="rules", preview_on_save=True)
        before = session.get()["state"]
        response = session.client.post(
            f"/sessions/{session.sid}/work-products/{product['object_id']}/versions",
            headers=headers,
            json={
                "schema_version": 2,
                "request_id": "agent-edit-" + str(version),
                "operation": "work_products.versions.create",
                "expected_version": before["business_seq"],
                "expected_workspace_revision": before["workspace_revision"],
                "payload": {
                    "product_id": product["object_id"],
                    "expected_head": version,
                    "kind": "text",
                    "content": "Authorized agent revision " + str(version),
                },
            },
        )
        assert response.status_code == 200, response.text
        assert "preview_feedback" not in response.json()["result"]
        assert response.json()["result"]["ref"]["version"] == version + 1
