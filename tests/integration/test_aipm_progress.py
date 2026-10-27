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
        content_revision="aipm-phase1-draft-2",
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
    assert [r["kind"] for r in by_id["boundary"]["evidence_refs"]] == ["aipm_design"]
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


def test_a_later_design_save_does_not_send_triage_back_to_recheck(enabled):
    post(enabled, "enrollment", "aipm.enroll")
    row = TriageRow(
        id="row1",
        need_ref="expenses",
        user_request="Final expense approval",
        target_action="approve",
        route="agent_confirmation",
        rationale="",
        final_authority="ai",
    )
    design = AipmDesign(id="design", session_id=enabled["sid"], revision=1, rows=(row,))
    for revision in (1, 2):
        # The second save is another sheet's: the rows are the same and the rules run again.
        saved = post(
            enabled,
            "designs",
            "aipm.design.save",
            {
                "design": design.model_copy(update={"revision": revision}).model_dump(mode="json"),
                "expected_revision": revision - 1,
            },
        )
        assert saved.status_code == 200, saved.text
    boundary = steps(result(get(enabled, "progress")))["boundary"]
    assert boundary["work_status"] == "recorded"
    assert not any(m["code"] == "recheck" for m in boundary["missing"])
    assert all(f["input_ref"]["version"] == 2 for f in boundary["open_feedback"])


def test_limited_agent_sees_partial_projection_without_private_detail(enabled):
    post(enabled, "enrollment", "aipm.enroll")
    actor, _ = fixture.grant(enabled, allowed_actions=("observation",))
    progress = result(get(enabled, "progress", actor["token"]))
    assert progress["projection"]["complete"] is False
    assert progress["submission_feedback"] == []
    blocked, _ = fixture.grant(enabled, allowed_actions=("submissions.list",))
    assert get(enabled, "progress", blocked["token"]).status_code == 403
    assert "grading" not in json.dumps(result(get(enabled, "guide", actor["token"])))


