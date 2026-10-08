"""Fixed evidence and scripted provider responses; no network-capable model."""

from typing import Literal

from career_lab.contracts import v2 as contract
from career_lab.rubrics.v4.judge import AdvisoryJudge
from career_lab.rubrics.v4.support import EvidenceSupportVerifier
from career_lab.runtime.model_adapter import ModelReply

Language = Literal["zh", "en"]
Case = Literal["valid", "unknown_citation", "wrong_quote", "provider_failure", "unavailable"]
CASES: tuple[Case, ...] = (
    "valid",
    "unknown_citation",
    "wrong_quote",
    "provider_failure",
    "unavailable",
)


class FixedModel:
    provider = "controlled-local"
    revision = "controlled-local/fixed-feedback-v1"
    retries = 0

    def __init__(self, response: dict[str, object] | None) -> None:
        self.response = response
        self.calls = 0

    def complete(self, messages: list[dict[str, object]], tools: list[object]) -> ModelReply:
        self.calls += 1
        assert messages and tools == []
        if self.response is None:
            raise TimeoutError("controlled provider timeout")
        return ModelReply(text=contract.canonical(self.response))


def fixed_input(language: Language) -> contract.EvidencePackageV2:
    text = "The hotel limit is 400." if language == "en" else "住宿报销上限为400。"
    reference = contract.EvidenceRefV2(
        session_id="fixed-session",
        kind="material",
        object_id="policy",
        version=2,
        observed_at_seq=3,
        quote=text,
        span_start=0,
        span_end=len(text),
    )
    subject = contract.EvidenceRefV2(
        session_id="fixed-session",
        kind="product",
        object_id="decision",
        version=1,
        observed_at_seq=3,
    )
    body = {
        "schema_version": 2,
        "item_id": "fixed-support",
        "task_type": "criterion",
        "criterion": "R2.support",
        "claim": text,
        "subjects": [subject.model_dump(mode="json")],
        "purpose": "commitment",
        "as_of": {
            "schema_version": 2,
            "business_seq": 3,
            "workspace_revision": 2,
            "storage_revision": 5,
        },
        "applicability": "applicable",
        "completeness": "complete",
        "candidate_evidence": [
            {
                "schema_version": 2,
                "id": "policy-v2",
                "text": text,
                "ref": reference.model_dump(mode="json"),
            }
        ],
        "rule_context": {},
        "rule_bound": None,
        "dropped_refs": [],
        "missing_refs": [],
    }
    return contract.EvidencePackageV2.model_validate({**body, "input_hash": contract.digest(body)})


def evaluate_case(language: Language, case: Case) -> dict[str, object]:
    package = fixed_input(language)
    quote = package.candidate_evidence[0].text
    model = FixedModel(
        None
        if case == "provider_failure"
        else {
            "criterion": "R2.support",
            "label": "MET",
            "applicability": "applicable",
            "explanation": "Fixed evidence supports the claim."
            if language == "en"
            else "固定证据支持该判断。",
            "citation_ids": ["not-authorized"] if case == "unknown_citation" else ["policy-v2"],
        }
    )
    verifier = FixedModel(
        {
            "relation": "SUPPORTED",
            "reason": "Controlled verification",
            "spans": [
                {
                    "id": "policy-v2",
                    "quote": "invented quote" if case == "wrong_quote" else quote,
                }
            ],
        }
    )
    judge = AdvisoryJudge(
        None if case == "unavailable" else model, EvidenceSupportVerifier(verifier)
    )
    outcome = judge.evaluate(package, work_language=language)
    return {
        "input": package.model_dump(mode="json"),
        "output": {
            "item": outcome.item.model_dump(mode="json"),
            "attempts": list(outcome.attempts),
        },
        "provider": model.provider,
        "model": model.revision,
        "calls": {"judge": model.calls, "support": verifier.calls},
        "retries": model.retries,
    }
