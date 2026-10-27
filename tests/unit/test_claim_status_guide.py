import re

import pytest

from career_lab.aipm.review_model import SYSTEM
from career_lab.rubrics.v4.claim_status import claim_status_guide


@pytest.mark.parametrize(
    "language,principles",
    [
        (
            "zh",
            (
                "现有记录中已有的信息、提议以后采集的信息，以及声称已经完成采集",
                "仅凭现有资料缺少某个字段，不能否定以后采集该字段的提议",
                "提议的方法及采集责任归属应另行核对",
                "声称字段已经存在或采集已经完成，仍须有依据",
                "不能把提议当成已验证结果",
            ),
        ),
        (
            "en",
            (
                "information already in existing records, proposals for future collection, "
                "and claims that collection is complete",
                "A field missing from existing records alone cannot refute a proposal "
                "to collect it later",
                "Check the proposed method and responsibility for collection separately",
                "Claims that a field already exists or collection is complete "
                "still require evidence",
                "never treat a proposal as a verified result",
            ),
        ),
    ],
)
def test_reviewer_distinguishes_proposals_from_recorded_and_completed_claims(language, principles):
    guide = claim_status_guide(language)
    for principle in principles:
        assert principle in guide
    assert re.search(r"\b[A-Z]{1,12}-\d+\b", guide, re.IGNORECASE) is None
    for case_detail in ("SD-", "实际工时", "actual handling time", "duration_minutes"):
        assert case_detail.casefold() not in guide.casefold()
    assert guide in SYSTEM[language]
