"""v2 section review on the real Gateway/store. Coverage/mentor rules here are synthetic."""

import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest

from career_lab.aipm.install import install_aipm
from career_lab.aipm.types import AipmDesign, CoverageRule, MentorRule, NeedDeclaration

spec = importlib.util.spec_from_file_location(
    "aipm_review_progress", Path(__file__).with_name("test_aipm_progress.py")
)
progress = importlib.util.module_from_spec(spec)
spec.loader.exec_module(progress)
fixture = progress.fixture
env = fixture.env
base = progress.base
get, post, result, steps = progress.get, progress.post, progress.result, progress.steps

COVERAGE = (
    CoverageRule(
        id="need.raw",
        step_id="need",
        check="citation",
        predicate={"materials": ["public-material"]},
        severity="high",
        owner="business",
        label={"zh": "引用原始资料", "en": "Cites raw material"},
        look_again={"zh": "原始资料", "en": "The raw material"},
        look_again_materials=("public-material",),
    ),
    CoverageRule(
        id="need.claim",
        step_id="need",
        check="choice",
        predicate={"field": "needs"},
        severity="medium",
        owner="manager",
        label={"zh": "需求判断", "en": "Need claim"},
        look_again={"zh": "需求访谈", "en": "Demand interviews"},
    ),
    CoverageRule(
        id="need.counterfact",
        step_id="need",
        check="model",
        severity="medium",
        owner="manager",
        label={"zh": "反证", "en": "A fact that would stop us"},
        look_again={"zh": "反对意见", "en": "Objections"},
    ),
)
MENTOR = (
    MentorRule(
        id="mentor.need",
        step_id="need",
        when_coverage={"need.counterfact": ("to_check",)},
        colleague="manager",
        question={"zh": "什么结果会让你建议不做？", "en": "What result would make you stop?"},
    ),
)


@pytest.fixture
def enabled(base):
    content = replace(
        progress.content_for(base),
        coverage_rules=COVERAGE,
        coverage_revision="test-1",
        mentor_rules=MENTOR,
        mentor_revision="test-1",
    )
    install_aipm(base["app"], [content])
    post(base, "enrollment", "aipm.enroll")
    return base


def call(env, name, payload):
    body = fixture.command(env, name, payload)
    return env["app"].state.w06.call(
        env["sid"], env["token"], name, {"session_id": env["sid"], "command": body}
    )


def prd(env, text, head=None):
    payload = {
        "kind": "plan",
        "purpose": "plan",
        "structured_payload": {"type": "plan", "sections": {"need": text}},
    }
    if head is None:
        out = call(env, "work_products.create", payload)
    else:
        payload |= {"product_id": head["object_id"], "expected_head": head["version"]}
        out = call(env, "work_products.versions.create", payload)
    return next(r for r in out["objects"] if r["kind"] == "product")


def design(env, prd_ref, revision=1, cite=True):
    material = {**fixture_material(env), "observed_at_seq": 0}
    value = AipmDesign(
        id="design",
        session_id=env["sid"],
        revision=revision,
        prd_ref=prd_ref,
        needs=(
            NeedDeclaration(
                id="n1",
                problem="Slow answers",
                claim_status="hypothesis",
                counterevidence_or_unknown="",
                next_validation="",
            ),
        ),
        section_refs={"need": (material,)} if cite else {},
    )
    saved = post(
        env,
        "designs",
        "aipm.design.save",
        {"design": value.model_dump(mode="json"), "expected_revision": revision - 1},
    )
    assert saved.status_code == 200, saved.text
    return saved.json()["result"]["ref"]


def fixture_material(env):
    return {
        "session_id": env["sid"],
        "kind": "material",
        "object_id": "public-material",
        "version": 1,
    }


def review(env, prd_ref, design_ref, token=None):
    body = fixture.command(
        env,
        "aipm.section_review.create",
        {"step_id": "need", "prd_ref": prd_ref, "design_ref": design_ref},
    )
    return env["client"].post(
        f"/sessions/{env['sid']}/aipm/section-reviews",
        json=body,
        headers={"Authorization": "Bearer " + (token or env["token"])},
    )


