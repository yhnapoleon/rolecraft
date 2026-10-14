"""Continue codes: the way back to a practice from another browser or device.

- ``GET  /sessions/{sid}/continue-code``: whether a code exists. The code is never returned again.
- ``POST /sessions/{sid}/continue-code``: create or replace the practice's one code; shown once.

Only the practice's own person may do either. The server keeps a verifier keyed with the deployment
key, never the code. Replacing a code stops the old one at once.
"""

import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Response
from sqlalchemy import Column, Integer, MetaData, String, Table, insert, select, update

from career_lab.contracts import v2 as C
from career_lab.security.credentials import DeploymentKey, checked_key
from career_lab.storage.v2_store import V2Store

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford Base32: no I, L, O or U.
LENGTH = 20  # 100 bits.
GROUP = 4
_VERIFIER = b"rolecraft-continue-code-v1\x00"

_META = MetaData()
# A separate integration table; the frozen v2 tables are not altered.
codes = Table(
    "v4_continue_codes",
    _META,
    Column("session_id", String, primary_key=True),
    Column("verifier", String, nullable=False, unique=True),
    Column("key_id", String, nullable=False),
    Column("generation", Integer, nullable=False),
    Column("issued_by", String, nullable=False),
    Column("created_at", String, nullable=False),
)


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))


def grouped(code: str) -> str:
    return "-".join(code[i : i + GROUP] for i in range(0, LENGTH, GROUP))


def verifier(key: DeploymentKey, code: str) -> str:
    return hmac.new(key.secret, _VERIFIER + code.encode(), hashlib.sha256).hexdigest()


def status(store: V2Store, session_id: str) -> dict[str, C.JsonValue]:
    with store.db.engine.connect() as c:
        row = c.execute(select(codes).where(codes.c.session_id == session_id)).mappings().first()
    if row is None:
        return {"exists": False, "generation": None, "created_at": None}
    return {"exists": True, "generation": row["generation"], "created_at": row["created_at"]}


def issue(store: V2Store, auth: C.AuthContext, expected_generation: int) -> dict[str, C.JsonValue]:
    """Create the code, or replace the one the person saw. A concurrent replacement wins once."""
    key = checked_key(store.credential_key_provider)
    code = new_code()
    created_at = datetime.now(UTC).isoformat()
    with store.db.transaction() as c:
        store._auth(c, auth, "delegate")
        row = (
            c.execute(select(codes).where(codes.c.session_id == auth.session_id).with_for_update())
            .mappings()
            .first()
        )
        current = row["generation"] if row else 0
        if current != expected_generation:
            raise C.ProtocolError("continue_code_changed", status=409)
        values = {
            "verifier": verifier(key, code),
            "key_id": key.key_id,
            "generation": current + 1,
            "issued_by": auth.credential_id,
            "created_at": created_at,
        }
        if row is None:
            c.execute(insert(codes).values(session_id=auth.session_id, **values))
        else:
            c.execute(update(codes).where(codes.c.session_id == auth.session_id).values(**values))
    return {"code": grouped(code), "generation": current + 1, "created_at": created_at}


def mount_continue_codes(app: FastAPI, *, person: Callable[..., C.AuthContext]) -> None:
    """``person`` is the route dependency for the practice's own person with owner rights."""
    store: V2Store = app.state.v2_store
    _META.create_all(store.db.engine)

    @app.get("/sessions/{session_id}/continue-code", response_model=C.ContinueCodeStatusResponse)
    def read_continue_code(auth: Annotated[C.AuthContext, Depends(person)]):
        return {"schema_version": 2, "result": status(store, auth.session_id)}

    @app.post("/sessions/{session_id}/continue-code", response_model=C.ContinueCodeIssueResponse)
    def create_continue_code(
        body: C.ContinueCodeIssueInput,
        response: Response,
        auth: Annotated[C.AuthContext, Depends(person)],
    ):
        response.headers["Cache-Control"] = "no-store"
        return {"schema_version": 2, "result": issue(store, auth, body.expected_generation)}
