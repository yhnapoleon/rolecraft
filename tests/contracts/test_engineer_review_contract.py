"""Versioned engineer file contracts; all assertions use production decoders."""

import hashlib
from pathlib import Path

import pytest
from pydantic import JsonValue

from career_lab.contracts.v2 import canonical
from career_lab.contracts.v2.engineer import EngineerReviewInput, decode_engineer_document

FREEZE = Path(__file__).resolve().parents[2] / "docs/contracts/expansion-v3/examples"


@pytest.mark.parametrize("kind", ["EngineerPack", "EngineerSubmission", "RegressionReport"])
def test_engineer_01_legacy_identity_is_preserved(kind: str) -> None:
    raw = (FREEZE / (kind + ".json")).read_bytes()
    decoded = decode_engineer_document(kind, raw)
    import json

    assert canonical(decoded) == canonical(json.loads(raw))
    assert hashlib.sha256(raw).hexdigest() == LEGACY_HASHES[kind]


LEGACY_HASHES = {
    "EngineerPack": "6cb219b97659fb110442246565f13427d9863606794a048f950bfe0be03b4834",
    "EngineerSubmission": "12691f48a380354a3210f388b94c2f91b5817388fe88c90eead7e23e1486e395",
    "RegressionReport": "38bd0f78dc210bb27db6f3b03f2e1cf129a6c194d479b2ab270bfb807aa4fc09",
}


def submission_payload() -> dict[str, JsonValue]:
    import json

    old = json.loads((FREEZE / "EngineerSubmission.json").read_text())
    old.pop("claimed_results")
    return {
        **old,
        "contract_version": "engineer-review-v1",
        "base_config_hash": "1" * 64,
        "regression_report": {"path": "declared.json", "sha256": "2" * 64},
        "unresolved": [
            {"id": "open-1", "description": "Still needs human fallback", "probe_ids": ["p1"]}
        ],
        "created_at": "2026-10-09T02:00:00+08:00",
        "work_language": "en",
    }


def test_engineer_02_submission_roundtrip_keeps_structured_facts() -> None:
    import json

    record = decode_engineer_document("EngineerSubmission", json.dumps(submission_payload()))
    assert record.base_config_hash == "1" * 64
    assert record.regression_report.path == "declared.json"
    assert record.unresolved[0].probe_ids == ("p1",)
    assert record.created_at.utcoffset().total_seconds() == 8 * 3600
    assert decode_engineer_document("EngineerSubmission", record.model_dump_json()) == record


@pytest.mark.parametrize(
    "change",
    [
        {"contract_version": "unknown"},
        {"contract_version": None},
        {"command": "sh run.sh"},
        {"code": "exec(1)"},
        {"url": "https://invalid.example"},
        {"config": {"path": "../secret", "sha256": "0" * 64}},
        {"created_at": "2026-10-09T00:00:00"},
        {"unresolved": None},
    ],
)
def test_engineer_03_05_invalid_version_fields_and_time_rejected(
    change: dict[str, JsonValue],
) -> None:
    import json

    from pydantic import ValidationError

    from career_lab.contracts.v2 import ProtocolError

    with pytest.raises((ValidationError, ProtocolError)):
        decode_engineer_document("EngineerSubmission", json.dumps(submission_payload() | change))


def test_engineer_04_submission_binds_trusted_pack_and_config_bytes(tmp_path: Path) -> None:
    import json

    from career_lab.contracts.v2 import FileRef, ProtocolError
    from career_lab.contracts.v2.engineer import validate_submission_files

    def file(name: str, value: dict[str, JsonValue]) -> FileRef:
        raw = json.dumps(value).encode()
        (tmp_path / name).write_bytes(raw)
        return FileRef(path=name, sha256=hashlib.sha256(raw).hexdigest())

    config = json.loads((FREEZE / "AssistantConfig.json").read_text())
    base = file("baseline.json", config)
    candidate = file("candidate.json", config | {"update_strategy": "realtime"})
    pack = json.loads((FREEZE / "EngineerPack.json").read_text())
    pack["config"] = {
        "session_id": config["session_id"],
        "kind": "config",
        "object_id": config["id"],
        "version": config["version"],
        "config_version": config["config_version"],
    }
    pack_ref = file("pack.json", pack)
    payload = submission_payload() | {
        "pack": pack_ref.model_dump(mode="json"),
        "config": candidate.model_dump(mode="json"),
        "base_config_hash": base.sha256,
        "regression_report": None,
    }
    record = decode_engineer_document("EngineerSubmission", json.dumps(payload))
    parsed = validate_submission_files(tmp_path, record, expected_pack=pack_ref, baseline=base)
    assert parsed.update_strategy == "realtime"
    wrong = record.model_copy(update={"base_config_hash": "0" * 64})
    with pytest.raises(ProtocolError, match="engineer base config mismatch"):
        validate_submission_files(tmp_path, wrong, expected_pack=pack_ref, baseline=base)
    with pytest.raises(ProtocolError, match="engineer pack mismatch"):
        validate_submission_files(tmp_path, record, expected_pack=base, baseline=base)
    (tmp_path / "candidate.json").write_text("{}")
    with pytest.raises(ProtocolError, match="file hash mismatch"):
        validate_submission_files(tmp_path, record, expected_pack=pack_ref, baseline=base)


