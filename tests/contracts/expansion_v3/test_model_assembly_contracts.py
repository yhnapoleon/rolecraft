"""DTO-01/02/03: optional model-assembly fields, label domains and synthetic display.

Expected bytes come from the pre-change export (main d163747), never from this code.
"""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from career_lab.contracts import v2 as C
from career_lab.contracts.v2.discovery import public_models
from career_lab.contracts.v2.export import integration_example
from career_lab.contracts.v2.projection import project_feedback_content
from career_lab.contracts.v2.provenance import FeedbackProvenance, RegisteredModelIdentity

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures/model_assembly"
RUBRIC = {
    "id": "rubric-v2-final-20261009",
    "sha256": "aa0de4302ca42368a262dc516fd3d8dab83286dd10dff7350c35b0c3772321cd",
}
LEGACY_IDENTITY = {
    "id": "registered-relation",
    "model_revision": "relation-v1",
    "scope": "external_candidate",
    "quality_validated": False,
}


def exported(value: C.JsonValue) -> bytes:
    """The exporter's on-disk example format."""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def legacy_feedback() -> dict[str, C.JsonValue]:
    return json.loads((ROOT / "docs/contracts/expansion-v3/examples/FeedbackV2.json").read_text())


def source(object_id: str = "source-a", session_id: str = "example") -> dict[str, C.JsonValue]:
    return {
        "session_id": session_id,
        "kind": "document",
        "object_id": object_id,
        "version": 1,
        "observed_at_seq": 0,
    }


def advice(**changes: C.JsonValue) -> dict[str, C.JsonValue]:
    value: dict[str, C.JsonValue] = {
        "criterion": "R2.support",
        "request_id": "review-request",
        "job_id": "feedback-job",
        "input_hash": "a" * 64,
        "registration": dict(LEGACY_IDENTITY),
        "status": "completed",
        "label": "SUPPORTED",
        "evidence_ids": ["source-a"],
        "citations": [source()],
        "mode": "advisory",
        "affects_score": False,
    }
    return value | changes


def criterion_identity(**changes: C.JsonValue) -> dict[str, C.JsonValue]:
    return (
        LEGACY_IDENTITY
        | {
            "id": "registered-criterion",
            "kind": "linear",
            "task_type": "criterion",
            "criteria": ["R1.metrics", "R6.alternatives"],
            "rubric_version": dict(RUBRIC),
        }
        | changes
    )


def synthetic_identity(**changes: C.JsonValue) -> dict[str, C.JsonValue]:
    return LEGACY_IDENTITY | {"id": "fixture", "scope": "synthetic_fixture"} | changes


def unit(index: int, label: str | None = "SUPPORTED", **changes: C.JsonValue):
    text = "Keep human fallback." if index % 2 else "Defer until the owner is verified."
    value: dict[str, C.JsonValue] = {
        "index": index,
        "subject": {
            "session_id": "example",
            "kind": "product",
            "object_id": "work",
            "version": 1,
            "observed_at_seq": 0,
            "span_start": 40 * index,
            "span_end": 40 * index + len(text),
            "quote": text,
        },
        "unit_hash": f"{index:064x}",
        "status": "completed" if label else "abstained",
        "label": label,
        "evidence_ids": ["source-a"] if label in {"SUPPORTED", "CONTRADICTED"} else [],
        "citations": [source()] if label in {"SUPPORTED", "CONTRADICTED"} else [],
        "reason_code": None if label else "unit_exceeds_encoder_limit",
    }
    return value | changes


def counts(**values: int) -> dict[str, int]:
    zero = dict.fromkeys(
        (
            "supported",
            "contradicted",
            "insufficient",
            "abstained",
            "failed",
            "skipped_short",
            "over_budget",
        ),
        0,
    )
    return zero | values


def feedback_with(*items: dict[str, C.JsonValue]) -> C.FeedbackV2:
    return C.FeedbackV2.model_validate(legacy_feedback() | {"model_advice": list(items)})


# DTO-01 ------------------------------------------------------------------------------


def test_dto_01_every_public_example_keeps_its_pre_change_bytes() -> None:
    golden = json.loads((FIXTURES / "examples-main-d163747.json").read_text())["examples"]
    models = public_models()
    assert sorted(models) == sorted(golden)
    changed = [
        name
        for name, model in models.items()
        if hashlib.sha256(exported(integration_example(model).model_dump(mode="json"))).hexdigest()
        != golden[name]
    ]
    assert changed == []


