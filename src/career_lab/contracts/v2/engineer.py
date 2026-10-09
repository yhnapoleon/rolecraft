"""Versioned engineer file protocol, independent of the frozen legacy namespace."""

import json
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .core import (
    V2,
    Executor,
    FileRef,
    Hash,
    Identifier,
    ProtocolError,
    Timestamp,
    VersionPoint,
    digest,
    read_file,
)
from .research import EngineerPack, EngineerSubmission, RegressionReport
from .world import AssistantConfig, EffectiveConfig, TestResultV2

DocumentKind = Literal["EngineerPack", "EngineerSubmission", "RegressionReport"]
LEGACY_MODELS: dict[str, type[V2]] = {
    "EngineerPack": EngineerPack,
    "EngineerSubmission": EngineerSubmission,
    "RegressionReport": RegressionReport,
}


class EngineerUnresolvedItem(V2):
    id: Identifier
    description: str
    visibility: Literal["public", "hidden"] = "public"
    probe_ids: tuple[Identifier, ...] = ()


class EngineerSubmissionRecord(V2):
    contract_version: Literal["engineer-review-v1"]
    id: Identifier
    pack: FileRef
    config: FileRef
    base_config_hash: Hash
    regression_report: FileRef | None
    unresolved: tuple[EngineerUnresolvedItem, ...]
    explanation: str
    executor: Executor
    created_at: Timestamp
    work_language: Literal["zh", "en"]


REVIEW_MODELS: dict[str, type[V2]] = {"EngineerSubmission": EngineerSubmissionRecord}


def decode_engineer_document(kind: DocumentKind, raw: bytes | str) -> V2:
    """Parse the original records without adding defaults to their identity."""
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ProtocolError("engineer_document_invalid")
    if "contract_version" not in value:
        return LEGACY_MODELS[kind].model_validate(value)
    if value["contract_version"] != "engineer-review-v1" or kind not in REVIEW_MODELS:
        raise ProtocolError("engineer_contract_version_unsupported")
    return REVIEW_MODELS[kind].model_validate(value)


def validate_submission_files(
    root: Path,
    submission: EngineerSubmissionRecord,
    *,
    expected_pack: FileRef,
    baseline: FileRef,
) -> AssistantConfig:
    """Validate bytes against trusted pack metadata; this does not grant access or run probes.

    The caller must authenticate the owner and derive both references from the
    authorized original pack, never from candidate-supplied metadata.
    """
    if submission.pack != expected_pack:
        raise ProtocolError("engineer_pack_mismatch", status=409)
    if submission.base_config_hash != baseline.sha256:
        raise ProtocolError("engineer_base_config_mismatch", status=409)
    pack = EngineerPack.model_validate_json(read_file(root, expected_pack))
    original = AssistantConfig.model_validate_json(read_file(root, baseline))
    if (
        pack.config.session_id != original.session_id
        or pack.config.object_id != original.id
        or pack.config.version != original.version
        or pack.config.config_version != original.config_version
    ):
        raise ProtocolError("engineer_base_config_mismatch", status=409)
    candidate = AssistantConfig.model_validate_json(read_file(root, submission.config))
    if candidate.session_id != original.session_id or candidate.id != original.id:
        raise ProtocolError("engineer_candidate_identity_mismatch", status=409)
    if submission.regression_report is not None:
        claimed = EngineerClaimedReport.model_validate_json(
            read_file(root, submission.regression_report)
        )
        if claimed.pack != submission.pack or claimed.config != submission.config:
            raise ProtocolError("engineer_claim_identity_mismatch", status=409)
    return candidate


class EngineerReviewInput(V2):
    """Canonical digest of this entire object is the immutable review input hash."""

    contract_version: Literal["engineer-review-v1"]
    pack: FileRef
    baseline_config: FileRef
    config: FileRef
    scenario: FileRef
    probe_suite: FileRef
    reviewer_version: FileRef
    resource_snapshot: FileRef
    submission: FileRef
    probe_ids: tuple[Identifier, ...] = Field(min_length=1)
    source_as_of: VersionPoint
    resolved_config: EffectiveConfig
    work_language: Literal["zh", "en"]
    model: FileRef | None


