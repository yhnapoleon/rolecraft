"""``verify-return``: independent review of a frozen label/evidence return.

Local files only; no training, provider calls or execution of producer commands. The held-out
test split opens once, behind a freeze, an approved campaign and an exclusively created ledger
record; there is deliberately no option to confirm, force or repeat an opening.
"""

import argparse
import json
from pathlib import Path

from career_lab.contracts.v2.core import ProtocolError

from .held_out import HeldOutRequest
from .return_verification import verify_return

HELD_OUT_OPTIONS = ("freeze", "freeze_hash", "campaign", "campaign_hash", "ledger", "operator")


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
    held_out = verify.add_argument_group(
        "held-out test (--partition test)",
        "The approval is the campaign file; the opening is recorded once under --ledger.",
    )
    held_out.add_argument("--freeze", type=Path, help="Freeze record; its folder is the root")
    held_out.add_argument("--freeze-hash")
    held_out.add_argument("--campaign", type=Path, help="Approved TestCampaign in the same root")
    held_out.add_argument("--campaign-hash")
    held_out.add_argument("--ledger", type=Path, help="Opening records: <ledger>/<dataset>/test.json")
    held_out.add_argument("--operator", help="Who runs this opening (recorded)")


def run(args: argparse.Namespace) -> int:
    """Print the report; exit 2 when the return is rejected or a check refuses it."""
    supplied = {name: getattr(args, name) for name in HELD_OUT_OPTIONS}
    held_out = HeldOutRequest(**supplied) if any(v is not None for v in supplied.values()) else None
    try:
        result = verify_return(
            args.dataset_root,
            args.dataset_hash,
            args.predictions,
            partition=args.partition,
            checkpoint_manifest=args.checkpoint_manifest,
            registry_root=args.registry,
            registration_path=args.registration_path,
            registration_hash=args.registration_hash,
            held_out=held_out,
        )
    except ProtocolError as error:
        print(
            json.dumps(
                {
                    "error": error.code,
                    "status": error.status,
                    "record_id": getattr(error, "record_id", None),
                    "quality_validated": False,
                    "message": str(error),
                },
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 2 if result["status"] == "rejected" else 0
