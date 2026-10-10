"""Validate reference-run inputs without model calls or credential discovery."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from career_lab.contracts.v2.core import ProtocolError
from career_lab.reference_agent.loop import run_loop
from career_lab.reference_agent.runner import run_checklist
from career_lab.reference_agent.suite import load_manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--manifest", type=Path, required=True)
    run = commands.add_parser("run", help="Execute or recover a fixed local checklist")
    loop = commands.add_parser("loop", help="Run or recover an ordinary or active tool loop")
    for command in (run, loop):
        for name in ("manifest", "registry", "database", "credentials", "scenario-root", "output"):
            command.add_argument("--" + name, type=Path, required=True)
        command.add_argument("--runtime-id", required=True)
        command.add_argument("--evaluation-id", required=True)
        command.add_argument("--resume", action="store_true")
    loop.add_argument("--strategy", choices=("ordinary", "active"), required=True)
    loop.add_argument("--goal", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            manifest = load_manifest(args.manifest)
            report = {"run_id": manifest.id, "protocol_valid": True, "executed": False}
        else:
            if args.command == "loop":
                runner = run_loop
                strategy = {"strategy": args.strategy, "goal": args.goal}
            else:
                runner = run_checklist
                strategy = {}
            report = runner(
                manifest_path=args.manifest,
                registry_path=args.registry,
                runtime_id=args.runtime_id,
                evaluation_id=args.evaluation_id,
                database=args.database,
                credentials_path=args.credentials,
                scenario_root=args.scenario_root,
                output=args.output,
                resume=args.resume,
                **strategy,
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
