"""245 original bilingual Agent drafts: exact references, strict time checks, no provider."""

import json
from pathlib import Path

import pytest

from career_lab.contracts import v2 as C
from career_lab.evidence.v2.assembler import EvidenceAssemblerV2, base_ref
from career_lab.evidence.v2.ports import RuleSnapshot, SourceRecord
from career_lab.rubrics.v4.final_rubric import final_policies
from career_lab.rubrics.v4.judge import AdvisoryJudge
from career_lab.runtime.model_adapter import ModelReply

FIXTURE = Path(__file__).parent / "fixtures/second_round_agent_references.json"


class OriginalSources:
    def __init__(self, sample):
        self.records = {}
        for raw in [sample["product"], *sample["sources"]]:
            ref = C.EvidenceRefV2.model_validate(raw["ref"])
            self.records[C.canonical(base_ref(ref))] = SourceRecord(
                ref, raw["text"], C.VersionPoint.model_validate(raw["created_at"])
            )

    def read(self, auth, ref, at):
        assert auth.session_id == ref.session_id
        return self.records[C.canonical(base_ref(ref))]


class LocalProbe:
    revision = "local-probe"
    retries = 0

    def __init__(self):
        self.calls = []

    def complete(self, messages, tools):
        payload = json.loads(messages[-1]["content"])
        self.calls.append(payload)
        return ModelReply(
            text=json.dumps(
                {
                    "criterion": payload["criterion"],
                    "label": "INSUFFICIENT",
                    "applicability": "applicable",
                    "explanation": "Local routing probe only.",
                    "citation_ids": [],
                }
            )
        )


def packages(language, *, corrected=False, budget=16000):
    sample = json.loads(FIXTURE.read_text())[language]
    submission = C.SubmissionV2.model_validate(sample["submission"])
    reader = OriginalSources(sample)
    auth = C.AuthContext(
        session_id=submission.session_id,
        actor_id="learner",
        executor=submission.executor,
        capabilities=("read",),
        credential_id="local-test",
    )
    refs = tuple(C.EvidenceRefV2.model_validate(r) for r in sample["product"]["declared_refs"])
    if corrected:
        refs = tuple(
            r.model_copy(
                update={
                    "observed_at_seq": reader.read(auth, r, submission.as_of).ref.observed_at_seq
                }
            )
            for r in refs
        )
    assembler = EvidenceAssemblerV2(reader, budget, work_language=language)
    return [
        assembler.assemble(
            auth=auth,
            subject_id=submission.id,
            subjects=submission.products,
            evidence_refs=refs,
            purpose="commitment",
            decision=submission.decision,
            as_of=submission.as_of,
            policy=policy,
            snapshot=RuleSnapshot(submission.as_of),
            anchor_mode="submission",
            requested_at=submission.as_of,
        )
        for policy in final_policies(work_language=language)
    ]


@pytest.mark.parametrize("language", ["zh", "en"])
def test_original_agent_refs_remain_rejected_with_the_specific_time_reason(language, monkeypatch):
    monkeypatch.delenv("CAREER_LAB_RECOGNIZERS", raising=False)
    model = LocalProbe()
    eligible = [p for p in packages(language) if p.applicability == "applicable"]
    assert len(eligible) == 9
    for package in eligible:
        assert package.completeness == "missing"
        assert len(package.missing_refs) == 4
        assert not package.dropped_refs
        result = AdvisoryJudge(model).evaluate(package, work_language=language)
        assert result.item.label == "INSUFFICIENT"
        assert (
            "记录时点" if language == "zh" else "reference timestamps"
        ) in result.item.explanation
    assert not model.calls


@pytest.mark.parametrize("language", ["zh", "en"])
def test_correct_timestamp_control_routes_all_nine_items_without_changing_the_draft(
    language, monkeypatch
):
    monkeypatch.delenv("CAREER_LAB_RECOGNIZERS", raising=False)
    model = LocalProbe()
    eligible = [p for p in packages(language, corrected=True) if p.applicability == "applicable"]
    for package in eligible:
        assert package.completeness == "complete"
        result = AdvisoryJudge(model, lambda p, i: "supported").evaluate(
            package, work_language=language
        )
        assert result.attempts[0]["status"] == "valid_advice"
    assert len(model.calls) == 9


@pytest.mark.parametrize("language", ["zh", "en"])
def test_budget_failure_has_a_distinct_reason_and_still_skips_the_provider(language, monkeypatch):
    monkeypatch.delenv("CAREER_LAB_RECOGNIZERS", raising=False)
    model = LocalProbe()
    package = packages(language, corrected=True, budget=512)[0]
    assert package.completeness == "text_overflow"
    result = AdvisoryJudge(model).evaluate(package, work_language=language)
    assert ("预算" if language == "zh" else "budget") in result.item.explanation
    assert not model.calls
