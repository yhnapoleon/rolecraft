"""Bind one server-configured registration to normal feedback for this service instance."""

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from career_lab.api.modules import JobEnvelope
from career_lab.contracts import v2 as C
from career_lab.contracts.v2.provenance import RegisteredModelIdentity
from career_lab.models.v3.advisory import RegisteredAdvisory, to_public_prediction
from career_lab.models.v3.core import LABELS
from career_lab.models.v3.encoder_registry import PROTOCOL as ENCODER_PROTOCOL
from career_lab.models.v3.encoder_registry import inspect_registration
from career_lab.models.v3.registry import inference_runtime, load_registration
from career_lab.rubrics.v4.feedback import FeedbackEngine
from career_lab.rubrics.v4.support import registered_relation_input
from career_lab.runtime.model_adapter import ModelAdapter
from career_lab.runtime.roles_v2 import LocalRoleModel
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.storage.v2_store import Mutation, TransactionView, V2Store

AdviceError = Literal[
    "pretrained_encoder_dependencies_unavailable",
    "model_files_changed",
    "model_reference_invalid",
    "model_load_failed",
    "model_prediction_invalid",
]
FeedbackHandler = Callable[[V2Store, TransactionView, JobEnvelope, C.AuthContext], Mutation]


def safe_model_error(error: Exception) -> AdviceError:
    code = getattr(error, "code", "")
    if code == "pretrained_encoder_dependencies_unavailable":
        return "pretrained_encoder_dependencies_unavailable"
    if code in {
        "file_hash_mismatch",
        "registered_inference_runtime_changed",
        "model_registration_drift",
    }:
        return "model_files_changed"
    if code in {
        "file_missing",
        "file_outside_root",
        "model_registration_identity_mismatch",
        "model_registration_protocol_invalid",
    }:
        return "model_reference_invalid"
    return "model_load_failed"


def predict_or_recover(
    adapter: RegisteredAdvisory,
    item: C.RelationInput,
    request_id: str,
    language: str,
) -> dict[str, Any]:
    try:
        return adapter.predict(item, request_id=request_id, work_language=language)
    except Exception as error:
        if getattr(error, "code", None) == "advisory_request_id_reused":
            raise
        # Inference may already have saved its definitive failure before raising.
        # Read only: do not restart prediction or reset the original reservation.
        try:
            return adapter.recover(request_id)
        except (ValueError, OSError, TypeError):
            raise error from None


def registered_identity(root: Path, ref: C.FileRef) -> RegisteredModelIdentity:
    entry = json.loads(C.read_file(root, ref))
    if entry.get("protocol") == ENCODER_PROTOCOL:
        entry = inspect_registration(root, ref, runtime=inference_runtime())
    else:
        _, entry = load_registration(root, ref)
    if entry["task_type"] != "relation" or entry["labels"] != list(LABELS["relation"]):
        raise C.ProtocolError("registered_model_task_mismatch")
    return RegisteredModelIdentity.model_validate(
        {key: entry[key] for key in RegisteredModelIdentity.model_fields}
    )