def test_dto_01_unset_identity_advice_and_provenance_fields_keep_legacy_bytes() -> None:
    identity = RegisteredModelIdentity.model_validate(
        LEGACY_IDENTITY
        | {
            "kind": None,
            "task_type": "relation",
            "criteria": None,
            "dataset": None,
            "components": None,
            "fusion": None,
            "weights_stage": None,
            "rubric_version": None,
        }
    )
    assert identity.model_dump(mode="json") == LEGACY_IDENTITY
    legacy = advice()
    explicit = C.RegisteredModelAdvice.model_validate(
        legacy
        | {"task_type": "relation", "units": None, "aggregation": None}
        | {"reconciliation": None}
    )
    assert C.canonical(explicit) == C.canonical(C.RegisteredModelAdvice.model_validate(legacy))
    assert set(explicit.model_dump(mode="json")) == set(legacy) | {"error_code", "schema_version"}
    old = {
        "code": {"status": "clean", "commit": "parent-commit", "snapshot": "parent-snapshot"},
        "evaluation_version": "unchanged",
        "rules_version": "unchanged",
        "prompt_version": "unchanged",
        "provider": "not_configured",
        "model": "not_configured",
        "retries": 0,
        "registered_model": LEGACY_IDENTITY,
    }
    provenance = FeedbackProvenance.model_validate(
        old | {"registered_models": None, "support_model": None, "base_url": None}
    )
    assert provenance.model_dump(mode="json") == old
    report = legacy_feedback()
    restored = C.FeedbackV2.model_validate(report)
    assert C.canonical(restored) == C.canonical(report)
    assert C.digest(restored) == "3e671eb62c2c180eeb6499093a2da1f643be64850c21877b1761162ae481fa6d"


def test_dto_01_new_identity_fields_round_trip_when_recorded() -> None:
    fusion = RegisteredModelIdentity.model_validate(
        LEGACY_IDENTITY
        | {
            "id": "fusion",
            "kind": "probability_fusion",
            "dataset": {
                "dataset_id": "rolecraft-relations-v1",
                "dataset_manifest_sha256": "b" * 64,
                "label_tiers": ["G0", "G2v"],
            },
            "components": [
                {
                    "role": "left",
                    "id": "linear-a",
                    "kind": "linear",
                    "model_revision": "linear-return:x",
                    "alpha": 0.25,
                },
                {
                    "role": "right",
                    "id": "encoder-b",
                    "kind": "huggingface_encoder",
                    "model_revision": "hf-finetuned:y",
                    "alpha": 0.75,
                },
            ],
            "fusion": {"alpha": 0.25, "evidence_threshold": 0.5, "fusion_gain_observed": True},
            "weights_stage": "supervised_finetuned",
        }
    )
    dumped = fusion.model_dump(mode="json")
    assert "task_type" not in dumped and "criteria" not in dumped
    assert dumped["dataset"]["label_tiers"] == ["G0", "G2v"]
    assert RegisteredModelIdentity.model_validate(dumped) == fusion
    criterion = RegisteredModelIdentity.model_validate(criterion_identity())
    assert criterion.model_dump(mode="json")["rubric_version"] == RUBRIC
    assert criterion.model_dump(mode="json")["task_type"] == "criterion"
    both = FeedbackProvenance.model_validate(
        {
            "code": {"status": "not_recorded"},
            "evaluation_version": "e",
            "rules_version": "r",
            "prompt_version": "p",
            "provider": "openai_compatible",
            "model": "qa-loopback-judge",
            "registered_model": LEGACY_IDENTITY,
            "registered_models": [LEGACY_IDENTITY, criterion_identity()],
            "support_model": {"provider": "openai_compatible", "model": "qa-loopback-support"},
            "base_url": "http://127.0.0.1:8000/v1",
        }
    )
    assert both.model_dump(mode="json")["support_model"] == {
        "provider": "openai_compatible",
        "model": "qa-loopback-support",
    }
    assert both.model_dump(mode="json")["base_url"] == "http://127.0.0.1:8000/v1"
    hosted = both.support_model.model_copy(update={"base_url": "https://api.deepseek.com"})
    assert hosted.model_dump(mode="json")["base_url"] == "https://api.deepseek.com"
    assert len(both.registered_models) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"rubric_version": None},
        {"criteria": None},
        {"criteria": []},
        {"task_type": "relation"},
        {"rubric_version": {"id": "rubric-v2-final-20261009", "sha256": "short"}},
    ],
)
def test_dto_01_criterion_registration_requires_its_rubric_version_and_criteria(
    change: dict[str, C.JsonValue],
) -> None:
    with pytest.raises(ValidationError):
        RegisteredModelIdentity.model_validate(criterion_identity(**change))


