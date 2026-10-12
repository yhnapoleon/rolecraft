"""Bind server-configured registrations to normal feedback for this service instance.

Assembly and dispatch only; advice itself comes from ``models.v3.consumer.AdviceSource``.
Configuration (read once at startup):

- ``CAREER_LAB_MODEL_REGISTRY``: registry root shared by every registration;
- ``CAREER_LAB_MODEL_REGISTRATIONS``: ``{"relation": FileRef, "criterion": FileRef}``,
  either key optional; the historical ``CAREER_LAB_MODEL_REGISTRATION`` names the relation
  registration alone. Setting both is ambiguous and refuses to start;
- ``CAREER_LAB_MODEL_JOURNAL``: advice journal (default ``<registry>/journal``).
"""

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from career_lab.api.evaluation_runtime import create_feedback_handler
from career_lab.api.modules import JobEnvelope
from career_lab.contracts import v2 as C
from career_lab.contracts.v2.provenance import RegisteredModelIdentity
from career_lab.models.v3.consumer import (
    AdviceError,
    AdviceSource,
    advice_dependencies,
    predict_or_recover,
    registered_identity,
    safe_model_error,
)
from career_lab.rubrics.v4.feedback import FeedbackEngine
from career_lab.rubrics.v4.rubric_v2 import CRITERIA
from career_lab.runtime.model_slots import ModelSlots
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.storage.v2_store import Mutation, TransactionView, V2Store

__all__ = [
    "AdviceError",
    "FeedbackHandler",
    "RegisteredFeedback",
    "RegisteredModelFactory",
    "install_registered_models",
    "predict_or_recover",
    "registered_identity",
    "safe_model_error",
]

FeedbackHandler = Callable[[V2Store, TransactionView, JobEnvelope, C.AuthContext], Mutation]
# Criterion advice follows the rubric's canonical order, after R2.support relation advice.
CANONICAL_CRITERIA = tuple(row[0] for row in CRITERIA)
TASKS = ("relation", "criterion")


@dataclass(frozen=True)
class RegisteredModelFactory:
    """The configured advice sources of one service instance, in fixed dispatch order."""

    relation: AdviceSource | None
    criterion: AdviceSource | None = None

    @property
    def identity(self) -> RegisteredModelIdentity | None:
        return self.relation.identity if self.relation is not None else None

    @property
    def identities(self) -> tuple[RegisteredModelIdentity, ...] | None:
        """Every resolved registration, recorded only when a criterion model is configured."""
        if self.criterion is None:
            return None
        found = tuple(
            source.identity
            for source in (self.relation, self.criterion)
            if source is not None and source.identity is not None
        )
        return found or None

    def create(self, engine: FeedbackEngine, envelope: JobEnvelope) -> "RegisteredFeedback":
        return RegisteredFeedback(engine, self, envelope)


class RegisteredFeedback:
    """Append advice while delegating every rule and scoring operation to the existing engine."""

    def __init__(
        self, engine: FeedbackEngine, factory: RegisteredModelFactory, envelope: JobEnvelope
    ) -> None:
        self.engine = engine
        self.factory = factory
        self.envelope = envelope
        self.dependencies: dict[str, tuple[C.ObjectRef, ...]] = {}

    def evaluate(
        self,
        session_id: str,
        subject: C.ObjectRef,
        evaluation: C.FileRef,
        as_of: C.VersionPoint,
        packages: tuple[C.EvidencePackageV2, ...],
        expected_model_revision: str | None = None,
        *,
        work_language: str = "zh",
    ) -> tuple[C.FeedbackV2, dict[str, Any]]:
        report, diagnostics = self.engine.evaluate(
            session_id,
            subject,
            evaluation,
            as_of,
            packages,
            expected_model_revision,
            work_language=work_language,
        )
        advice = []
        relation, criterion = self.factory.relation, self.factory.criterion
        if relation is not None:
            for package in packages:
                if package.criterion == "R2.support":
                    advice.append(self.traced(relation, package, work_language, relation=True))
        if criterion is not None:
            for name in CANONICAL_CRITERIA:
                for package in packages:
                    if package.criterion == name and package.task_type == "criterion":
                        found = self.traced(criterion, package, work_language, relation=False)
                        if found is not None:
                            advice.append(found)
        return report.model_copy(update={"model_advice": tuple(advice)}), diagnostics

    def traced(
        self, source: AdviceSource, package: C.EvidencePackageV2, language: str, *, relation: bool
    ) -> C.RegisteredModelAdvice | None:
        item = source.projected(package)
        self.dependencies[C.digest(item)] = advice_dependencies(item)
        if relation:
            return source.relation_advice(package, self.envelope, language)
        return source.criterion_advice(package, self.envelope, language)


def configured_registrations() -> dict[str, C.FileRef | Exception] | None:
    """Parse the registration variables; ``None`` when no registration is configured."""
    root_value = os.environ.get("CAREER_LAB_MODEL_REGISTRY")
    single = os.environ.get("CAREER_LAB_MODEL_REGISTRATION")
    several = os.environ.get("CAREER_LAB_MODEL_REGISTRATIONS")
    if single is not None and several is not None:
        raise C.ProtocolError("model_registration_config_ambiguous", status=503)
    if root_value is None and single is None and several is None:
        return None
    if several is None:
        # Historical single relation variable: errors stay advice errors, as before.
        try:
            if not root_value or not single:
                raise C.ProtocolError("model_registration_identity_mismatch")
            return {"relation": C.FileRef.model_validate_json(single)}
        except Exception as error:
            return {"relation": error}
    try:
        value = json.loads(several)
        if not isinstance(value, dict) or not value or set(value) - set(TASKS):
            raise ValueError("registration object names relation and/or criterion")
        parsed = {task: C.FileRef.model_validate(value[task]) for task in TASKS if task in value}
    except ValueError:
        raise C.ProtocolError("model_registration_config_invalid", status=503) from None
    if not root_value:
        return {task: C.ProtocolError("model_registration_identity_mismatch") for task in parsed}
    return dict(parsed)


def install_registered_models(
    module: ScenarioModule,
    fallback: FeedbackHandler | None,
    slots: ModelSlots,
) -> FeedbackHandler | None:
    configured = configured_registrations()
    if configured is None:
        return fallback
    root_value = os.environ.get("CAREER_LAB_MODEL_REGISTRY", "")
    sources: dict[str, AdviceSource] = {}
    for task, ref in configured.items():
        if isinstance(ref, Exception):
            sources[task] = AdviceSource.unusable(ref, task)
            continue
        root = Path(root_value)
        journal = Path(os.environ.get("CAREER_LAB_MODEL_JOURNAL", str(root / "journal")))
        sources[task] = AdviceSource.from_registration(root, ref, journal, task_type=task)
    return create_feedback_handler(
        module,
        slots=slots,
        engine_factory=RegisteredModelFactory(sources.get("relation"), sources.get("criterion")),
    )