@dataclass(frozen=True)
class RegisteredModelFactory:
    adapter: RegisteredAdvisory | None
    identity: RegisteredModelIdentity | None
    error_code: AdviceError | None = None

    def create(self, engine: FeedbackEngine, envelope: JobEnvelope) -> "RegisteredFeedback":
        return RegisteredFeedback(engine, self, envelope)

    def advice(
        self, item: C.RelationInput, envelope: JobEnvelope, language: str
    ) -> C.RegisteredModelAdvice:
        values = {
            "request_id": envelope.origin_request_id,
            "job_id": envelope.job_id,
            "input_hash": C.digest(item),
            "registration": self.identity,
            "status": "unavailable",
            "error_code": self.error_code or "model_unavailable",
        }
        if self.adapter is None:
            return C.RegisteredModelAdvice.model_validate(values)
        if not item.evidence.claim.strip():
            return C.RegisteredModelAdvice.model_validate(
                values | {"error_code": "claim_not_available"}
            )
        request_id = "feedback-advice-" + C.digest(
            [
                item.evidence.subjects[0].session_id if item.evidence.subjects else "",
                envelope.origin_request_id,
                envelope.job_id,
                envelope.context.refresh_count,
                [
                    ref.model_dump(mode="json", include=set(C.ObjectRef.model_fields))
                    for ref in item.evidence.subjects
                ],
            ]
        )
        try:
            outcome = predict_or_recover(self.adapter, item, request_id, language)
        except Exception as error:
            return C.RegisteredModelAdvice.model_validate(
                values
                | {
                    "status": "failed",
                    "error_code": safe_model_error(error),
                }
            )
        if outcome["status"] == "unconfirmed":
            return C.RegisteredModelAdvice.model_validate(
                values | {"error_code": "model_result_unconfirmed"}
            )
        try:
            public = to_public_prediction(outcome, item)
            recorded = RegisteredModelIdentity.model_validate(
                {key: outcome["registration"][key] for key in RegisteredModelIdentity.model_fields}
            )
            if (
                outcome["request_id"] != request_id
                or public.labels != LABELS["relation"]
                or (self.identity is not None and recorded != self.identity)
            ):
                raise C.ProtocolError("advisory_model_revision_mismatch")
        except (ValueError, KeyError, TypeError):
            return C.RegisteredModelAdvice.model_validate(
                values
                | {
                    "status": "failed",
                    "error_code": "model_prediction_invalid",
                }
            )
        values["registration"] = recorded
        if outcome["status"] == "failed":
            error_code = (
                "model_timeout"
                if outcome.get("error_code") == "TimeoutError"
                else "model_infrastructure_failed"
                if outcome.get("failure_kind") == "infrastructure"
                else "model_prediction_invalid"
            )
            return C.RegisteredModelAdvice.model_validate(
                values
                | {
                    "status": "failed",
                    "error_code": error_code,
                }
            )
        prediction = outcome.get("prediction")
        if not isinstance(prediction, dict) or prediction.get("status") != "ok":
            return C.RegisteredModelAdvice.model_validate(
                values | {"error_code": "evidence_unavailable"}
            )
        if recorded.scope == "synthetic_fixture":
            return C.RegisteredModelAdvice.model_validate(
                values
                | {
                    "status": "synthetic_mechanism_only",
                    "error_code": "synthetic_mechanism_only",
                }
            )
        if public.status != "success" or public.probabilities is None:
            return C.RegisteredModelAdvice.model_validate(
                values | {"error_code": "evidence_unavailable"}
            )
        candidates = {candidate.id: candidate for candidate in item.evidence.candidate_evidence}
        label = public.labels[max(range(len(public.labels)), key=lambda i: public.probabilities[i])]
        return C.RegisteredModelAdvice.model_validate(
            values
            | {
                "status": "completed",
                "error_code": None,
                "label": label,
                "evidence_ids": public.evidence_ids,
                "citations": tuple(candidates[key].ref for key in public.evidence_ids),
            }
        )


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
        packages = tuple(package for package in packages if package.criterion == "R2.support")
        advice = []
        for package in packages:
            item = registered_relation_input(package)
            refs = (
                *item.evidence.subjects,
                *(candidate.ref for candidate in item.evidence.candidate_evidence),
            )
            dependencies = {
                C.canonical(
                    ref.model_dump(mode="json", include=set(C.ObjectRef.model_fields))
                ): C.ObjectRef.model_validate(
                    ref.model_dump(mode="json", include=set(C.ObjectRef.model_fields))
                )
                for ref in refs
            }
            self.dependencies[C.digest(item)] = tuple(dependencies.values())
            advice.append(self.factory.advice(item, self.envelope, work_language))
        return report.model_copy(update={"model_advice": tuple(advice)}), diagnostics


def install_registered_models(
    module: ScenarioModule,
    fallback: FeedbackHandler | None,
    model: ModelAdapter | LocalRoleModel,
) -> FeedbackHandler | None:
    root_value = os.environ.get("CAREER_LAB_MODEL_REGISTRY")
    ref_value = os.environ.get("CAREER_LAB_MODEL_REGISTRATION")
    if root_value is None and ref_value is None:
        return fallback
    adapter = None
    identity = None
    error_code = None
    try:
        if not root_value or not ref_value:
            raise C.ProtocolError("model_registration_identity_mismatch")
        root = Path(root_value)
        ref = C.FileRef.model_validate_json(ref_value)
        journal = Path(os.environ.get("CAREER_LAB_MODEL_JOURNAL", str(root / "journal")))
        adapter = RegisteredAdvisory(root, ref, journal, allow_synthetic=True)
        identity = registered_identity(root, ref)
    except Exception as error:
        error_code = safe_model_error(error)
    from career_lab.api.evaluation_runtime import create_feedback_handler

    return create_feedback_handler(
        module,
        model=None if isinstance(model, LocalRoleModel) else model,
        engine_factory=RegisteredModelFactory(adapter, identity, error_code),
    )
