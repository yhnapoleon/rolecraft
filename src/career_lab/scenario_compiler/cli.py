"""Validate an author candidate; publication requires trusted integration inputs."""

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from career_lab.scenario_compiler.boundaries import validate_boundary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Check an unpublished author declaration")
    validate.add_argument("--declaration", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = json.loads(args.declaration.read_bytes())
    except (ValueError, OSError):
        report = {
            "status": "invalid",
            "published": False,
            "issues": [{"code": "declaration_unreadable", "location": "declaration"}],
        }
    else:
        # Trusted confirmation and installed effects have no public reader yet.
        # Author-controlled files/flags must never supply those authority inputs.
        result = validate_boundary(value, installed_effects={}, confirmed_digest=None)
        report = {
            "status": result.status,
            "published": False,
            "issues": [asdict(issue) for issue in result.issues],
        }
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    return 2
