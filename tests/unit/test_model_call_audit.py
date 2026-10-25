"""Model transport and validation accounting, including rejected and skipped outputs."""

import json
from dataclasses import asdict

import pytest
from test_w05_pipeline import env as env
from test_w05_pipeline import package
from test_w05_responsibility_support import proposal, support_reply

from career_lab.rubrics.v4.judge import AdvisoryJudge
from career_lab.rubrics.v4.support import EvidenceSupportVerifier
from career_lab.runtime.model_adapter import ModelReply, ScriptedModel


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "calls.jsonl"
    monkeypatch.setenv("CAREER_LAB_MODEL_AUDIT_PATH", str(path))
    return path


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_judge_records_usage_even_when_json_is_invalid(env, ledger):
    p = package(env, criterion="R6.comparison", purpose="option")
    model = ScriptedModel(
        [
            ModelReply(
                text="{",
                usage={"prompt_tokens": 123, "completion_tokens": 512},
                finish_reason="length",
            )
        ]
    )
    result = AdvisoryJudge(model).evaluate(p)
    assert result.item.source == "pending"
    records = rows(ledger)
    assert [r["event"] for r in records] == [
        "model_call_started",
        "model_call_finished",
        "model_validation",
    ]
    usage = records[1]["usage"]
    assert usage["input_tokens"] == 123 and usage["output_tokens"] == 512
    assert records[1]["finish_reason"] == "length"
    assert records[2]["code"] == "JSONDecodeError"
    assert all(r["criterion"] == p.criterion and r["session_id"] == "s" for r in records)
    assert len({r["call_id"] for r in records}) == 1


def test_support_records_success_and_preflight_skip(env, ledger):
    p = package(env, criterion="R6.comparison", purpose="option")
    model = ScriptedModel(
        [
            ModelReply(
                text=json.dumps(support_reply(p)),
                usage={"prompt_tokens": 42, "completion_tokens": 21},
                finish_reason="stop",
            )
        ]
    )
    assert EvidenceSupportVerifier(model).verify(p, proposal(p)).verdict == "supported"
    assert (
        EvidenceSupportVerifier(model, input_bytes=512).verify(p, proposal(p)).status
        == "input_overflow"
    )
    records = rows(ledger)
    assert sum(r["event"] == "model_call_started" for r in records) == 1
    assert records[-1]["status"] == "input_overflow" and records[-1]["called"] is False
    assert records[-1]["slot"] == "SUPPORT"


def test_transport_error_never_writes_exception_or_unknown_usage_as_zero(env, ledger):
    p = package(env, criterion="R6.comparison", purpose="option")

    class Broken:
        revision = "test-model"

        def complete(self, *_):
            raise TimeoutError("SECRET_HEADER_AND_BODY")

    AdvisoryJudge(Broken()).evaluate(p)
    records = rows(ledger)
    assert "SECRET_HEADER_AND_BODY" not in ledger.read_text()
    usage = next(r["usage"] for r in records if r["event"] == "model_call_finished")
    assert usage["status"] == "timeout" and usage["usage_known"] is False
    assert usage["input_tokens"] is None


def test_evaluation_slot_defaults_fit_structured_evidence_and_keep_explicit_budgets():
    from career_lab.runtime.model_slots import slot_config

    configured = {"CAREER_LAB_JUDGE_PROVIDER": "deepseek"}
    judge = slot_config("JUDGE", "local", configured)
    support = slot_config("SUPPORT", "local", configured, judge)
    assert judge.max_tokens == support.max_tokens == 2048
    assert slot_config("ROLES", "local", {}).max_tokens == 512
    assert slot_config("JUDGE", "local", {}).max_tokens == 512
    small = slot_config("JUDGE", "local", configured | {"CAREER_LAB_JUDGE_MAX_TOKENS": "300"})
    assert small.max_tokens == 300
    assert slot_config("SUPPORT", "local", configured, small).max_tokens == 300


