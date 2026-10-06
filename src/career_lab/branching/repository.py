"""Private W10 SQLite repository; public storage mounting belongs to W01/032."""
import json
import sqlite3
import fcntl
from uuid import uuid4
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from career_lab.contracts.v2 import AuthContext, BranchManifest, ProtocolError, canonical, digest


def authorize(auth: AuthContext, parent_session: str, now=None):
    now = now or datetime.now(timezone.utc)
    if auth.session_id != parent_session or "research" not in auth.capabilities:
        raise ProtocolError("research_forbidden", status=403)
    if auth.expires_at is not None and auth.expires_at <= now:
        raise ProtocolError("research_credential_expired", status=403)
    # Object/action-restricted credentials must be expanded and checked by the
    # shared authorization service before requesting an entire research prefix.
    if auth.allowed_objects is not None or auth.allowed_actions is not None:
        raise ProtocolError("restricted_research_requires_scope_check", status=403)


class BranchRepository:
    def __init__(self, path: Path):
        self.path = str(Path(path).resolve())
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables - {"w10_branches", "w10_branch_history", "w10_failures", "sqlite_sequence"}:
                raise ProtocolError("unrelated_database_rejected")
            conn.execute("""CREATE TABLE IF NOT EXISTS w10_branches(
                id TEXT PRIMARY KEY, parent_session TEXT NOT NULL, request_id TEXT NOT NULL,
                request_hash TEXT NOT NULL, manifest TEXT NOT NULL, status TEXT NOT NULL,
                preparation TEXT, restore TEXT, error_code TEXT,
                UNIQUE(parent_session, request_id))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS w10_branch_history(
                branch_id TEXT NOT NULL, revision INTEGER NOT NULL, status TEXT NOT NULL,
                content TEXT NOT NULL, PRIMARY KEY(branch_id, revision))""")

            conn.execute("""CREATE TABLE IF NOT EXISTS w10_failures(
                parent_session TEXT NOT NULL, request_id TEXT NOT NULL,
                request_hash TEXT NOT NULL, code TEXT NOT NULL,
                UNIQUE(parent_session,request_id,request_hash,code))""")

    def record_failure(self, auth, parent_session, request_id, fingerprint, code):
        authorize(auth, parent_session)
        with self.connection() as conn:
            conn.execute("INSERT OR IGNORE INTO w10_failures VALUES(?,?,?,?)",
                         (parent_session, request_id, fingerprint, code))

    def failures(self, auth):
        authorize(auth, auth.session_id)
        with self.connection() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM w10_failures WHERE parent_session=?", (auth.session_id,))]

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def operation(self, branch_id):
        """Kernel-held claim; process exit releases it, active writers are never stolen."""
        directory = Path(self.path + ".locks")
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / digest(branch_id)).open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ProtocolError("branch_operation_in_progress", status=409) from None
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def claim_restore(self, auth, branch_id, parent_digest):
        with self.connection() as conn:
            row = self._row(conn, auth, branch_id)
            if row["status"] == "restored":
                return self._decode(row), None
            prior = json.loads(row["restore"]) if row["restore"] else {}
            confirmed = {"restore_identity_or_state_mismatch", "restore_prefix_mismatch",
                         "restore_prefix_identity_mismatch", "parent_changed_during_restore"}
            if (not row["preparation"] or row["status"] not in {"prepared", "restoring", "unresolved", "failed"}
                    or row["status"] == "failed" and (row["error_code"] in confirmed or prior.get("confirmed_failure"))):
                raise ProtocolError("branch_not_prepared", status=409)
            token = uuid4().hex
            claim = {"claim_token": token, "request_id": "restore-" + branch_id,
                     "attempt": prior.get("attempt", 0) + 1,
                     "recovering": row["status"] != "prepared",
                     "parent_digest": prior.get("parent_digest", parent_digest)}
            conn.execute("UPDATE w10_branches SET status='restoring', restore=? WHERE id=?",
                         (canonical(claim), branch_id))
            self._history(conn, branch_id, "restoring", claim)
            return self._decode(conn.execute("SELECT * FROM w10_branches WHERE id=?", (branch_id,)).fetchone()), token

    def finish_restore(self, auth, branch_id, token, status, *, evidence=None, error_code=None):
        if status not in {"restored", "unresolved", "failed"}:
            raise ValueError("invalid restore completion")
        with self.connection() as conn:
            row = self._row(conn, auth, branch_id)
            if row["status"] == "restored":
                return self._decode(row)  # A late error cannot poison accepted evidence.
            claim = json.loads(row["restore"]) if row["restore"] else {}
            if row["status"] != "restoring" or claim.get("claim_token") != token:
                raise ProtocolError("restore_claim_lost", status=409)
            if status == "restored" and (not evidence or evidence.get("external_calls") != 0 or evidence.get("prefix_equal") is not True):
                raise ProtocolError("restore_evidence_invalid")
            value = {**claim, **(evidence or {}), "error_code": error_code, "confirmed_failure": status == "failed"}
            conn.execute("UPDATE w10_branches SET status=?,restore=?,error_code=? WHERE id=? AND status='restoring'",
                         (status, canonical(value), error_code, branch_id))
            self._history(conn, branch_id, status, value)
            return self._decode(conn.execute("SELECT * FROM w10_branches WHERE id=?", (branch_id,)).fetchone())

    def reserve(self, auth, parent_session, request_id, manifest, source_snapshot_hash):
        authorize(auth, parent_session)
        manifest = BranchManifest.model_validate_json(manifest.model_dump_json())
        identity = {"manifest": manifest.model_dump(mode="json"),
                    "snapshot_hash": source_snapshot_hash,
                    "executor": auth.executor.model_dump(mode="json"),
                    "credential_id": auth.credential_id}
        fingerprint = digest(identity)
        with self.connection() as conn:
            prior = conn.execute("SELECT * FROM w10_branches WHERE parent_session=? AND request_id=?",
                                 (parent_session, request_id)).fetchone()
            if prior:
                if prior["request_hash"] != fingerprint:
                    raise ProtocolError("branch_request_conflict", status=409)
                return self._decode(prior), False
            try:
                conn.execute("INSERT INTO w10_branches VALUES(?,?,?,?,?,?,?,?,?)",
                    (manifest.id, parent_session, request_id, fingerprint,
                     canonical(manifest), "preparing", None, None, None))
            except sqlite3.IntegrityError:
                raise ProtocolError("branch_identity_conflict", status=409) from None
            self._history(conn, manifest.id, "preparing", {"source_snapshot_hash": source_snapshot_hash})
            return self._decode(conn.execute("SELECT * FROM w10_branches WHERE id=?", (manifest.id,)).fetchone()), True

    def prepared(self, auth, branch_id, preparation):
        return self._transition(auth, branch_id, "preparing", "prepared", "preparation", preparation)

    def failed(self, auth, branch_id, code):
        with self.connection() as conn:
            row = self._row(conn, auth, branch_id)
            if row["status"] == "failed":
                if row["error_code"] != code:
                    raise ProtocolError("failure_record_conflict", status=409)
                return self._decode(row)
            if row["status"] != "preparing":
                raise ProtocolError("branch_failure_transition_conflict", status=409)
            conn.execute("UPDATE w10_branches SET status='failed', error_code=? WHERE id=?", (code, branch_id))
            self._history(conn, branch_id, "failed", {"code": code})
            return self._decode(conn.execute("SELECT * FROM w10_branches WHERE id=?", (branch_id,)).fetchone())

    def get(self, auth, branch_id):
        with self.connection() as conn:
            return self._decode(self._row(conn, auth, branch_id))

    def _transition(self, auth, branch_id, expected, status, column, value):
        encoded = canonical(value)
        with self.connection() as conn:
            row = self._row(conn, auth, branch_id)
            if row["status"] == status and row[column] == encoded:
                return self._decode(row)
            if row["status"] != expected:
                raise ProtocolError("branch_transition_conflict", status=409)
            conn.execute(f"UPDATE w10_branches SET status=?, {column}=? WHERE id=?",
                         (status, encoded, branch_id))
            self._history(conn, branch_id, status, value)
            return self._decode(conn.execute("SELECT * FROM w10_branches WHERE id=?", (branch_id,)).fetchone())

    def _row(self, conn, auth, branch_id):
        row = conn.execute("SELECT * FROM w10_branches WHERE id=?", (branch_id,)).fetchone()
        if row is None:
            raise ProtocolError("branch_not_found", status=404)
        authorize(auth, row["parent_session"])
        return row

    def _history(self, conn, branch_id, status, value):
        revision = conn.execute("SELECT COUNT(*) FROM w10_branch_history WHERE branch_id=?", (branch_id,)).fetchone()[0] + 1
        conn.execute("INSERT INTO w10_branch_history VALUES(?,?,?,?)",
                     (branch_id, revision, status, canonical(value)))

    def _decode(self, row):
        result = dict(row)
        for name in ("manifest", "preparation", "restore"):
            result[name] = json.loads(result[name]) if result[name] else None
        if result.get("status") == "restored" and result.get("restore", {}).get("effective_manifest"):
            result["request_manifest"] = result["manifest"]
            result["manifest"] = result["restore"]["effective_manifest"]
        return result
