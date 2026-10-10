"""Check or refresh the protected release identities in tests/regression/release-identity.json.

Run --check at any time. Run --refresh only after an authorized regeneration of frozen exports:
it recomputes every existing protected sha256 from the current tree and adds the given paths.
"commit", "scenarios" and "scope" are never changed.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IDENTITY = ROOT / "tests/regression/release-identity.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(identity: Path, root: Path) -> list[str]:
    """Same semantics as compare.protected_changes(), for any identity file and root."""
    expected = json.loads(identity.read_text())["protected"]
    return [
        "protected release file changed: " + name
        for name, sha in expected.items()
        if not (root / name).is_file() or digest(root / name) != sha
    ]


def refresh(identity: Path, root: Path, added: list[str]) -> dict[str, list[str]]:
    data = json.loads(identity.read_text())
    protected = data["protected"]
    missing = [name for name in [*protected, *added] if not (root / name).is_file()]
    if missing:
        raise SystemExit("missing protected file: " + ", ".join(sorted(set(missing))))
    current = {name: digest(root / name) for name in sorted({*protected, *added})}
    changed = sorted(name for name in protected if protected[name] != current[name])
    new = sorted(name for name in current if name not in protected)
    data["protected"] = current
    identity.write_text(json.dumps(data, indent=2) + "\n")
    return {"changed": changed, "added": new}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--refresh", nargs="*", metavar="PATH")
    args = parser.parse_args()
    if args.check:
        problems = check(IDENTITY, ROOT)
        print("\n".join(problems + [f"Release identity: {len(problems)} problems"]))
        sys.exit(bool(problems))
    print(json.dumps(refresh(IDENTITY, ROOT, args.refresh), indent=2))


if __name__ == "__main__":
    main()
