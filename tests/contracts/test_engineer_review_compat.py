"""Records written before additive engineer-review-v1 fields keep their bytes and digests.

The fixture under fixtures/engineer-review-v1-legacy was produced by the unmodified
origin/main 4b069b2 engineer CLI (W13 freshness_guard none -> warn flow, zh and en,
with an accurate self-report). Its hashes are pinned independently of the current
implementation; do not regenerate the files to bless a change.
"""

import hashlib
import json
from pathlib import Path

import pytest

from career_lab.contracts.v2 import digest
from career_lab.contracts.v2.engineer import (
    EngineerRegressionReport,
    decode_engineer_document,
    public_engineer_report,
)
from career_lab.contracts.v2.engineer_examples import engineer_examples
from career_lab.contracts.v2.engineer_export import json_bytes
from career_lab.engineer.files import encode

ROOT = Path(__file__).resolve().parents[2]
LEGACY = Path(__file__).resolve().parent / "fixtures" / "engineer-review-v1-legacy"
PUBLISHED = ROOT / "docs/contracts/engineer-review-v1/examples"

LEGACY_FILES = {
    "en/baseline-results.json": "6fc75c78f50d37205329bad1c1b96798eb37fa8b709f80cf46883195656e7a21",
    "en/baseline.json": "c188426add6daea08120c3ba62e7c37c50c8874800e7c941a8777239a0b7c243",
    "en/candidate.json": "18e105ce5e49c4fcc5dfb36735453ec440471f23da6599e0897afca1fc4f1912",
    "en/claim.json": "92197f4f78c5482cbb7e2571ceb4c85f72aef289a9f828f37b3f024c958a9ea8",
    "en/private-report.json": "afed0b8725565b30f81bd9059ac82831c130508444af87d5df531c041983904f",
    "en/public-report.json": "2d469f3fe6089dd4ca8cd236854c09fa6a96c412494ca8574b437d3c3e7a50c1",
    "en/submission.json": "f20062321807a52ec36a353025d5483661033767ea784452ebecef91849123e2",
    "zh/baseline-results.json": "2be0e7213aa03b7832f38041c4ca02814f051e61f722ddcb12ed808177ddb6a7",
    "zh/baseline.json": "e6d1e94cbcc5aa4a7be284ccf7e87a3f00cb809a57d11388c27a87fb5452bef7",
    "zh/candidate.json": "8f0952957f4221f8d0737a772456d324b41bfb2bf069da5b81a6c12458d5374a",
    "zh/claim.json": "e834ab28e441ac65c839a25d75da4dd2595e1027832af73b0ac102b4868a374c",
    "zh/private-report.json": "24665ce1863b7ef7876ae3d55eb44198ca8e9ecaf44650e9a4020122a0dc1c8b",
    "zh/public-report.json": "956c099bb25b6c60956fe78165de361e59a9b875381437e2b518b334c45e0408",
    "zh/submission.json": "8666d0e490d0235e710dd76e758115ba95feda6c7c3026bbd881e2331471b7f9",
}

# engineer-review-v1 examples as published at origin/main 4b069b2.
PUBLISHED_EXAMPLES = {
    "EngineerAdvice": "566628980a224cda2d5645cd60ce8e1137bb02f2b5d445ecff30459dfd7799bc",
    "EngineerArtifactIdentity": "d05208603cce74dda3dff19a835c9810001d01fc108fcdc1fdd066b3d1a9ea93",
    "EngineerClaimedReport": "a8cc74ca8f8d78a41dd3a373eb08c5616e36effb5f5537ddc4d964207e299dfe",
    "EngineerFinding": "dac4a94452bcbcfed6ac1db4fad6ef5a9a427b10bc08ef41f37b3115e9e2bd45",
    "EngineerProbeClaim": "9a690544cc346f966020b05822a13dd64be6b1d16a24260a3d631d9cf4867b87",
    "EngineerProbeExpectation": "e33d93dd42156c6873a2c53eea9a09311499b5833f760ca8485830e6cba2837f",
    "EngineerProbeResult": "1322ec97d97acdaf52274874d06eb608f98ac9754d635783315330b3eb864b35",
    "EngineerProbeSummary": "1f1f83a134bc25d54f3e3cd2b1590502e9f223d998b05fb2bd89b69fe6a3459c",
    "EngineerPublicAdvice": "603f43c537077c9fc865549b21235b3094e7c5eef4a686c97623c8ea4ae90c1e",
    "EngineerPublicProbeResult": "6301c7c2d0fe6c6a0fc99cc5d7857c0018818b0d6fc325d6a1da9e9eaa5f5571",
    "EngineerPublicReport": "26c390fce688912c96eda99ed5d5427a8d6ae4c2104b1eaf2b3211251eb00c2c",
    "EngineerRegressionReport": "b3576fffc679b028b220b508b9054a25826776e9a74f80c24c31702f53602c41",
    "EngineerReportApplicability": (
        "ab35674b59f2f1c55c27e318e57231f562d594fd439583d923bcb1c0ac81c825"
    ),
    "EngineerReviewInput": "2bb3a2f2c829e711487dadf88b97ddeea6157c3a206871a3c52803630cf94135",
    "EngineerSubmissionRecord": "dfaaaeed83a96b4195b9fe4cdc60198ae3def50b513748899167c75473fbfad0",
    "EngineerUnresolvedItem": "1c1eb002cb6e4a220c6273d101664001bc9fd896115820fb6007305852f21546",
}


