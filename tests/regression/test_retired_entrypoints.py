"""Retired patch/prototype entry points stay unavailable; formal publication remains."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_in_place_patch_command_is_retired() -> None:
    retired = subprocess.run(
        [sys.executable, str(ROOT / "docs/integration/rebind_runtime.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert retired.returncode != 0, "in-place release patch command must be retired"
    assert "can't open file" in retired.stderr
    formal = subprocess.run(
        [sys.executable, "-m", "career_lab.scenarios.v2.rebind", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--protocol" in formal.stdout and "scenario-release-v1" in formal.stdout


def test_retired_private_review_authority_is_not_an_importable_runtime() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import career_lab.evidence.v2.review_ports"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, "retired private transaction protocol must not be installed"
    assert "ModuleNotFoundError" in result.stderr
    assert "career_lab.evidence.v2.review_ports" in result.stderr
