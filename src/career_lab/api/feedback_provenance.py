"""Attach actual producer metadata once; historical readers never infer it."""

import json
from dataclasses import replace
from typing import Protocol

from career_lab.contracts.v2 import EvaluationBundle, read_file
from career_lab.contracts.v2.provenance import FeedbackProvenance
from career_lab.runtime.provenance import execution_identity
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.scenarios.v2.release import EVALUATION_VERSION, PROMPT_VERSION
from career_lab.storage.v2_store import Mutation


class ModelIdentity(Protocol):
    revision: str


def feedback_provenance(
    module: ScenarioModule, bundle: EvaluationBundle, model: ModelIdentity | None
) -> FeedbackProvenance:
    if model is not None and getattr(model, "retries", 0) != 0:
        raise ValueError("Feedback providers must disable automatic retries")
    rules = json.loads(read_file(module.package.root, bundle.rules))
    return FeedbackProvenance(
        code=execution_identity(),
        evaluation_version=EVALUATION_VERSION,
        rules_version=rules.get("revision", "not_recorded"),
        prompt_version=PROMPT_VERSION,
        provider="not_configured" if model is None else getattr(model, "provider", "not_recorded"),
        model="not_configured" if model is None else model.revision,
    )


def attach_provenance(plan: Mutation, provenance: FeedbackProvenance) -> Mutation:
    writes = tuple(
        write.model_copy(
            update={"content": {**write.content, "provenance": provenance.model_dump(mode="json")}}
        )
        if write.ref.kind == "feedback"
        else write
        for write in plan.writes
    )
    return replace(plan, writes=writes)
