"""Official serve failures remain visible without exposing process configuration."""

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.regression.published import write_catalog


@pytest.mark.parametrize(
    "entry", ["career_lab.cli", "career_lab.delegations", "career_lab.scenarios.v2"]
)
def test_occupied_port_reports_fixed_safe_failure(tmp_path: Path, entry: str) -> None:
    package = json.loads(write_catalog(tmp_path / "catalog.json").read_text())["scenarios"][0][
        "root"
    ]
    private = "PRIVATE-STARTUP-DATABASE"
    arguments = ["--database-url", "sqlite:///" + str(tmp_path / (private + ".db"))]
    if entry == "career_lab.cli":
        arguments = ["serve", *arguments]
    elif entry == "career_lab.delegations":
        arguments += ["--scenario-package", package]
    else:
        arguments = ["serve", package, *arguments]
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        port = occupied.getsockname()[1]
        result = subprocess.run(
            [sys.executable, "-m", entry, *arguments, "--port", str(port)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    assert result.returncode != 0
    assert "HTTP server error; check the configured host and port." in result.stderr
    assert private not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr


def test_existing_logger_remains_enabled_without_emitting_private_text() -> None:
    program = """
import logging
from career_lab.api.error_boundary import configure_http_logging
logger = logging.getLogger("existing_dependency")
logger.addHandler(logging.StreamHandler())
logger.propagate = False
configure_http_logging()
assert logger.isEnabledFor(logging.WARNING)
logger.warning("PRIVATE-DEPENDENCY-TEXT")
logging.getLogger("uvicorn.error").error("PRIVATE-STARTUP-EXCEPTION", exc_info=True)
"""
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr.strip() == "HTTP server error; check the configured host and port."
    assert "PRIVATE-" not in result.stdout + result.stderr
