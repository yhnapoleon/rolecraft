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
    for command in (pack, reproduce):
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
        else:
            result = reproduce_pack(store, module, auth, args.pack, args.output)
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
