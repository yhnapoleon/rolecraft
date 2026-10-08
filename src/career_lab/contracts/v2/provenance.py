"""Execution provenance is evidence, never an admission allowlist for content."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class CodeIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["clean", "modified", "not_recorded"] = "not_recorded"
    commit: str | None = None
    snapshot: str | None = None


class FeedbackProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: CodeIdentity
    evaluation_version: str
    rules_version: str
    prompt_version: str
    provider: str
    model: str
    retries: Literal[0] = 0
