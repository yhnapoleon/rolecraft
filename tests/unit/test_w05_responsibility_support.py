"""Product responsibility counterexamples and verifier protocol checks.

Provider responses below are explicit transport fixtures, not semantic-quality
measurements. No paid or online model is called by this suite.
"""

from dataclasses import replace
import json
import pytest

from career_lab.contracts.v2 import ProtocolError
from career_lab.evidence.v2.ports import ResponsibilityFact, VerifiedFact
from career_lab.evidence.v2.assembler import model_input
from career_lab.rubrics.v4.rules import run_rules
from career_lab.rubrics.v4.support import EvidenceSupportVerifier
from career_lab.rubrics.v4.judge import AdvisoryJudge
from career_lab.rubrics.v4.provider import create_feedback_engine
from career_lab.runtime.model_adapter import ModelReply
from test_w05_pipeline import env, package, INITIAL, product_ref, advice


@pytest.mark.parametrize(
    "purpose", ["commitment", "result", "plan", "exploration", "option", "test_plan", "unknown"]
)
@pytest.mark.parametrize("decision", [None, "launch", "no_go", "defer_with_conditions"])
@pytest.mark.parametrize("criterion", ["R3.capacity", "R3.resources", "R4.functional_tests"])
def test_purpose_and_decision_gate_launch_requirements_before_history(
    env, purpose, decision, criterion
):
    a = env["authority"]
    a.participants = 0
    a.incurred = {criterion}
    item = package(env, criterion=criterion, purpose=purpose, decision=decision)
    result = run_rules(item)
    if purpose == "unknown" or (purpose == "commitment" and decision is None):
        assert result.source == "pending"
    elif purpose == "commitment" and decision == "launch":
        assert result.applicability == "applicable"
    else:
        assert result.label == "NOT_APPLICABLE"


def test_explicit_source_spans_use_original_exact_text_without_claiming_truncated_completeness(env):
    from career_lab.contracts.v2.core import canonical

    a = env["authority"]
    a.add("product", "p1", 1, "待核对的方案。" * 360)
    refs = []
    for n in range(3):
        body = "背景资料。" * 300 + "第七天的有效约束为30名用户。" + "其他记录。" * 300
        r = a.add("material", "m" + str(n), 1, body)
        start = body.index("第七天")
        refs.append(
            r.model_copy(
                update={
                    "quote": "第七天的有效约束为30名用户。",
                    "span_start": start,
                    "span_end": start + len("第七天的有效约束为30名用户。"),
                }
            )
        )
    item = package(env, criterion="R6.comparison", purpose="option", refs=tuple(refs))
    assert item.completeness == "complete" and not item.dropped_refs
    payload = canonical(model_input(item))
    assert "背景资料。" not in payload and payload.count("第七天的有效约束为30名用户。") == 3
    too_small = package(
        env, criterion="R6.comparison", purpose="option", refs=tuple(refs), budget=1000
    )
    assert too_small.completeness == "text_overflow" and too_small.dropped_refs


class VerifierResponseFixture:
    revision = "support-protocol-fixture-only"
    retries = 0

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def complete(self, messages, tools):
        self.calls.append(messages)
        return ModelReply(text=json.dumps(self.reply, ensure_ascii=False))


def proposal(item):
    from career_lab.contracts.v2.evaluation import FeedbackItem

    return FeedbackItem(
        criterion=item.criterion,
        label="MET",
        applicability="applicable",
        source="model_advice",
        explanation="方案比较有明确证据支持，供人工复核。",
        citations=(item.candidate_evidence[0].ref,),
    )


def support_reply(item, relation="SUPPORTED"):
    c = item.candidate_evidence[0]
    return {
        "relation": relation,
        "reason": "测试提供的关系结论，仅验证协议，不证明语义正确。",
        "spans": [{"id": c.id, "quote": c.text}],
    }


