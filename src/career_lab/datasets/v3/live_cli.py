"""Local operator commands for explicit consent and authorized historical export."""

import argparse
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI

from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts.v2 import AuthContext, ProtocolError, VersionPoint
from career_lab.research.authorization import issue, public_identity

from .common import json_bytes, read_json


def connection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database-url")
    parser.add_argument("--session")
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--scenario-root", type=Path)
    parser.add_argument("--point", type=Path)
    parser.add_argument("--key-file", type=Path)


def register_authorization(commands: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = commands.add_parser("authorize", help="Record explicit research-purpose consent")
    connection_arguments(parser)
    parser.add_argument(
        "--purpose", required=True, choices=("dataset_export", "branch_restore", "engineer_report")
    )
    parser.add_argument("--consent", action="store_true", required=True)
    parser.add_argument("--expires-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


@contextmanager
def connection(args: argparse.Namespace) -> Iterator[tuple[FastAPI, AuthContext, VersionPoint]]:
    if not all((args.database_url, args.session, args.token_file, args.point)):
        raise ProtocolError("live_connection_required")
    point = VersionPoint.model_validate(read_json(args.point))
    app = create_runtime_app(args.database_url, provider="local", scenario_root=args.scenario_root)
    try:
        auth = app.state.v2_store.authenticate(args.session, args.token_file.read_text().strip())
        app.state.v2_store.authorize(auth, "read")
        # Confirm the requested historical boundary through the existing public read port.
        app.state.v2_store.query_at(auth, point, lambda view: view.state)
        yield app, auth, point
    finally:
        app.state.store.close()


def authorize(args: argparse.Namespace) -> dict[str, object]:
    if args.key_file is None:
        raise ProtocolError("research_authority_key_required")
    with connection(args) as (_, auth, point):
        signed = issue(
            auth,
            purpose=args.purpose,
            through_point=point,
            expires_at=datetime.fromisoformat(args.expires_at),
            key=args.key_file.read_bytes(),
        )
    with os.fdopen(
        os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
    ) as handle:
        handle.write(json_bytes(signed.model_dump(mode="json")))
        handle.flush()
        os.fsync(handle.fileno())
    return public_identity(signed.authorization)


def export_live(args: argparse.Namespace) -> dict[str, object]:
    if args.authorization is None or args.key_file is None:
        raise ProtocolError("research_authorization_required", status=403)
    from career_lab.api.dataset_export import capture_session
    from career_lab.api.scenario_history import ScenarioReadCatalog
    from career_lab.contracts.v2 import SourceIdentity
    from career_lab.research.authorization import SignedAuthorization
    from career_lab.runtime.provenance import execution_identity

    from .live import save_capture

    signed = SignedAuthorization.model_validate(read_json(args.authorization))
    code = execution_identity()
    if code.commit is None or code.snapshot is None:
        raise ProtocolError("export_code_identity_unavailable")
    identity = SourceIdentity(base_commit=code.commit, source_digest=code.snapshot)
    with connection(args) as (app, auth, point):
        bindings = app.state.v2_store.query_at(auth, point, lambda view: view.bindings)
        catalog = ScenarioReadCatalog(
            app.state.scenario_v2,
            os.getenv("CAREER_LAB_SCENARIO_ARCHIVE", "runs/local/scenario-archive"),
        )
        module = catalog.resolve(bindings)
        capture = capture_session(
            app.state.gateway,
            module,
            auth,
            signed,
            args.key_file.read_bytes(),
            identity,
            point,
        )
        return save_capture(args.output, capture)
