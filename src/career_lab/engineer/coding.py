"""The coding exercise of an engineer ticket: one fixed function, run outside the product.

The engineer (or their own Coding Agent) writes ``current_limit``: from the retrieved chunks
and the source registry it picks the policy clause that is in force and extracts the amount
with code, never from a generated answer. The platform runs it on frozen cases:

- the learner's code runs in a fresh child process (``python -I``, an empty temporary
  directory, no inherited environment, a wall-clock limit, an audit hook refusing sockets,
  subprocesses and writes). This is a trusted-user level for the demo, not a security
  boundary, and it never runs inside the API or worker process;
- only the case inputs enter the child; the expected values stay here and the comparison is
  made after the child has exited;
- public cases come back row by row; hidden cases only as a count.

A scenario without an exercise file has no coding step.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from career_lab.contracts import v2 as C

EXERCISES = Path(__file__).resolve().parent / "exercises"
EXERCISE_ID = "policy_limit"
FUNCTION = "current_limit"
# Scenarios whose materials carry the hotel/taxi policy and the meal rule the cases quote.
SCENARIOS = frozenset({"pm_pilot", "pm_pilot_capacity15", "pm_pilot_urgent"})
CODE_LIMIT = 20_000
TIMEOUT_SECONDS = 10
OUTPUT_LIMIT = 200_000
PRINT_LIMIT = 2_000
ERROR_LIMIT = 300
STATUSES = ("answered", "answered_with_warning", "fallback")

HARNESS = r"""
import io, json, os, sys, traceback

ROOT = os.path.realpath(os.getcwd())
sys.path.insert(0, ROOT)  # -I leaves the script's folder off the path
LIBS = tuple(os.path.realpath(p) for p in {sys.prefix, sys.base_prefix, sys.exec_prefix})
BLOCKED = ("socket.", "subprocess.", "os.system", "os.exec", "os.spawn", "os.posix_spawn",
           "os.fork", "os.kill", "os.remove", "os.rename", "os.rmdir", "os.mkdir",
           "shutil.", "ctypes.", "winreg.", "webbrowser.", "urllib.", "http.client.")

def inside(path, roots):
    try:
        real = os.path.realpath(os.fsdecode(path))
    except (TypeError, ValueError):
        return False
    return any(real == r or real.startswith(r + os.sep) for r in roots)

def hook(event, args):
    if event.startswith(BLOCKED):
        raise PermissionError("blocked in the exercise sandbox: " + event)
    if event == "open":
        path, mode = args[0], args[1] or "r"
        if isinstance(path, int):
            return
        if any(flag in str(mode) for flag in "wax+"):
            raise PermissionError("blocked in the exercise sandbox: writing files")
        if not inside(path, (ROOT,) + LIBS):
            raise PermissionError("blocked in the exercise sandbox: reading outside the exercise")

def failure():
    kind, value, tb = sys.exc_info()
    frames = [f for f in traceback.extract_tb(tb) if f.filename.endswith("solution.py")]
    where = ("solution.py line %d: %s\n" % (frames[-1].lineno, frames[-1].line)) if frames else ""
    text = "".join(traceback.format_exception_only(kind, value)).strip()
    return where + text.replace(ROOT + os.sep, "")

def plain(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))

def main():
    cases = json.loads(sys.stdin.read())
    out = sys.stdout
    printed = io.StringIO()
    sys.stdout = printed
    sys.addaudithook(hook)
    rows = []
    try:
        import solution
        function = getattr(solution, "current_limit")
    except BaseException:
        error = failure()
        rows = [{"id": c["id"], "output": None, "error": error} for c in cases]
    else:
        for case in cases:
            try:
                value = function(case["question"], case["chunks"], case["registry"])
                rows.append({"id": case["id"], "output": plain(value), "error": None})
            except BaseException:
                rows.append({"id": case["id"], "output": None,
                             "error": failure()})
    out.write(json.dumps({"rows": rows, "printed": printed.getvalue()[-2000:]},
                         ensure_ascii=False))