# DTO-02 ------------------------------------------------------------------------------


def criterion_advice(**changes: C.JsonValue) -> dict[str, C.JsonValue]:
    return (
        advice(
            criterion="R1.metrics",
            task_type="criterion",
            registration=criterion_identity(),
            label="MET",
            reconciliation={"rule_conflict": False, "applicability_established": True},
        )
        | changes
    )


def test_dto_02_criterion_advice_uses_the_five_label_domain() -> None:
    for label in ("MET", "PARTIAL", "NOT_MET", "INSUFFICIENT", "NOT_APPLICABLE"):
        report = feedback_with(criterion_advice(label=label))
        dumped = report.model_dump(mode="json")["model_advice"][0]
        assert dumped["task_type"] == "criterion" and dumped["label"] == label
    relation = feedback_with(advice()).model_dump(mode="json")["model_advice"][0]
    assert "task_type" not in relation and relation["criterion"] == "R2.support"


@pytest.mark.parametrize(
    "value",
    [
        criterion_advice(label="SUPPORTED"),
        criterion_advice(label="CONTRADICTED"),
        advice(label="MET"),
        advice(label="NOT_APPLICABLE"),
        criterion_advice(units=[unit(0)], aggregation={"policy": "p", "counts": counts()}),
        advice(reconciliation={"rule_conflict": False, "applicability_established": True}),
        criterion_advice(reconciliation={"rule_conflict": True, "applicability_established": True}),
        criterion_advice(
            status="unavailable",
            label=None,
            evidence_ids=[],
            citations=[],
            error_code="verified_rule_conflict",
        ),
        criterion_advice(
            status="unavailable",
            label=None,
            evidence_ids=[],
            citations=[],
            error_code="applicability_not_established",
        ),
        criterion_advice(task_type="relation"),
    ],
)
def test_dto_02_label_domain_and_reconciliation_are_checked(value) -> None:
    with pytest.raises(ValidationError):
        feedback_with(value)


@pytest.mark.parametrize(
    "error_code",
    [
        "verified_rule_conflict",
        "applicability_not_established",
        "criterion_not_supported_by_model",
        "criterion_rubric_version_mismatch",
    ],
)
def test_dto_02_criterion_outcomes_without_labels_are_explicit(error_code: str) -> None:
    reconciliation = {
        "verified_rule_conflict": {"rule_conflict": True, "applicability_established": True},
        "applicability_not_established": {
            "rule_conflict": False,
            "applicability_established": False,
        },
    }.get(error_code)
    value = criterion_advice(
        status="unavailable",
        label=None,
        evidence_ids=[],
        citations=[],
        error_code=error_code,
        reconciliation=reconciliation,
    )
    stored = feedback_with(value).model_dump(mode="json")["model_advice"][0]
    assert stored["error_code"] == error_code and stored["label"] is None
    assert stored["affects_score"] is False


