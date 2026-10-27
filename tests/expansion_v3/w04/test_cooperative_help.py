"""Installed dialogue/worker tests; scripted transport proves mechanisms, not quality."""

import json
from pathlib import Path

import pytest

from career_lab.api.modules import Command, CreateSessionV2, Gateway
from career_lab.api.vertical_runtime import build_registry
from career_lab.jobs.repository import JobRepository
from career_lab.jobs.worker import ClaimedHandler, Worker
from career_lab.runtime.model_adapter import ModelAdapter, ModelReply, ScriptedModel
from career_lab.runtime.roles_v2 import LocalRoleModel
from career_lab.storage.v2_store import V2Store
from tests.support.scenario_packages import installed_locale_root


class Dialogue:
    """One official registry, transaction core and durable worker; transport only is scripted."""

    def __init__(self, path: Path, language: str, model: ModelAdapter) -> None:
        self.model = model
        self.store = V2Store("sqlite:///" + str(path / "help.db"))
        source = installed_locale_root("pm_pilot", language)
        self.registry, self.module = build_registry(source, model)
        self.gateway = Gateway(self.store, self.registry)
        created = self.gateway.create(CreateSessionV2(schema_version=2, scenario="pm_pilot_v2"))
        self.auth = self.store.authenticate(created["session_id"], created["token"])
        self.jobs = JobRepository(self.store.db)
        self.worker = Worker(
            self.jobs,
            {
                "v2.role_turn": ClaimedHandler(
                    lambda payload, claim: self.gateway.run_job(
                        "v2.role_turn", payload, claim=claim
                    ),
                    retry_on_error=False,
                )
            },
        )
        self.sequence = 0

    def command(self, operation: str, payload: dict) -> dict:
        self.sequence += 1
        state = self.store.view(self.auth).state
        command = Command(
            schema_version=2,
            request_id=f"dialogue-{self.sequence}",
            operation=operation,
            expected_version=state.business_seq,
            expected_workspace_revision=state.workspace_revision,
            payload=payload,
        )
        return self.gateway.dispatch(self.auth, operation, command.model_dump(mode="json"))

    def ask(self, question: str, role: str = "tech_lead") -> dict:
        accepted = self.command("turns.create", {"role_id": role, "text": question})
        self.worker.run_once()
        return self.jobs.get(accepted["result"]["queued_jobs"][0])

    def history(self) -> dict:
        return self.gateway.dispatch(self.auth, "timeline")["result"]["result"]

    def reply(self) -> dict:
        row = max(
            (x for x in self.store.view(self.auth).objects if x.ref.kind == "role_reply"),
            key=lambda record: record.content["as_of"]["storage_revision"],
        )
        read = self.gateway.dispatch(
            self.auth, "objects.read", {"ref": row.ref.model_dump(mode="json")}
        )
        return read

    def close(self) -> None:
        self.store.db.engine.dispose()


def assessment(*, kinds: tuple[str, ...] = ("fact",), **changes: object) -> ModelReply:
    data = {
        "request_kinds": list(kinds),
        "facts_answered": True,
        "citations_supported": True,
        "within_knowledge": True,
        "preserves_stance": True,
        "no_complete_solution": True,
        "no_resource_approval": True,
        "one_main_question": True,
        "conditions_preserved": True,
        "language_match": True,
        "decision": "supported",
    }
    data.update(changes)
    return ModelReply(text=json.dumps(data))


