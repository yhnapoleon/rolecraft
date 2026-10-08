"""Register and inspect immutable file bundles; execution is verified by the runner."""

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from pydantic import JsonValue

from career_lab.contracts.v2.core import FileRef, ProtocolError
from career_lab.registry.v3.store import BundleRegistry


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--registry", type=Path, required=True)
    commands = root.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register")
    register.add_argument("--kind", choices=("runtime", "evaluation", "candidate"), required=True)
    register.add_argument("--source", type=Path, required=True)
    register.add_argument("--manifest", required=True)
    register.add_argument("--sha256", required=True)
    load = commands.add_parser("load")
    load.add_argument("identity")
    for name in ("bind", "compare"):
        command = commands.add_parser(name)
        command.add_argument("--runtime", required=True)
        command.add_argument("--evaluation", required=True)
        if name == "compare":
            command.add_argument("--candidate-runtime", required=True)
            command.add_argument("--candidate-evaluation", required=True)
    return root


def execute(args: argparse.Namespace) -> dict[str, JsonValue]:
    registry = BundleRegistry(args.registry)
    if args.command == "register":
        identity = registry.register(
            args.kind, args.source, FileRef(path=args.manifest, sha256=args.sha256)
        )
        return {"identity": identity, "execution_verified": False}
    if args.command in {"bind", "compare"}:
        binding = registry.bind(args.runtime, args.evaluation)
        if args.command == "compare":
            candidate = registry.bind(args.candidate_runtime, args.candidate_evaluation)
            registry.compare(binding, candidate)
            return {"comparable": True, "execution_verified": False}
        return {"binding": asdict(binding), "execution_verified": False}
    return {
        "identity": args.identity,
        "manifest": registry.load(args.identity).model_dump(mode="json"),
        "execution_verified": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = execute(args)
    except (ValueError, OSError) as error:
        result = {
            "error": error.code if isinstance(error, ProtocolError) else "registry_input_invalid",
            "execution_verified": False,
        }
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0
