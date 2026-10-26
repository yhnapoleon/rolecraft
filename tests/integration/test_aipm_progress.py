"""Seven-step progress against the real Gateway/store; content is the authored draft."""

import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest

from career_lab.aipm.install import install_aipm
from career_lab.aipm.progress import AipmContent
from career_lab.aipm.types import AipmDesign, AipmGuide, TriageRow
from career_lab.api.feedback_integration import install_feedback_recovery
from career_lab.contracts import v2 as C
from career_lab.storage.v2_lifecycle import record_submission

ROOT = Path(__file__).resolve().parents[2]
CONTENT = ROOT / "scenarios/pm_pilot/aipm-phase1"
spec = importlib.util.spec_from_file_location(
    "aipm_progress_w06", Path(__file__).with_name("test_w06_gateway.py")
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
env = fixture.env


def content_for(env):
    binding = env["app"].state.v2_store.view(env["owner"]).bindings
    return AipmContent(
        scenario_hash=binding.scenario.sha256,
        content_revision="aipm-phase1-draft-1",
        work_language="en",
        guide=AipmGuide.model_validate_json((CONTENT / "public/guide.en.json").read_bytes()),
        design_public=json.loads((CONTENT / "public/design.en.json").read_text()),
        design_rules=CONTENT / "private/grading/design.json",
    )


@pytest.fixture
def base(env):
    registry = env["app"].state.gateway.registry
    registry.scenarios["controlled-w06"] = replace(
        registry.scenarios["controlled-w06"], work_language="en"
    )
    install_feedback_recovery(registry)
    install_aipm(env["app"])
    return env


@pytest.fixture
def enabled(base):
    install_aipm(base["app"], [content_for(base)])
    return base


def get(env, suffix, token=None):
    return env["client"].get(
        f"/sessions/{env['sid']}/aipm/{suffix}",
        headers={"Authorization": "Bearer " + (token or env["token"])},
    )


def post(env, suffix, operation, payload=None):
    body = fixture.command(env, operation, payload or {})
    return env["client"].post(f"/sessions/{env['sid']}/aipm/{suffix}", json=body)


def result(response):
    assert response.status_code == 200, response.text
    return response.json()["result"]["result"]


def steps(progress):
    return {step["id"]: step for step in progress["steps"]}


def test_old_binding_stays_disabled(base):
    for response in (
        get(base, "guide"),
        get(base, "progress"),
        post(base, "enrollment", "aipm.enroll"),
    ):
        assert response.status_code == 409
        assert response.json()["code"] == "aipm_not_enabled"


def test_enrollment_is_idempotent_and_progress_starts_unrecorded(enabled):
    assert get(enabled, "progress").json()["code"] == "aipm_not_enrolled"
    first = post(enabled, "enrollment", "aipm.enroll")
    assert first.status_code == 200, first.text
    again = post(enabled, "enrollment", "aipm.enroll")
    assert again.status_code == 200, again.text
    profiles = [
        r
        for r in enabled["app"].state.v2_store.view(enabled["owner"]).objects
        if r.ref.kind == "aipm_profile"
    ]
    assert len(profiles) == 1
    guide = result(get(enabled, "guide"))
    assert [s["id"] for s in guide["steps"]][0] == "business" and len(guide["steps"]) == 7
    progress = result(get(enabled, "progress"))
    assert progress["focus_step"] == progress["suggested_step"] == "business"
    assert progress["projection"]["complete"] is True
    assert all(s["work_status"] == "not_started" and not s["completed"] for s in progress["steps"])
    assert all(s["completion_meaning"] == "work_recorded_not_mastery" for s in progress["steps"])
    assert len(json.dumps(progress)) < 20_000


def test_focus_link_design_and_submission_shape_progress(enabled):
    post(enabled, "enrollment", "aipm.enroll")
    assert post(enabled, "focus", "aipm.focus.set", {"step_id": "need"}).status_code == 200
    service = enabled["app"].state.w06
    body = fixture.command(enabled, "work_products.create", {"kind": "text", "content": "Notes"})
    created = service.call(
        enabled["sid"],
        enabled["token"],
        "work_products.create",
        {"session_id": enabled["sid"], "command": body},
    )
    product = next(r for r in created["objects"] if r["kind"] == "product")
    linked = post(
        enabled,
        "step-links",
        "aipm.step_links.save",
        {"step_id": "business", "product_ref": product},
    )
    assert linked.status_code == 200, linked.text
    design = AipmDesign(
        id="design",
        session_id=enabled["sid"],
        revision=1,
        rows=(
            TriageRow(
                id="row1",
                need_ref="expenses",
                user_request="Final expense approval",
                target_action="approve",
                route="agent_confirmation",
                rationale="",
                final_authority="ai",
            ),
        ),
    )
    saved = post(
        enabled,
        "designs",
        "aipm.design.save",
        {"design": design.model_dump(mode="json"), "expected_revision": 0},
    )
    assert saved.status_code == 200, saved.text
    assert result(get(enabled, "designs/design"))["ref"]["version"] == 1
    progress = result(get(enabled, "progress"))
    by_id = steps(progress)
    assert progress["focus_step"] == "need"
    assert by_id["business"]["work_status"] == "recorded"
    assert by_id["business"]["evidence_refs"] == [product]
    assert by_id["boundary"]["work_status"] == "recorded"
    page = result(get(enabled, "process-feedback?limit=1"))
    assert page["items"] and all(i["affects_formal_score"] is False for i in page["items"])

    store = enabled["app"].state.v2_store
    submit = C.Command.model_validate(
        fixture.command(enabled, "submit", {"decision": "no_go", "products": []})
    )
    store.execute(enabled["owner"], submit, record_submission, capability="submit")
    by_id = steps(result(get(enabled, "progress")))
    assert by_id["decision"]["work_status"] == "recorded"
    assert by_id["solution"]["work_status"] == "uncovered"
    assert result(get(enabled, "progress"))["submission_feedback"][0]["status"] == "not_ready"


def test_limited_agent_sees_partial_projection_without_private_detail(enabled):
    post(enabled, "enrollment", "aipm.enroll")
    actor, _ = fixture.grant(enabled, allowed_actions=("observation",))
    progress = result(get(enabled, "progress", actor["token"]))
    assert progress["projection"]["complete"] is False
    assert progress["submission_feedback"] == []
    blocked, _ = fixture.grant(enabled, allowed_actions=("submissions.list",))
    assert get(enabled, "progress", blocked["token"]).status_code == 403
    assert "grading" not in json.dumps(result(get(enabled, "guide", actor["token"])))
