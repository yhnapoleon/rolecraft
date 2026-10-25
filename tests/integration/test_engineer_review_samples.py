"""The sample command reruns the demo end to end and writes real public reviews."""

import json
from pathlib import Path

import pytest

from scripts.engineer_review_samples import main

REVIEW_KEYS = {
    "review_id",
    "status",
    "signed_at",
    "signed_by",
    "draft_id",
    "draft_executor",
    "ticket_id",
    "impact_note",
    "retrieval",
    "report",
    "evaluation",
}


def labels(review: dict) -> dict[str, str | None]:
    return {item["criterion"][:2]: item["label"] for item in review["evaluation"]["criteria"]}


def test_samples_are_real_reviews_in_both_languages(tmp_path: Path) -> None:
    output = tmp_path / "samples"
    assert main(["--output", str(output)]) == 0
    names = sorted(path.name for path in output.glob("*.json"))
    assert names == [
        "en-demo-overreach.json",
        "en-root-cause.json",
        "zh-demo-overreach.json",
        "zh-root-cause.json",
    ]
    for language in ("zh", "en"):
        fixed = json.loads((output / f"{language}-root-cause.json").read_text())
        caught = json.loads((output / f"{language}-demo-overreach.json").read_text())
        for review in (fixed, caught):
            assert set(review) == REVIEW_KEYS
            assert review["report"]["work_language"] == language
            assert review["retrieval"]["mode"] == "rule_based"
        assert (labels(fixed)["E1"], labels(fixed)["E2"]) == ("MET", "MET")
        assert fixed["report"]["hidden_comparison"]["fixed"] == 2
        assert fixed["report"]["hidden_comparison"]["new_failures"] == 0
        assert labels(caught)["E2"] == "NOT_MET"
        assert caught["report"]["hidden_comparison"]["new_failures"] == 1
    # Nothing but the samples: no database, private review store or path in the output.
    assert sorted(path.name for path in output.iterdir()) == names
    text = "\n".join(path.read_text() for path in output.iterdir())
    assert str(tmp_path) not in text and "private-reviews" not in text


def test_samples_never_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "samples"
    output.mkdir()
    with pytest.raises(SystemExit):
        main(["--output", str(output)])
