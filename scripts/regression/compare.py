"""Compare test identities, outcomes and release bytes; failures return nonzero."""

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/regression"


def backend_results(path: Path) -> dict[str, str]:
    results = {}
    for case in ElementTree.parse(path).iter("testcase"):
        key = case.attrib["classname"] + "::" + case.attrib["name"]
        if key in results:
            raise ValueError("Duplicate backend test ID: " + key)
        results[key] = next(
            (name for name in ("failure", "error", "skipped") if case.find(name) is not None),
            "passed",
        )
    if not results:
        raise ValueError("Empty backend report")
    return results


def frontend_results(path: Path) -> dict[str, str]:
    report = json.loads(path.read_text())
    results = {}
    for suite in report["testResults"]:
        name = suite["name"].split("/apps/web/")[-1]
        for case in suite["assertionResults"]:
            key = name + "::" + case["fullName"]
            if key in results:
                raise ValueError("Duplicate frontend test ID: " + key)
            results[key] = case["status"]
    if not results or report.get("numRuntimeErrorTestSuites", 0):
        raise ValueError("Missing or incomplete frontend report")
    return results


def regressions(baseline: dict[str, str], current: dict[str, str]) -> list[str]:
    problems = ["missing: " + key for key in baseline.keys() - current.keys()]
    for key, status in current.items():
        if status in {"failure", "error", "failed"}:
            problems.append("failed: " + key)
        elif status != "passed" and baseline.get(key) != status:
            problems.append("new skip or changed outcome: " + key)
    return sorted(problems)


def platform_baseline(baseline: dict, overrides: dict, platform: str) -> dict:
    """Apply the documented per-platform outcome overrides to the frozen baseline.

    Only listed tests change, and only to the listed outcome; each entry carries a reason.
    """
    result = {kind: dict(values) for kind, values in baseline.items() if isinstance(values, dict)}
    result.update({k: v for k, v in baseline.items() if not isinstance(v, dict)})
    for kind, entries in overrides.get(platform, {}).items():
        for key, entry in entries.items():
            if key not in result[kind] or not entry.get("reason"):
                raise ValueError("baseline override without a baseline entry or reason: " + key)
            result[kind][key] = entry["status"]
            print(f"baseline override ({platform}): {key} -> {entry['status']}")
    return result


def protected_changes() -> list[str]:
    expected = json.loads((FIXTURES / "release-identity.json").read_text())["protected"]
    problems = []
    for name, identity in expected.items():
        path = ROOT / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != identity:
            problems.append("protected release file changed: " + name)
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path)
    parser.add_argument("--frontend", type=Path)
    args = parser.parse_args()
    expected = platform_baseline(
        json.loads((FIXTURES / "test-baseline.json").read_text()),
        json.loads((FIXTURES / "test-baseline-overrides.json").read_text()),
        sys.platform,
    )
    problems = protected_changes()
    for kind, report, read in (
        ("backend", args.backend, backend_results),
        ("frontend", args.frontend, frontend_results),
    ):
        if report is not None:
            current = read(report)
            problems.extend(regressions(expected[kind], current))
            print(kind, dict(Counter(current.values())))
    for problem in problems:
        print(problem)
    print(f"Regression gate: {len(problems)} problems")
    raise SystemExit(bool(problems))


if __name__ == "__main__":
    main()
