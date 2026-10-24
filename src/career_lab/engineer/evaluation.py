"""E1-E4 rule conclusions from a trusted review; E5 waits for a model. Pure: no I/O.

Inputs come from the private review store. Only public probe IDs, hidden counts,
configuration field names and authored reason codes reach the output.
"""

import hashlib
from collections.abc import Iterable

from pydantic import JsonValue
from pydantic_core import to_jsonable_python

from career_lab.contracts.v2 import AssistantConfig
from career_lab.contracts.v2.engineer import (
    CHANGE_FIELDS,
    EngineerChangeClaim,
    EngineerClaimedReport,
    EngineerProbeResult,
    EngineerRegressionReport,
    EngineerSubmissionRecord,
)
from career_lab.contracts.v2.engineer_evaluation import (
    RUBRIC_REVISION,
    CriterionId,
    EngineerCriterionConclusion,
    EngineerFieldCheck,
    EngineerRemainingPrecheck,
    EngineerRuleEvaluation,
    FieldCheckStatus,
    RubricLabel,
)

from .files import encode

Rows = dict[str, EngineerProbeResult]


def evaluate_review(
    report: EngineerRegressionReport,
    submission: EngineerSubmissionRecord,
    baseline: AssistantConfig,
    candidate: AssistantConfig,
    *,
    claimed: EngineerClaimedReport | None,
) -> EngineerRuleEvaluation:
    """Conclude E1-E5 for one review.

    `claimed` is the self-report the submission references (None when it references none).
    Inputs that are not the reviewed submission, configurations or self-report raise ValueError.
    """
    check_binding(report, submission, baseline, candidate, claimed)
    rows = {row.probe_id: row for row in report.results}
    return EngineerRuleEvaluation(
        rubric_revision=RUBRIC_REVISION,
        review_id=report.id,
        submission_hash=report.submission.sha256,
        criteria=(
            target_fixed(report, rows),
            no_regressions(report, rows),
            change_consistency(submission, baseline, candidate),
            reproducibility(report, rows, claimed),
            remaining_explanation(report, submission),
        ),
    )


def check_binding(
    report: EngineerRegressionReport,
    submission: EngineerSubmissionRecord,
    baseline: AssistantConfig,
    candidate: AssistantConfig,
    claimed: EngineerClaimedReport | None,
) -> None:
    if hashlib.sha256(encode(submission)).hexdigest() != report.submission.sha256:
        raise ValueError("submission is not the reviewed submission")
    if candidate != report.input.resolved_config.requested:
        raise ValueError("candidate configuration is not the reviewed candidate")
    if hashlib.sha256(encode(baseline)).hexdigest() != report.input.baseline_config.sha256:
        raise ValueError("baseline configuration is not the reviewed baseline")
    if (submission.regression_report is None) != (claimed is None):
        raise ValueError("claimed report must be given exactly when the submission references one")
    if claimed is not None and (
        claimed.pack != submission.pack or claimed.config != submission.config
    ):
        raise ValueError("claimed report is bound to another pack or configuration")


def rule(
    criterion: CriterionId,
    label: RubricLabel,
    reasons: Iterable[str],
    probes: tuple[tuple[str, ...], int] = ((), 0),
    checks: tuple[EngineerFieldCheck, ...] = (),
) -> EngineerCriterionConclusion:
    return EngineerCriterionConclusion(
        criterion=criterion,
        status="concluded",
        basis="rule",
        label=label,
        reason_codes=tuple(reasons),
        probe_ids=probes[0],
        hidden_probes=probes[1],
        field_checks=checks,
    )


def split(probe_ids: Iterable[str], rows: Rows) -> tuple[tuple[str, ...], int]:
    """Public IDs in first-seen order; hidden probes only as a count."""
    unique = tuple(dict.fromkeys(probe_ids))
    public = tuple(pid for pid in unique if rows[pid].visibility == "public")
    return public, len(unique) - len(public)


def target_fixed(report: EngineerRegressionReport, rows: Rows) -> EngineerCriterionConclusion:
    """Each pack target with a matching trusted probe has one target_fix finding."""
    criterion: CriterionId = "E1.target_fixed"
    findings = [f for f in report.findings if f.kind == "target_fix"]
    if not findings:
        # The reviewer records at least one target finding per pack target.
        return rule(criterion, "NOT_APPLICABLE", ["no_targets"])
    probed = [f for f in findings if f.probe_ids]
    unverified = [pid for f in probed if f.status == "unverified" for pid in f.probe_ids]
    reasons = []
    if len(probed) != len(findings):
        reasons.append("target_without_trusted_probe")
    if any(rows[pid].result == "error" for pid in unverified):
        reasons.append("target_verification_incomplete")
    if any(rows[pid].result != "error" for pid in unverified):
        # The original configuration did not fail this target under the frozen suite.
        reasons.append("target_baseline_not_failing")
    if reasons:
        return rule(criterion, "INSUFFICIENT", reasons, split(unverified, rows))
    passed = [pid for f in probed if f.status == "pass" for pid in f.probe_ids]
    failed = [pid for f in probed if f.status == "fail" for pid in f.probe_ids]
    if not failed:
        return rule(criterion, "MET", ["targets_repaired"], split(passed, rows))
    if passed:
        return rule(criterion, "PARTIAL", ["targets_partially_repaired"], split(failed, rows))
    return rule(criterion, "NOT_MET", ["targets_not_repaired"], split(failed, rows))


