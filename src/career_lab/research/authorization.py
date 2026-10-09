"""Explicit research consent, signed by a separately held local authority.

Possessing a session credential establishes access, never consent. Callers must
first authenticate the issuer with their trusted gateway. Keys and bearer grants
stay outside research artifacts; only public_identity is safe to export.
"""

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from career_lab.contracts.v2.core import (
    AuthContext,
    Executor,
    ProtocolError,
    VersionPoint,
    canonical,
    digest,
)

ResearchPurpose = Literal["dataset_export", "branch_restore", "engineer_report"]


def within(left: VersionPoint, right: VersionPoint) -> bool:
    """Compare the complete logical clock, including non-business writes."""
    return all(
        getattr(left, field) <= getattr(right, field)
        for field in ("business_seq", "workspace_revision", "storage_revision")
    )


class ResearchAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["research-authorization-v1"] = "research-authorization-v1"
    session_id: str = Field(min_length=1)
    purpose: ResearchPurpose
    issuer: Executor
    issuer_credential_id: str = Field(min_length=1)
    from_point: VersionPoint
    through_point: VersionPoint
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def window(self) -> "ResearchAuthorization":
        if any(value.tzinfo is None for value in (self.issued_at, self.expires_at)):
            raise ValueError("timezone required")
        if self.expires_at <= self.issued_at or not within(self.from_point, self.through_point):
            raise ValueError("invalid authorization window")
        return self


class SignedAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    authorization: ResearchAuthorization
    signature: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)


def _signature(authorization: ResearchAuthorization, key: bytes) -> str:
    if len(key) < 32:
        raise ProtocolError("research_authority_key_invalid", status=403)
    return hmac.new(
        key, canonical(authorization.model_dump(mode="json")).encode(), hashlib.sha256
    ).hexdigest()


def issue(
    issuer: AuthContext,
    *,
    purpose: ResearchPurpose,
    through_point: VersionPoint,
    expires_at: datetime,
    key: bytes,
    from_point: VersionPoint | None = None,
    now: datetime | None = None,
) -> SignedAuthorization:
    """Sign explicit consent after the caller authenticates an unrestricted owner."""
    if (
        issuer.executor.kind != "human"
        or issuer.actor_id != "learner"
        or issuer.allowed_objects is not None
        or "read" not in issuer.capabilities
    ):
        raise ProtocolError("research_consent_owner_required", status=403)
    issued_at = now or datetime.now(UTC)
    if issuer.expires_at is not None and issuer.expires_at <= issued_at:
        raise ProtocolError("research_consent_owner_expired", status=403)
    authorization = ResearchAuthorization(
        session_id=issuer.session_id,
        purpose=purpose,
        issuer=issuer.executor,
        issuer_credential_id=issuer.credential_id,
        from_point=from_point
        or VersionPoint(business_seq=0, workspace_revision=0, storage_revision=0),
        through_point=through_point,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    return SignedAuthorization(
        authorization=authorization, signature=_signature(authorization, key)
    )


def validate(
    signed: SignedAuthorization,
    *,
    key: bytes,
    session_id: str,
    purpose: ResearchPurpose,
    point: VersionPoint,
    now: datetime | None = None,
) -> ResearchAuthorization:
    """Fail closed on tampering, wrong purpose, session, logical window or expiry."""
    signed = SignedAuthorization.model_validate(signed.model_dump(mode="json"))
    grant = signed.authorization
    if not hmac.compare_digest(signed.signature, _signature(grant, key)):
        raise ProtocolError("research_authorization_invalid", status=403)
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None or not grant.issued_at <= instant < grant.expires_at:
        raise ProtocolError("research_authorization_expired", status=403)
    if grant.session_id != session_id or grant.purpose != purpose:
        raise ProtocolError("research_authorization_scope", status=403)
    if not within(grant.from_point, point) or not within(point, grant.through_point):
        raise ProtocolError("research_authorization_window", status=403)
    return grant


def public_identity(grant: ResearchAuthorization) -> dict[str, object]:
    """Non-secret audit projection; this identity cannot authorize a read."""
    value = grant.model_dump(mode="json", exclude={"issuer_credential_id"})
    return {"id": "research-" + digest(grant.model_dump(mode="json")), **value}