def legacy(language: str, name: str) -> bytes:
    raw = (LEGACY / language / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == LEGACY_FILES[language + "/" + name]
    return raw


def test_legacy_fixture_is_the_pinned_capture() -> None:
    files = {p.relative_to(LEGACY).as_posix() for p in LEGACY.rglob("*") if p.is_file()}
    assert files == set(LEGACY_FILES)
    for name, sha in LEGACY_FILES.items():
        assert hashlib.sha256((LEGACY / name).read_bytes()).hexdigest() == sha


@pytest.mark.parametrize("language", ["zh", "en"])
def test_legacy_submission_reencodes_to_identical_bytes(language: str) -> None:
    raw = legacy(language, "submission.json")
    record = decode_engineer_document("EngineerSubmission", raw)
    assert encode(record) == raw
    assert hashlib.sha256(encode(record)).hexdigest() == LEGACY_FILES[language + "/submission.json"]
    assert digest(record) == digest(json.loads(raw))
    assert record.changes == ()
    assert "changes" not in json.loads(encode(record))


@pytest.mark.parametrize("language", ["zh", "en"])
def test_legacy_reports_reencode_and_project_to_identical_bytes(language: str) -> None:
    raw = legacy(language, "private-report.json")
    report = EngineerRegressionReport.model_validate_json(raw)
    assert encode(report) == raw
    assert report.id == "review-" + digest(report.input)
    assert (
        report.submission.sha256 == hashlib.sha256(legacy(language, "submission.json")).hexdigest()
    )
    assert report.hidden_comparison is None
    assert "hidden_comparison" not in json.loads(encode(report))
    public = public_engineer_report(report)
    assert encode(public) == legacy(language, "public-report.json")
    assert public.hidden_comparison is None


def test_published_examples_keep_their_bytes() -> None:
    examples = engineer_examples()
    for name, sha in PUBLISHED_EXAMPLES.items():
        raw = (PUBLISHED / (name + ".json")).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == sha, name
        assert json_bytes(examples[name].model_dump(mode="json")) == raw, name
        model = type(examples[name])
        assert json_bytes(model.model_validate_json(raw).model_dump(mode="json")) == raw, name


@pytest.mark.parametrize("language", ["zh", "en"])
def test_legacy_review_records_still_evaluate_and_compare(language: str) -> None:
    from career_lab.contracts.v2 import AssistantConfig
    from career_lab.contracts.v2.engineer import EngineerClaimedReport, EngineerProbeResult
    from career_lab.engineer.evaluation import evaluate_review
    from career_lab.engineer.findings import hidden_comparison

    report = EngineerRegressionReport.model_validate_json(legacy(language, "private-report.json"))
    baseline = tuple(
        EngineerProbeResult.model_validate(row)
        for row in json.loads(legacy(language, "baseline-results.json"))
    )
    comparison = hidden_comparison(baseline, report.results)
    assert (comparison.new_failures, comparison.unverified) == (1, 0)
    with_counts = report.model_dump(mode="json") | {"hidden_comparison": comparison.model_dump()}
    validated = EngineerRegressionReport.model_validate(with_counts)
    assert public_engineer_report(validated).hidden_comparison == comparison
    evaluation = evaluate_review(
        report,
        decode_engineer_document("EngineerSubmission", legacy(language, "submission.json")),
        AssistantConfig.model_validate_json(legacy(language, "baseline.json")),
        AssistantConfig.model_validate_json(legacy(language, "candidate.json")),
        claimed=EngineerClaimedReport.model_validate_json(legacy(language, "claim.json")),
    )
    assert [item.label for item in evaluation.criteria] == [
        "MET",
        "NOT_MET",
        "INSUFFICIENT",
        "MET",
        None,
    ]
    assert evaluation.conclusion("E3.change_consistency").reason_codes == (
        "change_claims_not_provided",
    )
