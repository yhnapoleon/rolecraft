"""Model step of a section review with a stand-in Judge: one call, cache, degrade, no leaks."""

import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from career_lab.aipm.install import install_aipm
from career_lab.aipm.types import MentorRule

spec = importlib.util.spec_from_file_location(
    "aipm_review_base", Path(__file__).with_name("test_aipm_section_review.py")
)
base_tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base_tests)
fixture = base_tests.fixture
env = fixture.env
base = base_tests.base
progress = base_tests.progress
prd, design, review = base_tests.prd, base_tests.design, base_tests.review
get, post, result = progress.get, progress.post, progress.result

MENTOR = (
    *base_tests.MENTOR,
    MentorRule(
        id="mentor.need.model",
        step_id="need",
        when_coverage={"need.counterfact": ("missing",)},
        colleague="business",
        question={"zh": "什么事实会让我们不做？", "en": "Which fact would make us stop?"},
    ),
)


class FakeJudge:
    """Stands in for the configured JUDGE provider. retries=0 like the real slot."""

    retries = 0
    revision = "fake-judge-1"
    provider = "fake"

    def __init__(self, reply=None, error=None):
        self.calls, self.messages = 0, []
        self.reply, self.error = reply, error

    def complete(self, messages, tools):
        self.calls += 1
        self.messages.append(messages)
        if self.error:
            raise self.error
        return SimpleNamespace(text=json.dumps(self.reply), tool_calls=[])


REPLY = {
    "items": [
        {
            "id": "need.counterfact",
            "mark": "missing",
            "note": "The section names no fact that would stop the pilot; see the objections.",
            "citation_ids": ["c1"],
        }
    ]
}


def configure(env, judge):
    content = replace(
        progress.content_for(env),
        coverage_rules=base_tests.COVERAGE,
        coverage_revision="test-1",
        mentor_rules=MENTOR,
        mentor_revision="test-1",
    )
    install_aipm(env["app"], [content])
    env["app"].state.model_slots = SimpleNamespace(
        judge=judge, support=None, judge_input_bytes=64000, support_input_bytes=64000
    )
    env["app"].state.aipm_reviewer.sync = True
    post(env, "enrollment", "aipm.enroll")


def latest(env):
    return result(get(env, "section-reviews?step_id=need&limit=1"))["items"][0]["review"]


def test_model_items_merge_once_and_are_cached_per_prd_version(base):
    judge = FakeJudge(REPLY)
    configure(base, judge)
    first = prd(base, "Tickets take 429 minutes.")
    design_ref = design(base, first)
    made = review(base, first, design_ref).json()["result"]["review"]
    assert made["model_status"] == "running" and made["revision"] == 1
    done = latest(base)
    assert done["model_status"] == "done" and done["revision"] == 2
    assert judge.calls == 1
    marks = {m["id"]: m for m in done["coverage"]}
    assert marks["need.counterfact"]["mark"] == "missing"
    assert marks["need.counterfact"]["source"] == "model_suggestion"
    assert done["model_items"][0]["source"] == "model_suggestion"
    assert done["affects_formal_score"] is False
    assert "mentor.need.model" not in json.dumps(done)  # trigger ids are coverage/rule ids
    assert {p["trigger_id"] for p in done["mentor_prompts"]} == {"need.counterfact"}
    assert any(
        "stop us" in p["question"] or "stop" in p["question"] for p in done["mentor_prompts"]
    )
    assert done["status"] == "based"  # a medium point missing keeps it short of solid

    # Same inputs: the stored review, no second call.
    review(base, first, design_ref)
    assert judge.calls == 1
    # A new design on the same PRD version reuses the judged items.
    newer_design = design(base, first, revision=2)
    again = review(base, first, newer_design).json()["result"]["review"]
    assert again["model_status"] == "done" and judge.calls == 1

    sent = json.dumps(judge.messages[0], ensure_ascii=False)
    assert "Tickets take 429 minutes." in sent
    stored = json.dumps(done)
    for private in (
        "predicate",
        "false_positive_examples",
        "when_coverage",
        "look_again_materials",
    ):
        assert private not in stored


def test_model_failure_degrades_to_to_check_with_a_reason(base):
    judge = FakeJudge(error=TimeoutError("provider timed out"))
    configure(base, judge)
    first = prd(base, "Draft")
    review(base, first, design(base, first))
    done = latest(base)
    assert done["model_status"] == "failed" and done["model_reason"]
    assert "timed out" not in done["model_reason"]
    marks = {m["id"]: m["mark"] for m in done["coverage"]}
    assert marks["need.counterfact"] == "to_check"
    assert judge.calls == 1


def test_rejected_model_output_is_not_trusted(base):
    judge = FakeJudge({"items": [{"id": "invented", "mark": "covered", "note": "x"}]})
    configure(base, judge)
    first = prd(base, "Draft")
    review(base, first, design(base, first))
    assert latest(base)["model_status"] == "failed"


@pytest.mark.parametrize("slots", [None, SimpleNamespace(judge=None)])
def test_local_makes_no_model_calls(base, slots):
    content = replace(progress.content_for(base), coverage_rules=base_tests.COVERAGE)
    install_aipm(base["app"], [content])
    if slots is not None:
        base["app"].state.model_slots = slots
    post(base, "enrollment", "aipm.enroll")
    first = prd(base, "Draft")
    made = review(base, first, design(base, first)).json()["result"]["review"]
    assert made["model_status"] == "not_configured" and made["model_items"] == []
    assert latest(base)["revision"] == 1


