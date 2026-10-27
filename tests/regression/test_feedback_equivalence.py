"""Stable full-output comparisons including exact evidence, prompts and model identity."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from career_lab.contracts import v2 as contract

from .feedback_cases import CASES, Case, Language, evaluate_case, fixed_input

EXPECTED = Path(__file__).with_name("feedback-baseline.json")
# The judge and support prompts gained the shared claim-status guidance
# (dd9cb8f5, generalized in 263559ad). Removing only that guidance reproduces the
# registered baseline exactly, so it keeps its original bytes; these are the only
# digests the guidance changes (recorded digest -> current digest).
PROMPT_DIGESTS = {
    "zh": {
        "prompt_hash": (
            "6565bc26733b37e9061ed08a9118402155368c9f8e1250b8e17a5b6fc654d1d4",
            "21576b592fbdaa38121b1152973a0659c7b8c40a87882f90448ae6250400f8de",
        ),
        "support_input_hash": (
            "62cf5bb8cc6f1f5c5795dae196f48da5f44885ab55c9e4f23adef3b7f6264196",
            "972c7b2ab95c81aa69f6ec7b88f791642bc2725d1ef8a6a9cc504c7034b5ec9a",
        ),
    },
    "en": {
        "prompt_hash": (
            "09aa82cf6705d5a80feb9ffdc9f44a723b144db5aa769beae19f3ef1b3e16bff",
            "4a267efa60513d7c90dafd8fd244242ab8f2eb139090ba68812c80c6c1c21e86",
        ),
        "support_input_hash": (
            "51b3c4d51c93d9fc4cd49f807fcf9088046389c13fa901976d76b624c1879cb6",
            "a98143786888427fa9084232ffe7a50bb80cb7ae4be8db8623a1c0b2957a769f",
        ),
    },
}


def with_current_prompts(expected: dict, language: Language) -> dict:
    digests = PROMPT_DIGESTS[language]
    for attempt in expected["output"]["attempts"]:
        if "prompt_hash" in attempt:
            recorded, current = digests["prompt_hash"]
            assert attempt["prompt_hash"] == recorded
            attempt["prompt_hash"] = current
        if attempt.get("support"):
            recorded, current = digests["support_input_hash"]
            assert attempt["support"]["input_hash"] == recorded
            attempt["support"]["input_hash"] = current
    return expected


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("case", CASES)
def test_fixed_feedback_matches_baseline(language: Language, case: Case) -> None:
    expected = with_current_prompts(json.loads(EXPECTED.read_text())[language][case], language)
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
