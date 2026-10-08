"""Candidate authoring must stay closed without trusted publication inputs."""

import json
import subprocess
import sys
from pathlib import Path


def run_validation(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "career_lab.scenario_compiler",
            "validate",
            "--declaration",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_SCN_01_cli_reports_missing_fields_without_publication(tmp_path: Path) -> None:
    declaration = tmp_path / "declaration.json"
    declaration.write_text("{}")
    result = run_validation(declaration)
    assert result.stdout.strip(), result.stderr
    report = json.loads(result.stdout)
    assert result.returncode == 2
    assert report["status"] == "needs_confirmation"
    assert report["published"] is False
    assert {issue["location"] for issue in report["issues"]} >= {"roles", "title"}
    assert "public_description" not in report


def test_SCN_01_valid_candidate_cannot_supply_its_own_confirmation(tmp_path: Path) -> None:
    from test_scenario_role_contract import declaration

    from career_lab.contracts.v2.core import digest

    source = declaration()
    source["confirmed_digest"] = digest(source)
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(source))
    result = run_validation(path)
    report = json.loads(result.stdout)
    assert result.returncode == 2
    assert report["status"] == "needs_confirmation"
    assert report["published"] is False
    assert "public_description" not in report
    assert set(tmp_path.iterdir()) == {path}


def test_SCN_01_invalid_json_has_a_safe_machine_readable_failure(tmp_path: Path) -> None:
    path = tmp_path / "candidate.json"
    path.write_text("private author content, not JSON")
    result = run_validation(path)
    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "status": "invalid",
        "published": False,
        "issues": [{"code": "declaration_unreadable", "location": "declaration"}],
    }
    assert "private author content" not in result.stdout + result.stderr
