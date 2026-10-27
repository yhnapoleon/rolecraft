from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from career_lab.contracts import v2 as C
from career_lab.evidence.v2.assembler import product_text, product_texts
from career_lab.scenarios.v2.module import ScenarioModule


@pytest.mark.parametrize("language", ["zh", "en"])
def test_saved_seven_section_work_uses_exact_same_quote_projection(language):
    sections = {
        key: (
            "拟议采集实际工时，尚未完成。"
            if language == "zh"
            else "Propose collecting actual handling time; not completed."
        )
        for key in (
            "business",
            "stakeholders",
            "need",
            "boundary",
            "solution",
            "assurance",
            "decision",
        )
    }
    payload = C.PlanPayload(sections=sections)
    actor = C.Executor(id="owner", kind="human")
    product = C.WorkProductVersion(
        product_id="prd",
        session_id="s",
        version=2,
        cycle=C.ObjectRef(session_id="s", kind="cycle", object_id="c", version=1),
        kind="plan",
        content="",
        structured_payload=payload,
        author=actor,
        executor=actor,
        created_at=datetime.now(UTC),
        content_hash=C.digest(
            {"content": "", "structured_payload": payload.model_dump(mode="json")}
        ),
    )
    text = product_text(product, work_language=language)
    module = SimpleNamespace(work_language=language)
    view = SimpleNamespace(
        state=SimpleNamespace(business_seq=2),
        get=lambda _: SimpleNamespace(content=product.model_dump(mode="json")),
    )
    auth = SimpleNamespace(session_id="s")
    ref = C.EvidenceRefV2(
        session_id="s",
        kind="product",
        object_id="prd",
        version=2,
        observed_at_seq=2,
        span_start=0,
        span_end=len(text),
        quote=text,
    )
    assert ScenarioModule.check_evidence(module, view, auth, ref)
    with pytest.raises(C.ProtocolError) as error:
        ScenarioModule.check_evidence(
            module, view, auth, ref.model_copy(update={"quote": "Fabricated evidence"})
        )
    assert error.value.code == "reference_span_forbidden"


def saved_work(payload, *, kind):
    actor = C.Executor(id="owner", kind="human")
    return C.WorkProductVersion(
        product_id="work",
        session_id="s",
        version=1,
        cycle=C.ObjectRef(session_id="s", kind="cycle", object_id="c", version=1),
        kind=kind,
        content="",
        structured_payload=payload,
        author=actor,
        executor=actor,
        created_at=datetime.now(UTC),
        content_hash=C.digest(
            {"content": "", "structured_payload": payload.model_dump(mode="json")}
        ),
    )


def saved_test_plan(language):
    query = {"zh": "每晚住宿报销上限是多少？", "en": "What is the nightly hotel limit?"}[language]
    expected = {"zh": "每晚 500 元", "en": "CNY 500 per night"}[language]
    return saved_work(
        C.TestPlanPayload(
            cases=(
                C.TestCase(id="c1", query=query, declared_expected=expected),
                C.TestCase(id="c2", query=query + "?"),
            )
        ),
        kind="test_plan",
    )


def investigation(language):
    question = {"zh": "答案为何过期？", "en": "Why is the answer stale?"}[language]
    note = {"zh": "索引未更新", "en": "The index was not refreshed"}[language]
    return saved_work(
        C.InvestigationPayload(
            question=question,
            blocks=(C.InvestigationBlock(id="b1", type="note", text=note),),
            review_note=note,
        ),
        kind="investigation",
    )


def has_cjk(text):
    return any("\u3000" <= ch <= "\u9fff" or "\uff00" <= ch <= "\uffef" for ch in text)


def test_english_work_is_labelled_in_english():
    plan = product_text(saved_test_plan("en"), work_language="en")
    assert plan == (
        "What is the nightly hotel limit?\nExpected outcome (unverified): CNY 500 per night"
        "\n\nWhat is the nightly hotel limit??"
    )
    note = product_text(investigation("en"), work_language="en")
    assert note.endswith("Author interpretation (unverified): The index was not refreshed")
    assert not has_cjk(plan) and not has_cjk(note)


def test_chinese_work_projects_byte_for_byte_as_before():
    plan = saved_test_plan("zh")
    # The literal projection every Chinese session has had since the label was introduced.
    before = "每晚住宿报销上限是多少？\n预期（待验证）：每晚 500 元\n\n每晚住宿报销上限是多少？?"
    assert product_text(plan, work_language="zh").encode() == before.encode()
    assert product_text(plan).encode() == before.encode()
    assert product_texts(plan, work_language="zh") == (before,)
    note = investigation("zh")
    assert product_texts(note, work_language="zh") == (
        "答案为何过期？\n\n索引未更新\n\n作者判断（待核对）：索引未更新",
    )


def check(language, product, start, end, text):
    view = SimpleNamespace(
        state=SimpleNamespace(business_seq=1),
        get=lambda _: SimpleNamespace(content=product.model_dump(mode="json")),
    )
    ref = C.EvidenceRefV2(
        session_id="s",
        kind="product",
        object_id="work",
        version=1,
        observed_at_seq=1,
        span_start=start,
        span_end=end,
        quote=text[start:end],
    )
    module = SimpleNamespace(work_language=language)
    return ScenarioModule.check_evidence(module, view, SimpleNamespace(session_id="s"), ref)


def test_quotes_of_an_english_test_plan_pass_the_evidence_check():
    plan = saved_test_plan("en")
    current, earlier = product_texts(plan, work_language="en")
    assert current == product_text(plan, work_language="en")
    # Quoted as the evidence reader now shows it: the expected outcome and its label.
    start = current.index("Expected outcome")
    assert check("en", plan, start, current.index("\n\n"), current)
    # A quote stored before 2026-10-27 points into the Chinese-labelled projection.
    assert earlier == product_text(plan)
    assert check("en", plan, earlier.index("预期"), earlier.index("\n\n"), earlier)
    with pytest.raises(C.ProtocolError) as error:
        check("zh", plan, current.index("Expected"), current.index("\n\n"), current)
    assert error.value.code == "reference_span_forbidden"
