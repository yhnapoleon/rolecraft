"""Local preview of the AIPM phase 1 candidate through the standard demo launcher.

New product manager practices bind to the rebuilt candidate (zh/en) instead of the installed
pm_pilot package, so they enter the seven-step experience; every other catalog entry is the demo
catalog unchanged. Nothing installed is modified: the candidate stays a build output, the catalog
is written to the run directory, and the launcher itself is unchanged.

    uv run --no-project --python 3.12 scenarios/pm_pilot/aipm-phase1/build/aipm_env.py up \
        --run-dir /private/tmp/aipm-int-run --web-port 18810 --api-port 18812 \
        --no-demo-pack --no-recognition
    uv run --no-project --python 3.12 scenarios/pm_pilot/aipm-phase1/build/aipm_env.py down \
        --run-dir /private/tmp/aipm-int-run

The candidate is read from build/out/<AIPM_CANDIDATE, default int-1>; build it first with
build_candidate.py --output scenarios/pm_pilot/aipm-phase1/build/out/int-1.
"""

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

from scripts.demo import launcher  # noqa: E402


def candidate_catalog(run_dir: Path) -> tuple[Path, list[Path]]:
    out = Path(__file__).resolve().parent / "out" / os.getenv("AIPM_CANDIDATE", "int-1")
    identity = json.loads((out / "identity.json").read_text())
    if identity.get("missing_content"):
        print("AIPM candidate incomplete:", identity["missing_content"], file=sys.stderr)
    catalog = json.loads(launcher.CATALOGS["demo"].read_text())
    roots = []
    for language, package in identity["packages"].items():
        root = Path(package["root"]).resolve()
        replaced = False
        for entry in catalog["scenarios"]:
            if entry["scenario_hash"] == package["base_scenario_hash"]:
                entry.update(
                    root=str(root.relative_to(REPO)),
                    scenario_hash=package["scenario_hash"],
                    authored_manifest=package["scenario_hash"],
                )
                entry.pop("reviewed_authored_manifest", None)
                replaced = True
        if not replaced:
            raise SystemExit(f"base package for {language} not in the demo catalog")
        roots.append(root)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "aipm-source-catalog.json"
    path.write_text(json.dumps(catalog, indent=2) + "\n")
    return path, roots


def main(argv: list[str]) -> int:
    if argv[:1] == ["up"]:
        run_dir = Path(argv[argv.index("--run-dir") + 1]) if "--run-dir" in argv else None
        if run_dir is None:
            raise SystemExit("--run-dir is required so the preview never reuses the demo stack")
        catalog, roots = candidate_catalog(run_dir.resolve())
        launcher.CATALOGS["aipm"] = catalog
        env_file = run_dir.resolve() / "aipm.env"
        env_file.write_text("CAREER_LAB_AIPM_PACKAGES=" + os.pathsep.join(map(str, roots)) + "\n")
        argv = [*argv, "--catalog", "aipm", "--env-file", str(env_file)]
    return launcher.main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
