"""Build locale runtimes offline from immutable W02 content; never repair at startup."""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from career_lab.scenarios.v2.loader import load_package
from career_lab.scenarios.v2.module import ScenarioModule


def reviewed_authored_identity(source, package):
    """Prove unchanged authored bytes against the exact independently reviewed manifest."""
    folder = Path("scenarios/pm_pilot/v2/variants/reviews")
    approval = json.loads((folder / "content-approval-2.9.0.json").read_text())
    lineage = json.loads((folder / "authored-lineage-2.9.6.json").read_text())
    approved = {
        (x["scenario_id"], x["work_language"], x["scenario_hash"]) for x in approval["bundles"]
    }
    match = next(
        (x for x in lineage["bundles"] if Path(x["root"]).resolve() == source.resolve()), None
    )
    if match is None:
        return None
    raw = match["reviewed_manifest_text"].encode()
    identity = hashlib.sha256(raw).hexdigest()
    if (
        approval.get("verdict") != "accepted"
        or approval.get("scope") != "authored_content_only"
        or (package.bundle.id, package.locale, identity) not in approved
    ):
        raise RuntimeError("Source content lacks an exact independent approval")
    previous = json.loads(raw)
    current = json.loads((source / "manifest.json").read_text())
    if {k: v for k, v in previous.items() if k != "files"} != {
        k: v for k, v in current.items() if k != "files"
    }:
        raise RuntimeError("Authored manifest metadata changed")
    if {r["path"] for r in previous["files"]} != {r["path"] for r in current["files"]}:
        raise RuntimeError("Authored file membership changed")
    for ref in previous["files"]:
        if (
            not ref["path"].startswith("runtime/")
            and hashlib.sha256((source / ref["path"]).read_bytes()).hexdigest() != ref["sha256"]
        ):
            raise RuntimeError("Previously reviewed authored content changed: " + ref["path"])
    return identity


def main():
    """Prepare fresh runtime fixtures with the formal content-preserving release CLI."""
    from career_lab.scenarios.v2.release import read_release

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    repo = Path.cwd()
    current = json.loads((repo / "scenarios/pm_pilot/v2/installed/current.json").read_text())
    main = repo / current["main"]["zh"]["root"]
    sources = [main, main / "locales/en"]
    for name in ("pm_pilot_urgent", "pm_pilot_capacity15"):
        sources.extend((main.parent / name, main.parent / name / "locales/en"))
    manifest = repo / "docs/contracts/expansion-v3/manifest.json"
    contract = "expansion-v3-" + hashlib.sha256(manifest.read_bytes()).hexdigest()
    entries = []
    for source in sources:
        package = load_package(source)
        locale = package.locale
        target = args.output / package.bundle.id / locale
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "career_lab.scenarios.v2.rebind",
                "--source",
                str(source),
                "--output",
                str(target),
                "--protocol",
                "scenario-release-v1",
                "--contract-revision",
                contract,
                "--scenario-revision",
                "prepared-protocol-v1",
                "--runtime-revision",
                "prepared-protocol-v1-" + locale,
                "--smoke-database",
                str(args.output / (package.bundle.id + "-" + locale + ".db")),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        module = ScenarioModule(target)
        release = read_release(module.package)
        if release is None:
            raise RuntimeError("Formal CLI did not produce the requested protocol")
        entries.append(
            {
                "root": str(target.resolve()),
                "work_language": locale,
                "scenario_hash": module.package.content_hash,
                "authored_manifest": release.original_release_identity,
                "reviewed_authored_manifest": release.review.reviewed_source_hash,
                "content_unchanged": True,
            }
        )
    index = args.output / "catalog.json"
    index.write_text(json.dumps({"schema_version": 1, "scenarios": entries}, indent=2) + "\n")
    print(index.resolve())


if __name__ == "__main__":
    main()
