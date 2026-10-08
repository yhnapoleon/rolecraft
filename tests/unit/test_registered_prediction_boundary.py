"""Product projections reject temporally invalid model evidence; no fitting or provider."""

from test_w08_models import examples

from career_lab.contracts.v2 import EvidencePackageV2, RelationInput, digest
from career_lab.models.v3.advisory import to_public_prediction
from career_lab.models.v3.core import LABELS, Prediction


def test_model_04_product_prediction_rejects_expired_selected_evidence() -> None:
    original = examples("dev")[0].item
    body = original.evidence.model_dump(mode="json", exclude={"input_hash"})
    body["candidate_evidence"][0]["ref"]["valid_until_seq"] = body["as_of"]["business_seq"]
    item = RelationInput(evidence=EvidencePackageV2(**body, input_hash=digest(body)))
    outcome = {
        "status": "completed",
        "input_hash": digest(item),
        "registration": {
            "model_revision": "test-transport",
            "labels": list(LABELS["relation"]),
            "scope": "external_candidate",
        },
        "prediction": Prediction(
            "relation", digest(item), "test-transport", "ok", "SUPPORTED", (1.0, 0.0, 0.0), ("e1",)
        ).as_dict(),
    }
    projected = to_public_prediction(outcome, item)
    assert projected.status == "invalid"
    assert projected.error_code == "invalid_evidence_time"
    assert projected.probabilities is None and projected.evidence_ids == ()
    assert projected.model_revision == "test-transport" and projected.input_hash == digest(item)
    outcome["prediction"]["evidence_ids"] = ["e2"]
    valid = to_public_prediction(outcome, item)
    assert valid.status == "success" and valid.evidence_ids == ("e2",)


def test_model_04_missing_validity_context_never_becomes_public_success() -> None:
    original = examples("dev")[0].item
    body = original.evidence.model_dump(mode="json", exclude={"input_hash"})
    body["rule_context"] = {}
    item = RelationInput(evidence=EvidencePackageV2(**body, input_hash=digest(body)))
    outcome = {
        "status": "completed",
        "input_hash": digest(item),
        "registration": {
            "model_revision": "test-transport",
            "labels": list(LABELS["relation"]),
            "scope": "external_candidate",
        },
        "prediction": Prediction(
            "relation", digest(item), "test-transport", "ok", "SUPPORTED", (1.0, 0.0, 0.0), ("e1",)
        ).as_dict(),
    }
    projected = to_public_prediction(outcome, item)
    assert projected.status == "invalid"
    assert projected.error_code == "temporal_scope_undetermined"
    assert projected.probabilities is None and projected.evidence_ids == ()


def test_model_04_malformed_validity_ids_become_stable_invalid_result() -> None:
    original = examples("dev")[0].item
    body = original.evidence.model_dump(mode="json", exclude={"input_hash"})
    body["rule_context"]["evidence_time_context"]["validity_known_ids"] = [{}]
    item = RelationInput(evidence=EvidencePackageV2(**body, input_hash=digest(body)))
    outcome = {
        "status": "completed",
        "input_hash": digest(item),
        "registration": {
            "model_revision": "test-transport",
            "labels": list(LABELS["relation"]),
            "scope": "external_candidate",
        },
        "prediction": Prediction(
            "relation", digest(item), "test-transport", "ok", "SUPPORTED", (1.0, 0.0, 0.0), ("e1",)
        ).as_dict(),
    }
    projected = to_public_prediction(outcome, item)
    assert projected.status == "invalid"
    assert projected.error_code == "evidence_validity_undetermined"
    assert projected.probabilities is None and projected.evidence_ids == ()
