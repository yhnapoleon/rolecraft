"""Attach producer metadata and the rule score range once, when feedback is written.

Historical readers never infer either; records written without them keep their bytes.
"""

import json
from dataclasses import replace
from typing import Protocol

from career_lab.contracts.v2 import (
    EvaluationBundle,
    FeedbackV2,
    JsonValue,
    ProtocolError,
    read_file,
)
from career_lab.contracts.v2.provenance import FeedbackProvenance, RegisteredModelIdentity
from career_lab.rubrics.v4.score_range import rule_score_range
from career_lab.runtime.provenance import execution_identity
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.scenarios.v2.release import EVALUATION_VERSION, PROMPT_VERSION
from career_lab.storage.v2_store import Mutation


class ModelIdentity(Protocol):
    revision: str


def feedback_provenance(
    module: ScenarioModule,
    bundle: EvaluationBundle,
    model: ModelIdentity | None,
    *,
    registered_model: RegisteredModelIdentity | None = None,
) -> FeedbackProvenance:
    if model is not None and getattr(model, "retries", 0) != 0:
        raise ValueError("Feedback providers must disable automatic retries")
    rules = json.loads(read_file(module.package.root, bundle.rules))
    return FeedbackProvenance(
        code=execution_identity(),
        registered_model=registered_model,
        # A released package names its own installed evaluation; legacy packages predate it.
        evaluation_version=(
            module.release.evaluation_version
            if getattr(module, "release", None) is not None
            else EVALUATION_VERSION
        ),
        rules_version=rules.get("revision", "not_recorded"),
        prompt_version=PROMPT_VERSION,
        provider="not_configured" if model is None else getattr(model, "provider", "not_recorded"),
        model="not_configured" if model is None else model.revision,
    )


def attach_provenance(plan: Mutation, provenance: FeedbackProvenance) -> Mutation:
    writes = tuple(
        write.model_copy(
            update={
                "content": {
                    **write.content,
                    "provenance": effective_provenance(write.content, provenance).model_dump(
                        mode="json"
                    ),
                }
            }
        )
        if write.ref.kind == "feedback"
        else write
        for write in plan.writes
    )
    return replace(plan, writes=writes)


def effective_provenance(
    content: dict[str, JsonValue],
    provenance: FeedbackProvenance,
) -> FeedbackProvenance:
    identities = [
        advice.registration
        for advice in FeedbackV2.model_validate(content).model_advice or ()
        if advice.registration is not None
    ]
    if len({identity.model_dump_json() for identity in identities}) > 1:
        raise ProtocolError("feedback_registered_identity_mismatch")
    return (
        provenance.model_copy(update={"registered_model": identities[0]})
        if identities
        else provenance
    )


def attach_score_range(
    plan: Mutation, rubric: dict[str, JsonValue], rubric_sha256: str
) -> Mutation:
    """Record the weighted rule range with each criterion feedback; candidates get none."""
    writes = []
    for write in plan.writes:
        rule_items = (
            FeedbackV2.model_validate(write.content).rule_items
            if write.ref.kind == "feedback"
            else None
        )
        found = None if rule_items is None else rule_score_range(rule_items, rubric, rubric_sha256)
        writes.append(
            write
            if found is None
            else write.model_copy(
                update={"content": {**write.content, "score_range": found.model_dump(mode="json")}}
            )
        )
    return replace(plan, writes=tuple(writes))
