"""Fast local check: lint, then the backend unit and contract tests.

Run from the repository root with the project environment:

    .venv/bin/python -m scripts.check_fast

No browser, no gate lock and no output directory. Every step runs; each prints its
result and duration, and the exit status is nonzero when any step fails. This is not the
full gate: frontend tests, the state regression, the build, the per-ID comparison and the
browser flows run only in ``scripts.regression.run``.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_PATHS = ("tests/unit", "tests/contracts")


def isolated_environment(temporary: Path) -> dict[str, str]:
    """The caller's environment without deployment model, registry or database settings."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("CAREER_LAB_")}
    env.pop("PYTHONPATH", None)
    env.update(
        CAREER_LAB_SCENARIO_ARCHIVE=str(temporary / "archive"),
        PYTHONDONTWRITEBYTECODE="1",
        TMPDIR=str(temporary),
    )
    return env


def steps(temporary: Path) -> list[tuple[str, list[str]]]:
    python = sys.executable
    return [
        ("lint", [python, "-m", "scripts.regression.lint"]),
        (
            "backend unit and contract tests",
            [
                python,
                "-m",
                "pytest",
                "-q",
                "--tb=short",
                # A private base directory keeps concurrent runs in one checkout apart.
                "--basetemp=" + str(temporary / "pytest"),
                *TEST_PATHS,
            ],
        ),
    ]


def run_step(name: str, command: list[str], env: dict[str, str]) -> tuple[bool, float]:
    print("== " + name, flush=True)
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, env=env, check=False)
    elapsed = time.monotonic() - started
    passed = result.returncode == 0
    print(f"== {name}: {'PASS' if passed else 'FAIL'} in {elapsed:.1f} s", flush=True)
    return passed, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.parse_args()
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="rolecraft-check-fast-") as directory:
        temporary = Path(directory)
        env = isolated_environment(temporary)
        results = [(name, *run_step(name, command, env)) for name, command in steps(temporary)]
    print("\ncheck-fast summary", flush=True)
    for name, passed, elapsed in results:
        print(f"  {'PASS' if passed else 'FAIL'}  {elapsed:7.1f} s  {name}")
    failed = [name for name, passed, _ in results if not passed]
    total = time.monotonic() - started
    print(f"check-fast: {'FAIL' if failed else 'PASS'} in {total:.1f} s", flush=True)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
