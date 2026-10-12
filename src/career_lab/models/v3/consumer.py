"""Registered-model advice for one feedback job: fixed evidence in, advisory DTO out.

Product inference only. Each advice request is one journaled call; recovery reads the
recorded outcome and never repeats inference. Advice never changes rule results or scores.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from career_lab.contracts.v2.core import FileRef, ObjectRef, ProtocolError, canonical, digest
from career_lab.contracts.v2.data import CriterionInput, RelationInput
from career_lab.contracts.v2.evaluation import EvidencePackageV2, RegisteredModelAdvice
from career_lab.contracts.v2.provenance import RegisteredModelIdentity

from .advisory import RegisteredAdvisory, to_public_prediction
from .core import LABELS
from .projection import criterion_input, relation_input
from .registry import describe_registration

AdviceError = Literal[
    "pretrained_encoder_dependencies_unavailable",
    "model_files_changed",
    "model_reference_invalid",
    "model_load_failed",
    "model_prediction_invalid",
]
TaskType = Literal["relation", "criterion"]


class _JobContext(Protocol):
    @property
    def refresh_count(self) -> int: ...


class AdviceEnvelope(Protocol):
    """The parts of a feedback job envelope that name an advice request."""

    @property
    def origin_request_id(self) -> str: ...

    @property
    def job_id(self) -> str: ...

    @property
    def context(self) -> _JobContext: ...


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
    item: RelationInput | CriterionInput,
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


def advice_dependencies(item: RelationInput | CriterionInput) -> tuple[ObjectRef, ...]:
    """Every object one advice input reads: the work subjects and candidate evidence."""
    refs = (
        *item.evidence.subjects,
        *(candidate.ref for candidate in item.evidence.candidate_evidence),
    )
    bare = {
        canonical(ref.model_dump(mode="json", include=set(ObjectRef.model_fields))): ref
        for ref in refs
    }
    return tuple(
        ObjectRef.model_validate(ref.model_dump(mode="json", include=set(ObjectRef.model_fields)))
        for ref in bare.values()
    )


def registered_identity(
    registry_root: Path, ref: FileRef, task_type: TaskType = "relation"
) -> RegisteredModelIdentity:
    """Verified public identity of a registration serving ``task_type``."""
    summary = describe_registration(registry_root, ref)
    if summary.task_type != task_type or summary.labels != LABELS[task_type]:
        raise ProtocolError("registered_model_task_mismatch")
    return RegisteredModelIdentity.model_validate(summary.identity())


@dataclass(frozen=True)
class AdviceSource:
    """One configured registration (or the reason it is unusable) for one task.

    ``relation_advice`` serves R2.support from the learner's whole work;
    ``criterion_advice`` serves one rubric criterion and returns ``None`` while
    criterion inference is not installed. For tracing, an advice's ``input_hash``
    equals ``digest(source.projected(package))``.
    """

    adapter: RegisteredAdvisory | None
    identity: RegisteredModelIdentity | None
    error_code: AdviceError | None = None
    task_type: TaskType = "relation"

    @classmethod
    def from_registration(
        cls,
        registry_root: Path,
        ref: FileRef,
        journal_root: Path,
        *,
        task_type: TaskType = "relation",
    ) -> "AdviceSource":
        """Never raises: an unusable registration becomes an explicit advice error."""
        adapter = None
        try:
            adapter = RegisteredAdvisory(registry_root, ref, journal_root, allow_synthetic=True)
            identity = registered_identity(Path(registry_root), ref, task_type)
        except Exception as error:
            return cls(adapter, None, safe_model_error(error), task_type)
        return cls(adapter, identity, None, task_type)

    @classmethod
    def unusable(cls, error: Exception, task_type: TaskType = "relation") -> "AdviceSource":
        return cls(None, None, safe_model_error(error), task_type)

    def projected(self, package: EvidencePackageV2) -> RelationInput | CriterionInput:
        return relation_input(package) if self.task_type == "relation" else criterion_input(package)

    def criterion_advice(
        self, package: EvidencePackageV2, envelope: AdviceEnvelope, language: str
    ) -> RegisteredModelAdvice | None:
        return None

    def relation_advice(
        self, package: EvidencePackageV2, envelope: AdviceEnvelope, language: str
    ) -> RegisteredModelAdvice:
        item = relation_input(package)
        values = {
            "request_id": envelope.origin_request_id,
            "job_id": envelope.job_id,
            "input_hash": digest(item),
            "registration": self.identity,
            "status": "unavailable",
            "error_code": self.error_code or "model_unavailable",
        }
        if self.adapter is None:
            return RegisteredModelAdvice.model_validate(values)
        if not item.evidence.claim.strip():
            return RegisteredModelAdvice.model_validate(
                values | {"error_code": "claim_not_available"}
            )
        request_id = "feedback-advice-" + digest(
            [
                item.evidence.subjects[0].session_id if item.evidence.subjects else "",
                envelope.origin_request_id,
                envelope.job_id,
                envelope.context.refresh_count,
                [
                    ref.model_dump(mode="json", include=set(ObjectRef.model_fields))
                    for ref in item.evidence.subjects
                ],
            ]
        )
        try:
            outcome = predict_or_recover(self.adapter, item, request_id, language)
        except Exception as error:
            return RegisteredModelAdvice.model_validate(
                values | {"status": "failed", "error_code": safe_model_error(error)}
            )
        if outcome["status"] == "unconfirmed":
            return RegisteredModelAdvice.model_validate(
                values | {"error_code": "model_result_unconfirmed"}
            )
        try:
            public = to_public_prediction(outcome, item)
            recorded = RegisteredModelIdentity.model_validate(
                {key: outcome["registration"][key] for key in _RECORDED_IDENTITY}
            )
            if (
                outcome["request_id"] != request_id
                or public.labels != LABELS["relation"]
                or (self.identity is not None and _recorded_part(self.identity) != recorded)
            ):
                raise ProtocolError("advisory_model_revision_mismatch")
        except (ValueError, KeyError, TypeError):
            return RegisteredModelAdvice.model_validate(
                values | {"status": "failed", "error_code": "model_prediction_invalid"}
            )
        # The verified identity may carry more than the journal records; both name one model.
        values["registration"] = self.identity or recorded
        if outcome["status"] == "failed":
            error_code = (
                "model_timeout"
                if outcome.get("error_code") == "TimeoutError"
                else "model_infrastructure_failed"
                if outcome.get("failure_kind") == "infrastructure"
                else "model_prediction_invalid"
            )
            return RegisteredModelAdvice.model_validate(
                values | {"status": "failed", "error_code": error_code}
            )
        prediction = outcome.get("prediction")
        if not isinstance(prediction, dict) or prediction.get("status") != "ok":
            return RegisteredModelAdvice.model_validate(
                values | {"error_code": "evidence_unavailable"}
            )
        if recorded.scope == "synthetic_fixture":
            return RegisteredModelAdvice.model_validate(
                values
                | {"status": "synthetic_mechanism_only", "error_code": "synthetic_mechanism_only"}
            )
        if public.status != "success" or public.probabilities is None:
            return RegisteredModelAdvice.model_validate(
                values | {"error_code": "evidence_unavailable"}
            )
        candidates = {candidate.id: candidate for candidate in item.evidence.candidate_evidence}
        label = public.labels[max(range(len(public.labels)), key=lambda i: public.probabilities[i])]
        return RegisteredModelAdvice.model_validate(
            values
            | {
                "status": "completed",
                "error_code": None,
                "label": label,
                "evidence_ids": public.evidence_ids,
                "citations": tuple(candidates[key].ref for key in public.evidence_ids),
            }
        )


# The journal records the historical public identity fields of the registration.
_RECORDED_IDENTITY = ("id", "model_revision", "scope", "quality_validated")


def _recorded_part(identity: RegisteredModelIdentity) -> RegisteredModelIdentity:
    return RegisteredModelIdentity.model_validate(
        {key: getattr(identity, key) for key in _RECORDED_IDENTITY}
    )
