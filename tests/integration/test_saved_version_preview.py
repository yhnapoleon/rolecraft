"""Save-time rule checks belong to the saved work product, never to the reviews list."""

import pytest
from test_w05_http_support import WorkSession
from test_w05_http_support import work_session as work_session

CLARIFY_CONFIG = {
    "zh": "希望核对哪份候选配置？",
    "en": "Which candidate configuration should be checked?",
}


def save(session: WorkSession, text: str, *, purpose: str = "exploration") -> dict:
    return session.post(
        "work-products",
        "work_products.create",
        {"kind": "text", "purpose": purpose, "title": "Working note", "content": text},
    )["result"]


def versions(session: WorkSession, product: dict) -> dict:
    return session.get("work-products/" + product["object_id"] + "/versions")


def public_shape(session: WorkSession) -> tuple:
    timeline = session.get("timeline")
    return (
        session.get("reviews")["items"],
        [row["ref"]["kind"] for row in timeline["objects"]],
        [event["type"] for event in timeline["events"]],
        {key: session.get()["state"][key] for key in ("business_seq", "workspace_revision")},
    )


def test_plain_save_creates_no_review_entry(
    work_session: WorkSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = work_session
    saved = save(session, "保存即可" if session.language == "zh" else "Just saved")
    preview = session.get("feedback-records/" + saved["preview_feedback"]["object_id"])
    assert preview["feedback"]["subject"] == saved["ref"]
    assert session.get("reviews")["items"] == []
    product_feedback = session.client.get(
        f"/sessions/{session.sid}/feedback/{saved['ref']['object_id']}", headers=session.headers
    )
    assert product_feedback.status_code == 404, product_feedback.text
    # The same save without the check is the pre-preview public shape of reviews and timeline.
    monkeypatch.setenv("CAREER_LAB_PREVIEW_ON_SAVE", "0")
    plain = WorkSession(session.app, session.client, session.language)
    unchecked = save(plain, "保存即可" if session.language == "zh" else "Just saved")
    assert "preview_feedback" not in unchecked
    assert public_shape(session) == public_shape(plain)


def test_saved_preview_is_read_from_the_work_product(work_session: WorkSession) -> None:
    session = work_session
    saved = save(session, "待补充" if session.language == "zh" else "To clarify", purpose="")
    page = versions(session, saved["ref"])
    assert [row["subject"] for row in page["previews"]] == [saved["ref"]]
    preview = page["previews"][0]
    assert preview["id"] == saved["preview_feedback"]["object_id"]
    assert preview["preview_kind"] == "rules"
    assert preview["preview_language"] == session.language
    assert preview["generation_status"] == "waiting_model"
    assert [row["kind"] for row in preview["outcomes"]] == ["fact", "pending_verification"]
    assert preview["outcomes"][0]["basis_refs"][0]["object_id"] == saved["ref"]["object_id"]
    assert {"purpose", "candidate_config"} <= set(preview["missing_inputs"])
    assert CLARIFY_CONFIG[session.language] in preview["clarification"]
    revised = session.post(
        "work-products/" + saved["ref"]["object_id"] + "/versions",
        "work_products.versions.create",
        {
            "product_id": saved["ref"]["object_id"],
            "expected_head": 1,
            "kind": "text",
            "purpose": "plan",
            "content": "补充用途" if session.language == "zh" else "Purpose added",
        },
    )["result"]
    page = versions(session, saved["ref"])
    assert [row["subject"] for row in page["previews"]] == [saved["ref"], revised["ref"]]
    assert "purpose" not in page["previews"][1]["missing_inputs"]
    assert all("previews" not in row for row in session.get("work-products")["items"])
    assert "previews" not in session.get("work-products")
    assert session.get("reviews")["items"] == []


def test_explicit_review_requests_each_create_exactly_one_review(
    work_session: WorkSession,
) -> None:
    session = work_session
    product = save(session, "需要评审" if session.language == "zh" else "Needs a review")["ref"]
    first = session.review(product)
    reviews = session.get("reviews")["items"]
    assert [row["id"] for row in reviews] == [first["subject"]["object_id"]]
    assert reviews[0]["subjects"] == [product]
    second = session.review(product, preview_kind="rules")
    assert [row["id"] for row in session.get("reviews")["items"]] == [
        first["subject"]["object_id"],
        second["subject"]["object_id"],
    ]
    assert second["preview_kind"] == "rules"


def test_disabled_checks_write_no_preview(
    work_session: WorkSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = work_session
    monkeypatch.setenv("CAREER_LAB_PREVIEW_ON_SAVE", "0")
    deployment_off = save(session, "部署关闭" if session.language == "zh" else "Deployment off")
    assert "preview_feedback" not in deployment_off
    assert "previews" not in versions(session, deployment_off["ref"])
    monkeypatch.delenv("CAREER_LAB_PREVIEW_ON_SAVE")
    product = save(session, "偏好作品" if session.language == "zh" else "Preference work")["ref"]
    session.review(product, preview_kind="rules", preview_on_save=False)
    preference_off = save(session, "会话关闭" if session.language == "zh" else "Session off")
    assert "preview_feedback" not in preference_off
    assert "previews" not in versions(session, preference_off["ref"])
    session.review(product, preview_kind="rules", preview_on_save=True)
    restored = save(session, "会话恢复" if session.language == "zh" else "Session restored")
    assert [row["subject"] for row in versions(session, restored["ref"])["previews"]] == [
        restored["ref"]
    ]


def test_scoped_reader_sees_a_preview_only_when_granted_it(work_session: WorkSession) -> None:
    session = work_session
    saved = save(session, "私人检查" if session.language == "zh" else "Private check")
    product_id = saved["ref"]["object_id"]
    cycle_id = versions(session, saved["ref"])["items"][0]["cycle"]["object_id"]
    product_only = session.delegate({product_id, cycle_id})
    page = session.get("work-products/" + product_id + "/versions", headers=product_only)
    assert [row["version"] for row in page["items"]] == [1]
    assert "previews" not in page
    granted = session.delegate({product_id, cycle_id, saved["preview_feedback"]["object_id"]})
    page = session.get("work-products/" + product_id + "/versions", headers=granted)
    assert [row["id"] for row in page["previews"]] == [saved["preview_feedback"]["object_id"]]
