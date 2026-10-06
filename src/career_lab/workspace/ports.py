"""Private W03 adapter boundary until W01 publishes its transaction implementation.

These are Python ports, not replacement public contracts. Objects crossing the
boundary use the immutable W01 draft. No adapter silently creates a world.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Callable


from career_lab.contracts.v2.core import AuthContext, ObjectRef, ProtocolError, VersionPoint
from career_lab.contracts.v2.research import StoredObject
from career_lab.contracts.v2.world import WorldStateV2


@dataclass(frozen=True)
class Snapshot:
    state: WorldStateV2
    objects: tuple[StoredObject, ...]
    reference_allowed: Callable[[ObjectRef], bool]
    roles: tuple[str, ...]
    object_allowed: Callable[[str], bool] | None = None

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


def object_scope(auth: AuthContext, oid: str, snapshot: Snapshot | None = None) -> None:
    if snapshot is not None and snapshot.object_allowed is not None:
        allowed = snapshot.object_allowed(oid)
    else:
        allowed = auth.allowed_objects is None or oid in auth.allowed_objects
    if not allowed:
        raise ProtocolError('not_found', status=404)