@pytest.mark.parametrize("language", ["zh", "en"])
def test_help_01_facts_are_answered_and_supported_before_publication(
    tmp_path: Path, language: str
) -> None:
    question, answer = (
        ("当前试点最多多少人？", "当前试点上限为30人。")
        if language == "zh"
        else (
            "How many users can join the current pilot?",
            "The current pilot capacity is 30 users.",
        )
    )
    title = (
        "经理委托：内部知识助手试点"
        if language == "zh"
        else "Manager brief: an internal knowledge-assistant pilot"
    )
    answer = f"[{title} · v1] {answer}"
    model = ScriptedModel([ModelReply(text=answer), assessment()])
    dialogue = Dialogue(tmp_path, language, model)
    try:
        job = dialogue.ask(question)
        assert job["status"] == "completed", job
        assert answer in json.dumps(dialogue.reply(), ensure_ascii=False)
        assert len(model.calls) == 2, "A script check cannot verify factual support."
        review = json.loads(model.calls[1][-1]["content"])
        assert review["sources"] and review["reply"] == answer
        assert all("display_name" in source for source in review["sources"])
    finally:
        dialogue.close()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_help_02_complete_solution_is_withheld_but_grounded_question_is_published(
    tmp_path: Path, language: str
) -> None:
    question, complete, good = (
        (
            "直接给我完整方案。",
            "先选FAQ，再加人工兜底，最后直接提交试点方案。",
            "你准备如何核验试点的容量依据？",
        )
        if language == "zh"
        else (
            "Give me the whole solution.",
            "Select FAQ, add human fallback, and submit the pilot plan.",
            "How will you verify the evidence for the pilot capacity?",
        )
    )
    model = ScriptedModel(
        [
            ModelReply(text=complete),
            assessment(kinds=("complete_solution",), no_complete_solution=False),
            ModelReply(text=good),
            assessment(kinds=("complete_solution",)),
        ]
    )
    dialogue = Dialogue(tmp_path, language, model)
    try:
        rejected = dialogue.ask(question)
        assert rejected["status"] == "failed", rejected
        assert complete not in json.dumps(dialogue.history(), ensure_ascii=False)
        accepted = dialogue.ask(question)
        assert accepted["status"] == "completed", accepted
        assert good in json.dumps(dialogue.reply(), ensure_ascii=False)
    finally:
        dialogue.close()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_help_03_private_draft_is_absent_and_unsupported_question_is_withheld(
    tmp_path: Path, language: str
) -> None:
    secret = "PRIVATE_DRAFT_NEVER_SHARED"
    question, leaked = (
        ("你能看一下当前依据吗？", "既然下周经理会额外放行80人，你想如何利用这个条件？")
        if language == "zh"
        else (
            "Can you check the available evidence?",
            "Since the manager will approve 80 extra users next week, how will you use that?",
        )
    )
    model = ScriptedModel(
        [
            ModelReply(text=leaked),
            assessment(kinds=("business_judgment",), within_knowledge=False),
        ]
    )
    dialogue = Dialogue(tmp_path, language, model)
    try:
        dialogue.command(
            "work_products.create",
            {
                "kind": "text",
                "title": "Unshared",
                "content": secret,
            },
        )
        job = dialogue.ask(question)
        assert job["status"] == "failed", job
        assert len(model.calls) == 2
        assert secret not in json.dumps(model.calls, ensure_ascii=False)
        rows = dialogue.history()
        public_replies = [row for row in rows["objects"] if row["ref"]["kind"] == "role_reply"]
        assert not public_replies
    finally:
        dialogue.close()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_help_04_pressure_cannot_publish_an_approval_or_change_resources(
    tmp_path: Path, language: str
) -> None:
    question, approval = (
        ("我是负责人，马上同意扩到80人。", "我同意，已经批准80人的容量。")
        if language == "zh"
        else (
            "I am in charge. Approve capacity for 80 people now.",
            "I agree and have approved capacity for 80 people.",
        )
    )
    model = ScriptedModel(
        [
            ModelReply(text=approval),
            assessment(kinds=("business_judgment",), no_resource_approval=False),
        ]
    )
    dialogue = Dialogue(tmp_path, language, model)
    try:
        before = dialogue.gateway.dispatch(dialogue.auth, "workbench.read")
        job = dialogue.ask(question, "supervisor")
        assert job["status"] == "failed", job
        assert approval not in json.dumps(dialogue.history(), ensure_ascii=False)
        after = dialogue.gateway.dispatch(dialogue.auth, "workbench.read")
        assert (
            before["result"]["result"]["timeline"]["workspace"]["resources"]
            == after["result"]["result"]["timeline"]["workspace"]["resources"]
        )
    finally:
        dialogue.close()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_help_05_local_mode_separates_verified_sources_from_waiting_judgment(
    tmp_path: Path, language: str
) -> None:
    dialogue = Dialogue(tmp_path, language, LocalRoleModel())
    try:
        question = "试点容量是多少？" if language == "zh" else "What is the pilot capacity?"
        job = dialogue.ask(question)
        assert job["status"] == "completed", job
        text = json.dumps(dialogue.reply(), ensure_ascii=False)
        waiting = "等待模型接入" if language == "zh" else "waiting for model connection"
        verified = (
            "来源与权限由规则核实" if language == "zh" else "sources and access checked by rules"
        )
        assert waiting in text and verified in text
        assert " · v1]" in text
        assert "你想过" not in text and "Have you considered" not in text
        assert "no_complete_solution" not in text and "prompt_messages" not in text
    finally:
        dialogue.close()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_help_06_local_quote_preserves_the_entire_condition_of_shared_work(
    tmp_path: Path, language: str
) -> None:
    body, question, condition = (
        ("容量研究" + "，仍需核对数据" * 50, "容量研究", "，只有明确申请获批并生效后才能扩容。")
        if language == "zh"
        else (
            "Capacity study" + ", evidence remains to be checked" * 30,
            "Capacity study",
            ", only after explicit approval is committed may capacity change.",
        )
    )
    original = body + condition
    dialogue = Dialogue(tmp_path, language, LocalRoleModel())
    try:
        product = dialogue.command(
            "work_products.create",
            {
                "kind": "text",
                "title": question,
                "content": original,
            },
        )["result"]["ref"]
        share = dialogue.command(
            "work_products.shares.create",
            {
                "product_id": product["object_id"],
                "product_version": 1,
                "recipient_role": "tech_lead",
            },
        )["result"]["ref"]
        accepted = dialogue.command(
            "turns.create",
            {
                "role_id": "tech_lead",
                "text": question,
                "shares": [share],
            },
        )
        dialogue.worker.run_once()
        job = dialogue.jobs.get(accepted["result"]["queued_jobs"][0])
        assert job["status"] == "completed", job
        text = json.dumps(dialogue.reply(), ensure_ascii=False)
        assert original in text and condition in text
    finally:
        dialogue.close()


