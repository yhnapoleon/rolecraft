"""The public source kinds and audit shape supported by live session exports."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from career_lab.contracts.v2 import Executor, ObjectRef, VersionPoint

SOURCE_KINDS = frozenset(
    {
        "product",
        "test",
        "material",
        "config",
        "business_request",
        "business_decision",
        "submission",
        "review",
        "event",
        "role_turn",
        "role_reply",
    }
)


class SourceIndexEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: ObjectRef
    available_at: VersionPoint
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    language: Literal["zh", "en"]
    span_start: Literal[0]
    span_end: int = Field(ge=0)
    executor: Executor | None

    @model_validator(mode="after")
    def public_kind(self) -> "SourceIndexEntry":
        if self.ref.kind not in SOURCE_KINDS:
            raise ValueError("unsupported source kind")
        return self