def test_review_is_rules_only_idempotent_and_drives_the_sheet(enabled):
    first = prd(enabled, "Tickets take 429 minutes.")
    design_ref = design(enabled, first)
    made = review(enabled, first, design_ref)
    assert made.status_code == 200, made.text
    stored = made.json()["result"]["review"]
    assert stored["affects_formal_score"] is False and stored["sentence_labels"] is None
    marks = {m["id"]: m["mark"] for m in stored["coverage"]}
    assert marks == {"need.raw": "covered", "need.claim": "covered", "need.counterfact": "to_check"}
    assert stored["status"] == "solid"
    assert [p["trigger_id"] for p in stored["mentor_prompts"]] == ["need.counterfact"]
    assert all(r["source"] == "pending" for r in stored["rubric"])  # no intended decision yet
    # No private predicates leak into what the learner and Agent read.
    assert "predicate" not in json.dumps(stored)

    again = review(enabled, first, design_ref)
    assert again.json()["result"]["ref"] == made.json()["result"]["ref"]
    reviews = [
        r
        for r in enabled["app"].state.v2_store.view(enabled["owner"]).objects
        if r.ref.kind == "aipm_section_review"
    ]
    assert len(reviews) == 1

    sheet = steps(result(get(enabled, "progress")))["need"]["sheet"]
    assert sheet["status"] == "solid" and sheet["prd_version"] == 1
    assert result(get(enabled, "progress"))["prd_ref"] == first

    second = prd(enabled, "Tickets take 429 minutes; handling is unknown.", head=first)
    sheet = steps(result(get(enabled, "progress")))["need"]["sheet"]
    assert sheet["status"] == "draft" and sheet["edited_since_review"] is True
    page = result(get(enabled, "section-reviews?step_id=need"))
    assert page["items"][0]["review"]["stale"]["reason"] == "edited"

    design_ref = design(enabled, second, revision=2, cite=False)
    newer = review(enabled, second, design_ref).json()["result"]["review"]
    assert newer["status"] == "draft"  # high-severity citation now missing
    assert newer["delta"] == {"citations": [1, 0], "gaps": [0, 1], "wrong": [0, 0]}


def test_only_the_owner_reviews_and_agents_read_the_same_state(enabled):
    first = prd(enabled, "Draft")
    design_ref = design(enabled, first)
    agent, _ = fixture.grant(
        enabled, ("read", "act"), allowed_actions=("observation", "aipm.section_review.create")
    )
    assert review(enabled, first, design_ref, agent["token"]).status_code == 403
    review(enabled, first, design_ref)
    mine = result(get(enabled, "section-reviews?step_id=need"))
    theirs = result(get(enabled, "section-reviews?step_id=need", agent["token"]))
    assert mine == theirs
    agent_sheet = steps(result(get(enabled, "progress", agent["token"])))["need"]["sheet"]
    assert agent_sheet == steps(result(get(enabled, "progress")))["need"]["sheet"]
    narrow, _ = fixture.grant(enabled, allowed_actions=("observation",), allowed_objects=("x",))
    assert get(enabled, "section-reviews", narrow["token"]).status_code == 403


def test_old_binding_has_no_reviews(base):
    response = post(base, "section-reviews", "aipm.section_review.create", {})
    assert response.status_code in {409, 422}