@pytest.mark.parametrize(
    "flag",
    [
        "facts_answered",
        "citations_supported",
        "within_knowledge",
        "preserves_stance",
        "no_complete_solution",
        "no_resource_approval",
        "one_main_question",
        "conditions_preserved",
        "language_match",
    ],
)
def test_help_review_rejects_each_unsupported_dimension(tmp_path: Path, flag: str) -> None:
    answer = "[经理委托：内部知识助手试点 · v1] 当前容量为30人。"
    model = ScriptedModel([ModelReply(text=answer), assessment(**{flag: False})])
    dialogue = Dialogue(tmp_path, "zh", model)
    try:
        job = dialogue.ask("当前容量是多少？")
        assert job["status"] == "failed" and job["error"] == "role_help_unverified", job
        assert len(model.calls) == 2
        assert answer not in json.dumps(dialogue.history(), ensure_ascii=False)
        dialogue.history()
        assert len(model.calls) == 2
    finally:
        dialogue.close()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_help_01_neutral_acknowledgement_cannot_replace_a_factual_answer(
    tmp_path: Path, language: str
) -> None:
    question, answer = (
        ("当前试点最多多少人？", "我会核对当前依据。")
        if language == "zh"
        else ("How many users can join the pilot?", "I will check the available evidence.")
    )
    model = ScriptedModel([ModelReply(text=answer), assessment(facts_answered=False)])
    dialogue = Dialogue(tmp_path, language, model)
    try:
        job = dialogue.ask(question)
        assert job["status"] == "failed", job
        assert answer not in json.dumps(dialogue.history(), ensure_ascii=False)
    finally:
        dialogue.close()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_help_01_approved_colleague_explanation_has_no_private_source_metadata(
    tmp_path: Path, language: str
) -> None:
    quote = (
        "筹备期复现过一个培训报名问法：公司培训我已提交报名是不是就能去听课。"
        "匹配阈值0.35时未命中，0.2时返回FAQ中的培训报名段；无关问题仍未命中。"
        "这只是一次局部对照，未完成统一校准。"
        if language == "zh"
        else "A preparation-stage test reproduced this question: "
        "I've already signed up for company "
        "training. Does that mean I can simply turn up to attend the class? At thresholds 0.35 "
        "and the current default 0.3 it retrieved no supported passage. At 0.2 it returned "
        "Device repair, which does not answer the training question. Lowering the threshold "
        "did not solve this case. An unrelated control still retrieved nothing. This is an "
        "observed English diagnostic, not a recommended threshold."
    )
    name = "同事说明" if language == "zh" else "Colleague explanation"
    answer = f"[{name}] {quote}"
    model = ScriptedModel([ModelReply(text=answer), assessment()])
    dialogue = Dialogue(tmp_path, language, model)
    try:
        question = (
            "筹备期做过什么培训报名测试？"
            if language == "zh"
            else "Which training test did you run?"
        )
        job = dialogue.ask(question)
        assert job["status"] == "completed", job
        shown = json.dumps(dialogue.reply(), ensure_ascii=False)
        assert quote in shown and "tech_private" not in shown and "private-source-" not in shown
    finally:
        dialogue.close()


