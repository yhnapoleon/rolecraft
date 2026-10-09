"""Development CLI help describes the capability without implementation-line names."""

import subprocess
import sys

from scripts.regression.published import ROOT


def test_training_help_uses_capability_names() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "career_lab.experiments.v3.training", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Development training tools; all outputs advisory" in result.stdout
    assert "Local train/dev pipeline; no held-out evaluation" in result.stdout
    assert "W08" not in result.stdout
    for command in ("train-v3", "check-freeze-v3", "predict-v3"):
        assert command in result.stdout
