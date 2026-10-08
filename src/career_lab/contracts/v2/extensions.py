"""Human-only delegation listing and optional practice wire contracts."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .core import Executor, ObjectRef, V2, JsonValue
from .world import PublicState


class ShownPractice(BaseModel):
    # The UI returns the full displayed view; only these identities are trusted.
    source_feedback: ObjectRef
    source_feedback_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    suggestion_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    work_language: Literal["zh", "en"]


class PracticeChoiceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=120, strict=True)
    choice: Literal["choose", "choose_other", "decline", "continue_revision"]
    option_id: str | None = None
    shown: ShownPractice


class DelegationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    session_id: str
    executor: Executor
    capabilities: tuple[str, ...]
    allowed_actions: tuple[str, ...] | None
    allowed_objects: tuple[str, ...] | None
    create_under_tasks: tuple[str, ...]
    expires_at: datetime | None
    revoked: bool
    effective_status: Literal["active", "expired", "revoked"]


class DelegationListPage(V2):
    items: tuple[DelegationSummary, ...]
    next_cursor: None = None
    checked_at: datetime
    complete: Literal[True] = True


class DelegationListResult(V2):
    result: DelegationListPage


class DelegationListResponse(V2):
    result: DelegationListResult


class PracticeView(ShownPractice):
    options: tuple[dict[str, JsonValue], ...]
    can_decline: Literal[True] = True
    can_choose_other: Literal[True] = True
    learning_gain: Literal["not_established"] = "not_established"
    note: str
    available: bool
    catalog: tuple[dict[str, JsonValue], ...]
    links: tuple[dict[str, JsonValue], ...]


class PracticeReadResponse(V2):
    result: PracticeView


class PracticePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_feedback: ObjectRef
    source_feedback_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    suggestion_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    choice: Literal["choose", "choose_other", "decline", "continue_revision"]
    target: dict[str, JsonValue] | None
    creates_session: bool
    new_session_id: str | None
    help_source: Literal["optional_feedback_suggestion", "self_selected"]
    learning_gain: Literal["not_established"] = "not_established"


class PracticeSession(V2):
    session_id: str
    token: str  # Authorized creation/recovery response only; never a list or log.
    state: PublicState
    binding: dict[str, JsonValue]


class PracticeChoiceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: PracticePlan
    duplicate: bool
    session: PracticeSession | None
    scenario: str | None


class PracticeChoiceResponse(V2):
    result: PracticeChoiceResult
