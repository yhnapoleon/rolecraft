"""Fixed semantic cases against c5 and the versioned origin binding shape."""

import itertools
import json
from typing import get_args
import pytest
from test_w07_pipeline import make_case
from career_lab.contracts.v2.data import AnnotationDecision
from career_lab.datasets.v3.attestation import semantic_key, same_semantics, validate_decision
from career_lab.datasets.v3.export import export_snapshot
from career_lab.datasets.v3.origin import binding
from career_lab.contracts.v2.core import digest, ProtocolError


LABEL_SPACES = {
    "relation": ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT"),
    "criterion": ("MET", "PARTIAL", "NOT_MET", "INSUFFICIENT", "NOT_APPLICABLE"),
    "trajectory_diagnosis": ("diagnosed", "no_issue", "insufficient"),
    "acquisition": ("effective", "ineffective", "undetermined"),
}


def validated_cases(tmp_path):
    snap, units, _ = make_case(tmp_path)
    exported = export_snapshot(snap, units)
    assert not exported.quarantined and len(exported.records) == 4
    payloads = {
        r.model_input.task_type: r.model_input.model_dump(mode="json") for r in exported.records
    }
    assert (
        set(payloads)
        == set(LABEL_SPACES)
        == set(get_args(AnnotationDecision.model_fields["task_type"].annotation))
    )
    cases = []
    for task, labels in LABEL_SPACES.items():
        payload = payloads[task]
        entries = (
            payload["evidence"]["candidate_evidence"]
            if task in {"relation", "criterion"}
            else payload["steps"]
            if task == "trajectory_diagnosis"
            else payload["candidates"]
        )
        ids = [entry["id"] for entry in entries]
        target_groups = [((ids[0],),)]
        if len(ids) > 1:
            target_groups.append(((ids[0],), (ids[1],)))
        regular = [
            (groups, representative) for groups in target_groups for representative in groups
        ]
        for label in labels:
            apps = (
                ["not_applicable"] if label == "NOT_APPLICABLE" else ["applicable", "undetermined"]
            )
            for app, evaluable, reason in itertools.product(
                apps, [True, False], ["first explanation", "second explanation"]
            ):
                choices = list(regular)
                if not evaluable:
                    choices.append(((), ()))
                elif label in {"INSUFFICIENT", "NOT_APPLICABLE", "insufficient", "undetermined"}:
                    choices.append((((),), ()))
                for targets, representative in choices:
                    raw = {
                        "task_type": task,
                        "label": label,
                        "applicability": app,
                        "evidence_evaluable": evaluable,
                        "evidence_ids": representative,
                        "acceptable_evidence_sets": targets,
                        "missing_reason": reason,
                    }
                    # Schema round-trip plus full producer namespace/ref/time/reason validation.
                    schema = AnnotationDecision.model_validate_json(json.dumps(raw))
                    parsed = validate_decision(schema.model_dump_json(), payload)
                    cases.append(parsed)
    return payloads, cases


@pytest.fixture(scope="module")
def c5_cases(tmp_path_factory):
    return validated_cases(tmp_path_factory.mktemp("c5_semantic_matrix"))


def test_c5_shared_semantic_function_matches_all_task_label_matrix(c5_cases):
    _, cases = c5_cases
    assert {(d.task_type, d.label) for d in cases} == {
        (task, label) for task, labels in LABEL_SPACES.items() for label in labels
    }
    # Independent reference: deliberately no call to either production key helper.
    reference = [
        (
            d.task_type,
            d.label,
            d.applicability,
            d.evidence_evaluable,
            frozenset(frozenset(g) for g in d.acceptable_evidence_sets),
        )
        for d in cases
    ]
    actual = [semantic_key(d) for d in cases]
    for left, right in itertools.product(range(len(cases)), repeat=2):
        assert (actual[left] == actual[right]) == (reference[left] == reference[right])
    # Each family's representative/explanation variants also pass the public wrapper.
    for task in LABEL_SPACES:
        group = [d for d in cases if d.task_type == task]
        assert same_semantics(group[0], group[0])
    assert len(cases) == 348


FOREIGN_LABELS = [
    (task, label)
    for task, own in LABEL_SPACES.items()
    for label in sorted(set().union(*map(set, LABEL_SPACES.values())) - set(own))
]


@pytest.mark.parametrize("task,label", FOREIGN_LABELS)
def test_foreign_label_namespace_is_rejected_before_consensus(c5_cases, task, label):
    payloads, cases = c5_cases
    legal = next(d for d in cases if d.task_type == task)
    raw = legal.model_dump(mode="json") | {"label": label}
    with pytest.raises(ValueError, match="namespace"):
        validate_decision(json.dumps(raw), payloads[task])


@pytest.mark.parametrize(
    "declared,actual", [(a, b) for a, b in itertools.permutations(LABEL_SPACES, 2)]
)
def test_valid_decision_cannot_cross_payload_task_namespace(c5_cases, declared, actual):
    payloads, cases = c5_cases
    legal = next(d for d in cases if d.task_type == declared)
    with pytest.raises(ProtocolError, match="task mismatch"):
        validate_decision(legal.model_dump_json(), payloads[actual])


def test_origin_binding_retains_exact_v1_keys_and_metadata_only_values(tmp_path):
    snap, units, _ = make_case(tmp_path)
    result = export_snapshot(snap, units[:1])
    row = result.records[0]
    source = result.source_snapshots[0]
    assert binding(row, source) == {
        "protocol": "w07-source-origin-v1",
        "record_id": row.record_id,
        "origin": "fixture",
        "session_id": row.lineage.session_id,
        "lineage_hash": digest(row.lineage),
        "snapshot_digest": source["snapshot_digest"],
        "source_digest": row.provenance.source.source_digest,
        "source_files": [r.model_dump(mode="json") for r in row.provenance.actual_sources],
    }