def review_input() -> EngineerReviewInput:
    from career_lab.contracts.v2 import EffectiveConfig
    from career_lab.contracts.v2.engineer import EngineerReviewInput
    from career_lab.contracts.v2.examples import sample_model

    ref = {"path": "fixed.json", "sha256": "a" * 64}
    return EngineerReviewInput(
        contract_version="engineer-review-v1",
        pack=ref,
        baseline_config=ref,
        config=ref,
        scenario=ref,
        probe_suite=ref,
        reviewer_version=ref,
        resource_snapshot=ref,
        submission={"path": "submission.json", "sha256": "c" * 64},
        probe_ids=("public-1",),
        source_as_of={"business_seq": 4, "workspace_revision": 2, "storage_revision": 7},
        resolved_config=sample_model(EffectiveConfig),
        work_language="en",
        model=None,
    )


def test_engineer_06_review_identity_binds_every_fixed_input() -> None:
    from career_lab.contracts.v2 import digest

    original = review_input()
    for name in (
        "pack",
        "baseline_config",
        "config",
        "scenario",
        "probe_suite",
        "reviewer_version",
        "resource_snapshot",
        "submission",
    ):
        changed = original.model_copy(
            update={name: getattr(original, name).model_copy(update={"sha256": "b" * 64})}
        )
        assert digest(changed) != digest(original)
    assert digest(original.model_copy(update={"work_language": "zh"})) != digest(original)
    changed = original.resolved_config.model_copy(
        update={
            "effective": original.resolved_config.effective.model_copy(
                update={"update_strategy": "realtime"}
            )
        }
    )
    assert digest(original.model_copy(update={"resolved_config": changed})) != digest(original)
    requested = original.resolved_config.requested.model_copy(
        update={"participants": original.resolved_config.requested.participants + 1}
    )
    changed_requested = original.resolved_config.model_copy(update={"requested": requested})
    assert digest(original.model_copy(update={"resolved_config": changed_requested})) != digest(
        original
    )
    changed_point = original.source_as_of.model_copy(
        update={"business_seq": original.source_as_of.business_seq + 1}
    )
    assert digest(original.model_copy(update={"source_as_of": changed_point})) != digest(original)
    from career_lab.contracts.v2 import FileRef

    model = FileRef(path="evaluation-model.json", sha256="d" * 64)
    assert digest(original.model_copy(update={"model": model})) != digest(original)


def report_payload() -> dict[str, JsonValue]:
    from career_lab.contracts.v2 import TestResultV2, digest
    from career_lab.contracts.v2.examples import sample_model

    fixed = review_input()
    actual = sample_model(TestResultV2).model_dump(mode="json")
    actual["config"] = fixed.resolved_config.model_dump(mode="json")
    actual["as_of"] = fixed.source_as_of.model_dump(mode="json")
    actual["query"] = "public question"
    return {
        "contract_version": "engineer-review-v1",
        "id": "review-1",
        "submission": {"path": "submission.json", "sha256": "c" * 64},
        "input": fixed.model_dump(mode="json"),
        "input_hash": digest(fixed),
        "reviewer": {"id": "review-service", "kind": "system"},
        "created_at": "2026-10-09T00:00:00Z",
        "status": "verified",
        "claim_check": "not_provided",
        "results": [
            {
                "probe_id": "public-1",
                "visibility": "public",
                "query": "public question",
                "expected": {"status": "answered"},
                "actual": actual,
                "result": "pass",
                "elapsed_seconds": 0.01,
                "config_hash": digest(fixed.resolved_config.effective),
            }
        ],
        "findings": [],
        "unresolved": [],
        "advice": {"status": "waiting_model", "text": None, "model": None},
    }


