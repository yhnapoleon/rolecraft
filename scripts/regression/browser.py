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
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from scripts.regression.mcp import exercise, exercise_http
from scripts.regression.model_flows import (
    DEFAULT_PHASES,
    OPTIONAL_PHASES,
    build,
    check_slot_calls,
    slot_environment,
    slot_services,
)
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


@contextmanager
def services(
    output: Path, env: dict[str, str], api_port: int, web_port: int, database: str
) -> Iterator[None]:
    """API, worker and vite preview on one database; always stopped on exit."""
    api = f"http://127.0.0.1:{api_port}"
    web = f"http://127.0.0.1:{web_port}"
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
                str(api_port),
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
                str(web_port),
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
        yield
    finally:
        for process in reversed(processes):
            stop(process)


def model_flows(args: argparse.Namespace, output: Path, env: dict[str, str]) -> None:
    """FLOW-01..05: each phase serves one registration (and, for ``slots``, loopback
    JUDGE and ASSISTANT slots) and runs the bilingual normal-entry walkthrough."""
    phases = args.phases or (
        [*DEFAULT_PHASES, *OPTIONAL_PHASES] if args.optional_encoder else list(DEFAULT_PHASES)
    )
    summary = []
    for name in phases:
        target = output / name
        target.mkdir()
        phase = build(name, target / "model")
        journal = target / "journal"
        phase_env = env | phase.environment(journal) | {"OUT": str(target)}
        with ExitStack() as stack:
            calls = None
            if phase.slots:
                url, calls = stack.enter_context(slot_services())
                phase_env |= slot_environment(url)
            stack.enter_context(
                services(
                    target,
                    phase_env,
                    args.api_port,
                    args.web_port,
                    "sqlite:///" + str(target / "regression.db"),
                )
            )
            phase_env["MODEL_FLOWS_PHASE"] = json.dumps(
                {
                    "name": name,
                    "identity": phase.identity,
                    "journal": str(journal),
                    "drift_file": str(phase.drift_file) if phase.drift_file else None,
                    "slots": phase.slots,
                },
                ensure_ascii=False,
            )
            subprocess.run(
                ["node", "tests/regression/model-flows.mjs"],
                cwd=ROOT / "apps/web",
                env=phase_env,
                check=True,
            )
        result = {"phase": name, "identity_kind": phase.identity.get("kind")}
        if calls is not None:
            result["slot_calls"] = check_slot_calls(calls)
            if result["slot_calls"]["problems"]:
                raise RuntimeError("FLOW-05: " + "; ".join(result["slot_calls"]["problems"]))
        summary.append(result)
        print("model-flows phase passed:", name, flush=True)
    (output / "model-flows.json").write_text(json.dumps(summary, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--suite",
        choices=("published-flows", "known-defects", "model-flows", "qa-polish"),
        default="published-flows",
    )
    parser.add_argument("--api-port", type=int, default=19662)
    parser.add_argument("--web-port", type=int, default=19660)
    parser.add_argument(
        "--optional-encoder",
        action="store_true",
        help="model-flows: also the encoder, heterogeneous fusion and XLM-R phases (encoder extra)",
    )
    parser.add_argument("--phases", nargs="+", choices=(*DEFAULT_PHASES, *OPTIONAL_PHASES))
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
    if args.suite == "model-flows":
        model_flows(args, output, env)
        return
    if args.suite == "published-flows":
        # Real-DOM checks of the pre-submission card; their own dev server on any free port.
        subprocess.run(
            [
                str(ROOT / "apps/web/node_modules/.bin/vitest"),
                "run",
                "--config",
                "src/features/feedback-native/presubmit.vitest.config.ts",
            ],
            cwd=ROOT / "apps/web",
            env=env,
            check=True,
        )
    database = "sqlite:///" + str(output / "regression.db")
    with services(output, env, args.api_port, args.web_port, database):
        results = (
            [exercise(api, language) for language in ("zh", "en")]
            # Streamable HTTP through the web origin's /api proxy, as the connection card shows.
            + [exercise_http(api, web + "/api", language) for language in ("zh", "en")]
            if args.suite == "published-flows"
            else []
        )
        (output / "mcp.json").write_text(json.dumps(results, indent=2) + "\n")
        if results:
            print("MCP: bilingual stdio and HTTP read/return/replay/revoke passed", flush=True)
        # Every published flow emulates reduced motion; one more round keeps the default.
        # The pre-submission card and the feedback page's "at submission" lines, same services.
        rounds = (
            [args.suite, "default-motion", "presubmit-flows"]
            if args.suite == "published-flows"
            else [args.suite]
        )
        for name in rounds:
            subprocess.run(
                ["node", "tests/regression/" + name + ".mjs"],
                cwd=ROOT / "apps/web",
                env=env,
                check=True,
            )


if __name__ == "__main__":
    main()
