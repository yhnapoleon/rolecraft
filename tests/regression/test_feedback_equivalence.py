"""Stable full-output comparisons including exact evidence, prompts and model identity."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from career_lab.contracts import v2 as contract

from .feedback_cases import CASES, Case, Language, evaluate_case, fixed_input

EXPECTED = Path(__file__).with_name("feedback-baseline.json")


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("case", CASES)
def test_fixed_feedback_matches_baseline(language: Language, case: Case) -> None:
    expected = json.loads(EXPECTED.read_text())[language][case]
    actual = evaluate_case(language, case)
    assert json.loads(json.dumps(actual)) == expected
    assert actual["retries"] == 0
    assert actual["calls"]["judge"] <= 1
    assert actual["calls"]["support"] <= 1


@pytest.mark.parametrize("language", ["zh", "en"])
def test_future_evidence_and_changed_input_cannot_reuse_fixed_identity(
    language: Language,
) -> None:
    original = fixed_input(language).model_dump(mode="json")
    altered = json.loads(json.dumps(original))
    altered["candidate_evidence"][0]["ref"]["observed_at_seq"] = 4
    altered["input_hash"] = contract.digest({k: v for k, v in altered.items() if k != "input_hash"})
    with pytest.raises(ValidationError, match="future evidence"):
        contract.EvidencePackageV2.model_validate(altered)
    original["candidate_evidence"][0]["ref"]["version"] = 1
    with pytest.raises(ValidationError, match="evidence input hash mismatch"):
        contract.EvidencePackageV2.model_validate(original)


@pytest.mark.parametrize("language", ["zh", "en"])
def test_explicit_new_attempt_recovers_after_failure(language: Language) -> None:
    failed = evaluate_case(language, "provider_failure")
    assert failed["calls"] == {"judge": 1, "support": 0}
    assert failed["output"]["item"]["source"] == "pending"
    recovered = evaluate_case(language, "valid")
    assert recovered["input"] == failed["input"]
    assert recovered["output"]["item"]["source"] == "model_advice"
    assert recovered["calls"] == {"judge": 1, "support": 1}
