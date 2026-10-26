"""The shared v2 fixture stays valid against the server DTOs it stands in for."""

import json
from pathlib import Path

from career_lab.aipm import types as T

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures/aipm-phase1/section-review.json"


def test_section_review_fixture_matches_server_types():
    data = json.loads(FIXTURE.read_text())
    for key in ("review_en", "review_zh"):
        review = T.SectionReview.model_validate(data[key])
        assert review.affects_formal_score is False and review.sentence_labels is None
    for item in data["page"]["items"]:
        T.SectionReview.model_validate(item["review"])
    T.SheetState.model_validate(data["progress_step_sheet"])
    T.SheetState.model_validate(data["progress_step_sheet_recheck"])
    T.CoverageRule.model_validate(data["coverage_rule_example"])
    T.MentorRule.model_validate(data["mentor_rule_example"])