def test_support_exposes_truncation_without_accepting_partial_json(env, ledger):
    p = package(env, criterion="R6.comparison", purpose="option")
    model = ScriptedModel([ModelReply(text='{"relation":"SUPPORTED"', finish_reason="length")])
    result = EvidenceSupportVerifier(model).verify(p, proposal(p))
    assert result.verdict == "unverified"
    assert "code" not in asdict(result)
    assert rows(ledger)[-1]["code"] == "output_truncated"


@pytest.mark.parametrize(
    "code",
    [
        "response_shape_invalid",
        "relation_or_reason_invalid",
        "spans_invalid",
        "span_shape_invalid",
        "span_id_or_quote_invalid",
        "quote_not_unique_in_candidate",
        "cited_span_missing",
        "counterevidence_required",
        "json_invalid",
    ],
)
def test_support_validation_details_stay_in_ledger_and_do_not_leak_to_next_call(env, ledger, code):
    p = package(env, criterion="R6.comparison", purpose="option")
    body = support_reply(p)
    if code == "response_shape_invalid":
        body["extra"] = True
    elif code == "relation_or_reason_invalid":
        body["reason"] = ""
    elif code == "spans_invalid":
        body["spans"] = None
    elif code == "span_shape_invalid":
        body["spans"][0]["start"] = 0
    elif code == "span_id_or_quote_invalid":
        body["spans"][0]["id"] = "unknown"
    elif code == "quote_not_unique_in_candidate":
        body["spans"][0]["quote"] = "invented quote"
    elif code == "cited_span_missing":
        body["spans"] = []
    elif code == "counterevidence_required":
        body.update(relation="CONTRADICTED", spans=[])
    model = ScriptedModel(
        [
            ModelReply(text="{" if code == "json_invalid" else json.dumps(body)),
            ModelReply(text=json.dumps(support_reply(p))),
        ]
    )
    verifier = EvidenceSupportVerifier(model)
    failed = verifier.verify(p, proposal(p))
    recovered = verifier.verify(p, proposal(p))
    skipped = verifier.verify(p, proposal(p).model_copy(update={"citations": ()}))
    assert failed.verdict == "unverified"
    assert failed.status == "invalid_or_failed_verification"
    assert recovered.verdict == "supported" and skipped.status == "no_citations"
    assert all("code" not in asdict(result) for result in (failed, recovered, skipped))
    records = rows(ledger)
    validations = [row for row in records if row["event"] == "model_validation"]
    assert [row["code"] for row in validations] == [code, None, None]
    assert [row["called"] for row in validations] == [True, True, False]
    assert len({row["call_id"] for row in validations}) == 3
    assert sum(row["event"] == "model_call_started" for row in records) == 2


@pytest.mark.parametrize("error_type", [TimeoutError, ValueError, RuntimeError])
def test_support_provider_exception_body_never_enters_output_or_ledger(env, ledger, error_type):
    p = package(env, criterion="R6.comparison", purpose="option")

    class Broken:
        revision = "test-model"

        def complete(self, *_):
            raise error_type("SECRET_HEADER_AND_BODY")

    result = EvidenceSupportVerifier(Broken()).verify(p, proposal(p))
    assert result.verdict == "unverified" and "code" not in asdict(result)
    assert "SECRET_HEADER_AND_BODY" not in ledger.read_text() + str(asdict(result))
    assert rows(ledger)[-1]["code"] == "verification_failed"


@pytest.mark.parametrize("language", ["zh", "en"])
def test_nested_support_diagnostic_is_private_and_keeps_its_own_call_id(ledger, language):
    from tests.regression.feedback_cases import evaluate_case

    outcome = evaluate_case(language, "wrong_quote")
    assert "code" not in outcome["output"]["attempts"][0]["support"]
    records = rows(ledger)
    validations = {row["slot"]: row for row in records if row["event"] == "model_validation"}
    assert validations["SUPPORT"]["code"] == "quote_not_unique_in_candidate"
    assert validations["JUDGE"]["code"] is None
    assert validations["SUPPORT"]["call_id"] != validations["JUDGE"]["call_id"]
    for slot, row in validations.items():
        assert {r["event"] for r in records if r["call_id"] == row["call_id"]} == {
            "model_call_started",
            "model_call_finished",
            "model_validation",
        }
        assert all(r["slot"] == slot for r in records if r["call_id"] == row["call_id"])
