"""Read-only probes for ``scripts/demo/launcher.py check``, run inside the project environment.

Each command prints one JSON object. Nothing here writes to the database, calls a model or
exchanges a continue code (an exchange issues a credential and counts against the
per-source limit); codes are checked against their stored verifiers instead.

    python -m scripts.demo.probe encoder
    python -m scripts.demo.probe registrations
    python -m scripts.demo.probe codes --db <file> --codes <codes.json> --catalog <catalog.json>
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path


def encoder() -> dict:
    """Load the relation encoder the way the recognition layer does, and its stacked ensemble."""
    path = os.environ.get("CAREER_LAB_RELATION_ENCODER")
    if not path:
        return {"configured": False}
    if not Path(path).is_dir():
        return {"configured": True, "ok": False, "reason": "missing"}
    try:
        from career_lab.recognition.encoder_relation import EncoderRelation
        from career_lab.recognition.relation import stack_for

        model = EncoderRelation(path)
        stacked = stack_for(model) is not None
    except ModuleNotFoundError as error:
        return {"configured": True, "ok": False, "reason": "missing_module", "module": error.name}
    except Exception as error:  # noqa: BLE001 - reported by type only, never by content
        return {"configured": True, "ok": False, "reason": type(error).__name__}
    return {"configured": True, "ok": True, "revision": model.revision, "stack": stacked}


def registrations() -> dict:
    """Whether review-page model advice is registered, and whether its registry exists."""
    from career_lab.api.registered_models import configured_registrations

    try:
        configured = configured_registrations()
    except Exception as error:  # noqa: BLE001
        return {"configured": True, "ok": False, "reason": getattr(error, "code", "invalid")}
    if configured is None:
        return {"configured": False}
    tasks = {}
    for task, value in configured.items():
        tasks[task] = (
            getattr(value, "code", type(value).__name__) if isinstance(value, Exception) else "ok"
        )
    root = os.environ.get("CAREER_LAB_MODEL_REGISTRY", "")
    return {
        "configured": True,
        "ok": bool(root) and Path(root).is_dir() and all(v == "ok" for v in tasks.values()),
        "registry_exists": bool(root) and Path(root).is_dir(),
        "tasks": tasks,
    }


def codes(db: Path, listed: Path, catalog: Path) -> dict:
    """Each saved continue code against its stored verifier, key id and installed scenario."""
    from career_lab.api.continue_codes import normalize, verifier
    from career_lab.contracts.v2.core import ProtocolError
    from career_lab.security.credentials import deployment_key

    entries = json.loads(listed.read_text(encoding="utf-8")) if listed.is_file() else []
    if not entries:
        return {"codes": []}
    try:
        key = deployment_key()
    except ProtocolError:
        return {"codes": [{**_public(e), "ok": False, "reason": "no_key"} for e in entries]}
    installed = {
        entry["scenario_hash"]
        for entry in json.loads(catalog.read_text(encoding="utf-8"))["scenarios"]
    }
    connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    results = []
    try:
        for entry in entries:
            code = normalize(entry["code"])
            row = (
                connection.execute(
                    "SELECT session_id, key_id FROM v4_continue_codes WHERE verifier = ?",
                    (verifier(key, code),),
                ).fetchone()
                if code
                else None
            )
            if row is None:
                results.append({**_public(entry), "ok": False, "reason": "unknown_code"})
                continue
            if row[1] != key.key_id:
                results.append({**_public(entry), "ok": False, "reason": "key_changed"})
                continue
            session = connection.execute(
                "SELECT bindings FROM v2_sessions WHERE id = ?", (row[0],)
            ).fetchone()
            scenario = json.loads(session[0])["scenario"]["sha256"] if session else None
            if scenario not in installed:
                results.append({**_public(entry), "ok": False, "reason": "scenario_missing"})
                continue
            results.append({**_public(entry), "ok": True})
    finally:
        connection.close()
    return {"codes": results}


def _public(entry: dict) -> dict:
    """What the report may repeat about a code: never the code itself."""
    return {k: entry.get(k) for k in ("label", "scenario", "language", "status")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("encoder")
    sub.add_parser("registrations")
    listed = sub.add_parser("codes")
    listed.add_argument("--db", type=Path, required=True)
    listed.add_argument("--codes", type=Path, required=True)
    listed.add_argument("--catalog", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "encoder":
        result = encoder()
    elif args.command == "registrations":
        result = registrations()
    else:
        result = codes(args.db, args.codes, args.catalog)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
