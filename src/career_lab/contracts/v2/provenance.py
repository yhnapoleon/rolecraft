"""Execution provenance is evidence, never an admission allowlist for content."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from career_lab.contracts.base import Identifier

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Fraction = Annotated[float, Field(ge=0, le=1)]


def _unset(value: object) -> bool:
    return value is None


class CodeIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["clean", "modified", "not_recorded"] = "not_recorded"
    commit: str | None = None
    snapshot: str | None = None


class RegisteredModelDataset(BaseModel):
    """The training data release a registration names; tiers say how labels were made."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    dataset_id: Identifier
    dataset_manifest_sha256: Sha256
    label_tiers: tuple[Identifier, ...] = ()


class RegisteredModelComponent(BaseModel):
    """One already registered member of a fusion, referenced by identity, never copied."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    role: Literal["left", "right"]
    id: Identifier
    kind: Identifier
    model_revision: Identifier
    alpha: Fraction | None = Field(default=None, exclude_if=_unset)


class RegisteredModelFusion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    alpha: Fraction
    evidence_threshold: Fraction
    fusion_gain_observed: bool


class RubricVersion(BaseModel):
    """The rubric release a criterion model was labelled and trained against."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: Identifier
    sha256: Sha256


class RegisteredModelIdentity(BaseModel):
    """Public registration identity. Unset optional fields keep the historical wire bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: Identifier
    model_revision: Identifier
    scope: Literal["synthetic_fixture", "external_candidate"]
    quality_validated: Literal[False] = False
    kind: Identifier | None = Field(default=None, exclude_if=_unset)
    # Relation is the historical task and is not serialized.
    task_type: Literal["relation", "criterion"] = Field(
        default="relation", exclude_if=lambda value: value == "relation"
    )
    criteria: tuple[Identifier, ...] | None = Field(default=None, exclude_if=_unset)
    dataset: RegisteredModelDataset | None = Field(default=None, exclude_if=_unset)
    components: tuple[RegisteredModelComponent, ...] | None = Field(default=None, exclude_if=_unset)
    fusion: RegisteredModelFusion | None = Field(default=None, exclude_if=_unset)
    weights_stage: Identifier | None = Field(default=None, exclude_if=_unset)
    rubric_version: RubricVersion | None = Field(default=None, exclude_if=_unset)

    @model_validator(mode="after")
    def task_scope(self) -> "RegisteredModelIdentity":
        if self.task_type == "criterion":
            if not self.criteria or self.rubric_version is None:
                raise ValueError("a criterion registration names its criteria and rubric version")
            if len(set(self.criteria)) != len(self.criteria):
                raise ValueError("duplicate registered criterion")
        elif self.criteria is not None or self.rubric_version is not None:
            raise ValueError("criteria and rubric versions belong to criterion registrations")
        if self.components is not None and [c.role for c in self.components] != ["left", "right"]:
            raise ValueError("a fusion names its left and right components once each")
        return self


class SupportModelIdentity(BaseModel):
    """The support verifier's model when it is configured apart from the Judge."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: str
    model: str
    # The endpoint actually called (scheme, host, port, path), when one is configured.
    base_url: str | None = Field(default=None, exclude_if=_unset)


class FeedbackProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: CodeIdentity
    evaluation_version: str
    rules_version: str
    prompt_version: str
    provider: str
    model: str
    retries: Literal[0] = 0
    registered_model: RegisteredModelIdentity | None = Field(default=None, exclude_if=_unset)
    # Recorded only when a criterion registration is configured beside the relation one.
    registered_models: tuple[RegisteredModelIdentity, ...] | None = Field(
        default=None, exclude_if=_unset
    )
    support_model: SupportModelIdentity | None = Field(default=None, exclude_if=_unset)
    # The Judge endpoint actually called, recorded when its own slot variables configure it;
    # the shared configuration records none, as before.
    base_url: str | None = Field(default=None, exclude_if=_unset)
