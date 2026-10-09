"""Frozen 8663c44 wire values; additive preview fields must remain absent on old records."""

import json
from pathlib import Path

import pytest

from career_lab.contracts import v2 as C
from career_lab.contracts.v2.projection import project_feedback_content

REVIEWREQUEST_BYTES = (
    '{"as_of":{"business_seq":0,"schema_version":2,"storage_revision":1,"workspace_re'
    'vision":1},"decision":null,"evaluation":{"media_type":"application/json","path":'
    '"runtime/evaluation.json","schema_version":2,"sha256":"0000000000000000000000000'
    '000000000000000000000000000000000000000"},"executor":{"delegation_id":null,"id":'
    '"human","kind":"human","schema_version":2},"followup_of":[],"id":"fixed-review",'
    '"purpose":"exploration","question":"","schema_version":2,"scope":[],"session_id"'
    ':"fixed-session","subjects":[{"config_version":null,"kind":"product","object_id"'
    ':"fixed-work","schema_version":2,"session_id":"fixed-session","version":1}],"ver'
    'sion":1}'
)
REVIEWREQUEST_HASH = "2270d7ddaadf7464c5014f5d2ba55d467ffe076825b7fd455d82eed8f3e1e776"

FEEDBACKV2_BYTES = (
    '{"adoption_record":null,"as_of":{"business_seq":0,"schema_version":2,"storage_re'
    'vision":1,"workspace_revision":1},"business_response":"No recorded business deci'
    'sion.","evaluation":{"media_type":"application/json","path":"runtime/evaluation.'
    'json","schema_version":2,"sha256":"000000000000000000000000000000000000000000000'
    '0000000000000000000"},"historical_responsibilities":null,"id":"fixed-feedback","'
    'independent_understanding":"unobserved","items":[],"mode":"advisory","model_cove'
    'rage":0.0,"next_options":[],"read_boundaries":null,"read_projection":null,"rule_'
    'items":null,"schema_version":2,"session_id":"fixed-session","subject":{"config_v'
    'ersion":null,"kind":"review","object_id":"fixed-review","schema_version":2,"sess'
    'ion_id":"fixed-session","version":1},"verified_coverage":0.0,"verified_facts":nu'
    'll,"version":1}'
)
FEEDBACKV2_HASH = "463a980bc6e56e9f10e238b902f1e3d1c4b07e3ff58495336d3e807248e57a9e"

PROJECTION_FALSE = (
    '{"adoption_record":null,"as_of":{"business_seq":0,"schema_version":2,"storage_re'
    'vision":1,"workspace_revision":1},"business_response":"No recorded business deci'
    'sion.","evaluation":{"media_type":"application/json","path":"runtime/evaluation.'
    'json","schema_version":2,"sha256":"000000000000000000000000000000000000000000000'
    '0000000000000000000"},"historical_responsibilities":null,"id":"fixed-feedback","'
    'independent_understanding":"unobserved","items":[],"mode":"advisory","model_cove'
    'rage":0.0,"next_options":[],"read_boundaries":null,"read_projection":null,"rule_'
    'items":null,"schema_version":2,"session_id":"fixed-session","subject":{"config_v'
    'ersion":null,"kind":"review","object_id":"fixed-review","schema_version":2,"sess'
    'ion_id":"fixed-session","version":1},"verified_coverage":0.0,"verified_facts":nu'
    'll,"version":1}'
)

PROJECTION_TRUE = (
    '{"adoption_record":null,"as_of":{"business_seq":0,"schema_version":2,"storage_re'
    'vision":1,"workspace_revision":1},"business_response":"当前权限下部分支持依据不可核验，相关判断待核验。"'
    ',"evaluation":{"media_type":"application/json","path":"runtime/evaluation.json",'
    '"schema_version":2,"sha256":"000000000000000000000000000000000000000000000000000'
    '0000000000000"},"historical_responsibilities":null,"id":"fixed-feedback","indepe'
    'ndent_understanding":"unobserved","items":[],"mode":"advisory","model_coverage":'
    '0.0,"next_options":["可补充当前可访问的依据，或由具备权限的人核对。"],"read_boundaries":null,"read_proj'
    'ection":"partial","rule_items":null,"schema_version":2,"session_id":"fixed-sessi'
    'on","subject":{"config_version":null,"kind":"review","object_id":"fixed-review",'
    '"schema_version":2,"session_id":"fixed-session","version":1},"verified_coverage"'
    ':0.0,"verified_facts":null,"version":1}'
)


@pytest.mark.parametrize(
    ("model", "raw", "expected_hash"),
    [
        (C.ReviewRequest, REVIEWREQUEST_BYTES, REVIEWREQUEST_HASH),
        (C.FeedbackV2, FEEDBACKV2_BYTES, FEEDBACKV2_HASH),
    ],
)
def test_wire_03_saved_legacy_record_bytes(model, raw: str, expected_hash: str) -> None:
    value = model.model_validate_json(raw)
    assert C.canonical(value) == raw
    assert C.digest(value) == expected_hash


@pytest.mark.parametrize(
    ("limited", "expected"), [(False, PROJECTION_FALSE), (True, PROJECTION_TRUE)]
)
def test_wire_03_legacy_projection_bytes(limited: bool, expected: str) -> None:
    projected, partial = project_feedback_content(
        json.loads(FEEDBACKV2_BYTES), lambda ref: True, limited_scope=limited
    )
    assert C.canonical(projected) == expected
    assert partial is limited


def test_preview_public_errors_are_in_the_exported_contract(tmp_path: Path) -> None:
    from career_lab.contracts.v2.export import export

    root = Path(__file__).resolve().parents[2]
    export(root, tmp_path)
    expected = {
        "preview_kind_required",
        "human_preference_required",
        "preview_subject_required",
        "preview_cycle_closed",
    }
    for directory in (tmp_path, root / "docs/contracts/expansion-v3"):
        codes = set(json.loads((directory / "errors.json").read_text())["codes"])
        assert expected <= codes, sorted(expected - codes)
