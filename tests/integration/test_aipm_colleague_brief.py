"""The colleague brief: where the learner is, read from the real store, never the answer."""

import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest

from career_lab.aipm.install import install_aipm
from career_lab.aipm.progress import BRIEF_LIMIT, colleague_brief
from career_lab.aipm.types import AipmGuide, CoverageRule

spec = importlib.util.spec_from_file_location(
    "aipm_brief_review", Path(__file__).with_name("test_aipm_section_review.py")
)
reviews = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reviews)
progress = reviews.progress
env = reviews.env
base = reviews.base
post, review, design = reviews.post, reviews.review, reviews.design

# A gap label carrying an internal source id must never reach the brief.
SOURCE_ID_RULE = CoverageRule(
    id="need.export",
    step_id="need",
    check="citation",
    predicate={"materials": ["export"]},
    severity="high",
    owner="business",
    label={"zh": "引用了 SD-120 导出", "en": "Cites the SD-120 export"},
    look_again={"zh": "导出", "en": "The export"},
    look_again_materials=("export",),
)


def enable(env, language):
    content = progress.content_for(env)
    if language == "zh":
        content = replace(
            content,
            work_language="zh",
            guide=AipmGuide.model_validate_json(
                (progress.CONTENT / "public/guide.zh.json").read_bytes()
            ),
        )
    content = replace(
        content,
        coverage_rules=(*reviews.COVERAGE, SOURCE_ID_RULE),
        coverage_revision="test-1",
        mentor_rules=reviews.MENTOR,
        mentor_revision="test-1",
    )
    install_aipm(env["app"], [content])
    assert post(env, "enrollment", "aipm.enroll").status_code == 200


def brief(env, language="en"):
    store = env["app"].state.v2_store
    return colleague_brief(store.view(env["owner"]), env["owner"], language)


def plan(env, sections, head=None):
    payload = {
        "kind": "plan",
        "purpose": "plan",
        "structured_payload": {"type": "plan", "sections": sections},
    }
    name = "work_products.create"
    if head is not None:
        name = "work_products.versions.create"
        payload |= {"product_id": head["object_id"], "expected_head": head["version"]}
    out = reviews.call(env, name, payload)
    return next(r for r in out["objects"] if r["kind"] == "product")


def assert_safe(value):
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    assert len(text) <= BRIEF_LIMIT
    assert value["revision"] == "aipm-brief-v1"
    # No source ids, no review findings or mentor questions, no raw step or object ids.
    for banned in ("SD-120", "material", "什么结果会让你建议不做", "What result would make you"):
        assert banned not in text


@pytest.mark.parametrize("language", ["zh", "en"])
def test_brief_follows_the_learner_through_three_points(base, language):
    enable(base, language)
    words = {
        "zh": ("① 看懂业务", "①–⑦未开始", "③ 真需求", "①–③草稿；④–⑦未开始"),
        "en": ("1 Business", "1–7 not started", "3 Real need", "1–3 draft; 4–7 not started"),
    }[language]

    start = brief(base, "en")
    assert start == {"revision": "aipm-brief-v1", "step": words[0], "sheets": words[1]}

    # Half way: three sections written, the learner is on the need sheet, nothing reviewed.
    post(base, "focus", "aipm.focus.set", {"step_id": "need"})
    first = plan(base, {"business": "x", "stakeholders": "y", "need": "Tickets take 429 minutes."})
    design_ref = design(base, first)
    halfway = brief(base, "en")
    assert halfway == {"revision": "aipm-brief-v1", "step": words[2], "sheets": words[3]}
    assert_safe(halfway)

    # After a review: the step's state and its open gap labels, not the review's findings.
    made = review(base, first, design_ref)
    assert made.status_code == 200, made.text
    reviewed = brief(base, "en")
    assert_safe(reviewed)
    assert reviewed["latest_review"].startswith(words[2])
    assert (
        reviewed["latest_review"]
        == {
            "zh": "③ 真需求：还要再看「反证」",
            "en": "3 Real need: still to look at “A fact that would stop us”",
        }[language]
    )
    status = made.json()["result"]["review"]["status"]
    assert status in {"draft", "based", "solid"}

    # Editing after the review says so on that sheet.
    plan(base, {"business": "x", "stakeholders": "y", "need": "Edited."}, head=first)
    edited = brief(base, "en")
    assert ("批改后改过" if language == "zh" else "edited since review") in edited["sheets"]
    assert_safe(edited)


def test_brief_is_none_outside_an_ai_pm_session(base):
    assert brief(base) is None  # installed, not enrolled
    assert colleague_brief(None, None, "zh") is None  # unreadable view never raises


def test_learner_state_carries_the_brief_for_the_colleague(base):
    from career_lab.recognition import behavior
    from career_lab.recognition.roles import learner_state_entry, role_recognition

    enable(base, "en")
    post(base, "focus", "aipm.focus.set", {"step_id": "need"})
    view = base["app"].state.v2_store.view(base["owner"])
    state = behavior.learner_state(view, base["owner"], language="en")
    assert state["aipm"] == colleague_brief(view, base["owner"], "en")
    assert state["aipm"]["step"] == "3 Real need"
    with role_recognition({"learner_state": state}):
        entry, guide = learner_state_entry("en")
    assert entry["aipm"]["revision"] == "aipm-brief-v1"
    assert "aipm entry" in guide