def test_mcp_section_review_resource_tool_and_prompt_match_http(enabled):
    from fastapi.testclient import TestClient

    from career_lab.mcp.protocol import CAPABILITIES, MODERN, VERSION
    from career_lab.mcp.streamable_http import mount_mcp_http

    mount_mcp_http(enabled["app"])
    first = prd(enabled, "Tickets take 429 minutes.")
    review(enabled, first, design(enabled, first))
    post(enabled, "focus", "aipm.focus.set", {"step_id": "need"})
    agent, _ = fixture.grant(enabled, allowed_actions=("observation",))
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
        return response.json()["result"]

    uri = f"rolecraft://sessions/{enabled['sid']}/aipm/sections/need/review"
    value = json.loads(call("resources/read", {"uri": uri}, uri)["contents"][0]["text"])
    http = result(get(enabled, "section-reviews?step_id=need&limit=1", agent["token"]))
    assert value == {"step_id": "need", "latest": http["items"][0]}
    tool = call(
        "tools/call",
        {"name": "aipm.context.read", "arguments": {"kind": "section_review", "step_id": "need"}},
        "aipm.context.read",
    )
    assert tool["structuredContent"] == value
    templates = call("resources/templates/list", {})["resourceTemplates"]
    assert any(t["name"] == "aipm-section-review" for t in templates)
    prompt = call("prompts/get", {"name": "aipm-next-step", "arguments": {}}, "aipm-next-step")
    assert "Sheet status: solid" in prompt["messages"][0]["content"]["text"]
    client.close()


def test_rubric_lines_come_from_the_real_rule_check_with_the_intended_decision(tmp_path):
    import uuid

    from fastapi.testclient import TestClient

    from career_lab.aipm.progress import AipmContent
    from career_lab.aipm.types import AipmGuide
    from career_lab.api.vertical_runtime import create_runtime_app

    root = Path(__file__).resolve().parents[2]
    app = create_runtime_app("sqlite:///" + str(tmp_path / "rubric.db"))
    store = app.state.v2_store
    with TestClient(app) as client:
        created = client.post("/sessions", json={"schema_version": 2, "scenario": "pm_pilot_v2"})
        sid, token = created.json()["session_id"], created.json()["token"]
        auth = store.authenticate(sid, token)
        content = AipmContent(
            scenario_hash=store.view(auth).bindings.scenario.sha256,
            content_revision="aipm-phase1-draft-1",
            work_language="zh",
            guide=AipmGuide.model_validate_json(
                (root / "scenarios/pm_pilot/aipm-phase1/public/guide.zh.json").read_bytes()
            ),
            design_rules=root / "scenarios/pm_pilot/aipm-phase1/private/grading/design.json",
        )
        install_aipm(app, [content])
        headers = {"Authorization": "Bearer " + token}

        def command(operation, payload):
            state = store.view(auth).state
            return {
                "schema_version": 2,
                "request_id": uuid.uuid4().hex,
                "expected_version": state.business_seq,
                "expected_workspace_revision": state.workspace_revision,
                "operation": operation,
                "payload": payload,
            }

        def send(suffix, operation, payload):
            response = client.post(
                f"/sessions/{sid}/aipm/{suffix}", json=command(operation, payload), headers=headers
            )
            assert response.status_code == 200, response.text
            return response.json()["result"]

        send("enrollment", "aipm.enroll", {})
        plan = {
            "kind": "plan",
            "purpose": "plan",
            "structured_payload": {"type": "plan", "sections": {"solution": "先做检索问答。"}},
        }
        out = app.state.w06.call(
            sid,
            token,
            "work_products.create",
            {"session_id": sid, "command": command("work_products.create", plan)},
        )
        prd_ref = next(o for o in out["objects"] if o["kind"] == "product")
        value = AipmDesign(
            id="design",
            session_id=sid,
            revision=1,
            prd_ref=prd_ref,
            intended_decision="launch_narrow",
        )
        design_ref = send(
            "designs",
            "aipm.design.save",
            {"design": value.model_dump(mode="json"), "expected_revision": 0},
        )["ref"]
        stored = send(
            "section-reviews",
            "aipm.section_review.create",
            {"step_id": "solution", "prd_ref": prd_ref, "design_ref": design_ref},
        )["review"]
        assert stored["decision_used"] == "launch_narrow"
        assert {r["criterion"] for r in stored["rubric"]} == {
            "R3.capacity",
            "R3.resources",
            "R6.alternatives",
            "R6.consistency",
        }
        assert all(r["source"] in {"verified_rule", "pending"} for r in stored["rubric"])
