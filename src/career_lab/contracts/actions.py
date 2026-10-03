from typing import Literal

from pydantic import JsonValue, model_validator

from career_lab.contracts.base import Contract, Identifier, NonNegativeInt, PositiveInt
from career_lab.contracts.scenario import FactSpec, MaterialSpec


class EvidenceRef(Contract):
    kind: Literal["document", "event", "test_result", "artifact", "config"]
    object_id: Identifier
    version: PositiveInt
    span_id: Identifier | None = None
    observed_at_seq: NonNegativeInt


class WorldState(Contract):
    session_id: Identifier
    version: NonNegativeInt
    logical_time: NonNegativeInt
    resources: dict[str, NonNegativeInt]
    configs: dict[str, JsonValue]
    material_versions: dict[str, PositiveInt]
    indexed_versions: dict[str, PositiveInt] = {}
    applied_rules: tuple[str, ...] = ()
    pending_requests: tuple[str, ...] = ()
    action_count: NonNegativeInt = 0
    config_version: NonNegativeInt = 0
    status: Literal["active", "paused", "submitted"] = "active"


class Action(Contract):
    id: Identifier
    idempotency_key: Identifier
    expected_version: NonNegativeInt
    actor_id: Identifier
    tool: Identifier
    arguments: dict[str, JsonValue]


class Event(Contract):
    id: Identifier
    session_id: Identifier
    seq: PositiveInt
    event_type: Identifier
    actor_id: Identifier
    payload: dict[str, JsonValue]
    before_version: NonNegativeInt
    after_version: PositiveInt
    visible_to: tuple[Identifier, ...]

    @model_validator(mode="after")
    def advancing_version(self):
        if self.after_version != self.before_version + 1:
            raise ValueError("event must advance state version by one")
        return self


class TransitionResult(Contract):
    state: WorldState
    events: tuple[Event, ...]
    replayed: bool
    snapshots: tuple[WorldState, ...] = ()


class RoleView(Contract):
    role_id: Identifier
    state_version: NonNegativeInt
    permitted_facts: tuple[FactSpec, ...]
    permitted_materials: tuple[MaterialSpec, ...]
    recent_events: tuple[Event, ...]


class ToolResult(Contract):
    status: Literal["ok", "error"]
    data: dict[str, JsonValue]
    evidence_refs: tuple[EvidenceRef, ...]
    state_version: NonNegativeInt
    error_code: Identifier | None = None

    @model_validator(mode="after")
    def error_matches_status(self):
        if (self.status == "error") != (self.error_code is not None):
            raise ValueError("error_code is required exactly when status is error")
        return self

