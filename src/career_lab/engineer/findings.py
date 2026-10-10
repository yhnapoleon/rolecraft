"""Rule findings use trusted descriptions; original learner prose remains private."""

from typing import Literal

from career_lab.contracts.v2.engineer import (
    EngineerClaimedReport,
    EngineerFinding,
    EngineerProbeResult,
)

ClaimCheck = Literal["matched", "mismatch", "not_provided", "unverified"]
FindingStatus = Literal["pass", "fail", "unverified"]


def compare_claim(
    claimed: EngineerClaimedReport | None,
    results: tuple[EngineerProbeResult, ...],
) -> ClaimCheck:
    if claimed is None:
        return "not_provided"
    if any(row.result == "error" for row in results):
        return "unverified"
    actual = {row.probe_id: row.result for row in results if row.visibility == "public"}
    return "matched" if {r.probe_id: r.result for r in claimed.results} == actual else "mismatch"


def claim_finding(check: ClaimCheck, language: str) -> EngineerFinding:
    return EngineerFinding(
        kind="claim_consistency",
        status="pass" if check == "matched" else "fail" if check == "mismatch" else "unverified",
        visibility="public",
        description=(
            "Self-report compared with actual public probe results."
            if language == "en"
            else "自报与实际公开探针结果逐项核对。"
        ),
    )


def target_finding(
    previous: EngineerProbeResult,
    row: EngineerProbeResult,
    language: str,
) -> EngineerFinding:
    status: FindingStatus = "unverified"
    if previous.result == "fail" and row.result != "error":
        status = "pass" if row.result == "pass" else "fail"
    return EngineerFinding(
        kind="target_fix",
        visibility=row.visibility,
        probe_ids=(row.probe_id,),
        status=status,
        description=(
            "Target checked against the frozen suite expectation."
            if language == "en"
            else "目标问题按冻结探针预期核验。"
        ),
    )


def regression_finding(
    previous: EngineerProbeResult,
    row: EngineerProbeResult,
    language: str,
) -> EngineerFinding:
    status: FindingStatus = "pass"
    if "error" in {previous.result, row.result}:
        status = "unverified"
    elif previous.result == "pass" and row.result == "fail":
        status = "fail"
    return EngineerFinding(
        kind="new_regression",
        visibility=row.visibility,
        probe_ids=(row.probe_id,),
        status=status,
        description=(
            "Compared with the baseline under the same fixed conditions."
            if language == "en"
            else "与相同固定条件下的基线结果比较。"
        ),
    )


def unresolved_finding(row: EngineerProbeResult, language: str) -> EngineerFinding:
    error = row.result == "error"
    description = "核验未完成。" if error else "探针仍未通过。"
    if language == "en":
        description = "Verification unfinished." if error else "Probe remains unresolved."
    return EngineerFinding(
        kind="unresolved",
        visibility=row.visibility,
        probe_ids=(row.probe_id,),
        status="unverified" if error else "fail",
        description=description,
    )


def regression_findings(
    baseline: tuple[EngineerProbeResult, ...],
    actual: tuple[EngineerProbeResult, ...],
    target_queries: tuple[str, ...],
    language: str,
) -> tuple[EngineerFinding, ...]:
    originals = {row.probe_id: row for row in baseline}
    findings: list[EngineerFinding] = []
    for row in actual:
        previous = originals[row.probe_id]
        findings.append(regression_finding(previous, row, language))
        if row.query in target_queries:
            findings.append(target_finding(previous, row, language))
        if row.result != "pass":
            findings.append(unresolved_finding(row, language))
    if any(query not in {row.query for row in actual} for query in target_queries):
        findings.append(
            EngineerFinding(
                kind="target_fix",
                status="unverified",
                visibility="public",
                description=(
                    "Some target tests have no matching trusted suite expectation."
                    if language == "en"
                    else "部分目标测试没有匹配的可信探针预期，保留待核。"
                ),
            )
        )
    return tuple(findings)
