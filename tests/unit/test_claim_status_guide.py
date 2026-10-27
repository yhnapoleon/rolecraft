import pytest

from career_lab.aipm.review_model import SYSTEM
from career_lab.rubrics.v4.claim_status import claim_status_guide


@pytest.mark.parametrize(
    "language,proposal,completed",
    [
        ("zh", "提出另行采集实际工时", "声称现有字段或已经完成采集仍须有依据"),
        (
            "en",
            "A proposal to collect actual handling time later",
            "Claims that a field exists or collection is complete",
        ),
    ],
)
def test_reviewer_distinguishes_proposals_from_recorded_and_completed_claims(
    language, proposal, completed
):
    guide = claim_status_guide(language)
    assert proposal in guide
    assert completed in guide
    assert guide in SYSTEM[language]
