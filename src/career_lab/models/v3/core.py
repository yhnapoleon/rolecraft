"""Private model adapter types consuming W01's public inputs and labels."""
from dataclasses import dataclass
from typing import Any
import numpy as np
from pydantic import TypeAdapter

from career_lab.contracts.v2.core import ProtocolError, digest
from career_lab.contracts.v2.data import ModelInput, AnnotationV2
from .temporal import legal_evidence_ids,validate_gold_time

LABELS = {
    "relation": ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT"),
    "criterion": ("MET", "PARTIAL", "NOT_MET", "INSUFFICIENT", "NOT_APPLICABLE"),
}
INPUT = TypeAdapter(ModelInput)


def checked_input(item):
    raw = item.model_dump(mode="json") if hasattr(item, "model_dump") else item
    item = INPUT.validate_python(raw)
    if item.task_type not in LABELS:
        raise ProtocolError("unsupported_model_task")
    package = item.evidence
    sessions = {r.session_id for r in package.subjects} | {c.ref.session_id for c in package.candidate_evidence}
    if len(sessions) > 1:
        raise ProtocolError("cross_session_model_input")
    return item


def input_problem(item):
    if item.evidence.completeness != "complete":
        return "input_" + item.evidence.completeness
    if not item.evidence.claim.strip():
        return "empty_claim"
    try:legal_evidence_ids(item)
    except ProtocolError as exc:return exc.code
    return None


@dataclass(frozen=True)
class Example:
    record_id: str
    item: Any
    annotation: AnnotationV2
    split: str
    structure_id: str
    component_id: str
    language: str = "unspecified"
    bucket: str = "unspecified"
    fixture: bool = False

    def validate(self):
        try:return self._validate()
        except (ValueError,TypeError,KeyError) as cause:
            code=getattr(cause,"code","training_record_schema_invalid")
            error=ProtocolError(code,f"record {self.record_id}: {code}")
            error.record_id=self.record_id;error.report={"record_id":self.record_id,"reason":code,"cause_type":type(cause).__name__}
            raise error from cause

    def _validate(self):
        item = checked_input(self.item)
        annotation = AnnotationV2.model_validate(self.annotation.model_dump(mode="json"))
        if self.split not in {"train", "dev", "test", "regression"}:
            raise ProtocolError("unknown_partition")
        if annotation.record_id != self.record_id or annotation.input_hash != digest(item):
            exc=ProtocolError("training_input_annotation_mismatch");exc.record_id=self.record_id;raise exc
        if annotation.status != "accepted" or annotation.final is None:
            raise ProtocolError("unaccepted_training_label")
        if annotation.final.task_type != item.task_type or annotation.final.label not in LABELS[item.task_type]:
            raise ProtocolError("training_label_namespace")
        valid = {c.id for c in item.evidence.candidate_evidence}
        final = annotation.final
        validate_gold_time(item,final)
        if set(final.evidence_ids) - valid or any(set(s) - valid for s in final.acceptable_evidence_sets):
            raise ProtocolError("training_gold_reference_invalid")
        if any(len(s) != len(set(s)) for s in final.acceptable_evidence_sets):
            raise ProtocolError("training_gold_duplicate_reference")
        if final.evidence_evaluable:
            if not final.acceptable_evidence_sets:
                raise ProtocolError("training_evidence_targets_missing")
            if set(final.evidence_ids) not in [set(group) for group in final.acceptable_evidence_sets]:
                raise ProtocolError("final_evidence_not_an_acceptable_target")
            if any(not s for s in final.acceptable_evidence_sets) and final.label not in {"INSUFFICIENT", "NOT_APPLICABLE"}:
                raise ProtocolError("unsupported_empty_gold_evidence")
        return self


def training_examples(examples, task, *, split="train", require_all_classes=True):
    rows = list(examples)
    if task not in LABELS or not rows:
        raise ProtocolError("training_data_required")
    for row in rows:
        row.validate()
        if row.split != split:
            raise ProtocolError("training_partition_forbidden", status=403)
        if row.item.task_type != task:
            raise ProtocolError("mixed_training_tasks")
        if input_problem(row.item):
            raise ProtocolError("incomplete_training_input")
    if len({r.record_id for r in rows}) != len(rows):
        raise ProtocolError("duplicate_training_record")
    if require_all_classes and {r.annotation.final.label for r in rows} != set(LABELS[task]):
        raise ProtocolError("training_class_coverage_missing")
    return rows


