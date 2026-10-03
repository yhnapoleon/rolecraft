from typing import Literal

from pydantic import Field, model_validator

from career_lab.contracts.base import Contract, Identifier, NonNegativeInt, PositiveInt


class ValidationIssue(Contract):
    code: str
    location: str
    message: str


class RoleSpec(Contract):
    id: Identifier
    name: Identifier
    responsibility: Identifier


class MaterialSpec(Contract):
    id: Identifier
    version: PositiveInt
    title: Identifier
    path: Identifier
    visible_to: tuple[Identifier, ...] = Field(min_length=1)
    available_after_event: Identifier | None = None
    content: str = ""
    content_hash: str = ""


class FactSpec(Contract):
    id: Identifier
    value: int | str | bool
    description: Identifier
    visible_to: tuple[Identifier, ...] = Field(min_length=1)
    material_id: Identifier
    material_version: PositiveInt


class EventTrigger(Contract):
    kind: Literal["after_action_count", "approved_request"]
    action_count: PositiveInt | None = None
    request_tool: Identifier | None = None
    authorized_role: Identifier | None = None

    @model_validator(mode="after")
    def consistent_trigger(self):
        if self.kind == "after_action_count":
            if self.action_count is None or self.request_tool or self.authorized_role:
                raise ValueError("action trigger requires only action_count")
        elif self.action_count is not None or not self.request_tool or not self.authorized_role:
            raise ValueError("approval trigger requires request_tool and authorized_role")
        return self


class MaterialVersion(Contract):
    material_id: Identifier
    version: PositiveInt


class EventEffects(Contract):
    capacity: PositiveInt | None = None
    dev_days: NonNegativeInt | None = None
    deadline_day: PositiveInt | None = None
    material_versions: tuple[MaterialVersion, ...] = ()

    @model_validator(mode="after")
    def not_empty(self):
        if all(v is None for v in (self.capacity, self.dev_days, self.deadline_day)) and not self.material_versions:
            raise ValueError("event must have an explicit effect")
        return self


class EventRule(Contract):
    id: Identifier
    description: Identifier
    trigger: EventTrigger
    effects: EventEffects
    once: Literal[True] = True
    visible_to: tuple[Identifier, ...] = Field(min_length=1)


class DomainSpec(Contract):
    id: Identifier
    mutable: bool
    description: Identifier


class WorkItem(Contract):
    id: Identifier
    dev_days: NonNegativeInt
    description: Identifier


class ConstraintSpec(Contract):
    capacity: PositiveInt
    dev_days: NonNegativeInt
    realtime_sync_days: PositiveInt
    index_delay_hours: PositiveInt
    deadline_day: PositiveInt
    minimum_participants: PositiveInt = 1


class CriterionSpec(Contract):
    id: Identifier
    version: PositiveInt
    dimension: Identifier
    description: Identifier
    applicability: Identifier
    observation_window: Literal["session_start_to_submission", "as_of_judgment"]
    met: tuple[Identifier, ...] = Field(min_length=1)
    partial: tuple[Identifier, ...] = Field(min_length=1)
    not_met: tuple[Identifier, ...] = Field(min_length=1)
    insufficient: tuple[Identifier, ...] = Field(min_length=1)
    accepted_alternatives: tuple[Identifier, ...] = ()
    evidence_types: tuple[Identifier, ...] = Field(min_length=1)
    forbidden_shortcuts: tuple[Identifier, ...] = ()


class RubricDimension(Contract):
    id: Identifier
    name: Identifier
    weight: PositiveInt


class RubricSpec(Contract):
    id: Identifier
    version: PositiveInt
    dimensions: tuple[RubricDimension, ...] = Field(min_length=1)
    criteria: tuple[CriterionSpec, ...] = Field(min_length=1)


class ScenarioSpec(Contract):
    id: Identifier
    version: PositiveInt
    family_id: Identifier
    template_id: Identifier
    seed: NonNegativeInt = 0
    title: Identifier
    brief_material_id: Identifier
    roles: tuple[RoleSpec, ...] = Field(min_length=1)
    facts: tuple[FactSpec, ...] = Field(min_length=1)
    materials: tuple[MaterialSpec, ...] = Field(min_length=1)
    event_rules: tuple[EventRule, ...] = ()
    constraints: ConstraintSpec
    domains: tuple[DomainSpec, ...] = Field(min_length=1)
    work_items: tuple[WorkItem, ...] = Field(min_length=1)
    rubric: RubricSpec
    content_hash: str = ""


class PilotPlan(Contract):
    """Authoring-time feasibility probe; not the final learner submission schema."""

    participants: NonNegativeInt
    knowledge_domains: tuple[Identifier, ...]
    launch_day: PositiveInt
    update_strategy: Literal["daily", "realtime", "manual_policy"]
    fallback: Literal["human", "none"]
    work_items: tuple[Identifier, ...]

    @model_validator(mode="after")
    def no_duplicate_items(self):
        for items in (self.knowledge_domains, self.work_items):
            if len(items) != len(set(items)):
                raise ValueError("plan IDs must be unique")
        return self

