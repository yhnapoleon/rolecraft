"""Independent c4 probes after full AnnotationV2 revalidation, not model_copy shortcuts."""

from dataclasses import replace
import pytest
from test_w07_pipeline import make_case
from career_lab.contracts.v2.core import ProtocolError
from career_lab.contracts.v2.data import (
    AnnotationV2,
    validate_record_annotation,
    metadata_projection,
)
from career_lab.datasets.v3.export import export_snapshot
from career_lab.datasets.v3.temporal import validate_time_citations


@pytest.mark.parametrize(
    "family,label",
    [
        ("relation", "SUPPORTED"),
        ("relation", "CONTRADICTED"),
        ("criterion", "MET"),
        ("criterion", "PARTIAL"),
        ("criterion", "NOT_MET"),
    ],
)
@pytest.mark.parametrize("sets", [[], [[]], [["e1"], []], [["e1"]]])
def test_positive_evaluable_requires_every_alternative_nonempty(tmp_path, family, label, sets):
    snapshot, units, _ = make_case(tmp_path)
    record = export_snapshot(snapshot, [next(u for u in units if u.family == family)]).records[0]
    record = record.model_copy(update={"label_tier": "G0"})
    annotation = AnnotationV2.model_validate(
        {
            "record_id": record.record_id,
            "input_hash": record.input_hash,
            "annotation_version": "c4-probe",
            "label_tier": "G0",
            "status": "accepted",
            "verifier_id": "unit-schema-probe",
            "passes": [],
            "final": {
                "task_type": record.model_input.task_type,
                "label": label,
                "evidence_ids": ["e1"],
                "acceptable_evidence_sets": sets,
                "evidence_evaluable": True,
            },
        }
    )
    annotation = AnnotationV2.model_validate_json(annotation.model_dump_json())
    for check in [
        lambda: validate_record_annotation(record, annotation, require_accepted=True),
        lambda: validate_time_citations(record.model_input, annotation.final),
        lambda: metadata_projection(record, annotation),
    ]:
        if sets == [["e1"]]:
            check()
        else:
            with pytest.raises((ValueError, ProtocolError)):
                check()


@pytest.mark.parametrize(
    "family,label",
    [("relation", "INSUFFICIENT"), ("criterion", "INSUFFICIENT"), ("criterion", "NOT_APPLICABLE")],
)
@pytest.mark.parametrize("evaluable", [True, False])
def test_legal_empty_or_nonevaluable_boundaries_remain(tmp_path, family, label, evaluable):
    snapshot, units, _ = make_case(tmp_path)
    record = (
        export_snapshot(snapshot, [next(u for u in units if u.family == family)])
        .records[0]
        .model_copy(update={"label_tier": "G0"})
    )
    annotation = AnnotationV2.model_validate(
        {
            "record_id": record.record_id,
            "input_hash": record.input_hash,
            "annotation_version": "c4-probe",
            "label_tier": "G0",
            "status": "accepted",
            "verifier_id": "unit-schema-probe",
            "passes": [],
            "final": {
                "task_type": record.model_input.task_type,
                "label": label,
                "applicability": "not_applicable" if label == "NOT_APPLICABLE" else "undetermined",
                "evidence_ids": [],
                "acceptable_evidence_sets": [[]] if evaluable else [],
                "evidence_evaluable": evaluable,
                "missing_reason": "explicit fixture uncertainty",
            },
        }
    )
    annotation = AnnotationV2.model_validate_json(annotation.model_dump_json())
    validate_record_annotation(record, annotation, require_accepted=True)
    validate_time_citations(record.model_input, annotation.final)


def test_unknown_temporal_frame_and_pending_g1_cannot_be_accepted(tmp_path):
    snapshot, units, _ = make_case(tmp_path)
    result = export_snapshot(snapshot, [replace(units[0], evaluation_time_known=False)])
    record = result.records[0]
    pending = result.annotations[0]
    assert metadata_projection(record, pending).annotation_status == "pending"
    for tier in ["G1", "G2"]:
        r = record.model_copy(update={"label_tier": tier})
        a = AnnotationV2.model_validate(pending.model_dump(mode="json") | {"label_tier": tier})
        with pytest.raises(ValueError):
            validate_record_annotation(r, a, require_accepted=True)


@pytest.mark.parametrize(
    "field,value",
    [
        ("invocation_id", None),
        ("context_id", 17),
        ("context_id", "  "),
        ("independence_method", "shared_context"),
    ],
)
def test_invalid_actual_context_receipt_is_preserved_as_failure(tmp_path, field, value):
    from test_w07_pipeline import batch_for, signed

    batch, result, _ = batch_for(tmp_path)
    request = batch.claim(result.records[0].record_id, 1)
    receipt = signed(request) | {field: value}
    stored = batch.receive(receipt)
    assert (
        stored["pass"]["status"] == "failed"
        and stored["error_code"] == "actual_invocation_context_required"
    )
    assert (
        stored["receipt"][field] == value
        and batch.annotation(result.records[0].record_id).status == "pending"
    )
