"""Execution provenance is evidence, never an admission allowlist for content."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from career_lab.contracts.base import Identifier


class CodeIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["clean", "modified", "not_recorded"] = "not_recorded"
    commit: str | None = None
    snapshot: str | None = None


class RegisteredModelIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: Identifier
    model_revision: Identifier
    scope: Literal["synthetic_fixture", "external_candidate"]
    quality_validated: Literal[False] = False


class FeedbackProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: CodeIdentity
    evaluation_version: str
    rules_version: str
    prompt_version: str
    provider: str
    model: str
    retries: Literal[0] = 0
    registered_model: RegisteredModelIdentity | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
