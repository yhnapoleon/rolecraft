"""Validate reference-run inputs without model calls or credential discovery."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from career_lab.contracts.v2.core import ProtocolError
from career_lab.reference_agent.suite import load_manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--manifest", type=Path, required=True)
    run = commands.add_parser("run", help="Execute or recover a fixed local checklist")
    for name in ("manifest", "registry", "database", "credentials", "scenario-root", "output"):
        run.add_argument("--" + name, type=Path, required=True)
    run.add_argument("--runtime-id", required=True)
    run.add_argument("--evaluation-id", required=True)
    run.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            manifest = load_manifest(args.manifest)
            report = {"run_id": manifest.id, "protocol_valid": True, "executed": False}
        else:
            from career_lab.reference_agent.runner import run_checklist

            report = run_checklist(
                manifest_path=args.manifest,
                registry_path=args.registry,
                runtime_id=args.runtime_id,
                evaluation_id=args.evaluation_id,
                database=args.database,
                credentials_path=args.credentials,
                scenario_root=args.scenario_root,
                output=args.output,
                resume=args.resume,
            )
    except (ValueError, OSError, SQLAlchemyError) as error:
        report = {
            "error": error.code if isinstance(error, ProtocolError) else "run_input_invalid",
        }
        if args.command == "validate":
            report["executed"] = False
        else:
            report["execution_status"] = "unconfirmed"
            report["recovery"] = "use_same_manifest_and_output"
        print(json.dumps(report, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0 if args.command == "validate" or report["status"] == "completed" else 2
