"""MCP loads in a source checkout and resolves its software version only for replies."""

import subprocess
import sys

import pytest

from scripts.regression.published import ROOT


@pytest.mark.parametrize("installed", [True, False])
def test_mcp_resolves_package_version_only_when_replying(installed: bool) -> None:
    script = r"""
import importlib.metadata as metadata
import sys

calls = []
original = metadata.version
installed = sys.argv[1] == "True"
def lookup(name):
    if name != "career-lab":
        return original(name)
    calls.append(name)
    if not installed:
        raise metadata.PackageNotFoundError(name)
    return "9.8.7"
metadata.version = lookup

from career_lab.mcp.protocol import CAPABILITIES, MODERN, SERVER, VERSION, Protocol
assert calls == [], "Module import must not require distribution metadata"
protocol = Protocol(None)
assert calls == [], "Construction must not require distribution metadata"
expected = {"name": "rolecraft-workspace", "version": "9.8.7" if installed else "0.0.0+uninstalled"}
initialized = protocol.handle({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-11-25", "capabilities": {},
               "clientInfo": {"name": "regression", "version": "1"}},
})
assert initialized["serverInfo"] == expected
assert calls, "A reply must resolve the actual distribution version"
for method in ("server/discover", "ping"):
    result = protocol.handle({
        "jsonrpc": "2.0", "id": 2, "method": method,
        "params": {"_meta": {VERSION: MODERN, CAPABILITIES: {}}},
    })
    assert result["_meta"][SERVER] == expected
    assert result["resultType"] == "complete"
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(installed)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