def test_engineer_07_report_roundtrip_and_input_hash_check() -> None:
    import json

    from pydantic import ValidationError

    value = report_payload()
    report = decode_engineer_document("RegressionReport", json.dumps(value))
    assert report.results[0].actual.query == "public question"
    assert report.results[0].elapsed_seconds == 0.01
    assert report.advice.status == "waiting_model"
    with pytest.raises(ValidationError, match="input hash"):
        decode_engineer_document("RegressionReport", json.dumps(value | {"input_hash": "0" * 64}))
    with pytest.raises(ValidationError, match="duplicate probe"):
        decode_engineer_document(
            "RegressionReport", json.dumps(value | {"results": value["results"] * 2})
        )


def test_engineer_08_public_report_never_contains_hidden_probe_details() -> None:
    import copy
    import json

    from career_lab.contracts.v2.engineer import public_engineer_report

    value = report_payload()
    hidden = copy.deepcopy(value["results"][0])
    hidden.update(probe_id="secret-probe", visibility="hidden", query="hidden question")
    hidden["actual"]["query"] = "hidden question"
    hidden["actual"]["answer"] = "hidden answer"
    hidden["expected"]["contains"] = ["hidden gold"]
    value["results"].append(hidden)
    value["input"]["probe_ids"].append("secret-probe")
    from career_lab.contracts.v2 import digest
    from career_lab.contracts.v2.engineer import EngineerReviewInput

    value["input_hash"] = digest(EngineerReviewInput.model_validate(value["input"]))
    value["findings"] = [
        {
            "kind": "target_fix",
            "status": "pass",
            "visibility": "hidden",
            "description": "hidden explanation",
            "probe_ids": ["secret-probe"],
        }
    ]
    report = decode_engineer_document("RegressionReport", json.dumps(value))
    public = public_engineer_report(report)
    rendered = public.model_dump_json()
    assert public.hidden.passed == 1
    assert len(public.public_results) == 1
    for secret in (
        "secret-probe",
        "hidden question",
        "hidden answer",
        "hidden gold",
        "hidden explanation",
        "resource_snapshot",
    ):
        assert secret not in rendered
    assert "public question" in rendered


@pytest.mark.parametrize(
    "status,claim,result",
    [
        ("verified", "mismatch", "pass"),
        ("verified", "unverified", "pass"),
        ("verified", "matched", "error"),
        ("report_mismatch", "matched", "pass"),
        ("incomplete", "matched", "pass"),
    ],
)
def test_engineer_09_false_completed_and_mismatch_states_rejected(
    status: str, claim: str, result: str
) -> None:
    import json

    from pydantic import ValidationError

    value = report_payload() | {"status": status, "claim_check": claim}
    value["results"][0]["result"] = result
    if result == "error":
        value["results"][0].update(actual=None, error_code="provider_failed")
    with pytest.raises(ValidationError):
        decode_engineer_document("RegressionReport", json.dumps(value))


def test_engineer_09_mismatch_and_transport_failure_keep_separate_noncompleted_states() -> None:
    import json

    value = report_payload() | {"status": "report_mismatch", "claim_check": "mismatch"}
    mismatch = decode_engineer_document("RegressionReport", json.dumps(value))
    assert mismatch.status == "report_mismatch"
    value.update(status="incomplete", claim_check="unverified")
    value["results"][0].update(result="error", actual=None, error_code="provider_failed")
    failed = decode_engineer_document("RegressionReport", json.dumps(value))
    assert failed.results[0].error_code == "provider_failed"


def test_engineer_claim_report_is_typed_and_bound_to_candidate() -> None:
    from pydantic import ValidationError

    from career_lab.contracts.v2.engineer import EngineerClaimedReport

    ref = {"path": "candidate.json", "sha256": "a" * 64}
    payload = {
        "contract_version": "engineer-review-v1",
        "id": "declared-1",
        "pack": ref,
        "config": ref,
        "created_at": "2026-10-09T00:00:00Z",
        "results": [{"probe_id": "public-1", "result": "pass"}],
    }
    report = EngineerClaimedReport.model_validate(payload)
    assert report.results[0].result == "pass"
    with pytest.raises(ValidationError):
        EngineerClaimedReport.model_validate(payload | {"results": payload["results"] * 2})


