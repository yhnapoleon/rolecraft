"""Reproducible public regression selection, with no test exclusion.

Run using the checkout's locked Python environment:
  .venv/bin/python docs/integration/check_public.py --artifacts runs/local/checks/<new-run>
"""

from pathlib import Path
import argparse, datetime, hashlib, json, os, platform, subprocess, sys, tempfile

BASE = "80cf1f6189cd25610d609f44283ff9668582d759"
ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--collect-only", action="store_true")
    args = parser.parse_args()
    output = args.artifacts.resolve()
    output.mkdir(parents=True, exist_ok=False)
    files = subprocess.check_output(
        [
            "git",
            "-C",
            str(ROOT),
            "ls-tree",
            "--full-tree",
            "-r",
            "--name-only",
            BASE,
            "--",
            "tests",
        ],
        text=True,
    ).splitlines()
    selected = [
        path for path in files if Path(path).name.startswith("test_") and path.endswith(".py")
    ]
    assert selected and all((ROOT / path).is_file() for path in selected)
    command = [
        sys.executable,
        "-m",
        "pytest",
        *selected,
        "tests/contracts/expansion_v3",
        "apps/web/tests/test_existing_backend.py",
        "-q",
        "-p",
        "no:cacheprovider",
        "--basetemp=" + str(output / "pytest-temp"),
    ]
    if args.collect_only:
        command.append("--collect-only")
    allowed = (
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "TZ",
        "USER",
        "LOGNAME",
        "PYTHONHASHSEED",
        "GIT_DIR",
        "GIT_WORK_TREE",
    )
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    record = {
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "cwd": str(ROOT),
        "base_commit": BASE,
        "command": command,
        "original_base_tests": selected,
        "exclusions": [],
        "python_version": platform.python_version(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "environment": env,
        "environment_policy": "Only the recorded allowlist is inherited; provider secrets, arbitrary PYTHONPATH and PostgreSQL test variables are not inherited. Dependencies must already be installed from the project lock.",
    }
    with (output / "pytest.log").open("w") as log:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    record.update(
        exit_code=result.returncode,
        finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        log_sha256=hashlib.sha256((output / "pytest.log").read_bytes()).hexdigest(),
    )
    (output / "result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    print("\n".join((output / "pytest.log").read_text().splitlines()[-18:]))
    print("Evidence:", output / "result.json")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