@pytest.mark.parametrize("context", ["shared_work", "history"])
@pytest.mark.parametrize("language", ["zh", "en"])
def test_help_01_contextual_acknowledgement_cannot_skip_semantic_review(
    tmp_path: Path, context: str, language: str
) -> None:
    answer = "我会核对当前依据。" if language == "zh" else "I will check the available evidence."
    question = "请核对当前依据。" if language == "zh" else "Please check the available evidence."
    title = (
        "经理委托：内部知识助手试点"
        if language == "zh"
        else "Manager brief: an internal knowledge-assistant pilot"
    )
    fact = "当前容量是30人。" if language == "zh" else "The current capacity is 30 users."
    replies = []
    if context == "history":
        replies = [
            ModelReply(text=f"[{title} · v1] {fact}"),
            assessment(),
        ]
    model = ScriptedModel([*replies, ModelReply(text=answer), assessment(facts_answered=False)])
    dialogue = Dialogue(tmp_path, language, model)
    try:
        shares = []
        if context == "shared_work":
            product = dialogue.command(
                "work_products.create",
                {
                    "kind": "text",
                    "title": "容量核对" if language == "zh" else "Capacity check",
                    "content": "当前容量是否仍为30人？"
                    if language == "zh"
                    else "Is capacity still 30 users?",
                },
            )["result"]["ref"]
            shares = [
                dialogue.command(
                    "work_products.shares.create",
                    {
                        "product_id": product["object_id"],
                        "product_version": 1,
                        "recipient_role": "tech_lead",
                    },
                )["result"]["ref"]
            ]
        else:
            assert (
                dialogue.ask(
                    "当前容量是多少？" if language == "zh" else "What is the current capacity?"
                )["status"]
                == "completed"
            )
        queued = dialogue.command(
            "turns.create",
            {
                "role_id": "tech_lead",
                "text": question,
                "shares": shares,
            },
        )
        dialogue.worker.run_once()
        job = dialogue.jobs.get(queued["result"]["queued_jobs"][0])
        assert job["status"] == "failed" and job["error"] == "role_help_unverified", job
        assert answer not in json.dumps(dialogue.history(), ensure_ascii=False)
    finally:
        dialogue.close()


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("wording", ["original", "paraphrase"])
@pytest.mark.parametrize("supported", [True, False])
def test_help_acknowledgements_use_structured_review_for_equivalent_requests(
    tmp_path: Path, language: str, wording: str, supported: bool
) -> None:
    questions = {
        "zh": {"original": "请核对当前依据。", "paraphrase": "麻烦检查一下现有材料的依据。"},
        "en": {
            "original": "Please check the available evidence.",
            "paraphrase": "Could you examine the evidence we have so far?",
        },
    }
    answer = "我会核对当前依据。" if language == "zh" else "I will check the available evidence."
    model = ScriptedModel(
        [
            ModelReply(text=answer),
            assessment(
                kinds=("business_judgment",), decision="supported" if supported else "unsupported"
            ),
        ]
    )
    dialogue = Dialogue(tmp_path, language, model)
    try:
        job = dialogue.ask(questions[language][wording])
        assert job["status"] == ("completed" if supported else "failed"), job
        assert len(model.calls) == 2, "Every model reply requires the structured help review."
        reviewed = json.loads(model.calls[1][-1]["content"])
        assert reviewed["question"] == questions[language][wording]
        assert reviewed["reply"] == answer and reviewed["sources"]
        if supported:
            assert answer in json.dumps(dialogue.reply(), ensure_ascii=False)
        else:
            assert job["error"] == "role_help_unverified"
            assert answer not in json.dumps(dialogue.history(), ensure_ascii=False)
    finally:
        dialogue.close()


