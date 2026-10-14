"""A real API process serves MCP over Streamable HTTP in both languages; no model calls.

The server runs exactly as deployed (career_lab.cli serve, its whitelisted request log), so
the log written here is the one an operator would keep.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from scripts.regression.mcp import exercise_http
from scripts.regression.published import write_catalog

ROOT = Path(__file__).parents[2]


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_ready(url: str, server: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        assert server.poll() is None, "API exited before readiness"
        try:
            if httpx.get(url, timeout=1, trust_env=False).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise TimeoutError(url)


def test_mcp_http_real_api_returns_work_in_both_languages_and_logs_no_token(tmp_path):
    port = free_port()
    api = f"http://127.0.0.1:{port}"
    env = {
        key: value
        for key, value in os.environ.items()
        if key != "PYTHONPATH" and not key.startswith("CAREER_LAB_")
    }
    env.update(
        CAREER_LAB_CREDENTIAL_KEY_ID=os.environ["CAREER_LAB_CREDENTIAL_KEY_ID"],
        CAREER_LAB_CREDENTIAL_KEY=os.environ["CAREER_LAB_CREDENTIAL_KEY"],
        CAREER_LAB_SCENARIO_CATALOG=str(write_catalog(tmp_path / "catalog.json")),
        CAREER_LAB_SCENARIO_ARCHIVE=str(tmp_path / "archive"),
    )
    tokens: list[str] = []
    with (tmp_path / "api.log").open("w+") as log:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "career_lab.cli",
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--database-url",
                "sqlite:///" + str(tmp_path / "live.db"),
                "--provider",
                "local",
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            wait_ready(api + "/health", server)
            results = [
                exercise_http(api, api, language, on_token=tokens.append)
                for language in ("zh", "en")
            ]
        finally:
            server.terminate()
            server.wait(10)
        log.seek(0)
        written = log.read()
    assert [result["language"] for result in results] == ["zh", "en"]
    assert all(result["status"] == "passed" for result in results)
    assert len(tokens) == 2 and all(token not in written for token in tokens)
    assert all(result["product"]["session_id"] not in written for result in results)
    assert '"route": "/sessions/{session_id}/mcp"' in written
    assert '"code": "mcp_unauthorized"' in written