def evidence_target(row):
    row.validate()
    final = row.annotation.final
    if not final.evidence_evaluable:
        return None
    # Deterministic minimum alternative for training; evaluation considers every
    # acceptable set and never assumes this one is the only correct answer.
    return set(min(final.acceptable_evidence_sets, key=lambda s: (len(s), tuple(sorted(s)))))


def probabilities(values, task):
    array = np.asarray(values, dtype=float)
    if array.shape != (len(LABELS[task]),) or not np.isfinite(array).all() or (array < 0).any() or not np.isclose(array.sum(), 1.0, atol=1e-7):
        raise ProtocolError("invalid_classifier_probabilities")
    return tuple(float(x) for x in array)


def softmax(values, axis=-1):
    values = np.asarray(values, dtype=float)
    exp = np.exp(values - values.max(axis=axis, keepdims=True))
    return exp / exp.sum(axis=axis, keepdims=True)


@dataclass(frozen=True)
class Prediction:
    task_type: str
    input_hash: str
    model_revision: str
    status: str
    label: str | None
    probabilities: tuple[float, ...] | None
    evidence_ids: tuple[str, ...] = ()
    evidence_probabilities: tuple[tuple[str, float], ...] = ()
    reason_code: str | None = None

    def validate(self, item):
        item = checked_input(item)
        if not isinstance(self.model_revision,str) or not self.model_revision.strip():
            raise ProtocolError("prediction_model_identity_required")
        if self.task_type != item.task_type or self.input_hash != digest(item):
            raise ProtocolError("prediction_input_identity_mismatch")
        if self.status not in {"ok", "abstained", "failed"}:
            raise ProtocolError("prediction_status_invalid")
        if self.probabilities is not None:
            probabilities(self.probabilities, self.task_type)
        if self.status == "ok" and (self.label not in LABELS[self.task_type] or self.probabilities is None):
            raise ProtocolError("prediction_label_namespace")
        if self.status == "ok" and self.label != LABELS[self.task_type][int(np.argmax(self.probabilities))]:
            raise ProtocolError("prediction_probability_order_mismatch")
        if self.status != "ok" and (self.label is not None or not self.reason_code):
            raise ProtocolError("failed_prediction_requires_reason_without_label")
        valid = {c.id for c in item.evidence.candidate_evidence}
        if len(self.evidence_ids) != len(set(self.evidence_ids)) or set(self.evidence_ids) - valid:
            raise ProtocolError("prediction_invalid_reference")
        if len({k for k, v in self.evidence_probabilities}) != len(self.evidence_probabilities):
            raise ProtocolError("duplicate_evidence_probability")
        if any(k not in valid or not np.isfinite(v) or not 0 <= v <= 1 for k, v in self.evidence_probabilities):
            raise ProtocolError("invalid_evidence_probability")
        return self

    def as_dict(self):
        from dataclasses import asdict
        return asdict(self) | {"labels": list(LABELS[self.task_type]), "mode": "advisory", "affects_score": False,
                               "distribution_kind": "classifier_probability"}


def abstention(item, revision, reason):
    return Prediction(item.task_type, digest(item), revision, "abstained", None, None, reason_code=reason)


def prediction(item, revision, probs, scores, threshold=0.5):
    p = probabilities(probs, item.task_type)
    ids = tuple(c.id for c in item.evidence.candidate_evidence)
    if len(scores) != len(ids) or not 0 <= threshold <= 1:
        raise ProtocolError("invalid_evidence_head_shape")
    ev = tuple((eid, float(score)) for eid, score in zip(ids, scores, strict=True))
    out = Prediction(item.task_type, digest(item), revision, "ok", LABELS[item.task_type][int(np.argmax(p))], p,
                     tuple(eid for eid, score in ev if score >= threshold), ev)
    return out.validate(item)
