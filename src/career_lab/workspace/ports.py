"""Private W03 adapter boundary until W01 publishes its transaction implementation.

These are Python ports, not replacement public contracts. Objects crossing the
boundary use the immutable W01 draft. No adapter silently creates a world.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol

from sqlalchemy.engine import Connection

from career_lab.contracts.v2.core import AuthContext, ObjectRef, ProtocolError, VersionPoint
from career_lab.contracts.v2.research import StoredObject
from career_lab.contracts.v2.world import WorldStateV2


class WorkspaceAuthority(Protocol):
    def validate(self, conn: Connection, auth: AuthContext) -> None:
        """Recheck credential revocation/expiry on this transaction, including replay."""

    def state(self, conn: Connection, auth: AuthContext, *, lock: bool) -> WorldStateV2:
        """Read authoritative state; lock for mutation. Never trust client state."""

    def advance_workspace(self, conn: Connection, auth: AuthContext,
                          before: WorldStateV2, after: VersionPoint) -> None:
        """CAS workspace/storage revisions in this SAME transaction, not business state."""

    def can_reference(self, conn: Connection, auth: AuthContext, ref: ObjectRef) -> bool:
        """Exact, session/permission-filtered upstream evidence lookup; no LLM calls."""

    def roles(self, conn: Connection, auth: AuthContext) -> tuple[str, ...]:
        """Scenario role IDs valid as share recipients."""


@dataclass(frozen=True)
class Snapshot:
    state: WorldStateV2
    objects: tuple[StoredObject, ...]
    reference_allowed: Callable[[ObjectRef], bool]
    roles: tuple[str, ...]

    @property
    def point(self) -> VersionPoint:
        return VersionPoint(business_seq=self.state.business_seq,
                            workspace_revision=self.state.workspace_revision,
                            storage_revision=self.state.storage_revision)

    @property
    def next_point(self) -> VersionPoint:
        return VersionPoint(business_seq=self.state.business_seq,
                            workspace_revision=self.state.workspace_revision + 1,
                            storage_revision=self.state.storage_revision + 1)

    def get(self, kind: str, oid: str, version: int | None = None) -> StoredObject:
        candidates = [o for o in self.objects if o.ref.kind == kind and o.ref.object_id == oid
                      and (version is None or o.ref.version == version)]
        if not candidates:
            raise ProtocolError('not_found', status=404)
        return max(candidates, key=lambda o: o.ref.version)

    def heads(self, kind: str) -> tuple[StoredObject, ...]:
        ids = sorted({o.ref.object_id for o in self.objects if o.ref.kind == kind})
        return tuple(self.get(kind, oid) for oid in ids)


@dataclass(frozen=True)
class Mutation:
    """Private plan translated to W01 ObjectWrite/Mutation by the future adapter."""
    writes: tuple[StoredObject, ...]
    result: dict
    event_type: str


def authorize(auth: AuthContext, now: datetime, operation: str | None = None) -> None:
    if auth.expires_at is not None and auth.expires_at <= now:
        raise ProtocolError('credential_expired', status=401)
    if operation is None:
        if 'read' not in auth.capabilities:
            raise ProtocolError('capability_denied', status=403)
    elif auth.actor_id != 'learner' or 'act' not in auth.capabilities:
        raise ProtocolError('capability_denied', status=403)
    elif auth.allowed_actions is not None and operation not in auth.allowed_actions:
        raise ProtocolError('action_denied', status=403)


def object_scope(auth: AuthContext, oid: str) -> None:
    if auth.allowed_objects is not None and oid not in auth.allowed_objects:
        raise ProtocolError('not_found', status=404)
