"""Recorded business decisions in feedback read as one sentence per request (164 F16)."""

import re

import pytest

from career_lab.api.business_record import decision_line, recorded_decisions


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
            "Recorded business decisions (rule checked): \n"
            "Developer-days: requested 7 · declined\n"
            "Developer-days: requested 6 · approved 6",
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
            "截止日：申请第 9 天 · 未批准、开发人日：申请 6 · 未批准",
            id="zh-rejected",
        ),
        pytest.param(
            "en",
            "approved",
            {"dev_days": 6, "deadline_day": 9},
            "Deadline day: requested day 9 · approved day 9, "
            "Developer-days: requested 6 · approved 6",
            id="en-approved",
        ),
    ],
)
def test_several_terms_of_one_request_read_as_one_sentence(language, status, result, expected):
    line = decision_line(language, {"dev_days": 6, "deadline_day": 9}, status, result)
    assert line == expected
    # Chinese keeps full-width punctuation; neither language joins parts with semicolons.
    assert ";" not in line and "；" not in line
    if language == "zh":
        assert not re.search(r"[:,]", line)
