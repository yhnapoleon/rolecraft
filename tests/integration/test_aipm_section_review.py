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
