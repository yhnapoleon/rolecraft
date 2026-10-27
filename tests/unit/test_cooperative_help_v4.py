"""cooperative-help-v4: on the learner's own work, restate one assumption and ask one
question; never hand over the correct definition, field or number."""

import pytest

from career_lab.runtime.context_v2 import HELP_POLICY_REVISION, role_text


def test_revision_is_v4():
    assert HELP_POLICY_REVISION == "cooperative-help-v4"


@pytest.mark.parametrize(
    ("language", "phrases"),
    [
        (
            "zh",
            ("优先于上面的‘先说事实’", "不判断对错", "不给正确的定义、字段或数字", "不指出第二处"),
        ),
        (
            "en",
            (
                'overrides "lead with the facts"',
                "without judging it",
                "without giving the correct definition, field or number",
                "do not point out a second issue",
            ),
        ),
    ],
)
def test_own_work_help_restates_one_assumption_without_the_answer(language, phrases):
    policy = role_text(language, "help_policy")
    for phrase in phrases:
        assert phrase in policy
    # The reply-length rule the voice tests rely on stays.
    assert ("三句" if language == "zh" else "three short sentences") in policy