def test_engineer_10_generated_contracts_types_and_examples_are_deterministic(
    tmp_path: Path,
) -> None:
    import json

    from career_lab.contracts.v2.engineer_export import export_engineer_protocol

    first = export_engineer_protocol(tmp_path / "first")
    second = export_engineer_protocol(tmp_path / "second")
    assert first == second
    for relative, sha in first["files"].items():
        a, b = tmp_path / "first" / relative, tmp_path / "second" / relative
        assert a.read_bytes() == b.read_bytes()
        assert hashlib.sha256(a.read_bytes()).hexdigest() == sha
    api = json.loads((tmp_path / "first/openapi.json").read_text())
    assert api["paths"] == {}  # CLI file contracts do not advertise an unimplemented HTTP route.
    assert "EngineerRegressionReport" in api["components"]["schemas"]
    types = (tmp_path / "first/types.ts").read_text()
    assert "export type EngineerSubmissionRecord" in types
    assert "any" not in types.split()


def test_engineer_review_cannot_omit_suite_members_or_change_submission_identity() -> None:
    import json

    from pydantic import ValidationError

    from career_lab.contracts.v2 import digest

    value = report_payload()
    value["input"]["probe_ids"] = ["public-1", "required-2"]
    value["input"]["submission"] = value["submission"]
    from career_lab.contracts.v2.engineer import EngineerReviewInput

    value["input_hash"] = digest(EngineerReviewInput.model_validate(value["input"]))
    with pytest.raises(ValidationError, match="suite members"):
        decode_engineer_document("RegressionReport", json.dumps(value))


def test_engineer_published_freeze_matches_all_production_models_and_resolves_refs() -> None:
    import json

    from career_lab.contracts.v2 import engineer
    from career_lab.contracts.v2.engineer_examples import engineer_examples
    from career_lab.contracts.v2.engineer_export import export_engineer_protocol

    root = Path(__file__).resolve().parents[2] / "docs/contracts/engineer-review-v1"
    manifest = export_engineer_protocol(root)
    examples = engineer_examples()
    names = {
        name
        for name, value in vars(engineer).items()
        if isinstance(value, type) and value.__module__ == engineer.__name__
    }
    assert set(examples) == names
    for name, example in examples.items():
        assert (
            type(example).model_validate_json((root / "examples" / (name + ".json")).read_bytes())
            == example
        )
        assert (
            json.loads((root / "schemas" / (name + ".json")).read_text())
            == type(example).model_json_schema()
        )
    api = json.loads((root / "openapi.json").read_text())

    def check(value: object) -> None:
        if isinstance(value, dict):
            if "$ref" in value:
                found = api
                for part in value["$ref"].split("/")[1:]:
                    found = found[part]
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(api)
    assert manifest["protocol"] == "engineer-review-v1"


def test_engineer_actual_probe_cannot_use_a_different_source_point() -> None:
    from pydantic import ValidationError

    from career_lab.contracts.v2.engineer import EngineerRegressionReport

    value = report_payload()
    value["results"][0]["actual"]["as_of"]["business_seq"] += 1
    with pytest.raises(ValidationError, match="probe actual input mismatch"):
        EngineerRegressionReport.model_validate(value)


def test_engineer_hidden_only_public_report_keeps_applicability_without_details() -> None:
    from career_lab.contracts.v2 import digest
    from career_lab.contracts.v2.engineer import EngineerRegressionReport, public_engineer_report

    value = report_payload()
    value["results"][0]["visibility"] = "hidden"
    report = EngineerRegressionReport.model_validate(value)
    public = public_engineer_report(report)
    assert not public.public_results
    assert public.applicability.scenario.sha256 == report.input.scenario.sha256
    assert public.applicability.scenario.kind == "scenario"
    assert public.applicability.probe_suite_hash == report.input.probe_suite.sha256
    assert public.applicability.config.sha256 == report.input.config.sha256
    assert public.applicability.config.kind == "configuration"
    assert public.applicability.effective_config_hash == digest(
        report.input.resolved_config.effective
    )
    assert public.applicability.source_as_of == report.input.source_as_of
    assert "public question" not in public.model_dump_json()


