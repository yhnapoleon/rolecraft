"""A deliberately narrow numeric verifier. No open-text semantic claims are G0."""
import json
import math
import operator
import re

from career_lab.contracts.v2.data import AnnotationDecision, AnnotationV2
from career_lab.contracts.v2.core import ProtocolError
from .temporal import legal_evidence_ids

OPS = {"==": operator.eq, "<=": operator.le, ">=": operator.ge, "<": operator.lt, ">": operator.gt}
GRAMMAR = re.compile(r"^(capacity|config_version|dev_days|version) (==|<=|>=|<|>) (-?\d+(?:\.\d+)?)$")


def verify_numeric(record, *, annotation_version="numeric-v1"):
    if record.family != "relation":
        raise ProtocolError("g0_scope_not_supported")
    package = record.model_input.evidence
    match = GRAMMAR.fullmatch(package.claim)
    if not match or package.completeness != "complete":
        raise ProtocolError("g0_scope_not_supported")
    allowed=legal_evidence_ids(record.model_input)
    field, op, target = match.groups()
    target = float(target)
    values = []
    for item in package.candidate_evidence:
        try:
            data = json.loads(item.text)
        except ValueError:
            continue
        value = data.get(field) if isinstance(data, dict) else None
        if type(value) in (float, int) and math.isfinite(value):
            if item.id not in allowed:continue
            values.append((item.id, value))
    if len({v for _, v in values}) > 1:
        raise ProtocolError("g0_conflicting_values")
    label = "INSUFFICIENT" if not values else "SUPPORTED" if OPS[op](values[0][1], target) else "CONTRADICTED"
    decision = AnnotationDecision(task_type="relation", label=label, applicability=package.applicability,
        evidence_ids=tuple(i for i, _ in values[:1]), acceptable_evidence_sets=tuple((i,) for i, _ in values) if values else ((),),
        evidence_evaluable=True, missing_reason=f"missing current {field}" if not values else None)
    return AnnotationV2(record_id=record.record_id, input_hash=record.input_hash, annotation_version=annotation_version,
        label_tier="G0", status="accepted", passes=(), final=decision, verifier_id="w07-numeric-grammar-v1")