def no_regressions(report: EngineerRegressionReport, rows: Rows) -> EngineerCriterionConclusion:
    """Binary: a verified new failure, public or hidden, is never offset by target repairs."""
    criterion: CriterionId = "E2.no_regressions"
    findings = [f for f in report.findings if f.kind == "new_regression"]
    failed = [pid for f in findings if f.status == "fail" for pid in f.probe_ids]
    if failed:
        return rule(criterion, "NOT_MET", ["new_failures_found"], split(failed, rows))
    compared = {pid for f in findings if f.status == "pass" for pid in f.probe_ids}
    incomplete = [pid for pid, row in rows.items() if pid not in compared or row.result == "error"]
    if incomplete:
        return rule(
            criterion, "INSUFFICIENT", ["regression_coverage_incomplete"], split(incomplete, rows)
        )
    return rule(criterion, "MET", ["no_new_failures"])


def same_json(left: JsonValue, right: JsonValue) -> bool:
    """JSON equality: numbers by value, booleans never equal to numbers, lists in order."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, int | float) and isinstance(right, int | float):
        return left == right
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(map(same_json, left, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(same_json(left[k], right[k]) for k in left)
    return type(left) is type(right) and left == right


def setting(config: AssistantConfig, name: str) -> JsonValue:
    return to_jsonable_python(getattr(config, name))


def field_status(
    claim: EngineerChangeClaim, before: JsonValue, after: JsonValue
) -> FieldCheckStatus:
    claimed_before, claimed_after = (
        to_jsonable_python(claim.before),
        to_jsonable_python(claim.after),
    )
    claims_change = not same_json(claimed_before, claimed_after)
    changed = not same_json(before, after)
    if claims_change and not changed:
        return "change_not_made"
    if changed and not claims_change:
        return "change_denied"
    before_ok, after_ok = same_json(claimed_before, before), same_json(claimed_after, after)
    if before_ok and after_ok:
        return "matched"
    if after_ok:
        return "before_mismatch"
    return "after_mismatch" if before_ok else "values_mismatch"


def change_consistency(
    submission: EngineerSubmissionRecord, baseline: AssistantConfig, candidate: AssistantConfig
) -> EngineerCriterionConclusion:
    """Structured claims against the submitted-vs-original diff of learner-editable settings.

    Free-text explanations are not interpreted; motivations are never judged.
    """
    criterion: CriterionId = "E3.change_consistency"
    if not submission.changes:
        return rule(criterion, "INSUFFICIENT", ["change_claims_not_provided"])
    claims = {claim.field: claim for claim in submission.changes}
    checks: list[EngineerFieldCheck] = []
    for name in CHANGE_FIELDS:
        before, after = setting(baseline, name), setting(candidate, name)
        if name in claims:
            checks.append(
                EngineerFieldCheck(field=name, status=field_status(claims[name], before, after))
            )
        elif not same_json(before, after):
            checks.append(EngineerFieldCheck(field=name, status="omitted"))
    statuses = {check.status for check in checks}
    if statuses - {"matched", "omitted"}:
        return rule(criterion, "NOT_MET", ["change_claims_contradicted"], checks=tuple(checks))
    if "omitted" in statuses:
        return rule(criterion, "PARTIAL", ["changes_omitted"], checks=tuple(checks))
    return rule(criterion, "MET", ["changes_match_diff"], checks=tuple(checks))


def reproducibility(
    report: EngineerRegressionReport, rows: Rows, claimed: EngineerClaimedReport | None
) -> EngineerCriterionConclusion:
    """The self-report against the official public results.

    The explicitly limited scope of a self-report is the set of probe IDs it lists. The known
    required scope is every public probe (hidden probes are never claimable). A report listing a
    strict subset, each listed result reproduced, is PARTIAL; any contradicted listed result, or
    a listed ID outside the public suite, is NOT_MET.
    """
    criterion: CriterionId = "E4.reproducibility"
    public = {pid: row.result for pid, row in rows.items() if row.visibility == "public"}
    if report.claim_check == "not_provided":
        return rule(criterion, "INSUFFICIENT", ["claim_not_provided"])
    if report.claim_check == "unverified":
        errors = [pid for pid, row in rows.items() if row.result == "error"]
        return rule(criterion, "INSUFFICIENT", ["verification_incomplete"], split(errors, rows))
    if claimed is None:
        raise ValueError("claimed report must be given exactly when the submission references one")
    declared = {row.probe_id: row.result for row in claimed.results}
    if report.claim_check == "matched":
        if declared != public:
            raise ValueError("claimed report disagrees with the review claim check")
        return rule(criterion, "MET", ["claim_reproduced"], (tuple(public), 0))
    contradicted = [pid for pid in public if pid in declared and declared[pid] != public[pid]]
    reasons = ["claim_contradicts_rerun"] if contradicted else []
    if set(declared) - set(public):
        reasons.append("claim_outside_public_suite")
    if reasons:
        return rule(criterion, "NOT_MET", reasons, (tuple(contradicted), 0))
    uncovered = tuple(pid for pid in public if pid not in declared)
    if not uncovered:
        raise ValueError("claimed report disagrees with the review claim check")
    return rule(criterion, "PARTIAL", ["claim_scope_partial"], (uncovered, 0))


def remaining_explanation(
    report: EngineerRegressionReport, submission: EngineerSubmissionRecord
) -> EngineerCriterionConclusion:
    """No semantic label without a model; the precheck names still-failing probes left unstated."""
    explained = {pid for item in submission.unresolved for pid in item.probe_ids}
    unexplained = [
        row for row in report.results if row.result == "fail" and row.probe_id not in explained
    ]
    return EngineerCriterionConclusion(
        criterion="E5.remaining_explanation",
        status="waiting_model",
        basis="semantic_advice",
        label=None,
        reason_codes=("waiting_model",),
        precheck=EngineerRemainingPrecheck(
            unexplained_probe_ids=tuple(
                row.probe_id for row in unexplained if row.visibility == "public"
            ),
            unexplained_hidden=sum(row.visibility == "hidden" for row in unexplained),
        ),
    )
