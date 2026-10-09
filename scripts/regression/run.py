"""Run the architecture regression gate with isolated local data and published inputs."""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.regression.fixtures import materialize_historical_rules
from scripts.regression.published import ROOT


def run(name: str, command: list[str], output: Path, env: dict[str, str], cwd: Path) -> None:
    log = output / (name + ".log")
    with log.open("w") as stream:
        result = subprocess.run(
            command, cwd=cwd, env=env, stdout=stream, stderr=stream, check=False
        )
    lines = log.read_text().splitlines()
    print(name, "PASS" if result.returncode == 0 else "FAIL", flush=True)
    print("\n".join(lines[-12:] if result.returncode else lines[-3:]), flush=True)
    if result.returncode:
        raise subprocess.CalledProcessError(result.returncode, command)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--browser", action="store_true", help="Also run the normal bilingual UI and MCP"
    )
    args = parser.parse_args()
    if args.browser and not os.environ.get("CHROME_BIN"):
        parser.error("CHROME_BIN is required with --browser")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = {key: value for key, value in os.environ.items() if not key.startswith("CAREER_LAB_")}
    env.pop("PYTHONPATH", None)
    env.update(
        CAREER_LAB_CREDENTIAL_KEY_ID="regression-fixture-v1",
        CAREER_LAB_CREDENTIAL_KEY="isolated-regression-credential-key-not-for-deployment",
        CAREER_LAB_SCENARIO_ARCHIVE=str(output / "archive"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    python = sys.executable
    run("lint", [python, "-m", "scripts.regression.lint"], output, env, ROOT)
    # Short independent paths avoid SQLite and socket path limitations in old fixture helpers.
    with tempfile.TemporaryDirectory(prefix="rolecraft-regression-") as temporary:
        env["TMPDIR"] = temporary
        env["W02_W05_R10_ARCHIVE"] = str(
            materialize_historical_rules(Path(temporary) / "historical-rules.tar")
        )
        run(
            "backend",
            [
                python,
                "-m",
                "pytest",
                "-q",
                "--tb=short",
                "--basetemp=" + str(Path(temporary) / "pytest"),
                "--junitxml=" + str(output / "backend.xml"),
            ],
            output,
            env,
            ROOT,
        )
    env.pop("TMPDIR", None)
    env.pop("W02_W05_R10_ARCHIVE", None)
    web = ROOT / "apps/web"
    run(
        "frontend",
        [
            "node_modules/.bin/vitest",
            "run",
            "--reporter=json",
            "--outputFile=" + str(output / "frontend.json"),
        ],
        output,
        env,
        web,
    )
    run("state", ["npm", "run", "test:workbench"], output, env, web)
    run("build", ["npm", "run", "build"], output, env, web)
    run(
        "comparison",
        [
            python,
            "-m",
            "scripts.regression.compare",
            "--backend",
            str(output / "backend.xml"),
            "--frontend",
            str(output / "frontend.json"),
        ],
        output,
        env,
        ROOT,
    )
    if args.browser:
        # The browser runner keeps its own DB and archive and always stops its children.
        env.pop("TMPDIR", None)
        run(
            "browser",
            [python, "-m", "scripts.regression.browser", "--output", str(output / "browser")],
            output,
            env,
            ROOT,
        )


if __name__ == "__main__":
    main()