main()
"""


def available(package: Any) -> bool:
    return package.bundle.id in SCENARIOS and (EXERCISES / EXERCISE_ID).is_dir()


def exercise(language: str) -> dict[str, Any]:
    folder = EXERCISES / EXERCISE_ID
    data = json.loads((folder / (language + ".json")).read_text(encoding="utf-8"))
    data["skeleton"] = (folder / ("skeleton." + language + ".txt")).read_text(encoding="utf-8")
    return data


def public_view(language: str) -> dict[str, Any]:
    """What the engineer and their Agent may read: the task, the skeleton and public cases."""
    data = exercise(language)
    return {
        "id": EXERCISE_ID,
        "function": FUNCTION,
        "title": data["title"],
        "task": data["task"],
        "skeleton": data["skeleton"],
        # A public case's answer is named should_return: "expected" stays the word for the
        # review suite's expectations, which never leave the trusted review.
        "public_cases": [
            {
                **{key: case[key] for key in ("id", "point", "question", "chunks", "registry")},
                "should_return": case["expected"],
            }
            for case in data["cases"]
            if case["public"]
        ],
        "hidden_cases": sum(not case["public"] for case in data["cases"]),
    }


def summary_view(language: str) -> dict[str, Any]:
    """The exercise in the ticket detail: enough to know it is there."""
    data = exercise(language)
    return {
        "id": EXERCISE_ID,
        "function": FUNCTION,
        "title": data["title"],
        "public_cases": sum(case["public"] for case in data["cases"]),
        "hidden_cases": sum(not case["public"] for case in data["cases"]),
    }


def code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def execute(code: str, cases: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str | None]:
    """Run the code once on all case inputs; (child output, None) or (None, error code)."""
    inputs = [
        {key: case[key] for key in ("id", "question", "chunks", "registry")} for case in cases
    ]
    with tempfile.TemporaryDirectory(prefix="rc-exercise-") as folder:
        root = Path(folder)
        (root / "solution.py").write_text(code, encoding="utf-8")
        (root / "harness.py").write_text(HARNESS, encoding="utf-8")
        # Nothing of the server's environment: no keys, no paths (-I ignores PYTHON* too).
        # Windows needs SYSTEMROOT for the interpreter to start.
        env: dict[str, str] = {}
        if os.name == "nt" and os.environ.get("SYSTEMROOT"):
            env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
        try:
            done = subprocess.run(
                [sys.executable, "-I", "-B", "-X", "utf8", "harness.py"],
                input=json.dumps(inputs, ensure_ascii=False).encode("utf-8"),
                cwd=root,
                env=env,
                capture_output=True,
                timeout=TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return None, "engineer_code_timeout"
    if len(done.stdout) > OUTPUT_LIMIT:
        return None, "engineer_code_output_too_large"
    try:
        value = json.loads(done.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "engineer_code_crashed"
    if not isinstance(value, dict) or not isinstance(value.get("rows"), list):
        return None, "engineer_code_crashed"
    return value, None


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def matches(output: Any, expected: dict[str, Any]) -> bool:
    if not isinstance(output, dict) or output.get("status") != expected["status"]:
        return False
    if expected["status"] == "fallback":
        return True
    return (
        number(output.get("value")) == float(expected["value"])
        and output.get("source") == expected["source"]
        and output.get("version") == expected["version"]
    )


def short(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    return text if len(text) <= limit else "…" + text[-(limit - 1) :]


def run_code(code: str, language: str) -> dict[str, Any]:
    """Public rows, the hidden count and the overall status of one run."""
    if not isinstance(code, str) or not code.strip():
        raise C.ProtocolError("engineer_code_empty")
    if len(code) > CODE_LIMIT:
        raise C.ProtocolError("engineer_code_too_long")
    data = exercise(language)
    cases = data["cases"]
    value, failure = execute(code, cases)
    produced = {}
    if value is not None:
        produced = {row.get("id"): row for row in value["rows"] if isinstance(row, dict)}
    public, hidden = [], {"passed": 0, "total": 0}
    for case in cases:
        row = produced.get(case["id"], {})
        output, error = row.get("output"), row.get("error")
        if failure:
            error = failure
        passed = error is None and matches(output, case["expected"])
        if not case["public"]:
            hidden["total"] += 1
            hidden["passed"] += passed
            continue
        public.append(
            {
                "id": case["id"],
                "point": case["point"],
                "question": case["question"],
                "should_return": case["expected"],
                "actual": output if isinstance(output, dict) else None,
                "error": short(error if isinstance(error, str) else None, ERROR_LIMIT),
                "result": "pass" if passed else ("error" if error else "fail"),
            }
        )
    passed = sum(row["result"] == "pass" for row in public)
    return {
        "exercise": EXERCISE_ID,
        "code_sha256": code_hash(code),
        "status": failure or "completed",
        "public": public,
        "counts": {"passed": passed, "total": len(public)},
        "hidden": hidden,
        "all_passed": passed == len(public) and hidden["passed"] == hidden["total"],
        "printed": short(value.get("printed") if value else None, PRINT_LIMIT) or "",
    }
