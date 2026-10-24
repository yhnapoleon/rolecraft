"""Colleague replies read like a colleague: first person, short, never cut mid-sentence."""

import json

import httpx
import pytest
from test_bilingual import bilingual_fixture, req_for
from test_context import owner
from test_runtime import generate

from career_lab.contracts.v2 import ProtocolError
from career_lab.runtime.context_v2 import assemble_context, role_text
from career_lab.runtime.model_adapter import ModelReply, OpenAICompatibleModel, ScriptedModel


def reply_for(language, text, finish_reason):
    c, f, _, _ = bilingual_fixture(language)
    snap = assemble_context(c, f)
    model = ScriptedModel([ModelReply(text=text, finish_reason=finish_reason)])
    public, _ = generate(snap, owner(), req_for(snap, "Who should go first?"), model)
    return public.text


@pytest.mark.parametrize(
    ("language", "cut", "published"),
    [
        (
            "en",
            "I would start with the 20 new hires. The rest can wait until the err",
            "I would start with the 20 new hires.",
        ),
        ("zh", "我会先从20名新员工开始。其余的人等错误边界清楚后再", "我会先从20名新员工开始。"),
    ],
)
def test_length_cut_reply_is_published_up_to_its_last_whole_sentence(language, cut, published):
    assert reply_for(language, cut, "length") == published


def test_length_cut_reply_keeps_the_citation_that_closes_its_last_sentence():
    cut = "The pilot limit is 30 seats. [policy · v1]\n\nBefore we widen it, check the [policy · v2"
    assert reply_for("en", cut, "length") == "The pilot limit is 30 seats. [policy · v1]"


@pytest.mark.parametrize("language", ["zh", "en"])
def test_length_cut_reply_without_a_whole_sentence_is_not_published(language):
    with pytest.raises(ProtocolError) as exc:
        reply_for(language, "I would start with the twenty new hi", "length")
    assert exc.value.code == "role_model_invalid"


@pytest.mark.parametrize("finish_reason", ["stop", None])
def test_finished_reply_is_published_unchanged(finish_reason):
    text = "Which group would you trust to report a wrong answer quickly"
    assert reply_for("en", text, finish_reason) == text


def test_provider_reports_why_a_reply_ended(monkeypatch):
    def post(url, *, headers, json, timeout):
        body = {
            "choices": [{"message": {"content": "Half a sente"}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 512},
        }
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    model = OpenAICompatibleModel(None, "http://127.0.0.1:1", "controlled", retries=0)
    reply = model.complete([{"role": "user", "content": "q"}], [])
    assert reply.finish_reason == "length" and reply.text == "Half a sente"


def test_reply_without_finish_reason_serializes_as_before():
    assert "finish_reason" not in ModelReply(text="ok").model_dump(mode="json")


@pytest.mark.parametrize(
    ("language", "first_person", "brief"),
    [("en", "first person", "three short sentences"), ("zh", "第一人称", "三句")],
)
def test_colleague_prompt_asks_for_a_short_first_person_reply(language, first_person, brief):
    c, f, _, _ = bilingual_fixture(language)
    system = assemble_context(c, f).messages(owner())[0][0]["content"]
    assert first_person in role_text(language, "instructions")
    assert brief in role_text(language, "help_policy")
    assert role_text(language, "instructions") + role_text(language, "help_policy") in system


@pytest.mark.parametrize(
    ("language", "role_id", "name", "team"),
    [
        ("en", "supervisor", "Grace", ["Chen Min (Business lead)", "Daniel (Technical lead)"]),
        ("en", "business_lead", "Chen Min", ["Grace (Manager)", "Daniel (Technical lead)"]),
        ("en", "tech_lead", "Daniel", ["Grace (Manager)", "Chen Min (Business lead)"]),
        ("zh", "supervisor", "Grace", ["陈敏（业务负责人）", "Daniel（技术负责人）"]),
        ("zh", "business_lead", "陈敏", ["Grace（经理）", "Daniel（技术负责人）"]),
        ("zh", "tech_lead", "Daniel", ["Grace（经理）", "陈敏（业务负责人）"]),
    ],
)
def test_each_colleague_knows_its_own_name_and_the_other_two(language, role_id, name, team):
    c, f, _, _ = bilingual_fixture(language, role_id=role_id)
    system = assemble_context(c, f).messages(owner())[0][0]["content"]
    context = json.loads(system.split("\nCONTEXT\n", 1)[1])
    assert context["name"] == name and context["team"] == team
