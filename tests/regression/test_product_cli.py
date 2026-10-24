"""Public help names capabilities; MCP reports the installed software version."""

import subprocess
import sys
from importlib.metadata import version

import pytest

from career_lab.mcp.protocol import Protocol
from scripts.regression.published import ROOT


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        ("career_lab.delegations.openai_tools", "private delegation config"),
        ("career_lab.scenarios.v2", "Scenario module validation"),
    ],
)
def test_cli_help_names_the_product_capability(module: str, expected: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout
    assert "W06" not in result.stdout and "W02" not in result.stdout


def test_mcp_initialize_reports_installed_package_version() -> None:
    result = Protocol(None).handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "regression", "version": "1"},
            },
        }
    )
    assert result == {
        "protocolVersion": "2025-11-25",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "rolecraft-workspace", "version": version("career-lab")},
        "instructions": (
            "RoleCraft workspace tools for one delegated practice session. Only the listed tools "
            "are authorized; server permissions and business rules still apply. session_id is "
            "optional and defaults to the session this connection is authorized for; if given, "
            "it must match. Start with observation; tools shows which tools are available "
            "now. The JSON-RPC id is not the business request_id: after an unknown result keep "
            "command.request_id unchanged and read requests.read; re-execution requires an "
            "explicit user decision."
        ),
    }
