"""Independent consumer probes: fully parsed annotation, public pairing and strict gold check."""

from dataclasses import replace
import pytest
from test_w08_models import examples
from career_lab.contracts.v2.data import AnnotationV2
from career_lab.contracts.v2.core import ProtocolError


@pytest.mark.parametrize("sets", [[], [[]], [["e1"], []], [["e1"]]])
@pytest.mark.parametrize("label", ["SUPPORTED", "CONTRADICTED"])
def test_positive_joint_after_annotation_full_revalidation(sets, label):
    row = examples()[0]
    raw = row.annotation.model_dump(mode="json")
    raw["final"].update(
        label=label, evidence_ids=["e1"], acceptable_evidence_sets=sets, evidence_evaluable=True
    )
    annotation = AnnotationV2.model_validate_json(
        AnnotationV2.model_validate(raw).model_dump_json()
    )
    changed = replace(row, annotation=annotation)
    if sets == [["e1"]]:
        changed.validate()
    else:
        with pytest.raises(ProtocolError):
            changed.validate()


@pytest.mark.parametrize("evaluable", [True, False])
def test_insufficient_empty_boundary_stays_legal(evaluable):
    row = examples()[0]
    raw = row.annotation.model_dump(mode="json")
    raw["final"].update(
        label="INSUFFICIENT",
        evidence_ids=[],
        acceptable_evidence_sets=[[]] if evaluable else [],
        evidence_evaluable=evaluable,
        missing_reason="explicit fixture uncertainty",
    )
    replace(
        row,
        annotation=AnnotationV2.model_validate_json(
            AnnotationV2.model_validate(raw).model_dump_json()
        ),
    ).validate()
