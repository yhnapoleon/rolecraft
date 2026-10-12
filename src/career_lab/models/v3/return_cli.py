"""``verify-return``: independent review of a frozen label/evidence return.

Local files only; no training, provider calls or execution of producer commands.
"""

import argparse
import json
from pathlib import Path

from .return_verification import verify_return


def add_parser(commands: argparse._SubParsersAction) -> None:
    verify = commands.add_parser("verify-return", help="Check a frozen label/evidence return")
    verify.add_argument("--dataset-root", type=Path, required=True)
    verify.add_argument("--dataset-hash", required=True)
    verify.add_argument("--predictions", type=Path, required=True)
    verify.add_argument("--partition", default="dev")
    verify.add_argument("--checkpoint-manifest", type=Path)
    verify.add_argument("--registry", type=Path)
    verify.add_argument("--registration-path")
    verify.add_argument("--registration-hash")


def run(args: argparse.Namespace) -> int:
    """Print the report; exit 2 when the return is rejected. Errors propagate to the caller."""
    result = verify_return(
        args.dataset_root,
        args.dataset_hash,
        args.predictions,
        partition=args.partition,
        checkpoint_manifest=args.checkpoint_manifest,
        registry_root=args.registry,
        registration_path=args.registration_path,
        registration_hash=args.registration_hash,
    )
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 2 if result["status"] == "rejected" else 0
