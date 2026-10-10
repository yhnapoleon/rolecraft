"""Attach actual producer metadata once; historical readers never infer it."""

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
        evaluation_version=EVALUATION_VERSION,
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
