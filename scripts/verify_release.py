"""Verify a source archive in a newly extracted directory and separate uv environment."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import zipfile


def main():
    p = argparse.ArgumentParser()
    p.add_argument("archive", type=Path)
    p.add_argument("destination", type=Path)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument(
        "--controlled", action="store_true", help="Also reproduce the controlled v2 study"
    )
    args = p.parse_args()
    root = args.destination.resolve()
    root.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(args.archive) as archive:
        manifest = json.loads(archive.read("release-manifest.json"))
        for member in archive.namelist():
            if not (root / member).resolve().is_relative_to(root):
                raise ValueError("archive path escapes destination")
        for name, expected in manifest["files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected, name
        assert not any(
            Path(name).name in {"openai.txt", "ds.txt", ".env"} for name in archive.namelist()
        )
        archive.extractall(root)
    commands = [
        ["uv", "sync", "--locked", "--python", "3.12"],
        ["uv", "run", "--no-sync", "pytest", "-q"],
        ["uv", "run", "--no-sync", "career-lab", "demo", "--output", "runs/clean-demo.json"],
        ["uv", "run", "--no-sync", "career-lab", "data", "build", "--output", "data/releases/v1"],
        [
            "uv",
            "run",
            "--no-sync",
            "career-lab",
            "data",
            "audit",
            "--manifest",
            "data/releases/v1/manifest.json",
        ],
        [
            "uv",
            "run",
            "--no-sync",
            "career-lab",
            "train-baselines",
            "--manifest",
            "data/releases/v1/manifest.json",
            "--output",
            "runs/models/pilot-v1",
        ],
        [
            "uv",
            "run",
            "--no-sync",
            "career-lab",
            "eval",
            "run",
            "--config",
            "configs/eval_smoke.yaml",
        ],
        ["uv", "run", "--no-sync", "python", "scripts/evaluate_baselines.py"],
    ]
    if args.controlled:
        commands.extend(
            [
                ["uv", "run", "--no-sync", "python", "scripts/prepare_experiments.py", "pilot"],
                [
                    "uv",
                    "run",
                    "--no-sync",
                    "python",
                    "scripts/prepare_experiments.py",
                    "annotations",
                ],
                ["uv", "run", "--no-sync", "python", "scripts/prepare_experiments.py", "release"],
                [
                    "uv",
                    "run",
                    "--no-sync",
                    "career-lab",
                    "train-baselines",
                    "--manifest",
                    "data/releases/controlled-v2/manifest.json",
                    "--output",
                    "runs/models/controlled-v2",
                ],
                [
                    "uv",
                    "run",
                    "--no-sync",
                    "python",
                    "scripts/run_controlled_experiments.py",
                    "dev",
                ],
                [
                    "uv",
                    "run",
                    "--no-sync",
                    "python",
                    "scripts/run_controlled_experiments.py",
                    "freeze",
                ],
                [
                    "uv",
                    "run",
                    "--no-sync",
                    "python",
                    "scripts/run_controlled_experiments.py",
                    "test",
                ],
                ["uv", "run", "--no-sync", "python", "scripts/report_controlled_experiments.py"],
            ]
        )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("CAREER_LAB_")
        and k not in {"VIRTUAL_ENV", "PYTHONPATH", "UV_PROJECT_ENVIRONMENT"}
    }
    env["PYTHONUTF8"] = "1"
    results = []
    for command in commands:
        start = time.monotonic()
        result = subprocess.run(
            command,
            cwd=root,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=180,
        )
        results.append(
            dict(
                command=command,
                exit_code=result.returncode,
                seconds=round(time.monotonic() - start, 3),
                output=(result.stdout + result.stderr)[-6000:],
            )
        )
        print(f"{command[0]} {command[1]}: exit={result.returncode}", flush=True)
        if result.returncode:
            break
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(
            dict(
                archive_sha256=hashlib.sha256(args.archive.read_bytes()).hexdigest(),
                source_files=manifest["files"],
                clean_environment=True,
                commands=results,
                passed=len(results) == len(commands) and all(r["exit_code"] == 0 for r in results),
            ),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return 0 if len(results) == len(commands) and all(r["exit_code"] == 0 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
