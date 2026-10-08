"""Reject new frontend lint findings and lint changed Python code against Git."""

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps/web"
BASELINE = ROOT / "tests/regression/frontend-lint-baseline.json"


def run_json(command: list[str], cwd: Path) -> object:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr)
    try:
        return json.loads(result.stdout)
    except ValueError as error:
        raise RuntimeError(result.stderr or result.stdout) from error


def frontend_findings() -> Counter[str]:
    report = run_json(
        [str(WEB / "node_modules/.bin/biome"), "lint", "--reporter=json", "--max-diagnostics=none"],
        WEB,
    )
    if report["summary"]["diagnosticsNotPrinted"]:
        raise RuntimeError("Incomplete lint report")
    findings: Counter[str] = Counter()
    for diagnostic in report["diagnostics"]:
        location = diagnostic["location"]
        path = location["path"]
        source = (WEB / path).read_text().splitlines()
        line = source[location["start"]["line"] - 1].strip()
        key = json.dumps([path, diagnostic["category"], diagnostic["message"], line])
        findings[key] += 1
    return findings


def git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True)


def changed_files(base: str) -> list[str]:
    paths = set(git("diff", "--name-only", "--diff-filter=ACMR", base).splitlines())
    paths.update(git("ls-files", "--others", "--exclude-standard").splitlines())
    return sorted(path for path in paths if (ROOT / path).is_file())


def python_findings(path: str, content: str) -> Counter[str]:
    result = subprocess.run(
        [
            str(ROOT / ".venv/bin/ruff"),
            "check",
            "--output-format=json",
            "--stdin-filename",
            path,
            "-",
        ],
        cwd=ROOT,
        input=content,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr)
    lines = content.splitlines()
    return Counter(
        json.dumps([row["code"], row["message"], lines[row["location"]["row"] - 1].strip()])
        for row in json.loads(result.stdout)
    )


def check_python(paths: list[str], base: str) -> list[str]:
    failures = []
    for path in paths:
        if not path.endswith(".py"):
            continue
        previous = subprocess.run(
            ["git", "show", f"{base}:{path}"], cwd=ROOT, capture_output=True, text=True, check=False
        )
        current = (ROOT / path).read_text()
        new = python_findings(path, current) - python_findings(path, previous.stdout)
        failures.extend(path + ": " + key for key in new.elements())
        if previous.returncode != 0:
            formatted = subprocess.run(
                [str(ROOT / ".venv/bin/ruff"), "format", "--check", path],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if formatted.returncode:
                failures.append(path + ": format check failed")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="73e14e93c8fed05cb4b6e8caad10d17cacf7489d")
    args = parser.parse_args()
    current = frontend_findings()
    baseline = Counter(json.loads(BASELINE.read_text())["findings"])
    new = current - baseline
    failures = ["frontend: " + key for key in new.elements()]
    failures.extend(check_python(changed_files(args.base), args.base))
    for failure in failures:
        print(failure)
    print(f"Lint: {len(failures)} new findings; {sum(current.values())} existing frontend findings")
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