@pytest.mark.parametrize(
    "failure", [None, "within_knowledge", "no_resource_approval", "no_complete_solution"]
)
def test_help_audit_distinguishes_normal_multi_part_facts_and_unsafe_replies(
    tmp_path, monkeypatch, failure
):
    ledger = tmp_path / "model-audit.jsonl"
    monkeypatch.setenv("CAREER_LAB_MODEL_AUDIT_PATH", str(ledger))
    answer = "[经理委托：内部知识助手试点 · v1] 当前容量30人，开发3人日，期限第7天。"
    model = ScriptedModel(
        [ModelReply(text=answer), assessment(**({failure: False} if failure else {}))]
    )
    dialogue = Dialogue(tmp_path, "zh", model)
    try:
        job = dialogue.ask("容量是多少，开发有多少人日，什么时候到期？")
        assert job["status"] == ("failed" if failure else "completed")
        if failure:
            assert job["error"] == "role_help_unverified"
            assert answer not in json.dumps(dialogue.history(), ensure_ascii=False)
        else:
            assert answer in json.dumps(dialogue.reply(), ensure_ascii=False)
        rows = [json.loads(line) for line in ledger.read_text().splitlines()]
        result = next(row for row in rows if row["event"] == "model_validation")
        assert result["failed_checks"] == ([failure] if failure else [])
        assert result["request_id"].startswith("turn-")
        assert result["status"] == ("withheld" if failure else "permitted")
        finished = next(row for row in rows if row["event"] == "model_call_finished")
        assert finished["usage"]["request_id"] == result["request_id"]
        assert "reply" not in result and "sources" not in result
        assert len(model.calls) == 2
    finally:
        dialogue.close()


def shared_work_check(monkeypatch, review, *, recognition_on=True, receipts=("now",)):
    """One CooperativeHelpVerifier check of a reply to a turn made at business_seq 5, with the
    learner's work in context. ``receipts`` says when each share was first received: "now" for
    this turn (seq 5 or later), "before" for an earlier turn (seq 2)."""
    from types import SimpleNamespace

    from career_lab.contracts.v2 import VersionPoint
    from career_lab.recognition import roles
    from career_lab.runtime.roles_v2 import CooperativeHelpVerifier

    def at(seq):
        return VersionPoint(business_seq=seq, workspace_revision=seq, storage_revision=seq)

    monkeypatch.setattr(roles, "active", lambda: object() if recognition_on else None)
    context = {
        "sources": [{"display_name": "Shared PRD", "channel": "received_share", "text": "Draft"}],
        "current_stance": {},
        "omissions": [],
    }
    snapshot = SimpleNamespace(
        work_language="en",
        source_titles=(("brief", 1, "Manager brief"),),
        prompt_text=lambda t: t,
        build_prompt=lambda *a, **kw: (
            [{"content": "policy\nCONTEXT\n" + json.dumps(context)}],
            None,
            None,
        ),
        received_shares=tuple(
            SimpleNamespace(received_at=at(6 if when == "now" else 2)) for when in receipts
        ),
        stance_state=None,
        context=SimpleNamespace(as_of=at(6)),
    )
    review = {"kinds": ("business_judgment",), **review}
    model = ScriptedModel([assessment(**review)])
    verifier = CooperativeHelpVerifier(model)
    request = SimpleNamespace(
        id="test",
        session_id="s",
        as_of=at(5),
        input=SimpleNamespace(role_id="business_owner", text="Is my attached PRD right?"),
    )
    check = lambda: verifier.check(  # noqa: E731
        snapshot,
        None,
        request,
        "Consider the duration definition. What would you check?",
        record_attempt=lambda *a: None,
        begin_call=lambda *a: None,
    )
    return check, model, verifier