def test_dto_02_sentence_units_follow_the_relation_domain_and_their_counts() -> None:
    rows = [unit(0), unit(1, "CONTRADICTED"), unit(2, "INSUFFICIENT"), unit(3, None)]
    value = advice(
        label="CONTRADICTED",
        units=rows,
        aggregation={
            "policy": "r2-support-units-v1",
            "counts": counts(
                supported=1, contradicted=1, insufficient=1, abstained=1, skipped_short=2
            ),
        },
    )
    stored = feedback_with(value).model_dump(mode="json")["model_advice"][0]
    assert [row["label"] for row in stored["units"]] == [
        "SUPPORTED",
        "CONTRADICTED",
        "INSUFFICIENT",
        None,
    ]
    assert stored["units"][0]["subject"]["quote"] == "Defer until the owner is verified."
    assert stored["aggregation"]["counts"]["skipped_short"] == 2
    every = advice(
        status="unavailable",
        label=None,
        evidence_ids=[],
        citations=[],
        error_code="all_units_abstained",
        units=[unit(0, None), unit(1, None)],
        aggregation={"policy": "r2-support-units-v1", "counts": counts(abstained=2)},
    )
    assert feedback_with(every).model_advice[0].error_code == "all_units_abstained"
    for broken in (
        dict(value, units=rows[:3]),
        dict(value, units=[unit(0, "MET")] + rows[1:]),
        dict(value, units=[unit(0, None, status="completed")] + rows[1:]),
        dict(value, units=[unit(0, subject=dict(unit(0)["subject"], span_start=None))]),
        dict(value, aggregation=None),
        dict(value, units=None),
        dict(value, units=[unit(0), unit(0, "CONTRADICTED")] + rows[2:]),
    ):
        with pytest.raises(ValidationError):
            feedback_with(broken)


# DTO-03 ------------------------------------------------------------------------------


def test_dto_03_synthetic_advice_may_show_labels_only_for_synthetic_registrations() -> None:
    shown = advice(
        status="synthetic_mechanism_only",
        error_code="synthetic_mechanism_only",
        registration=synthetic_identity(),
        units=[unit(0), unit(1, "INSUFFICIENT")],
        aggregation={
            "policy": "r2-support-units-v1",
            "counts": counts(supported=1, insufficient=1),
        },
        label="INSUFFICIENT",
    )
    stored = feedback_with(shown).model_dump(mode="json")["model_advice"][0]
    assert stored["status"] == "synthetic_mechanism_only"
    assert stored["label"] == "INSUFFICIENT" and stored["evidence_ids"] == ["source-a"]
    assert stored["registration"]["scope"] == "synthetic_fixture"
    assert stored["affects_score"] is False
    criterion = criterion_advice(
        status="synthetic_mechanism_only",
        error_code="synthetic_mechanism_only",
        registration=criterion_identity(scope="synthetic_fixture"),
    )
    assert feedback_with(criterion).model_advice[0].label == "MET"
    for broken in (
        dict(shown, registration=dict(LEGACY_IDENTITY)),
        dict(shown, registration=None),
        dict(shown, status="completed", error_code=None),
        dict(shown, status="unavailable", error_code="model_unavailable"),
        dict(shown, status="failed", error_code="model_load_failed"),
        advice(status="unavailable", error_code="model_unavailable"),
    ):
        with pytest.raises(ValidationError):
            feedback_with(broken)


def test_dto_03_unit_citations_stay_in_session_and_time() -> None:
    rows = [unit(0, citations=[source(session_id="foreign")])]
    value = advice(
        units=rows,
        aggregation={"policy": "r2-support-units-v1", "counts": counts(supported=1)},
    )
    with pytest.raises(ValidationError, match="advice citation"):
        feedback_with(value)
    later = dict(unit(0)["subject"], observed_at_seq=10_000)
    with pytest.raises(ValidationError, match="advice citation"):
        feedback_with(dict(value, units=[unit(0, subject=later)]))


def test_dto_03_limited_readers_never_receive_sentence_results() -> None:
    shown = advice(
        status="synthetic_mechanism_only",
        error_code="synthetic_mechanism_only",
        registration=synthetic_identity(),
        units=[unit(0)],
        aggregation={"policy": "r2-support-units-v1", "counts": counts(supported=1)},
    )
    report = feedback_with(shown).model_dump(mode="json")
    report["read_boundaries"] = [
        C.FeedbackReadBoundary(
            path="/model_advice/0",
            content_hash=C.digest(report["model_advice"][0]),
            dependencies=(
                C.ObjectRef(session_id="example", kind="document", object_id="source-a", version=1),
            ),
        ).model_dump(mode="json")
    ]
    before = deepcopy(report)
    visible, partial = project_feedback_content(report, lambda ref: ref["object_id"] != "source-a")
    assert report == before and partial
    degraded = visible["model_advice"][0]
    assert degraded["status"] == "unavailable" and degraded["label"] is None
    assert "units" not in degraded and "aggregation" not in degraded
    assert C.FeedbackV2.model_validate(visible | {"read_projection": "partial"})