class EngineerProbeExpectation(V2):
    status: Literal["answered", "answered_with_warning", "fallback", "failed"]
    error_code: Identifier | None = None
    contains: tuple[str, ...] = ()
    citation_versions: dict[str, int] = {}
    effective_update_strategy: Literal["daily", "realtime", "manual_policy"] | None = None


class EngineerProbeResult(V2):
    probe_id: Identifier
    visibility: Literal["public", "hidden"]
    query: str
    expected: EngineerProbeExpectation
    actual: TestResultV2 | None
    result: Literal["pass", "fail", "error"]
    config_hash: Hash
    elapsed_seconds: Annotated[float, Field(ge=0)]
    error_code: Identifier | None = None


class EngineerFinding(V2):
    kind: Literal["target_fix", "new_regression", "claim_consistency", "unresolved"]
    status: Literal["pass", "fail", "unverified"]
    visibility: Literal["public", "hidden"]
    description: str
    probe_ids: tuple[Identifier, ...] = ()


class EngineerAdvice(V2):
    status: Literal["waiting_model", "success", "unavailable", "invalid", "timeout"]
    text: str | None
    model: FileRef | None
    affects_score: Literal[False] = False
    visibility: Literal["public", "hidden"] = "hidden"

    @model_validator(mode="after")
    def grounded_status(self) -> Self:
        if self.status == "success" and (not self.text or self.model is None):
            raise ValueError("successful advice requires text and model identity")
        if self.status != "success" and self.text is not None:
            raise ValueError("unavailable advice cannot invent text")
        return self


ReviewStatus = Literal["verified", "report_mismatch", "incomplete"]
ClaimCheck = Literal["matched", "mismatch", "not_provided", "unverified"]


def verification_status(claim_check: ClaimCheck, *, has_errors: bool) -> ReviewStatus:
    """Completion is execution plus claim comparison; business failures remain valid results."""
    if has_errors or claim_check == "unverified":
        return "incomplete"
    return "report_mismatch" if claim_check == "mismatch" else "verified"


class EngineerRegressionReport(V2):
    contract_version: Literal["engineer-review-v1"]
    id: Identifier
    submission: FileRef
    input: EngineerReviewInput
    input_hash: Hash
    reviewer: Executor
    created_at: Timestamp
    status: ReviewStatus
    claim_check: ClaimCheck
    results: tuple[EngineerProbeResult, ...] = Field(min_length=1)
    findings: tuple[EngineerFinding, ...]
    unresolved: tuple[EngineerUnresolvedItem, ...]
    advice: EngineerAdvice

    @model_validator(mode="after")
    def consistent_input(self) -> Self:
        if self.input_hash != digest(self.input):
            raise ValueError("review input hash mismatch")
        if self.submission != self.input.submission:
            raise ValueError("review submission identity mismatch")
        ids = [row.probe_id for row in self.results]
        if set(ids) != set(self.input.probe_ids) or len(self.input.probe_ids) != len(
            set(self.input.probe_ids)
        ):
            raise ValueError("review must account for all suite members exactly once")
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate probe result")
        errors = any(row.result == "error" for row in self.results)
        expected_status = verification_status(self.claim_check, has_errors=errors)
        if self.status != expected_status:
            raise ValueError("report status disagrees with verification outcome")
        for row in self.results:
            if row.config_hash != digest(self.input.resolved_config.effective):
                raise ValueError("probe config hash mismatch")
            if row.result == "error":
                if row.error_code is None:
                    raise ValueError("probe error requires a failure code")
            elif row.actual is None or row.error_code is not None:
                raise ValueError("completed probe requires actual behavior and no execution error")
            if row.actual is not None and (
                row.actual.config != self.input.resolved_config
                or row.actual.query != row.query
                or row.actual.as_of != self.input.source_as_of
            ):
                raise ValueError("probe actual input mismatch")
        for finding in self.findings:
            if not set(finding.probe_ids) <= set(ids):
                raise ValueError("finding references missing probe")
        return self


