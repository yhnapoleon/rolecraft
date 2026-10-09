"""Run the normal v4 UI against the published bilingual catalog; stop owned services."""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from scripts.regression.mcp import exercise
from scripts.regression.published import ROOT, write_catalog


def wait_ready(url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Service exited before readiness: " + url)
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except (OSError, urllib.error.URLError):
            time.sleep(0.1)
    raise TimeoutError("Service did not become ready: " + url)


def stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--suite", choices=("published-flows", "known-defects"), default="published-flows"
    )
    parser.add_argument("--api-port", type=int, default=19662)
    parser.add_argument("--web-port", type=int, default=19660)
    args = parser.parse_args()
    if not os.environ.get("CHROME_BIN"):
        parser.error("CHROME_BIN must name a Chrome/headless-shell executable")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for port in (args.api_port, args.web_port):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    env = {key: value for key, value in os.environ.items() if not key.startswith("CAREER_LAB_")}
    env.pop("PYTHONPATH", None)
    api = f"http://127.0.0.1:{args.api_port}"
    web = f"http://127.0.0.1:{args.web_port}"
    env.update(
        CAREER_LAB_CREDENTIAL_KEY_ID="regression-fixture-v1",
        CAREER_LAB_CREDENTIAL_KEY="isolated-regression-credential-key-not-for-deployment",
        CAREER_LAB_SCENARIO_CATALOG=str(write_catalog(output / "catalog.json")),
        CAREER_LAB_SCENARIO_ARCHIVE=str(output / "archive"),
        ROLECRAFT_API_TARGET=api,
        BASE=web + "/",
        OUT=str(output),
        PYTHONDONTWRITEBYTECODE="1",
    )
    database = "sqlite:///" + str(output / "regression.db")
    common = ["--database-url", database, "--provider", "local"]
    commands = [
        (
            "api",
            [
                sys.executable,
                "-m",
                "career_lab.cli",
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.api_port),
                *common,
            ],
            ROOT,
            api + "/health",
        ),
        ("worker", [sys.executable, "-m", "career_lab.cli", "worker", *common], ROOT, None),
        (
            "web",
            [
                str(ROOT / "apps/web/node_modules/.bin/vite"),
                "preview",
                "--port",
                str(args.web_port),
                "--strictPort",
            ],
            ROOT / "apps/web",
            web,
        ),
    ]
    processes = []
    try:
        for name, command, cwd, ready in commands:
            with (output / (name + ".log")).open("w") as log:
                process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=log)
            processes.append(process)
            if ready:
                wait_ready(ready, process)
        results = (
            [exercise(api, language) for language in ("zh", "en")]
            if args.suite == "published-flows"
            else []
        )
        (output / "mcp.json").write_text(json.dumps(results, indent=2) + "\n")
        if results:
            print("MCP: bilingual read/return/replay/revoke passed", flush=True)
        subprocess.run(
            ["node", "tests/regression/" + args.suite + ".mjs"],
            cwd=ROOT / "apps/web",
            env=env,
            check=True,
        )
    finally:
        for process in reversed(processes):
            stop(process)


if __name__ == "__main__":
    main()
