"""Human-only wire contracts: delegation listing, optional practice, submission rule check
and continue codes."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from .core import (
    Executor,
    FileRef,
    Identifier,
    JsonValue,
    NonNegativeInt,
    ObjectRef,
    PositiveInt,
    V2,
    VersionPoint,
)
from .evaluation import FeedbackItem
from .requests import SubmitInput
from .world import PublicState

# Twenty Crockford Base32 symbols (100 bits) in five groups of four.
CONTINUE_CODE_PATTERN = r"^[0-9A-HJKMNP-TV-Z]{4}(?:-[0-9A-HJKMNP-TV-Z]{4}){4}$"


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


class _ConfigTestRuns(V2):
    """Actual runs on one configuration version; retests followed the current policy update."""

    config_version: NonNegativeInt
    runs: NonNegativeInt
    retests: NonNegativeInt


class _RuleCheckFacts(V2):
    """Verified facts behind the rule items. Null where the rules could not verify one."""

    participants: NonNegativeInt | None = None
    capacity: NonNegativeInt | None = None
    required_dev_days: NonNegativeInt | None = None
    available_dev_days: NonNegativeInt | None = None
    requested_launch_day: NonNegativeInt | None = None
    deadline_day: NonNegativeInt | None = None
    unapproved_resource_excess: bool | None = None
    config_version: NonNegativeInt | None = None
    policy_version: PositiveInt | None = None
    adjustment_actions: NonNegativeInt | None = None
    # Empty while the test ledger is incomplete.
    test_runs: tuple[_ConfigTestRuns, ...] = ()


class SubmissionRuleCheckRequest(V2):
    """The submit command a person would send now, checked read-only. Nothing is recorded:
    request_id carries no idempotent result; the versions must equal the checked point."""

    schema_version: Literal[2]
    request_id: Identifier
    expected_version: NonNegativeInt
    expected_workspace_revision: NonNegativeInt
    operation: Literal["submissions.rule_check"]
    payload: SubmitInput


class SubmissionRuleCheck(V2):
    """Rule items a submission gets, before it is made (draft) or again for a saved one.

    rule_items equal the formal FeedbackV2.rule_items of the same inputs at as_of. No model
    runs and nothing is written; model-judged criteria stay pending here.
    """

    basis: Literal["draft", "saved"]
    mode: Literal["rules_only"] = "rules_only"
    session_id: Identifier
    as_of: VersionPoint
    submission: ObjectRef | None = None
    decision: Literal["launch", "launch_narrow", "defer_with_conditions", "no_go"]
    products: tuple[ObjectRef, ...]
    config: ObjectRef | None = None
    evaluation: FileRef
    work_language: Literal["zh", "en"]
    rule_items: tuple[FeedbackItem, ...]
    facts: _RuleCheckFacts = _RuleCheckFacts()
    # Recognition layer (demo edition, contract not re-exported): C1 sentence labels of the
    # work for the writing-area preview; see recognition.judge.preview.
    recognition: SkipJsonSchema[dict[str, JsonValue] | None] = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def saved_names_its_submission(self):
        if (self.basis == "saved") != (self.submission is not None):
            raise ValueError("only a saved submission check names its submission")
        return self


class SubmissionRuleCheckResponse(V2):
    result: SubmissionRuleCheck


class ContinueCodeStatus(BaseModel):
    """Whether the practice has a continue code; the code itself is never readable again."""

    model_config = ConfigDict(extra="forbid")
    exists: bool
    generation: PositiveInt | None = None
    created_at: datetime | None = None


class ContinueCodeStatusResponse(V2):
    result: ContinueCodeStatus


class ContinueCodeIssueInput(BaseModel):
    """Create or replace the code. ``expected_generation`` is the one the person saw; 0 = none."""

    model_config = ConfigDict(extra="forbid")
    expected_generation: NonNegativeInt


class ContinueCodeIssued(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=CONTINUE_CODE_PATTERN)  # This response only: never listed or logged.
    generation: PositiveInt
    created_at: datetime


class ContinueCodeIssueResponse(V2):
    result: ContinueCodeIssued


class ContinueCodeExchangeInput(BaseModel):
    """A continue code as typed: case, spaces and dashes are free; O reads as 0, I and L as 1."""

    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=1, max_length=120, strict=True)


class ContinueCodeExchangeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session: PracticeSession  # A new owner credential for this browser; other access is unchanged.
    scenario: str


class ContinueCodeExchangeResponse(V2):
    result: ContinueCodeExchangeResult
