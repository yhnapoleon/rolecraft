"""Model transport and validation accounting, including rejected and skipped outputs."""

import json

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
    assert result.verdict == "unverified" and result.code == "output_truncated"
    assert rows(ledger)[-1]["code"] == "output_truncated"
