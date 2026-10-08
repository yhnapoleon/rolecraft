"""Local commands. Credentials use the private api_url/session_id/token configuration format."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import quote

from sqlalchemy.exc import SQLAlchemyError

from career_lab.contracts.v2 import ProtocolError
from career_lab.delegations.credentials import load_credentials
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.storage.v2_store import V2Store


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="career-lab-engineer", description="Export and reproduce a fixed PM baseline"
    )
    operations = parser.add_subparsers(dest="engineer_operation", required=True)
    pack = operations.add_parser("pack", help="Export an authorized task package")
    pack.add_argument(
        "--test", action="append", required=True, help="Existing test ID; repeat to select more"
    )
    pack.add_argument("--output", type=Path, required=True)
    reproduce = operations.add_parser(
        "reproduce", help="Re-run recorded tests against their original snapshots; no source writes"
    )
    reproduce.add_argument("--pack", type=Path, required=True)
    reproduce.add_argument("--output", type=Path, required=True)
    probes = operations.add_parser(
        "probes-from-plan", help="Export a saved test plan as unverified review-only candidates"
    )
    probes.add_argument("--product", required=True, help="Existing PM work product ID")
    probes.add_argument("--product-version", type=int, required=True)
    probes.add_argument("--output", type=Path, required=True)
    probes.add_argument(
        "--span",
        action="append",
        default=[],
        help="Confirmed source span START:END; Unicode characters, end exclusive",
    )
    probes.add_argument("--text-field", choices=("content", "body"), default="content")
    probes.add_argument(
        "--confirm-extraction",
        action="store_true",
        help="Explicitly confirm selected source text as test intent, not truth",
    )
    submit = operations.add_parser("submit", help="Validate and retain a configuration submission")
    submit.add_argument("--pack", type=Path, required=True)
    submit.add_argument("--input", type=Path, required=True, help="Frozen submission JSON file")
    submit.add_argument(
        "--output", type=Path, required=True, help="Immutable submission repository"
    )
    for command in (pack, reproduce, probes, submit):
        command.add_argument(
            "--database",
            type=Path,
            required=True,
            help="Existing local SQLite database (read only)",
        )
        command.add_argument(
            "--credentials",
            type=Path,
            required=True,
            help="Private JSON: api_url, session_id, token; mode 0600; never a token in argv",
        )
        command.add_argument(
            "--scenario",
            type=Path,
            required=True,
            help="Trusted installed scenario directory matching this session",
        )
    return run(parser.parse_args(argv))


def run(args: argparse.Namespace) -> int:
    store = None
    try:
        credentials = load_credentials(args.credentials)
        database = args.database.resolve()
        if not database.is_file():
            raise ProtocolError("engineer_database_unavailable")
        module = ScenarioModule(args.scenario)
        store = V2Store("sqlite:///file:" + quote(str(database), safe="/") + "?mode=ro&uri=true")
        store.register_reference_resolver("material", module.reference_resolver, contextual=True)
        auth = store.authenticate(credentials.session_id, credentials.token)
        from .pack import export_pack, reproduce_pack

        if args.engineer_operation == "pack":
            result = export_pack(store, module, auth, args.test, args.output)
        elif args.engineer_operation == "reproduce":
            result = reproduce_pack(store, module, auth, args.pack, args.output)
        elif args.engineer_operation == "submit":
            from .submission import submit_configuration

            result = submit_configuration(store, module, auth, args.pack, args.input, args.output)
        else:
            from .probes import TextSelection, export_candidates

            result = export_candidates(
                store,
                module,
                auth,
                args.product,
                args.product_version,
                args.output,
                TextSelection(args.text_field, tuple(args.span), args.confirm_extraction),
            )
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result["status"] == "behavior_changed" else 0
    except ProtocolError as error:
        print(json.dumps({"status": "failed", "code": error.code}))
        return 1
    except (OSError, ValueError, SQLAlchemyError):
        # No raw database URLs, private filenames, submitted text or credentials.
        print(json.dumps({"status": "failed", "code": "engineer_source_or_configuration_invalid"}))
        return 1
    finally:
        if store is not None:
            store.db.engine.dispose()
