"""Recorded business decisions in feedback read as one sentence per request (164 F16)."""

import re
from types import SimpleNamespace

import pytest

from career_lab.api.business_record import decision_line, recorded_decisions
from career_lab.api.evaluation_runtime import ScenarioEvidencePort
from career_lab.contracts import v2 as C
from career_lab.evidence.v2.ports import RuleSnapshot


def row(kind, object_id, revision, content=None):
    return SimpleNamespace(
        ref=SimpleNamespace(kind=kind, object_id=object_id),
        content=content or {},
        created_storage_revision=revision,
    )


def decided(request, revision, status, **terms):
    return row(
        "business_decision",
        "decision-" + request + str(revision),
        revision,
        {"request": {"object_id": request}, "status": status, **terms},
    )


def test_requests_are_listed_in_the_order_they_were_made():
    # Object ids sort the other way round; "zzz" was asked first, then "mmm", then "aaa".
    objects = (
        row("business_request", "aaa", 11),
        decided("aaa", 12, "approved", granted={"dev_days": 6}),
        row("business_request", "mmm", 7),
        decided("mmm", 8, "rejected"),
        row("business_request", "zzz", 3),
        decided("zzz", 4, "countered", countered={"capacity": 60}),
        row("business_request", "zzz", 5),
        decided("zzz", 6, "accepted", granted={"capacity": 60}),
    )
    requests = (
        SimpleNamespace(id="aaa", requested={"dev_days": 6}),
        SimpleNamespace(id="mmm", requested={"dev_days": 7}),
        SimpleNamespace(id="zzz", requested={"capacity": 100}),
    )
    port = ScenarioEvidencePort.__new__(ScenarioEvidencePort)
    port.module = SimpleNamespace(work_language="zh")
    port.window = lambda auth, at: SimpleNamespace(
        objects=objects, snapshot=SimpleNamespace(requests=requests)
    )
    port.source = lambda auth, ref, at: SimpleNamespace(ref=ref)
    point = C.VersionPoint(business_seq=5, workspace_revision=1, storage_revision=13)
    result = port.with_business_response(None, RuleSnapshot(as_of=point))
    assert result.business_response == (
        "已记录的业务决定（规则核实）：\n"
        "名额：申请 100 · 已接受 60\n"
        "开发人日：申请 7 · 未批准\n"
        "开发人日：申请 6 · 已批准 6"
    )
    assert [ref.object_id for ref in result.business_response_refs] == [
        "decision-zzz6",
        "decision-mmm8",
        "decision-aaa12",
    ]


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        pytest.param(
            "zh",
            "已记录的业务决定（规则核实）：\n"
            "开发人日：申请 7 · 未批准\n"
            "开发人日：申请 6 · 已批准 6",
            id="zh",
        ),
        pytest.param(
            "en",
            "Recorded business decisions (rule checked):\n"
            "Person-days: requested 7 · declined\n"
            "Person-days: requested 6 · approved 6",
            id="en",
        ),
    ],
)
def test_each_request_is_one_line_under_the_heading(language, expected):
    record = recorded_decisions(
        language,
        [({"dev_days": 7}, "rejected", {}), ({"dev_days": 6}, "approved", {"dev_days": 6})],
    )
    assert record == expected


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        pytest.param("zh", "截止日：申请第 9 天 · 还价第 8 天，待接受", id="zh"),
        pytest.param(
            "en", "Deadline day: requested day 9 · counteroffer day 8, awaiting acceptance", id="en"
        ),
    ],
)
def test_a_deadline_reads_as_a_day(language, expected):
    line = decision_line(language, {"deadline_day": 9}, "countered", {"deadline_day": 8})
    assert line == expected


@pytest.mark.parametrize(
    ("language", "status", "result", "expected"),
    [
        pytest.param(
            "zh",
            "approved",
            {"dev_days": 6, "deadline_day": 9},
            "截止日：申请第 9 天 · 已批准第 9 天、开发人日：申请 6 · 已批准 6",
            id="zh-approved",
        ),
        pytest.param(
            "zh",
            "rejected",
            {},
            "截止日：申请第 9 天、开发人日：申请 6 · 未批准",
            id="zh-rejected",
        ),
        pytest.param(
            "zh",
            "countered",
            {"dev_days": 6, "deadline_day": 8},
            "截止日：申请第 9 天 · 还价第 8 天、开发人日：申请 6 · 还价 6，待接受",
            id="zh-countered",
        ),
        pytest.param(
            "en",
            "approved",
            {"dev_days": 6, "deadline_day": 9},
            "Deadline day: requested day 9 · approved day 9; Person-days: requested 6 · approved 6",
            id="en-approved",
        ),
        pytest.param(
            "en",
            "rejected",
            {},
            "Deadline day: requested day 9; Person-days: requested 6 · declined",
            id="en-rejected",
        ),
        pytest.param(
            "en",
            "countered",
            {"dev_days": 6, "deadline_day": 8},
            "Deadline day: requested day 9 · counteroffer day 8; "
            "Person-days: requested 6 · counteroffer 6, awaiting acceptance",
            id="en-countered",
        ),
    ],
)
def test_several_terms_of_one_request_read_as_one_sentence(language, status, result, expected):
    # The decision is the whole request's: a status without amounts is said once, at the end,
    # and so is what a counteroffer awaits; approved or countered amounts stay with each term.
    line = decision_line(language, {"dev_days": 6, "deadline_day": 9}, status, result)
    assert line == expected
    if language == "zh":
        # Full-width punctuation, nothing joined with semicolons.
        assert not re.search(r"[:,;；]", line)
    else:
        # Terms are separated by semicolons, so "60, awaiting acceptance" cannot read as a list.
        assert line.count("; ") == 1


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        pytest.param("zh", "一项申请（没有可读的条款） · 未批准", id="zh"),
        pytest.param("en", "A request (no readable terms) · declined", id="en"),
    ],
)
def test_a_request_without_readable_terms_still_has_its_line(language, expected):
    # 185 P3-5: an empty or unsupported request is still a recorded decision; its line keeps it
    # beside its reference instead of vanishing.
    assert decision_line(language, {}, "rejected", {}) == expected
    assert decision_line(language, {"budget": 5}, "rejected", {}) == expected
    record = recorded_decisions(language, [({}, "rejected", {}), ({"dev_days": 6}, "rejected", {})])
    assert len(record.split("\n")) == 3