REVIEW_MODELS["RegressionReport"] = EngineerRegressionReport


class EngineerProbeSummary(V2):
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    errors: int = Field(ge=0)


class EngineerReportApplicability(V2):
    scenario: FileRef
    config: FileRef
    base_config_hash: Hash
    probe_suite_hash: Hash
    reviewer_version_hash: Hash
    effective_config_hash: Hash
    source_as_of: VersionPoint


class EngineerPublicReport(V2):
    contract_version: Literal["engineer-review-v1"]
    id: Identifier
    submission: FileRef
    input_hash: Hash
    reviewer: Executor
    created_at: Timestamp
    work_language: Literal["zh", "en"]
    status: ReviewStatus
    claim_check: ClaimCheck
    applicability: EngineerReportApplicability
    public_results: tuple[EngineerProbeResult, ...]
    hidden: EngineerProbeSummary
    findings: tuple[EngineerFinding, ...]
    unresolved: tuple[EngineerUnresolvedItem, ...]
    advice: EngineerAdvice | None
    affects_score: Literal[False] = False

    @model_validator(mode="after")
    def public_only(self) -> Self:
        rows = (*self.public_results, *self.findings, *self.unresolved)
        if any(row.visibility != "public" for row in rows):
            raise ValueError("hidden records cannot enter a public report")
        if self.advice is not None and self.advice.visibility != "public":
            raise ValueError("hidden advice cannot enter a public report")
        probe_ids = [row.probe_id for row in self.public_results]
        if len(probe_ids) != len(set(probe_ids)):
            raise ValueError("duplicate public probe result")
        expected_status = verification_status(
            self.claim_check,
            has_errors=self.hidden.errors > 0
            or any(row.result == "error" for row in self.public_results),
        )
        if self.status != expected_status:
            raise ValueError("report status disagrees with verification outcome")
        ids = set(probe_ids)
        if any(not set(row.probe_ids) <= ids for row in (*self.findings, *self.unresolved)):
            raise ValueError("public finding references a non-public probe")
        return self


def public_engineer_report(report: EngineerRegressionReport) -> EngineerPublicReport:
    """Whitelist projection; private fixed inputs and hidden probe identities stay trusted."""
    public = tuple(row for row in report.results if row.visibility == "public")
    ids = {row.probe_id for row in public}
    hidden = tuple(row for row in report.results if row.visibility == "hidden")
    return EngineerPublicReport(
        contract_version=report.contract_version,
        id=report.id,
        submission=report.submission,
        input_hash=report.input_hash,
        reviewer=report.reviewer,
        created_at=report.created_at,
        work_language=report.input.work_language,
        status=report.status,
        claim_check=report.claim_check,
        applicability=EngineerReportApplicability(
            scenario=report.input.scenario,
            config=report.input.config,
            base_config_hash=report.input.baseline_config.sha256,
            probe_suite_hash=report.input.probe_suite.sha256,
            reviewer_version_hash=report.input.reviewer_version.sha256,
            effective_config_hash=digest(report.input.resolved_config.effective),
            source_as_of=report.input.source_as_of,
        ),
        public_results=public,
        hidden=EngineerProbeSummary(
            passed=sum(row.result == "pass" for row in hidden),
            failed=sum(row.result == "fail" for row in hidden),
            errors=sum(row.result == "error" for row in hidden),
        ),
        findings=tuple(
            row
            for row in report.findings
            if row.visibility == "public" and set(row.probe_ids) <= ids
        ),
        unresolved=tuple(
            row
            for row in report.unresolved
            if row.visibility == "public" and set(row.probe_ids) <= ids
        ),
        advice=report.advice if report.advice.visibility == "public" else None,
    )


class EngineerProbeClaim(V2):
    probe_id: Identifier
    result: Literal["pass", "fail", "error"]


class EngineerClaimedReport(V2):
    contract_version: Literal["engineer-review-v1"]
    id: Identifier
    pack: FileRef
    config: FileRef
    created_at: Timestamp
    results: tuple[EngineerProbeClaim, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_probes(self) -> Self:
        ids = [row.probe_id for row in self.results]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate claimed probe")
        return self
