"""Test the guard itself against false-green reports and modified release inputs."""

from pathlib import Path

import pytest

from scripts.regression.compare import backend_results, frontend_results, regressions


def test_test_id_comparison_rejects_missing_failures_and_new_skips() -> None:
    baseline = {"same": "passed", "lost": "passed", "allowed": "skipped"}
    current = {"same": "skipped", "new": "skipped", "broken": "failure", "allowed": "skipped"}
    assert regressions(baseline, current) == [
        "failed: broken",
        "missing: lost",
        "new skip or changed outcome: new",
        "new skip or changed outcome: same",
    ]
    assert regressions(baseline, {**baseline, "added": "passed"}) == []


def test_duplicate_or_empty_backend_report_cannot_hide_a_missing_test(tmp_path: Path) -> None:
    report = tmp_path / "report.xml"
    report.write_text(
        '<testsuite><testcase classname="a" name="b"/>'
        '<testcase classname="a" name="b"/></testsuite>'
    )
    with pytest.raises(ValueError, match="Duplicate"):
        backend_results(report)
    report.write_text("<testsuite/>")
    with pytest.raises(ValueError, match="Empty"):
        backend_results(report)


def test_frontend_runtime_failure_cannot_look_like_empty_success(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text('{"testResults": [], "numRuntimeErrorTestSuites": 1}')
    with pytest.raises(ValueError, match="incomplete"):
        frontend_results(report)
