"""MODEL-02/04/05 and WIRE-03: public feedback contract and disclosure boundary."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from career_lab.contracts import v2 as C

ROOT = Path(__file__).resolve().parents[2]


def legacy_feedback() -> dict[str, C.JsonValue]:
    return json.loads((ROOT / "docs/contracts/expansion-v3/examples/FeedbackV2.json").read_text())


def registered_advice() -> dict[str, C.JsonValue]:
    return {
        "criterion": "R2.support",
        "request_id": "review-request",
        "job_id": "feedback-job",
        "input_hash": "a" * 64,
        "registration": {
            "id": "registered-relation",
            "model_revision": "relation-v1",
            "scope": "external_candidate",
            "quality_validated": False,
        },
        "status": "completed",
        "label": "SUPPORTED",
        "evidence_ids": ["source-a"],
        "citations": [
            {
                "session_id": "example",
                "kind": "document",
                "object_id": "source-a",
                "version": 1,
                "observed_at_seq": 0,
            }
        ],
        "mode": "advisory",
        "affects_score": False,
    }


def test_model_02_registered_advice_is_separate_from_scoring() -> None:
    value = legacy_feedback() | {"model_advice": [registered_advice()]}
    report = C.FeedbackV2.model_validate(value)
    assert report.model_advice[0].label == "SUPPORTED"
    assert report.model_advice[0].affects_score is False
    assert report.items == () and report.rule_items is None
    assert report.verified_coverage == report.model_coverage == 1


@pytest.mark.parametrize(
    "change",
    [
        {
            "registration": {
                "id": "fixture",
                "model_revision": "mechanism-v1",
                "scope": "synthetic_fixture",
                "quality_validated": False,
            }
        },
        {"status": "synthetic_mechanism_only"},
        {"status": "failed", "error_code": "model_load_failed"},
        {"evidence_ids": ["source-a", "source-a"]},
        {"citations": []},
        {"input_hash": None},
        {"registration": None},
    ],
)
def test_model_02_invalid_advice_cannot_claim_semantic_success(
    change: dict[str, C.JsonValue],
) -> None:
    with pytest.raises(ValidationError):
        C.FeedbackV2.model_validate(
            legacy_feedback() | {"model_advice": [registered_advice() | change]}
        )


@pytest.mark.parametrize("limited_scope", [False, True])
@pytest.mark.parametrize("hidden", [None, "input-only", "source-a"])
def test_model_04_project_each_advice_by_all_input_dependencies(
    limited_scope: bool,
    hidden: str | None,
) -> None:
    from career_lab.contracts.v2.projection import project_feedback_content

    report = C.FeedbackV2.model_validate(
        legacy_feedback() | {"model_advice": [registered_advice(), registered_advice()]}
    ).model_dump(mode="json")
    visible = C.ObjectRef(session_id="example", kind="document", object_id="visible", version=1)
    source = visible.model_copy(update={"object_id": "source-a"})
    private = visible.model_copy(update={"object_id": "input-only"})
    traces = [
        C.FeedbackReadBoundary(
            path=f"/model_advice/{i}",
            content_hash=C.digest(report["model_advice"][i]),
            dependencies=(source, private) if i == 0 else (source,),
        )
        for i in range(2)
    ]
    for key in ("business_response", "next_options", "independent_understanding"):
        traces.append(
            C.FeedbackReadBoundary(
                path="/" + key,
                content_hash=C.digest(report[key]),
                dependencies=(visible,),
            )
        )
    report["read_boundaries"] = [trace.model_dump(mode="json") for trace in traces]
    before = C.canonical(report)
    actual, partial = project_feedback_content(
        report,
        lambda ref: ref["object_id"] != hidden,
        limited_scope=limited_scope,
    )
    assert C.canonical(report) == before
    assert partial == (hidden is not None)
    for i, advice in enumerate(actual["model_advice"]):
        unavailable = hidden == "source-a" or (hidden == "input-only" and i == 0)
        if unavailable:
            assert advice["status"] == "unavailable"
            assert advice["error_code"] == "evidence_unavailable"
            assert advice["label"] is None and advice["input_hash"] is None
            assert advice["evidence_ids"] == advice["citations"] == []
        else:
            assert advice == report["model_advice"][i]
        assert advice["registration"] == report["model_advice"][i]["registration"]
    for key in ("items", "rule_items", "verified_coverage", "model_coverage", "business_response"):
        assert actual[key] == report[key]


@pytest.mark.parametrize("limited_scope", [False, True])
@pytest.mark.parametrize("tampered", [False, True])
def test_model_04_missing_or_tampered_trace_fails_closed(
    limited_scope: bool,
    tampered: bool,
) -> None:
    from career_lab.contracts.v2.projection import project_feedback_content

    report = C.FeedbackV2.model_validate(
        legacy_feedback() | {"model_advice": [registered_advice()]}
    ).model_dump(mode="json")
    if tampered:
        report["read_boundaries"] = [
            C.FeedbackReadBoundary(
                path="/model_advice/0",
                content_hash="0" * 64,
                dependencies=(
                    C.ObjectRef(
                        session_id="example", kind="document", object_id="source-a", version=1
                    ),
                ),
            ).model_dump(mode="json")
        ]
    actual, partial = project_feedback_content(report, lambda _: True, limited_scope=limited_scope)
    assert partial and actual["model_advice"][0]["label"] is None
    assert actual["model_advice"][0]["error_code"] == "evidence_unavailable"


def test_wire_03_legacy_feedback_bytes_and_hash_are_unchanged() -> None:
    old = legacy_feedback()
    expected = C.canonical(old)
    restored = C.FeedbackV2.model_validate(old)
    assert C.canonical(restored) == expected
    assert C.digest(restored) == "3e671eb62c2c180eeb6499093a2da1f643be64850c21877b1761162ae481fa6d"
    assert C.canonical(restored.model_copy(update={"model_advice": None})) == expected


def test_wire_03_legacy_provenance_omits_new_identity() -> None:
    from career_lab.contracts.v2.provenance import FeedbackProvenance

    old = {
        "code": {"status": "clean", "commit": "parent-commit", "snapshot": "parent-snapshot"},
        "evaluation_version": "unchanged",
        "rules_version": "unchanged",
        "prompt_version": "unchanged",
        "provider": "not_configured",
        "model": "not_configured",
        "retries": 0,
    }
    assert FeedbackProvenance.model_validate(old).model_dump(mode="json") == old


@pytest.mark.parametrize("change", [{"session_id": "foreign"}, {"observed_at_seq": 1}])
def test_model_04_reject_cross_session_and_future_citations(change: dict[str, C.JsonValue]) -> None:
    advice = registered_advice()
    advice["citations"][0].update(change)
    with pytest.raises(ValidationError, match="advice citation"):
        C.FeedbackV2.model_validate(legacy_feedback() | {"model_advice": [advice]})
