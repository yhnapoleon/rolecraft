"""Module CLI registration. Shared CLI and real factories are integrator-owned."""
import argparse
import json
from pathlib import Path
from career_lab.contracts.v2 import SnapshotExport, ProtocolError
from .prefix import compare_prefix


def register_commands(commands, factory=None):
    parser = commands.add_parser("branch", help="Research branch tools")
    operations = parser.add_subparsers(dest="branch_operation", required=True)
    create = operations.add_parser("create")
    create.add_argument("--request", type=Path, required=True)
    compare = operations.add_parser("compare")
    compare.add_argument("--expected-prefix", type=Path, required=True)
    compare.add_argument("--actual-prefix", type=Path, required=True)
    parser.set_defaults(w10_factory=factory, w10_handler=execute)
    return parser


def execute(args):
    try:
        if args.branch_operation == "create":
            if args.w10_factory is None:
                raise ProtocolError("w10_factory_not_installed", status=503)
            result = args.w10_factory(json.loads(args.request.read_text()))
        else:
            result = compare_prefix(SnapshotExport.model_validate_json(args.expected_prefix.read_text()),
                                    SnapshotExport.model_validate_json(args.actual_prefix.read_text()))
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("equal", result.get("status") == "restored") else 2
    except Exception as exc:
        print(json.dumps({"status": "error", "code": exc.code if isinstance(exc, ProtocolError) else type(exc).__name__}))
        return 2


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m career_lab.branching.cli")
    register_commands(parser.add_subparsers(required=True))
    return execute(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
