"""Validate an author candidate; publication requires trusted integration inputs."""

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from pydantic import JsonValue

from career_lab.contracts.v2.core import ProtocolError
from career_lab.scenario_compiler.boundaries import validate_boundary
from career_lab.scenario_compiler.candidates import (
    EvaluationIdentity,
    attempt_summary,
    build_candidate,
    publication_candidate,
    validate_candidate,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Check an unpublished author declaration")
    source = validate.add_mutually_exclusive_group(required=True)
    source.add_argument("--declaration", type=Path)
    source.add_argument("--candidate", type=Path)
    build = commands.add_parser("build", help="Freeze an unpublished scenario candidate")
    for name in ("source", "declaration", "output"):
        build.add_argument("--" + name, type=Path, required=True)
    for name in (
        "author-id",
        "revision",
        "evaluation-id",
        "evaluation-revision",
        "evaluation-sha256",
    ):
        build.add_argument("--" + name, required=True)
    publish = commands.add_parser("publish", help="Check trusted publication prerequisites")
    publish.add_argument("--candidate", type=Path, required=True)
    attempts = commands.add_parser("attempts", help="Count every candidate generation attempt")
    attempts.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "validate" and args.declaration is not None:
        report = declaration_report(args.declaration)
    else:
        try:
            report = candidate_command(args)
        except (OSError, ValueError) as error:
            report = {
                "status": "invalid",
                "published": False,
                "error_code": error.code
                if isinstance(error, ProtocolError)
                else "candidate_input_invalid",
            }
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    return 0 if args.command == "attempts" and "error_code" not in report else 2


def candidate_command(args: argparse.Namespace) -> dict[str, JsonValue]:
    if args.command == "attempts":
        return attempt_summary(args.root)
    if args.command == "build":
        return build_candidate(
            source=args.source,
            declaration=args.declaration,
            output=args.output,
            author_id=args.author_id,
            revision=args.revision,
            evaluation=EvaluationIdentity(
                id=args.evaluation_id,
                revision=args.evaluation_revision,
                sha256=args.evaluation_sha256,
            ),
        )
    if args.command == "publish":
        return publication_candidate(args.candidate)
    return validate_candidate(args.candidate)


def declaration_report(path: Path) -> dict[str, JsonValue]:
    try:
        value = json.loads(path.read_bytes())
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
    return report
