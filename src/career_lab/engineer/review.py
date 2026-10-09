"""Trusted local review with isolated execution and immutable public projection."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from career_lab.contracts import v2 as C
from career_lab.contracts.v2.engineer import (
    EngineerAdvice,
    EngineerClaimedReport,
    EngineerProbeResult,
    EngineerRegressionReport,
    public_engineer_report,
)
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.scenarios.v2.policy import effective_config
from career_lab.storage.v2_store import V2Store

from .execution import account_for_baseline_errors, execute_suite, interrupted_results
from .files import encode, publish
from .findings import claim_finding, compare_claim, regression_findings
from .review_inputs import ReviewContext, prepare_review
from .review_store import load_report, review_lock, save_report


def build_report(
    context: ReviewContext,
    auth: C.AuthContext,
    baseline: tuple[EngineerProbeResult, ...],
    candidate: tuple[EngineerProbeResult, ...],
) -> EngineerRegressionReport:
    inputs, record = context.input, context.submission
    results = account_for_baseline_errors(baseline, candidate)
    claimed = (
        EngineerClaimedReport.model_validate_json(context.files[record.regression_report.path])
        if record.regression_report is not None
        else None
    )
    check = compare_claim(claimed, results)
    status = "report_mismatch" if check == "mismatch" else "verified"
    if any(row.result == "error" for row in results):
        status = "incomplete"
    return EngineerRegressionReport(
        contract_version="engineer-review-v1",
        id="review-" + C.digest(inputs),
        submission=inputs.submission,
        input=inputs,
        input_hash=C.digest(inputs),
        reviewer=auth.executor,
        created_at=datetime.now(UTC),
        status=status,
        claim_check=check,
        results=results,
        findings=(
            claim_finding(check, inputs.work_language),
            *regression_findings(baseline, results, context.targets, inputs.work_language),
        ),
        unresolved=tuple(
            item.model_copy(update={"visibility": "hidden"}) for item in record.unresolved
        ),
        advice=EngineerAdvice(status="waiting_model", text=None, model=None, visibility="public"),
    )


def execute_review(
    module: ScenarioModule,
    auth: C.AuthContext,
    context: ReviewContext,
    first_attempt: bool,
) -> tuple[EngineerRegressionReport, dict[str, bytes]]:
    inputs, snapshot, probes = context.input, context.snapshot, context.probes
    baseline = C.AssistantConfig.model_validate_json(context.files["baseline.json"])
    candidate = inputs.resolved_config.requested
    identity = "review-" + C.digest(inputs)
    if first_attempt:
        baseline_results = execute_suite(
            module, snapshot, auth, baseline, probes, identity + "-base"
        )
        results = execute_suite(module, snapshot, auth, candidate, probes, identity)
    else:
        baseline_hash = C.digest(
            effective_config(module.package, baseline, snapshot.world.resources).effective
        )
        baseline_results = interrupted_results(probes, baseline_hash)
        results = interrupted_results(probes, C.digest(inputs.resolved_config.effective))
    report = build_report(context, auth, baseline_results, results)
    before, after = baseline.model_dump(mode="json"), candidate.model_dump(mode="json")
    return report, {
        "report.json": encode(report),
        "baseline-results.json": encode(baseline_results),
        "candidate-results.json": encode(results),
        "config-diff.json": encode(
            {
                key: {"before": before[key], "after": value}
                for key, value in after.items()
                if value != before[key]
            }
        ),
    }


def publish_public(output: Path, report: EngineerRegressionReport) -> dict[str, Any]:
    publish(output / report.id, {"report.json": encode(public_engineer_report(report))})
    return {
        "status": report.status,
        "review_id": report.id,
        "semantic_status": "waiting_model",
        "semantic_message": "等待模型接入"
        if report.input.work_language == "zh"
        else "Waiting for model integration",
    }


def review_configuration(
    store: V2Store,
    module: ScenarioModule,
    auth: C.AuthContext,
    pack_root: Path,
    submission_root: Path,
    output: Path,
    private_output: Path,
) -> dict[str, Any]:
    public_path, private_path = output.resolve(), private_output.resolve()
    if public_path == private_path or private_path.is_relative_to(public_path):
        raise C.ProtocolError("engineer_private_output_required")
    context = prepare_review(store, module, auth, pack_root, submission_root)
    identity = "review-" + C.digest(context.input)
    inputs_path, report_path = (
        private_output / "inputs" / identity,
        private_output / "reports" / identity,
    )
    with review_lock(private_output, identity):
        first_attempt = not inputs_path.exists()
        publish(inputs_path, context.files)
        if report_path.exists():
            report = load_report(report_path, context.input)
        else:
            report, files = execute_review(module, auth, context, first_attempt)
            save_report(report_path, files)
        return publish_public(output, report)