def test_mcp_progress_resource_matches_http_and_hides_private_rules(enabled):
    from fastapi.testclient import TestClient

    from career_lab.mcp.protocol import CAPABILITIES, MODERN, VERSION
    from career_lab.mcp.streamable_http import mount_mcp_http

    mount_mcp_http(enabled["app"])
    post(enabled, "enrollment", "aipm.enroll")
    actor, _ = fixture.grant(enabled, allowed_actions=("observation",))
    client = TestClient(enabled["app"], base_url="http://127.0.0.1")

    def call(method, params, name):
        response = client.post(
            f"/sessions/{enabled['sid']}/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": {**params, "_meta": {VERSION: MODERN, CAPABILITIES: {}}},
            },
            headers={
                "Authorization": "Bearer " + actor["token"],
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": MODERN,
                "Mcp-Method": method,
                "Mcp-Name": name,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()["result"]

    listed = call("resources/list", {}, "")
    uris = {r["uri"] for r in listed["resources"]}
    uri = f"rolecraft://sessions/{enabled['sid']}/aipm/progress"
    assert uri in uris
    value = json.loads(call("resources/read", {"uri": uri}, uri)["contents"][0]["text"])
    assert value == result(get(enabled, "progress", actor["token"]))
    assert value["projection"]["complete"] is False
    tool = call(
        "tools/call",
        {"name": "aipm.context.read", "arguments": {"kind": "progress"}},
        "aipm.context.read",
    )
    assert tool["structuredContent"] == value
    prompt = call("prompts/get", {"name": "aipm-next-step", "arguments": {}}, "aipm-next-step")
    dumped = json.dumps([value, prompt])
    rules = json.loads((CONTENT / "private/grading/design.json").read_text())
    assert "private/grading" not in dumped
    assert all(r["predicate"] not in dumped for r in rules["rules"])
    client.close()


def agent_post(env, token, payload, key=None):
    body = fixture.command(env, "aipm.design.draft", payload, key=key)
    return env["client"].post(
        f"/sessions/{env['sid']}/aipm/drafts",
        json=body,
        headers={"Authorization": "Bearer " + token},
    )


ROW = TriageRow(
    id="row1",
    need_ref="expenses",
    user_request="Final expense approval",
    target_action="approve",
    route="agent_confirmation",
    rationale="",
    final_authority="ai",
).model_dump(mode="json")


def test_agent_draft_waits_for_owner_and_only_adoption_counts(enabled):
    post(enabled, "enrollment", "aipm.enroll")
    agent, _ = fixture.grant(
        enabled, ("read", "act"), allowed_actions=("observation", "aipm.design.draft")
    )
    draft = {
        "draft_id": "agent-1",
        "expected_revision": 0,
        "rows": [ROW],
        "prd_sections": {"boundary": "Approval stays with the manager."},
    }
    sent = agent_post(enabled, agent["token"], draft)
    assert sent.status_code == 200, sent.text
    out = sent.json()["result"]
    assert out["status"] == "pending_owner_review" and out["counts_toward_progress"] is False
    assert out["precheck"]["label"] == "draft_precheck_pending_owner"
    assert out["progress"]["pending_agent_drafts"][0]["ref"]["object_id"] == "agent-1"
    assert out["next_actions"][0]["action"] == "review_agent_draft"

    progress = result(get(enabled, "progress"))
    assert steps(progress)["boundary"]["work_status"] == "not_started"
    assert [d["author_kind"] for d in progress["pending_agent_drafts"]] == ["external_agent"]
    listed = result(get(enabled, "drafts"))["items"]
    assert listed[0]["draft"]["author"]["kind"] == "external_agent"
    assert listed[0]["draft"]["prd_sections"]["boundary"]
    assert listed[0]["precheck"]["label"] == "draft_precheck_pending_owner"

    # The Agent cannot adopt, save the owner's design or write without the granted action.
    body = fixture.command(enabled, "aipm.design.save", {})
    denied = enabled["client"].post(
        f"/sessions/{enabled['sid']}/aipm/designs",
        json=body,
        headers={"Authorization": "Bearer " + agent["token"]},
    )
    assert denied.status_code == 403
    reader, _ = fixture.grant(enabled, ("read", "act"), allowed_actions=("observation",))
    assert agent_post(enabled, reader["token"], {**draft, "draft_id": "x"}).status_code == 403
    narrow, _ = fixture.grant(
        enabled, ("read", "act"), allowed_actions=("aipm.design.draft",), allowed_objects=("a",)
    )
    assert agent_post(enabled, narrow["token"], {**draft, "draft_id": "y"}).status_code == 403

    design = AipmDesign(
        id="design", session_id=enabled["sid"], revision=1, rows=(TriageRow(**ROW),)
    )
    saved = post(
        enabled,
        "designs",
        "aipm.design.save",
        {"design": design.model_dump(mode="json"), "expected_revision": 0},
    )
    assert saved.status_code == 200, saved.text
    adopted = saved.json()["result"]["ref"]
    body = fixture.command(enabled, "work_products.create", {"kind": "text", "content": "PRD"})
    made = enabled["app"].state.w06.call(
        enabled["sid"],
        enabled["token"],
        "work_products.create",
        {"session_id": enabled["sid"], "command": body},
    )
    prd_ref = next(r for r in made["objects"] if r["kind"] == "product")
    resolved = post(
        enabled,
        "drafts/agent-1/state",
        "aipm.design_drafts.resolve",
        {
            "draft_id": "agent-1",
            "expected_revision": 1,
            "status": "adopted",
            "adopted_design_ref": adopted,
            "adopted_prd_ref": prd_ref,
        },
    )
    assert resolved.status_code == 200, resolved.text
    record = resolved.json()["result"]["draft"]
    assert record["adopted_prd_ref"] == prd_ref and record["author"]["kind"] == "external_agent"
    progress = result(get(enabled, "progress"))
    assert steps(progress)["boundary"]["work_status"] == "recorded"
    assert progress["pending_agent_drafts"] == []
    again = agent_post(enabled, agent["token"], {**draft, "expected_revision": 2})
    assert again.status_code == 409


def test_mcp_lists_and_calls_draft_tool_only_when_enrolled(enabled):
    from fastapi.testclient import TestClient

    from career_lab.mcp.protocol import CAPABILITIES, MODERN, VERSION
    from career_lab.mcp.streamable_http import mount_mcp_http

    mount_mcp_http(enabled["app"])
    agent, _ = fixture.grant(
        enabled, ("read", "act"), allowed_actions=("observation", "aipm.design.draft")
    )
    client = TestClient(enabled["app"], base_url="http://127.0.0.1")

    def call(method, params, name=""):
        response = client.post(
            f"/sessions/{enabled['sid']}/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": {**params, "_meta": {VERSION: MODERN, CAPABILITIES: {}}},
            },
            headers={
                "Authorization": "Bearer " + agent["token"],
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": MODERN,
                "Mcp-Method": method,
                "Mcp-Name": name,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    names = lambda: {t["name"] for t in call("tools/list", {})["result"]["tools"]}  # noqa: E731
    assert "aipm.design.draft" not in names()  # not enrolled yet
    post(enabled, "enrollment", "aipm.enroll")
    assert {"aipm.design.draft", "aipm.context.read"} <= names()
    command = fixture.command(
        enabled,
        "aipm.design.draft",
        {"draft_id": "mcp-1", "expected_revision": 0, "rows": [ROW]},
    )
    out = call(
        "tools/call",
        {"name": "aipm.design.draft", "arguments": {"command": command}},
        "aipm.design.draft",
    )["result"]
    assert out["isError"] is False, out
    value = out["structuredContent"]
    assert value["request_id"] == command["request_id"]
    assert value["precheck"]["label"] == "draft_precheck_pending_owner"
    rules = json.loads((CONTENT / "private/grading/design.json").read_text())
    assert all(r["predicate"] not in json.dumps(value) for r in rules["rules"])
    assert (
        result(get(enabled, "progress"))["pending_agent_drafts"][0]["ref"]["object_id"] == "mcp-1"
    )
    client.close()
