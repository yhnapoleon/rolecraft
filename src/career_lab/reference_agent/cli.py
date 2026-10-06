"""W09 command registration; global CLI wiring belongs to the integrator."""
import argparse
import json
from pathlib import Path
from .ports import PortError
from .suite import SuiteSpec, validate_suite, run_suite


def register_commands(commands, factory=None):
    parser = commands.add_parser("agent-suite", help="Validate or run a frozen reference-agent suite")
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.set_defaults(w09_factory=factory, w09_handler=execute)
    return parser


def execute(args):
    try:
        spec = SuiteSpec.model_validate_json(args.suite.read_text())
        if args.validate_only:
            rows = validate_suite(spec, args.root)
            result = {"status": "valid", "runs": len(rows), "research_acceptance": "not_assessed"}
        else:
            if args.w09_factory is None:
                raise PortError("w09_integration_factory_not_installed")
            if args.output is None:
                raise PortError("output_required")
            result = run_suite(spec, args.root, args.output, args.w09_factory, resume=args.resume)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if args.validate_only or (
            result["complete"] and all(r["status"] == "completed" for r in result["runs"])
        ) else 2
    except Exception as exc:
        print(json.dumps({"status": "error", "code": exc.code if isinstance(exc, PortError) else type(exc).__name__}))
        return 2


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m career_lab.reference_agent.cli")
    register_commands(parser.add_subparsers(required=True))
    args = parser.parse_args(argv)
    return execute(args)


if __name__ == "__main__":
    raise SystemExit(main())
