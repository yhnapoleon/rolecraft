"""Preserve exact historical scenario bytes from local Git for read-only recovery."""

import argparse, hashlib, json, subprocess, tempfile
from pathlib import Path
from types import SimpleNamespace
from career_lab.api.scenario_history import ScenarioReadCatalog, load_immutable_content


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("commits", nargs="+")
    parser.add_argument("--archive", type=Path, default=Path("runs/local/scenario-archive"))
    parser.add_argument("--source-root", default="scenarios/pm_pilot/v2")
    args = parser.parse_args()
    for revision in args.commits:
        commit = (
            subprocess.check_output(["git", "rev-parse", "--verify", revision + "^{commit}"])
            .decode()
            .strip()
        )
        raw = subprocess.check_output(
            ["git", "show", commit + ":" + args.source_root + "/manifest.json"]
        )
        manifest = json.loads(raw)
        with tempfile.TemporaryDirectory(prefix="rolecraft-scenario-archive-") as temp:
            root = Path(temp)
            (root / "manifest.json").write_bytes(raw)
            for ref in manifest["files"]:
                path = root / ref["path"]
                if not path.resolve().is_relative_to(root):
                    raise ValueError("Invalid archived path")
                data = subprocess.check_output(
                    ["git", "show", commit + ":" + args.source_root + "/" + ref["path"]]
                )
                assert hashlib.sha256(data).hexdigest() == ref["sha256"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            package = load_immutable_content(root)
            ScenarioReadCatalog(SimpleNamespace(package=package), args.archive)
            print(
                json.dumps(
                    {
                        "commit": commit,
                        "scenario_hash": package.content_hash,
                        "archive": str((args.archive / package.content_hash).resolve()),
                    }
                )
            )


if __name__ == "__main__":
    main()