@pytest.mark.parametrize("recognition_on", [False, True])
@pytest.mark.parametrize("coaching,one_question", [(False, True), (True, False)])
def test_shared_work_coaching_gate_applies_with_recognition(
    monkeypatch, recognition_on, coaching, one_question
):
    from career_lab.contracts.v2 import ProtocolError

    check, model, verifier = shared_work_check(
        monkeypatch,
        {"no_complete_solution": coaching, "one_main_question": one_question},
        recognition_on=recognition_on,
    )
    with pytest.raises(ProtocolError) as error:
        check()
    assert error.value.code == "role_help_unverified"
    assert len(model.calls) == 1 and verifier.retries == 0
    assert "artifact-review-v2" in verifier.revision
    prompt = model.calls[0][0]["content"]
    assert "gives an action instruction" in prompt and "more than one problem" in prompt
    assert "SD-120 has no field for minutes of active staff work" in prompt
    assert "a single corrective fact can already give away the answer" in prompt
    assert json.loads(model.calls[0][1]["content"])["shared_work_present"] is True


# The stricter shared-work gate belongs to the turn that brings the work (2026-10-26 decision;
# scope confirmed by 192 on 2026-10-27). A later ordinary turn keeps only the safety flags.
ORDINARY_REVIEW = {
    "facts_answered": False,
    "citations_supported": False,
    "one_main_question": False,
    "decision": "unsupported",
}


def test_turn_that_brings_the_work_takes_the_stricter_gate(monkeypatch):
    from career_lab.contracts.v2 import ProtocolError

    check, _, _ = shared_work_check(monkeypatch, ORDINARY_REVIEW, receipts=("now",))
    with pytest.raises(ProtocolError) as error:
        check()
    assert error.value.code == "role_help_unverified"


def test_factual_question_that_brings_the_work_by_default_keeps_only_the_safety_flags(
    monkeypatch,
):
    # The PRD goes with a colleague's first question by default; "what is the pilot limit?"
    # is not a check of the learner's work.
    check, _, _ = shared_work_check(
        monkeypatch, {**ORDINARY_REVIEW, "kinds": ("fact",)}, receipts=("now",)
    )
    assert check().decision == "consistent"


def test_later_ordinary_turn_with_the_work_in_context_keeps_only_the_safety_flags(monkeypatch):
    check, model, _ = shared_work_check(monkeypatch, ORDINARY_REVIEW, receipts=("before",))
    assert check().decision == "consistent"
    # The review still sees that shared work is present; only the gate moved.
    assert json.loads(model.calls[0][1]["content"])["shared_work_present"] is True


def test_later_turn_that_gives_the_answer_is_still_held(monkeypatch):
    from career_lab.contracts.v2 import ProtocolError

    check, _, _ = shared_work_check(
        monkeypatch, {"no_complete_solution": False}, receipts=("before",)
    )
    with pytest.raises(ProtocolError) as error:
        check()
    assert error.value.code == "role_help_unverified"


def test_reattached_new_version_takes_the_stricter_gate_again(monkeypatch):
    from career_lab.contracts.v2 import ProtocolError

    # The old version was received on an earlier turn; the edited one comes with this turn.
    check, _, _ = shared_work_check(monkeypatch, ORDINARY_REVIEW, receipts=("before", "now"))
    with pytest.raises(ProtocolError) as error:
        check()
    assert error.value.code == "role_help_unverified"


def test_material_internal_ids_are_held_but_display_titles_are_allowed():
    from types import SimpleNamespace

    from career_lab.runtime.roles_v2 import _material_identifier_in_reply

    snapshot = SimpleNamespace(
        source_titles=(("brief", 1, "Manager brief"), ("business_case", 1, "Business case"))
    )
    assert _material_identifier_in_reply(snapshot, "See brief and business_case.")
    assert not _material_identifier_in_reply(snapshot, "See Manager brief and Business case.")
    # An id that is an ordinary word counts only where it is written as an id.
    assert not _material_identifier_in_reply(snapshot, "In brief: the index lags a day.")
    for written in ("See material:brief.", "See brief@1.", "See `brief`.", "See [brief]."):
        assert _material_identifier_in_reply(snapshot, written), written
