"""Registered-model advice for one feedback job: fixed evidence in, advisory DTO out.

Product inference only. Each sentence of an advice request is one journaled call; recovery
reads the recorded outcome and never repeats inference. Advice never changes rule results
or scores.
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
from .projection import criterion_input, relation_input, sentence_input
from .registry import describe_registration
from .units import POLICY, SupportUnit, UnitResult, aggregate, support_units

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
        "encoder_registration_retired",
    }:
        return "model_reference_invalid"
    return "model_load_failed"


def predict_or_recover(
    adapter: RegisteredAdvisory,
    item: RelationInput | CriterionInput,
    request_id: str,
    language: str,
    *,
    enforce_input_limit: bool = False,
) -> dict[str, Any]:
    try:
        return adapter.predict(
            item,
            request_id=request_id,
            work_language=language,
            enforce_input_limit=enforce_input_limit,
        )
    except Exception as error:
        if getattr(error, "code", None) == "advisory_request_id_reused":
            raise
        # Inference may already have saved its definitive failure before raising.
        # Read only: do not restart prediction or reset the original reservation.
        try:
            return adapter.recover(request_id)
        except (ValueError, OSError, TypeError):
            raise error from None


# Resolved by the scenario module, not stored as session records: the store accepts them as
# dependencies only once declared as external references.
EXTERNAL_REFERENCE_KINDS = frozenset({"material"})


def advice_dependencies(item: RelationInput | CriterionInput) -> tuple[ObjectRef, ...]:
    """The session objects one advice input reads: work subjects and candidate evidence.

    Scenario materials are left out. A material the advice cites is traced through its
    citation, which declares it as an external reference, exactly as for rule items; an
    uncited material is not a dependency, so the store never rejects the feedback for it.
    """
    refs = (
        *item.evidence.subjects,
        *(
            candidate.ref
            for candidate in item.evidence.candidate_evidence
            if candidate.ref.kind not in EXTERNAL_REFERENCE_KINDS
        ),
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

    ``relation_advice`` serves R2.support from the learner's work, one sentence at a
    time; ``criterion_advice`` serves one rubric criterion and returns ``None`` while
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
        """R2.support advice judged sentence by sentence (policy ``r2-support-units-v1``).

        Each planned sentence is one journaled request; recovery reads it back without
        inference. The work-level label follows ``units.aggregate``; ``input_hash`` stays
        the whole-work input digest that read tracing keys on. Never raises: any failure
        becomes failed advice, so feedback and its rule results are always written.
        """
        try:
            return self._relation_advice(package, envelope, language)
        except Exception:
            return RegisteredModelAdvice.model_validate(
                {
                    "request_id": envelope.origin_request_id,
                    "job_id": envelope.job_id,
                    "input_hash": digest(relation_input(package)),
                    "registration": self.identity,
                    "status": "failed",
                    "error_code": "model_prediction_invalid",
                }
            )

    def _relation_advice(
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
        work_request = "feedback-advice-" + digest(
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
        plan = support_units(package)
        results: list[UnitResult] = []
        recorded: RegisteredModelIdentity | None = None
        load_error: str | None = None
        for unit in plan.units:
            result, identity, load_error = self._judge(
                unit,
                sentence_input(item, unit.subject, unit.text),
                unit_request_id(work_request, unit),
                language,
                load_error,
            )
            results.append(result)
            recorded = recorded or identity
        # The verified identity may carry more than the journal records; both name one model.
        values["registration"] = self.identity or recorded
        candidates = {candidate.id: candidate for candidate in item.evidence.candidate_evidence}
        conclusion = aggregate(results, plan, tuple(candidates))
        values |= {
            "units": tuple(_public_unit(row, candidates) for row in results),
            "aggregation": {"policy": POLICY, "counts": conclusion.counts},
        }
        if conclusion.label is None:
            failed = [row.reason_code for row in results if row.status == "failed"]
            if failed:
                return RegisteredModelAdvice.model_validate(
                    values | {"status": "failed", "error_code": failed[0]}
                )
            return RegisteredModelAdvice.model_validate(
                values | {"error_code": "all_units_abstained" if results else "claim_not_available"}
            )
        synthetic = values["registration"] is not None and (
            values["registration"].scope == "synthetic_fixture"
        )
        return RegisteredModelAdvice.model_validate(
            values
            | {
                "status": "synthetic_mechanism_only" if synthetic else "completed",
                "error_code": "synthetic_mechanism_only" if synthetic else None,
                "label": conclusion.label,
                "evidence_ids": conclusion.evidence_ids,
                "citations": tuple(candidates[key].ref for key in conclusion.evidence_ids),
            }
        )

    def _judge(
        self,
        unit: SupportUnit,
        item: RelationInput,
        request_id: str,
        language: str,
        load_error: str | None,
    ) -> tuple[UnitResult, RegisteredModelIdentity | None, str | None]:
        """One sentence's result, the identity its journal records, and any load error.

        Once loading has failed (``load_error``), later sentences only read back what was
        journaled and otherwise report that same error.
        """
        assert self.adapter is not None
        try:
            if load_error is None:
                outcome = predict_or_recover(
                    self.adapter, item, request_id, language, enforce_input_limit=True
                )
            else:
                outcome = self.adapter.recover(request_id)
        except Exception as error:
            code = load_error or safe_model_error(error)
            return UnitResult(unit, "failed", reason_code=code), None, code
        if outcome["status"] == "unconfirmed":
            return (
                UnitResult(unit, "failed", reason_code="model_result_unconfirmed"),
                None,
                load_error,
            )
        invalid = UnitResult(unit, "failed", reason_code="model_prediction_invalid")
        try:
            public = to_public_prediction(outcome, item, mechanism=True)
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
            return invalid, None, load_error
        if outcome["status"] == "failed":
            code = (
                "model_timeout"
                if outcome.get("error_code") == "TimeoutError"
                else "model_infrastructure_failed"
                if outcome.get("failure_kind") == "infrastructure"
                else "model_prediction_invalid"
            )
            return UnitResult(unit, "failed", reason_code=code), recorded, load_error
        prediction = outcome.get("prediction")
        if not isinstance(prediction, dict):
            return invalid, recorded, load_error
        if prediction.get("status") != "ok":
            reason = prediction.get("reason_code") or "evidence_unavailable"
            return UnitResult(unit, "abstained", reason_code=reason), recorded, load_error
        if public.status != "success" or public.probabilities is None:
            return invalid, recorded, load_error
        label = public.labels[max(range(len(public.labels)), key=lambda i: public.probabilities[i])]
        return UnitResult(unit, "completed", label, public.evidence_ids), recorded, load_error


def unit_request_id(work_request_id: str, unit: SupportUnit) -> str:
    """Journal identity of one sentence of one work-level advice request."""
    return "feedback-advice-unit-" + digest([work_request_id, unit.index, unit.unit_hash])


def _public_unit(row: UnitResult, candidates: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": row.unit.index,
        "subject": row.unit.subject,
        "unit_hash": row.unit.unit_hash,
        "status": row.status,
        "label": row.label,
        "evidence_ids": row.evidence_ids,
        "citations": tuple(candidates[key].ref for key in row.evidence_ids),
        "reason_code": row.reason_code,
    }


# The journal records the historical public identity fields of the registration.
_RECORDED_IDENTITY = ("id", "model_revision", "scope", "quality_validated")


def _recorded_part(identity: RegisteredModelIdentity) -> RegisteredModelIdentity:
    return RegisteredModelIdentity.model_validate(
        {key: getattr(identity, key) for key in _RECORDED_IDENTITY}
    )
