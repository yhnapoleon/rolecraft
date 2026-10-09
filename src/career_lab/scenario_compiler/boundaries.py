"""Local authoring checks, separate from public contracts and release authorization.

Confirmation digests and installed effects must come from the trusted integration
adapter. A successful check only permits further review; it never installs a case.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from career_lab.contracts.v2.core import digest

Text = Annotated[str, Field(strict=True, min_length=1, pattern=r"\S")]
Items = Annotated[tuple[Text, ...], Field(min_length=1)]


class AuthorValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LocalizedText(AuthorValue):
    zh: Text
    en: Text


class ResourceLimit(AuthorValue):
    name: Text
    unit: Text
    amount: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]


class BusinessTerms(AuthorValue):
    inputs: Items
    outputs: Items
    actions: Items
    consequences: Items
    permissions: Items
    resources: tuple[ResourceLimit, ...]


class RoleTranslation(AuthorValue):
    responsibility: Text
    terms: BusinessTerms


class RoleDeclaration(AuthorValue):
    role: Text
    task_id: Text
    execution_mode: Literal["business_decision", "bounded_config", "arbitrary_code"]
    zh: RoleTranslation
    en: RoleTranslation


class BoundaryDeclaration(AuthorValue):
    title: LocalizedText
    roles: Annotated[tuple[RoleDeclaration, ...], Field(min_length=1)]
    extensions: Annotated[tuple[LocalizedText, ...], Field(min_length=1)]
    unsupported: Annotated[tuple[LocalizedText, ...], Field(min_length=1)]


@dataclass(frozen=True)
class BoundaryIssue:
    code: str
    location: str


@dataclass(frozen=True)
class BoundaryResult:
    status: Literal["needs_confirmation", "unsupported", "ready_for_review"]
    issues: tuple[BoundaryIssue, ...]
    public_description: BoundaryDeclaration | None = None


def validate_boundary(
    value: object,
    *,
    installed_effects: Mapping[str, frozenset[str]],
    confirmed_digest: str | None,
) -> BoundaryResult:
    """Check an author declaration without writing a package or calling a model."""
    try:
        declaration = BoundaryDeclaration.model_validate(value)
    except ValidationError as exc:
        issues = tuple(
            BoundaryIssue("declaration_incomplete", ".".join(map(str, error["loc"])))
            for error in exc.errors()
        )
        return BoundaryResult("needs_confirmation", issues)
    # Bind the exact authored JSON, before numeric coercion (3 versus 3.0).
    # The integration adapter must resolve this digest from a trusted confirmation.
    authored = value.model_dump(mode="json") if isinstance(value, BoundaryDeclaration) else value
    try:
        content_digest = digest(authored)
    except (TypeError, ValueError):
        return BoundaryResult(
            "needs_confirmation", (BoundaryIssue("declaration_not_json", "roles"),)
        )
    if confirmed_digest != content_digest:
        return BoundaryResult(
            "needs_confirmation", (BoundaryIssue("confirmation_missing_or_stale", "roles"),)
        )
    aliases = {"pm": "aipm", "ai_pm": "aipm", "aipm": "aipm", "engineer": "engineer"}
    normalized = tuple(
        role.model_copy(update={"role": aliases.get(role.role, role.role)})
        for role in declaration.roles
    )
    modes = {"aipm": "business_decision", "engineer": "bounded_config"}
    for index, role in enumerate(normalized):
        if role.role not in modes or role.execution_mode != modes[role.role]:
            return BoundaryResult(
                "unsupported", (BoundaryIssue("execution_mode_unsupported", f"roles.{index}"),)
            )
    for index, role in enumerate(normalized):
        if role.zh.terms != role.en.terms:
            return BoundaryResult(
                "needs_confirmation",
                (BoundaryIssue("translated_business_terms_differ", f"roles.{index}"),),
            )
        for translation in (role.zh, role.en):
            terms = translation.terms
            effects = set().union(*(installed_effects.get(a, frozenset()) for a in terms.actions))
            if any(a not in installed_effects for a in terms.actions) or not set(
                terms.consequences
            ).issubset(effects):
                return BoundaryResult(
                    "unsupported", (BoundaryIssue("capability_unavailable", f"roles.{index}"),)
                )
    names = [role.role for role in normalized]
    if len(set(names)) != len(names):
        return BoundaryResult("needs_confirmation", (BoundaryIssue("duplicate_role", "roles"),))
    unique_tasks = len({role.task_id for role in normalized}) == len(normalized)
    distinct_descriptions = all(
        len({getattr(role, language).responsibility.strip() for role in normalized})
        == len(normalized)
        for language in ("zh", "en")
    )
    if not unique_tasks or not distinct_descriptions:
        return BoundaryResult(
            "needs_confirmation", (BoundaryIssue("role_responsibilities_overlap", "roles"),)
        )
    return BoundaryResult(
        "ready_for_review", (), declaration.model_copy(update={"roles": normalized})
    )
