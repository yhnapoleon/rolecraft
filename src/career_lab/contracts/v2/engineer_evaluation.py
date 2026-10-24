"""Rule conclusions for the final engineer rubric; not part of the engineer-review-v1 export.

Learner-facing: only public probe IDs and hidden counts, configuration field names without
values, and authored reason codes. E5 stays waiting for a model.
"""

from typing import Literal, Self, get_args

from pydantic import Field, model_validator

from .core import V2, Hash, Identifier, NonNegativeInt
from .engineer import ChangeField

RUBRIC_REVISION = "engineer-rubric-v1-final-20261009"
RubricLabel = Literal["MET", "PARTIAL", "NOT_MET", "INSUFFICIENT", "NOT_APPLICABLE"]
LABEL_ORDER: tuple[str, ...] = get_args(RubricLabel)
CriterionId = Literal[
    "E1.target_fixed",
    "E2.no_regressions",
    "E3.change_consistency",
    "E4.reproducibility",
    "E5.remaining_explanation",
]
CRITERIA: tuple[str, ...] = get_args(CriterionId)
RULE_CRITERIA = CRITERIA[:4]

FieldCheckStatus = Literal[
    "matched",  # the claim states the actual before and after values
    "omitted",  # the setting changed and no claim names it
    "before_mismatch",  # both say changed; the claimed original value is wrong
    "after_mismatch",  # both say changed; the claimed new value is wrong
    "values_mismatch",  # both claimed values are wrong
    "change_not_made",  # claimed a change; the setting is unchanged
    "change_denied",  # claimed unchanged (before == after); the setting changed
]


class EngineerFieldCheck(V2):
    field: ChangeField
    status: FieldCheckStatus


class EngineerRemainingPrecheck(V2):
    """Still-failing probes no submitted unresolved item names; hidden ones only as a count."""

    basis: Literal["rule"] = "rule"
    unexplained_probe_ids: tuple[Identifier, ...]
    unexplained_hidden: NonNegativeInt


class EngineerCriterionConclusion(V2):
    criterion: CriterionId
    status: Literal["concluded", "waiting_model"]
    basis: Literal["rule", "semantic_advice"]
    label: RubricLabel | None
    reason_codes: tuple[Identifier, ...] = Field(min_length=1)
    probe_ids: tuple[Identifier, ...] = ()  # public probes only
    hidden_probes: NonNegativeInt = 0
    field_checks: tuple[EngineerFieldCheck, ...] = ()
    precheck: EngineerRemainingPrecheck | None = None

    @model_validator(mode="after")
    def criterion_shape(self) -> Self:
        if self.criterion in RULE_CRITERIA:
            if self.status != "concluded" or self.basis != "rule" or self.label is None:
                raise ValueError("rule criteria require a concluded rule label")
            if self.precheck is not None:
                raise ValueError("only E5 carries a remaining-items precheck")
        elif (
            self.status != "waiting_model"
            or self.basis != "semantic_advice"
            or self.label is not None
            or self.precheck is None
        ):
            raise ValueError("E5 waits for a model and carries only the rule precheck")
        if self.criterion == "E2.no_regressions" and self.label == "PARTIAL":
            raise ValueError("no-regression is binary")
        if self.field_checks and self.criterion != "E3.change_consistency":
            raise ValueError("only E3 compares configuration fields")
        fields = [check.field for check in self.field_checks]
        if len(fields) != len(set(fields)) or len(self.probe_ids) != len(set(self.probe_ids)):
            raise ValueError("duplicate conclusion detail")
        return self


class EngineerRuleEvaluation(V2):
    rubric_revision: Literal["engineer-rubric-v1-final-20261009"]
    review_id: Identifier
    submission_hash: Hash
    criteria: tuple[EngineerCriterionConclusion, ...]
    affects_score: Literal[False] = False

    @model_validator(mode="after")
    def every_criterion_once(self) -> Self:
        if tuple(item.criterion for item in self.criteria) != CRITERIA:
            raise ValueError("evaluation must conclude E1-E5 once, in rubric order")
        return self

    def conclusion(self, criterion: str) -> EngineerCriterionConclusion:
        return next(item for item in self.criteria if item.criterion == criterion)
