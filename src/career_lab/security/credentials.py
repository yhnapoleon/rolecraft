"""Deterministic credentials require a deployment secret, never a DB digest alone."""

import hashlib
import hmac
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import Column, String, Table, insert, select
from sqlalchemy.engine import Connection

from career_lab.contracts.v2 import AuthContext, ProtocolError, canonical, digest
from career_lab.storage.database import metadata
from career_lab.storage.v2_tables import v2_credentials


@dataclass(frozen=True)
class DeploymentKey:
    key_id: str
    secret: bytes = field(repr=False)


def deployment_key() -> DeploymentKey:
    key_id = os.getenv("CAREER_LAB_CREDENTIAL_KEY_ID", "")
    secret = os.getenv("CAREER_LAB_CREDENTIAL_KEY", "").encode()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key_id) or len(secret) < 32:
        raise ProtocolError("credential_derivation_unavailable", status=503)
    return DeploymentKey(key_id, secret)


def derive_credential(
    provider: Callable[[], DeploymentKey],
    purpose: str,
    owner: AuthContext,
    owner_digest: str,
    target: AuthContext,
    request: object,
) -> tuple[str, str]:
    try:
        key = provider()
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key.key_id)
            or not isinstance(key.secret, bytes)
            or len(key.secret) < 32
        ):
            raise ValueError("invalid deployment key")
    except Exception:
        raise ProtocolError("credential_derivation_unavailable", status=503) from None
    body = canonical(
        {
            "version": 1,
            "key_id": key.key_id,
            "purpose": purpose,
            "owner": owner.model_dump(mode="json"),
            "owner_digest": owner_digest,
            "target": target.model_dump(mode="json"),
            "request": request,
        }
    )
    return key.key_id, hmac.new(key.secret, body.encode(), hashlib.sha256).hexdigest()


# Additive provenance: no secrets and no changes to the historical credential row.

derivations = Table(
    "v2_credential_derivations",
    metadata,
    Column("credential_id", String, primary_key=True),
    Column("purpose", String, nullable=False),
    Column("scheme", String, nullable=False),
    Column("key_id", String, nullable=False),
    Column("fingerprint", String, nullable=False),
    Column("token_hash", String, nullable=False),
)


aliases = Table(
    "v2_credential_aliases",
    metadata,
    Column("token_hash", String, primary_key=True),
    Column("credential_id", String, nullable=False),
)


def signed_credential(
    connection: Connection,
    provider: Callable[[], DeploymentKey],
    purpose: str,
    owner: AuthContext,
    target: AuthContext,
    request: object,
) -> str:
    owner_digest = connection.execute(
        select(v2_credentials.c.token_hash).where(v2_credentials.c.id == owner.credential_id)
    ).scalar_one()
    identity = digest(
        {
            "purpose": purpose,
            "owner": owner.model_dump(mode="json"),
            "owner_digest": owner_digest,
            "target": target.model_dump(mode="json"),
            "request": request,
        }
    )
    previous = (
        connection.execute(
            select(derivations).where(derivations.c.credential_id == target.credential_id)
        )
        .mappings()
        .first()
    )
    if previous and (previous["scheme"] != "hmac-sha256-v1" or previous["purpose"] != purpose):
        raise ProtocolError("credential_derivation_unavailable", status=503)
    if previous and previous["fingerprint"] != identity:
        raise ProtocolError("credential_request_reused", status=409)
    key_id, token = derive_credential(provider, purpose, owner, owner_digest, target, request)
    token_hash = digest(token)
    if previous:
        if previous["key_id"] != key_id or previous["token_hash"] != token_hash:
            raise ProtocolError("credential_derivation_unavailable", status=503)

        stored_hash = connection.execute(
            select(v2_credentials.c.token_hash).where(
                v2_credentials.c.id == target.credential_id,
            )
        ).scalar_one_or_none()
        alias = connection.execute(
            select(aliases.c.credential_id).where(
                aliases.c.token_hash == token_hash,
                aliases.c.credential_id == target.credential_id,
            )
        ).scalar_one_or_none()
        if stored_hash is None or (stored_hash != token_hash and alias is None):
            raise ProtocolError("credential_derivation_unavailable", status=503)
    else:
        old = (
            connection.execute(
                select(v2_credentials).where(v2_credentials.c.id == target.credential_id)
            )
            .mappings()
            .first()
        )
        if old and owner.executor.kind != "human":
            raise ProtocolError("human_delegation_required", status=403)
        connection.execute(
            insert(derivations).values(
                credential_id=target.credential_id,
                purpose=purpose,
                scheme="hmac-sha256-v1",
                key_id=key_id,
                fingerprint=identity,
                token_hash=token_hash,
            )
        )
        if old and old["token_hash"] != token_hash:
            connection.execute(
                insert(aliases).values(
                    token_hash=token_hash,
                    credential_id=target.credential_id,
                )
            )
    return token


def require_original_delegation_request(
    connection: Connection,
    owner: AuthContext,
    target: AuthContext,
) -> None:
    """A new ID cannot replace recovery of the same legacy authorization."""

    scope = target.model_dump(mode="json", exclude={"credential_id", "executor"})
    rows = connection.execute(
        select(v2_credentials).where(
            v2_credentials.c.session_id == owner.session_id,
            v2_credentials.c.id != target.credential_id,
        )
    ).mappings()
    for row in rows:
        context = AuthContext.model_validate_json(row["context"])
        if (
            context.executor.kind != "external_agent"
            or context.model_dump(mode="json", exclude={"credential_id", "executor"}) != scope
        ):
            continue
        signed = (
            connection.execute(
                select(derivations).where(derivations.c.credential_id == context.credential_id)
            )
            .mappings()
            .first()
        )
        if signed is None or signed["token_hash"] != row["token_hash"]:
            raise ProtocolError("delegation_id_reused", status=409)
