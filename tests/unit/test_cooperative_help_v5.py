"""cooperative-help-v5: on the learner's own work the whole reply is two sentences, one restated
assumption and one question; never the correct definition, field or number. colleague-help-v4:
a colleague holds their own position until the learner brings the evidence that changes it."""

import pytest

from career_lab.runtime.context_v2 import (
    HELP_POLICY_REVISION,
    ROLE_PROMPT_REVISION,
    role_text,
)


def test_revisions():
    assert HELP_POLICY_REVISION == "cooperative-help-v5"
    assert ROLE_PROMPT_REVISION == "colleague-help-v4"


@pytest.mark.parametrize(
    ("language", "phrases"),
    [
        (
            "zh",
            (
                "优先于上面关于事实、引用和篇幅的所有要求",
                "整条回复只有两句",
                "不点出具体字段名、定义或答案所在的那一行",
                "不判断对错",
                "不给正确的定义、字段或数字",
                "不指出第二处",
                "不再加第二段，也不再问第二个问题",
            ),
        ),
        (
            "en",
            (
                "overrides everything above about facts, citations and length",
                "the whole reply is two sentences",
                "not the specific field, definition or line that holds the answer",
                "without judging it",
                "Give no correct definition, field or number",
                "do not point out a second issue",
                "add a second paragraph or ask a second question",
            ),
        ),
    ],
)
def test_own_work_help_is_one_restated_assumption_and_one_question(language, phrases):
    policy = role_text(language, "help_policy")
    for phrase in phrases:
        assert phrase in policy
    # The reply-length rule the voice tests rely on stays for every other request.
    assert ("三句" if language == "zh" else "three short sentences") in policy


@pytest.mark.parametrize(
    ("language", "phrases"),
    [
        (
            "zh",
            (
                "学员拿出那条具体证据之前",
                "goals 里写着你还没核对过的东西，你就还不知道核对结果",
                "即使你收到的材料里有能推翻它的字段或定义",
                "不主动指出你自己测算或立场里的问题",
                "不说出会让你改变判断的那条反证",
                "数字和算式照材料原样说",
            ),
        ),
        (
            "en",
            (
                "Until the learner brings that specific evidence",
                "you do not yet know the result",
                "even when a field or definition in",
                "do not point out a",
                "name the counter-evidence that would change your mind",
                "State numbers and calculations exactly as the material does",
            ),
        ),
    ],
)
def test_colleague_keeps_their_position_until_the_learner_brings_evidence(language, phrases):
    instructions = role_text(language, "instructions")
    for phrase in phrases:
        assert phrase in instructions
