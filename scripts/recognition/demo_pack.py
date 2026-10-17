"""Demo session pack: export fully played practice sessions, import them anywhere.

    # export (read-only on the source database)
    python -m scripts.recognition.demo_pack export --db runs/local/dev/rolecraft.db \
        --session <sid> --label "pm_pilot 中文：完整一局" [--session ... --label ...] \
        --out demo/demo-pack-v1.json
    # import into another deployment's database, then print one continue code per session
    python -m scripts.recognition.demo_pack import --db <target.db> --pack demo/demo-pack-v1.json
    # list what a pack holds
    python -m scripts.recognition.demo_pack show --pack demo/demo-pack-v1.json

The pack copies every row of each session (objects, events, transactions, snapshots, jobs,
recognition records inside the feedback/test/reply objects), keeping the session id; no
model is called on import. Rows that depend on the source deployment's key (continue codes,
derived credentials) are not copied: import mints a fresh continue code with the target's
CAREER_LAB_CREDENTIAL_KEY / _KEY_ID. The target must have the same scenario packages
installed (same manifest hashes, e.g. from this repository); no restart is needed after
import. Open the code on the home page under 「有继续码？」.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

FORMAT = "rolecraft-demo-pack-v1"
BY_SESSION = (
    "v2_sessions",
    "v2_credentials",
    "v2_objects",
    "v2_heads",
    "v2_relations",
    "v2_events",
    "v2_transactions",
    "v2_snapshots",
    "v2_external_refs",
    "v2_request_meta",
    "v2_role_model_calls",
    "v2_delegation_job_limits",
    "v2_restores",
)
SESSION_COLUMN = {"v2_sessions": "id", "v2_restores": "target_session_id"}
TABLES = (*BY_SESSION, "jobs", "job_times")


def _rows(c: sqlite3.Connection, sql: str, args=()) -> list[dict]:
    cur = c.execute(sql, args)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row, strict=False)) for row in cur.fetchall()]


def _schema(c: sqlite3.Connection) -> dict[str, str]:
    marks = ",".join("?" * len(TABLES))
    return dict(
        c.execute(
            f"SELECT name, sql FROM sqlite_master WHERE type='table' AND name IN ({marks})", TABLES
        )
    )


def export_session(c: sqlite3.Connection, sid: str, tables: set[str], catalog: dict) -> dict:
    rows: dict[str, list[dict]] = {}
    for table in BY_SESSION:
        if table in tables:
            column = SESSION_COLUMN.get(table, "session_id")
            rows[table] = _rows(c, f"SELECT * FROM {table} WHERE {column} = ?", (sid,))
    if not rows.get("v2_sessions"):
        raise SystemExit(f"session {sid} not found")
    jobs = _rows(
        c,
        (
            "SELECT * FROM jobs WHERE request_key LIKE ? OR json_extract(payload, "
            "'$.context.session_id') = ?"
        ),
        (sid + ":%", sid),
    )
    rows["jobs"] = jobs
    ids = [j["id"] for j in jobs]
    rows["job_times"] = (
        _rows(c, f"SELECT * FROM job_times WHERE id IN ({','.join('?' * len(ids))})", ids)
        if ids and "job_times" in tables
        else []
    )
    session = rows["v2_sessions"][0]
    state = json.loads(session["state"])
    manifest = (json.loads(session["bindings"]).get("scenario") or {}).get("sha256")
    scenario, language = catalog.get(manifest, (None, None))
    return {
        "session_id": sid,
        "scenario": scenario,
        "work_language": language,
        "scenario_manifest_sha256": manifest,
        "status": state.get("status"),
        "rows": rows,
    }


def read_catalog(path: str | None) -> dict[str, tuple[str, str]]:
    """manifest sha256 -> (registered scenario name, work language), from a dev catalog."""
    if not path or not Path(path).is_file():
        return {}
    found = {}
    for row in json.loads(Path(path).read_text(encoding="utf-8"))["scenarios"]:
        bundle = json.loads((Path(row["root"]) / "manifest.json").read_text(encoding="utf-8"))
        found[row["scenario_hash"]] = (bundle["id"] + "_v2", row["work_language"])
    return found


def cmd_export(args) -> int:
    if len(args.label) not in (0, len(args.session)):
        raise SystemExit("give one --label per --session, or none")
    c = sqlite3.connect(f"file:{Path(args.db).resolve().as_posix()}?mode=ro", uri=True)
    schema = _schema(c)
    catalog = read_catalog(args.catalog)
    sessions = []
    for i, sid in enumerate(args.session):
        entry = export_session(c, sid, set(schema), catalog)
        entry["label"] = args.label[i] if args.label else sid
        sessions.append(entry)
        counts = {t: len(v) for t, v in entry["rows"].items() if v}
        print(entry["label"], sid, entry["status"], counts)
    pack = {
        "format": FORMAT,
        "created": datetime.now(UTC).isoformat(),
        "schema": schema,
        "sessions": sessions,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(pack, ensure_ascii=False, indent=1) + "\n").encode()
    # Snapshots repeat the whole state per revision; .json.gz keeps the pack small in git.
    out.write_bytes(gzip.compress(raw, mtime=0) if out.suffix == ".gz" else raw)
    print("wrote", out, f"{out.stat().st_size / 1024:.0f} KB")
    return 0


def read_pack(path: str) -> dict:
    raw = Path(path).read_bytes()
    return json.loads(gzip.decompress(raw) if path.endswith(".gz") else raw)


def _owner(rows: list[dict]) -> dict | None:
    for row in rows:
        context = json.loads(row["context"])
        if (
            not row["revoked"]
            and (context.get("executor") or {}).get("kind") == "human"
            and "delegate" in (context.get("capabilities") or [])
        ):
            return context
    return None


def import_session(c: sqlite3.Connection, entry: dict, replace: bool) -> bool:
    sid = entry["session_id"]
    if c.execute("SELECT 1 FROM v2_sessions WHERE id = ?", (sid,)).fetchone():
        if not replace:
            return False
        for table in BY_SESSION:
            column = SESSION_COLUMN.get(table, "session_id")
            c.execute(f"DELETE FROM {table} WHERE {column} = ?", (sid,))
        ids = [j["id"] for j in entry["rows"].get("jobs", [])]
        if ids:
            marks = ",".join("?" * len(ids))
            c.execute(f"DELETE FROM jobs WHERE id IN ({marks})", ids)
            c.execute(f"DELETE FROM job_times WHERE id IN ({marks})", ids)
        c.execute("DELETE FROM v4_continue_codes WHERE session_id = ?", (sid,))
    for table, rows in entry["rows"].items():
        for row in rows:
            if table == "jobs" and row["status"] in ("queued", "running"):
                # Never let the target's worker pick an imported job up and call a model.
                row = {
                    **row,
                    "status": "failed",
                    "lease_token": None,
                    "lease_until": 0,
                    "error": "imported",
                }
            names = list(row)
            c.execute(
                f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join('?' * len(names))})",
                [row[n] for n in names],
            )
    return True


def cmd_import(args) -> int:
    pack = read_pack(args.pack)
    if pack.get("format") != FORMAT:
        raise SystemExit("not a demo pack")
    from career_lab.api import continue_codes
    from career_lab.contracts import v2 as C
    from career_lab.storage.v2_store import V2Store

    db = Path(args.db).resolve()
    store = V2Store("sqlite:///" + db.as_posix())  # creates the v2 and job tables if missing
    continue_codes._META.create_all(store.db.engine)
    c = sqlite3.connect(db)
    present = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, sql in pack["schema"].items():
        if table not in present and sql:
            c.execute(sql)
    hashes = None
    catalog = args.catalog
    if catalog and Path(catalog).is_file():
        hashes = {
            s["scenario_hash"]
            for s in json.loads(Path(catalog).read_text(encoding="utf-8"))["scenarios"]
        }
    results = []
    with c:
        for entry in pack["sessions"]:
            if hashes is not None and entry["scenario_manifest_sha256"] not in hashes:
                print(
                    f"! {entry['label']}: scenario "
                    f"{entry['scenario_manifest_sha256'][:12]} is not in {catalog}"
                )
            done = import_session(c, entry, args.replace)
            results.append((entry, done))
    c.close()
    print()
    for entry, done in results:
        if not done:
            print(
                f"- {entry['label']}: already present (use --replace to overwrite); a new "
                "code is still issued"
            )
        owner = _owner(entry["rows"]["v2_credentials"])
        if owner is None:
            print(f"- {entry['label']}: no owner credential, cannot issue a continue code")
            continue
        auth = C.AuthContext.model_validate(owner)
        generation = continue_codes.status(store, entry["session_id"])["generation"] or 0
        code = continue_codes.issue(store, auth, generation)["code"]
        print(
            f"{code}  {entry['label']}  ({entry['scenario']}, {entry['work_language']}, "
            f"{entry['status']})"
        )
    return 0


def cmd_show(args) -> int:
    pack = read_pack(args.pack)
    print(pack["format"], pack["created"])
    for entry in pack["sessions"]:
        counts = {t: len(v) for t, v in entry["rows"].items() if v}
        print(
            f"- {entry['label']}  {entry['scenario']} {entry['work_language']} "
            f"{entry['status']}  {counts}"
        )
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="demo_pack")
    sub = parser.add_subparsers(dest="command", required=True)
    e = sub.add_parser("export")
    e.add_argument("--db", required=True)
    e.add_argument("--session", action="append", required=True)
    e.add_argument("--label", action="append", default=[])
    e.add_argument("--out", required=True)
    e.add_argument("--catalog", default="runs/local/dev/catalog.json", help="names the scenarios")
    i = sub.add_parser("import")
    i.add_argument("--db", required=True)
    i.add_argument("--pack", required=True)
    i.add_argument("--replace", action="store_true")
    i.add_argument(
        "--catalog", default=None, help="warn when a session's scenario is not installed"
    )
    s = sub.add_parser("show")
    s.add_argument("--pack", required=True)
    args = parser.parse_args(argv)
    return {"export": cmd_export, "import": cmd_import, "show": cmd_show}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
