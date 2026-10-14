"""Continue codes: the way back to a practice from another browser or device.

- ``GET  /sessions/{sid}/continue-code``: whether a code exists. The code is never returned again.
- ``POST /sessions/{sid}/continue-code``: create or replace the practice's one code; shown once.
- ``POST /continue-codes/exchange``: a code, without a bearer, for a new owner credential.

Only the practice's own person may read or create a code. The server keeps a verifier keyed with the
deployment key, never the code. Replacing a code stops the old one at once; access already issued
stays valid, so work queued under it keeps its credential.
"""

import hashlib
import hmac
import secrets
import time
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response
from sqlalchemy import Column, Integer, MetaData, String, Table, delete, insert, select, update

from career_lab.api.modules import public_state
from career_lab.contracts import v2 as C
from career_lab.security.credentials import DeploymentKey, checked_key, signed_credential
from career_lab.storage.v2_store import V2Store, session_owner
from career_lab.storage.v2_tables import v2_credentials, v2_sessions

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford Base32: no I, L, O or U.
LENGTH = 20  # 100 bits.
GROUP = 4
PURPOSE = "continue-code"  # Derivation purpose of owner credentials opened with a code.
WINDOW_SECONDS = 15 * 60
MAX_ATTEMPTS = 10  # Exchange tries per source and window, successful ones included.
_VERIFIER = b"rolecraft-continue-code-v1\x00"
_SOURCE = b"rolecraft-continue-code-source-v1\x00"
_DASHES = frozenset("-\u2010\u2011\u2012\u2013\u2014\u2015\u2212")
_READS_AS = {"O": "0", "I": "1", "L": "1"}

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

# Keyed hash of the client address, never the address.
attempts = Table(
    "v4_continue_code_attempts",
    _META,
    Column("source", String, primary_key=True),
    Column("window_start", Integer, nullable=False),
    Column("used", Integer, nullable=False),
)
clock: Callable[[], float] = time.time


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))


def grouped(code: str) -> str:
    return "-".join(code[i : i + GROUP] for i in range(0, LENGTH, GROUP))


def normalize(text: str) -> str | None:
    """The code as stored, from what a person typed; None when it cannot be a code.

    Full-width forms, case, spaces and dashes are free; O reads as 0, I and L as 1.
    """
    symbols = []
    for character in unicodedata.normalize("NFKC", text).upper():
        if character.isspace() or character in _DASHES:
            continue
        symbol = _READS_AS.get(character, character)
        if symbol not in ALPHABET:
            return None
        symbols.append(symbol)
    return "".join(symbols) if len(symbols) == LENGTH else None


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


def reserve_attempt(store: V2Store, key: DeploymentKey, address: str) -> None:
    """Count one exchange try from this source; the eleventh in fifteen minutes is refused."""
    source = hmac.new(key.secret, _SOURCE + address.encode(), hashlib.sha256).hexdigest()
    now = int(clock())
    with store.db.transaction() as c:
        c.execute(delete(attempts).where(attempts.c.window_start <= now - WINDOW_SECONDS))
        row = (
            c.execute(select(attempts).where(attempts.c.source == source).with_for_update())
            .mappings()
            .first()
        )
        if row is None:
            c.execute(insert(attempts).values(source=source, window_start=now, used=1))
            return
        if row["used"] >= MAX_ATTEMPTS:
            error = C.ProtocolError("continue_code_rate_limited", status=429)
            error.details = {"retry_after_seconds": row["window_start"] + WINDOW_SECONDS - now}
            raise error
        c.execute(update(attempts).where(attempts.c.source == source).values(used=row["used"] + 1))


Identity = Callable[[C.SessionBindings], tuple[str, str | None] | None]


def exchange(
    store: V2Store, identity: Identity, text: str, request_id: str, address: str
) -> dict[str, C.JsonValue]:
    """A new owner credential for the code's practice; the same request returns the same one."""
    key = checked_key(store.credential_key_provider)
    reserve_attempt(store, key, address)
    code = normalize(text)
    if code is None:
        raise C.ProtocolError("continue_code_malformed")
    with store.db.transaction() as c:
        row = (
            c.execute(
                select(codes).where(codes.c.verifier == verifier(key, code)).with_for_update()
            )
            .mappings()
            .first()
        )
        if row is None or row["key_id"] != key.key_id:
            raise C.ProtocolError("continue_code_invalid", status=404)
        sid = row["session_id"]
        session = c.execute(select(v2_sessions).where(v2_sessions.c.id == sid)).mappings().one()
        bindings = C.SessionBindings.model_validate_json(session["bindings"])
        found = identity(bindings)
        if found is None or found[1] not in ("zh", "en"):
            raise C.ProtocolError("continue_code_scenario_unavailable", status=409)
        scenario, language = found
        issuer = C.AuthContext.model_validate_json(
            c.execute(
                select(v2_credentials.c.context).where(v2_credentials.c.id == row["issued_by"])
            ).scalar_one()
        )
        target = session_owner(sid, C.digest([PURPOSE, sid, row["generation"], request_id])[:32])
        held = c.execute(
            select(v2_credentials.c.id).where(v2_credentials.c.id == target.credential_id)
        ).first()
        token = signed_credential(
            c,
            store.credential_key_provider,
            PURPOSE,
            issuer,
            target,
            {"generation": row["generation"], "request_id": request_id},
        )
        if held is None:
            store._credential(c, target, token)
        store._auth(c, target, "read")
        state = C.WorldStateV2.model_validate_json(session["state"])
    return {
        "session": {
            "schema_version": 2,
            "session_id": sid,
            "token": token,
            "state": public_state(state),
            "binding": {
                "protocol": 2,
                "sessionId": sid,
                "workLanguage": language,
                "scenarioHash": bindings.scenario.sha256,
            },
        },
        "scenario": scenario,
    }


def mount_continue_codes(
    app: FastAPI, *, person: Callable[..., C.AuthContext], identity: Identity
) -> None:
    """``person``: the practice's own person with owner rights; ``identity``: a session's
    running scenario name and work language."""
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

    @app.post("/continue-codes/exchange", response_model=C.ContinueCodeExchangeResponse)
    def exchange_continue_code(
        body: C.ContinueCodeExchangeInput, request: Request, response: Response
    ):
        response.headers["Cache-Control"] = "no-store"
        address = request.client.host if request.client else ""
        result = exchange(store, identity, body.code, body.request_id, address)
        return {"schema_version": 2, "result": result}
