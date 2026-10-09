"""Regenerating the historical report preserves access to archived evidence."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_COMMIT = "2c07160b5e829ac08afb8a31667440bbda72df73"


def test_report_cli_keeps_archived_evidence_links(tmp_path: Path) -> None:
    run = tmp_path / "runs/controlled-v2"
    run.mkdir(parents=True)
    reports = tmp_path / "docs/reports"
    reports.mkdir(parents=True)
    for source, target in (
        ("controlled-v2-dev.json", "development.json"),
        ("controlled-v2-test.json", "confirmatory.json"),
    ):
        raw = subprocess.check_output(
            ["git", "show", f"{HISTORICAL_COMMIT}:docs/reports/{source}"], cwd=ROOT
        )
        (run / target).write_bytes(raw)
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/report_controlled_experiments.py")],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    report = (reports / "controlled-v2-results.md").read_text()
    for name in ("controlled-v2-dev.json", "controlled-v2-final-tests.xml"):
        url = (
            f"https://github.com/yhnapoleon/rolecraft/blob/{HISTORICAL_COMMIT}/docs/reports/{name}"
        )
        assert f"[{name}]({url})" in report
    assert (reports / "controlled-v2-comparison.csv").is_file()