@pytest.mark.parametrize(
    "defect",
    [
        "missing_span",
        "invented_quote",
        "wrong_offset",
        "unknown_id",
        "empty_reason",
        "tools",
        "overflow",
        "provider_failure",
        "ambiguous_quote",
    ],
)
def test_verifier_rejects_unsupported_protocol_responses_instead_of_approving_existing_ids(
    env, defect
):
    item = package(env, criterion="R6.comparison", purpose="option")
    body = support_reply(item)
    if defect == "ambiguous_quote":
        env["authority"].add("product", "p1", 1, "重复。重复。")
        item = package(env, criterion="R6.comparison", purpose="option")
        body = support_reply(item)
        body["spans"][0]["quote"] = "重复。"
    if defect == "missing_span":
        body["spans"] = []
    if defect == "invented_quote":
        body["spans"][0]["quote"] = "输入中不存在"
    if defect == "wrong_offset":
        body["spans"][0]["start"] = 1
    if defect == "unknown_id":
        body["spans"][0]["id"] = "unknown"
    if defect == "empty_reason":
        body["reason"] = " "
    model = VerifierResponseFixture(body)
    if defect == "tools":
        from career_lab.runtime.model_adapter import ToolCall

        model.complete = lambda *_: ModelReply(
            text="{}", tool_calls=(ToolCall(id="x", name="read_secret", arguments={}),)
        )
    if defect == "provider_failure":

        def fail(*_):
            raise RuntimeError("secret should never leave provider")

        model.complete = fail
    result = EvidenceSupportVerifier(
        model, input_bytes=512 if defect == "overflow" else 64000
    ).verify(item, proposal(item))
    assert result.verdict == "unverified" and "secret" not in str(result)


def test_verifier_checks_conclusion_label_full_evidence_and_retains_inspectable_spans(env):
    item = package(env, criterion="R6.comparison", purpose="option")
    p = proposal(item)
    model = VerifierResponseFixture(support_reply(item))
    result = EvidenceSupportVerifier(model).verify(item, p)
    payload = json.loads(model.calls[0][1]["content"])
    assert payload["conclusion"] == p.explanation and payload["proposed_label"] == p.label
    assert payload["responsibility"] == item.claim and len(payload["evidence"]) == len(
        item.candidate_evidence
    )
    assert (
        result.verdict == "supported" and result.spans and result.input_hash and result.output_hash
    )
    assert result.model_revision == "support-protocol-fixture-only"
    assert EvidenceSupportVerifier().verify(item, p).status == "provider_unavailable"


def test_real_provider_assembly_uses_bounded_calls_and_default_is_still_unavailable(
    env, monkeypatch
):
    import httpx

    item = package(env, criterion="R6.comparison", purpose="option")
    requests = []

    def post(url, **kwargs):
        requests.append((url, kwargs))
        payload = kwargs["json"]
        system = payload["messages"][0]["content"]
        text = (
            json.dumps(support_reply(item), ensure_ascii=False)
            if "核验这项具体责任" in system
            else advice(item)
        )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": text}}], "usage": {"total_tokens": 1}}
        )

    monkeypatch.setattr(httpx, "post", post)
    engine = create_feedback_engine(
        api_key="fixture-only",
        base_url="https://example.invalid",
        model="judge-fixture",
        support_model="support-fixture",
        timeout=4,
    )
    outcome = engine.judge.evaluate(item)
    assert outcome.item.source == "model_advice" and len(requests) == 2
    assert {r[1]["json"]["model"] for r in requests} == {"judge-fixture", "support-fixture"}
    assert all(r[1]["timeout"] == 4 and r[1]["json"]["max_tokens"] == 512 for r in requests)
    assert outcome.attempts[0]["support"]["status"] == "model_relation"
    assert AdvisoryJudge().evaluate(item).item.source == "pending"


@pytest.mark.parametrize(
    "relation,expected", [("CONTRADICTED", "unsupported"), ("INSUFFICIENT", "unverified")]
)
def test_semantic_verifier_preserves_negative_or_uncertain_relation(env, relation, expected):
    item = package(env, criterion="R6.comparison", purpose="option")
    model = VerifierResponseFixture(support_reply(item, relation))
    result = EvidenceSupportVerifier(model).verify(item, proposal(item))
    assert result.verdict == expected and result.reason and len(model.calls) == 1