@pytest.mark.parametrize(
    "case",
    [
        "hidden_errors",
        "mismatch",
        "unverified",
        "public_error",
        "duplicate",
        "false_mismatch",
        "false_incomplete",
    ],
)
def test_public_report_direct_decode_rejects_contradictory_completion(case: str) -> None:
    from pydantic import ValidationError

    from career_lab.contracts.v2.engineer import EngineerPublicReport
    from career_lab.contracts.v2.engineer_examples import engineer_examples

    value = engineer_examples()["EngineerPublicReport"].model_dump(mode="json")
    if case == "hidden_errors":
        value["hidden"]["errors"] = 1
    elif case in {"mismatch", "unverified"}:
        value["claim_check"] = case
    elif case == "public_error":
        value["public_results"][0]["result"] = "error"
    elif case == "duplicate":
        value["public_results"] *= 2
    else:
        value["status"] = "report_mismatch" if case == "false_mismatch" else "incomplete"
    with pytest.raises(ValidationError):
        EngineerPublicReport.model_validate_json(canonical(value))


@pytest.mark.parametrize(
    "status,claim,errors,result,hidden_only",
    [
        ("verified", "not_provided", 0, "pass", False),
        ("verified", "matched", 0, "fail", False),
        ("report_mismatch", "mismatch", 0, "fail", False),
        ("incomplete", "unverified", 0, "pass", False),
        ("incomplete", "matched", 1, "pass", False),
        ("incomplete", "mismatch", 1, "error", False),
        ("verified", "matched", 0, "pass", True),
        ("report_mismatch", "mismatch", 0, "fail", True),
        ("incomplete", "unverified", 1, "error", True),
    ],
)
def test_public_report_direct_decode_keeps_consistent_and_hidden_only_summaries(
    status: str,
    claim: str,
    errors: int,
    result: str,
    hidden_only: bool,
) -> None:
    from career_lab.contracts.v2.engineer import EngineerPublicReport
    from career_lab.contracts.v2.engineer_examples import engineer_examples

    value = engineer_examples()["EngineerPublicReport"].model_dump(mode="json")
    value.update(status=status, claim_check=claim)
    value["hidden"] = {"passed": 1, "failed": 1, "errors": errors}
    value["public_results"][0]["result"] = result
    if hidden_only:
        value.update(public_results=[], findings=[], unresolved=[])
    parsed = EngineerPublicReport.model_validate_json(canonical(value))
    assert parsed.status == status and parsed.claim_check == claim
    assert parsed.hidden.passed == 1 and parsed.hidden.failed == 1
    assert bool(parsed.public_results) is not hidden_only


def test_public_projection_keeps_prose_file_names_and_quote_text_out_of_shared_dto() -> None:
    from career_lab.contracts.v2 import digest
    from career_lab.contracts.v2.engineer import EngineerRegressionReport, public_engineer_report

    marker = "PRIVATE-FREE-TEXT-AND-FILE-METADATA"
    value = report_payload()
    for field in ("config", "scenario", "submission"):
        value["input"][field].update(path=marker + ".json", media_type=marker)
    value["submission"] = value["input"]["submission"]
    value["results"][0]["actual"]["answer"] = marker
    for reference in value["results"][0]["actual"]["citations"]:
        reference["quote"] = marker
    value["findings"] = [
        {
            "kind": "target_fix",
            "status": "pass",
            "visibility": "public",
            "description": marker,
            "probe_ids": ["public-1"],
        }
    ]
    value["unresolved"] = [{"id": marker, "description": marker, "visibility": "public"}]
    value["advice"] = {
        "status": "success",
        "text": marker,
        "visibility": "public",
        "model": {"path": marker + ".json", "sha256": "e" * 64, "media_type": marker},
    }
    value["input"]["model"] = value["advice"]["model"]
    value["input_hash"] = digest(EngineerReviewInput.model_validate(value["input"]))
    report = EngineerRegressionReport.model_validate(value)
    private_before = report.model_dump_json()
    public = public_engineer_report(report)
    assert marker not in public.model_dump_json()
    assert report.model_dump_json() == private_before
    assert marker in private_before
    assert public.public_results[0].query == "public question"
    assert public.applicability.config.sha256 == report.input.config.sha256


@pytest.mark.parametrize("model", [None, {"kind": "configuration", "sha256": "a" * 64}])
def test_public_advice_success_requires_a_model_identity(
    model: dict[str, JsonValue] | None,
) -> None:
    from pydantic import ValidationError

    from career_lab.contracts.v2.engineer import EngineerPublicAdvice

    with pytest.raises(ValidationError):
        EngineerPublicAdvice.model_validate({"status": "success", "model": model})
    valid = EngineerPublicAdvice.model_validate(
        {
            "status": "success",
            "model": {"kind": "model", "sha256": "a" * 64},
        }
    )
    assert valid.model.sha256 == "a" * 64 and valid.text is None