class CriterionJudge(FakeJudge):
    """Answers the formal Judge's per-criterion prompt with an honest INSUFFICIENT."""

    def complete(self, messages, tools):
        self.calls += 1
        payload = json.loads(messages[-1]["content"])
        criterion = payload.get("criterion") or payload.get("package", {}).get("criterion")
        return SimpleNamespace(
            text=json.dumps(
                {
                    "criterion": criterion,
                    "label": "INSUFFICIENT",
                    "applicability": "applicable",
                    "explanation": "The section does not say how the minutes were counted.",
                    "citation_ids": [],
                }
            ),
            tool_calls=[],
        )


def test_pending_rubric_criteria_go_through_the_installed_judge(tmp_path):
    import uuid

    from fastapi.testclient import TestClient

    from career_lab.aipm.progress import AipmContent
    from career_lab.aipm.types import AipmDesign, AipmGuide
    from career_lab.api.vertical_runtime import create_runtime_app

    root = Path(__file__).resolve().parents[2]
    app = create_runtime_app("sqlite:///" + str(tmp_path / "judge.db"))
    store = app.state.v2_store
    judge = CriterionJudge()
    with TestClient(app) as client:
        created = client.post("/sessions", json={"schema_version": 2, "scenario": "pm_pilot_v2"})
        sid, token = created.json()["session_id"], created.json()["token"]
        auth = store.authenticate(sid, token)
        install_aipm(
            app,
            [
                AipmContent(
                    scenario_hash=store.view(auth).bindings.scenario.sha256,
                    content_revision="aipm-phase1-draft-1",
                    work_language="zh",
                    guide=AipmGuide.model_validate_json(
                        (root / "scenarios/pm_pilot/aipm-phase1/public/guide.zh.json").read_bytes()
                    ),
                    design_rules=root
                    / "scenarios/pm_pilot/aipm-phase1/private/grading/design.json",
                )
            ],
        )
        app.state.model_slots = replace(app.state.model_slots, judge=judge)
        app.state.aipm_reviewer.sync = True
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
            "structured_payload": {
                "type": "plan",
                "sections": {"need": "工单平均处理 429 分钟，所以每单节省 429 分钟人工。"},
            },
        }
        out = app.state.w06.call(
            sid,
            token,
            "work_products.create",
            {"session_id": sid, "command": command("work_products.create", plan)},
        )
        prd_ref = next(o for o in out["objects"] if o["kind"] == "product")
        value = AipmDesign(
            id="design", session_id=sid, revision=1, prd_ref=prd_ref, intended_decision="no_go"
        )
        design_ref = send(
            "designs",
            "aipm.design.save",
            {"design": value.model_dump(mode="json"), "expected_revision": 0},
        )["ref"]
        made = send(
            "section-reviews",
            "aipm.section_review.create",
            {"step_id": "need", "prd_ref": prd_ref, "design_ref": design_ref},
        )["review"]
        pending = {r["criterion"] for r in made["rubric"] if r["source"] == "pending"}
        read = client.get(f"/sessions/{sid}/aipm/section-reviews?step_id=need", headers=headers)
        done = read.json()["result"]["result"]["items"][0]["review"]
        assert done["model_status"] == "done", done.get("model_reason")
        judged = {i["id"] for i in done["model_items"] if i["target"] == "rubric"}
        assert judged and judged <= pending
        assert all(i["mark"] == "to_check" for i in done["model_items"])
        assert judge.calls >= len(judged)


def test_learner_writes_around_the_background_model_write(base):
    """The model step bumps workspace_revision. A learner command built before it lands is a
    definite 409 version_conflict (never executed), and the same action rebuilt from the
    current point succeeds; commands built after it succeed directly."""
    judge = FakeJudge(REPLY)
    configure(base, judge)
    reviewer = base["app"].state.aipm_reviewer
    queued = []

    def hold(auth, ref):  # an in-flight model step that has not written yet
        queued.append((auth, ref))
        reviewer._running.add(ref.object_id)

    reviewer.start = hold
    first = prd(base, "Tickets take 429 minutes.")
    review(base, first, design(base, first))
    assert latest(base)["model_status"] == "running"

    before = fixture.command(base, "aipm.focus.set", {"step_id": "need"})
    # A learner write that completes before the model step: fine.
    assert post(base, "focus", "aipm.focus.set", {"step_id": "business"}).status_code == 200
    reviewer.run(*queued.pop())  # the model step writes revision 2 now
    assert latest(base)["model_status"] == "done"

    stale = base["client"].post(f"/sessions/{base['sid']}/aipm/focus", json=before)
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"
    focus = [
        r
        for r in base["app"].state.v2_store.view(base["owner"]).objects
        if r.ref.kind == "aipm_focus"
    ]
    assert max(r.ref.version for r in focus) == 1  # the rejected command did not execute
    # Rebuilt from the current point (what the host does on retry): succeeds.
    assert post(base, "focus", "aipm.focus.set", {"step_id": "need"}).status_code == 200
    # A plain write after the model step, e.g. saving the next PRD version: succeeds.
    prd(base, "Tickets take 429 minutes; handling unknown.", head=first)
    assert judge.calls == 1
