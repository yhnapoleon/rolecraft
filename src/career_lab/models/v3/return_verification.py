"""Independent return metrics. A format example never proves training or product quality."""

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from career_lab.contracts import v2 as C
from career_lab.experiments.v3.training.metrics import grade, summarize
from career_lab.experiments.v3.training.review import review_registered

from .encoder_artifact import file_map, validate_return_identity, verify_file
from .return_data import ReturnDataset, json_lines, load_return_dataset, strict_json, unique_records
from .return_predictions import ReturnedPrediction, parse_returned


# Absolute per-probability tolerance (143 §5.2): producers may run other hardware or library
# builds, so probabilities need not be bit-identical; labels and evidence sets must be.
ENCODER_KINDS = {"huggingface_encoder", "numpy_attention"}
TOLERANCE = {"linear": 1e-6, "encoder": 1e-4}


def comparison_tolerance(kinds) -> dict[str, Any]:
    """Unknown kinds use the strict tier: a false rejection is safer than a false match."""
    basis = "encoder" if set(kinds) & ENCODER_KINDS else "linear"
    return {"absolute": TOLERANCE[basis], "basis": basis, "model_kinds": sorted(kinds)}


def compare_prediction(actual: dict[str, Any], expected: ReturnedPrediction, tolerance: float):
    """Fields that differ, and the largest absolute probability difference seen."""
    fields = [
        key
        for key in ("input_hash", "model_revision", "task_type", "status", "label")
        if actual[key] != getattr(expected, key)
    ]
    if set(actual["evidence_ids"]) != set(expected.evidence_ids):
        fields.append("evidence_ids")
    left, right = actual["probabilities"], expected.probabilities
    deviation = 0.0
    if (left is None) != (right is None) or (left is not None and len(left) != len(right)):
        fields.append("probabilities")
    elif left is not None:
        deviation = max(abs(a - b) for a, b in zip(left, right, strict=True))
        if deviation > tolerance:
            fields.append("probabilities")
    return fields, deviation


def reload_return(
    dataset: ReturnDataset,
    returned: dict[str, ReturnedPrediction],
    registry_root: Path | None,
    registration_path: str | None,
    registration_hash: str | None,
    *,
    held_out_opening: Any = None,
) -> dict[str, Any]:
    if registry_root is None and registration_path is None and registration_hash is None:
        return {"status": "blocked_missing_registration"}
    if registry_root is None or registration_path is None or registration_hash is None:
        raise C.ProtocolError("return_registration_identity_required")
    review = review_registered(
        registry_root,
        C.FileRef(path=registration_path, sha256=registration_hash),
        dataset.examples,
        held_out_opening=held_out_opening,
    )
    tolerance = comparison_tolerance(review["model_kinds"])
    mismatches, largest = [], 0.0
    for entry in review["predictions"]:
        fields, deviation = compare_prediction(
            entry["prediction"], returned[entry["record_id"]], tolerance["absolute"]
        )
        largest = max(largest, deviation)
        if fields:
            mismatches.append({"record_id": entry["record_id"], "fields": fields})
    return {
        "status": "producer_mismatch" if mismatches else "matched",
        "reload_predictions_identical": review["reload_predictions_identical"],
        "reload_skipped_failed_record_ids": review["reload_skipped_failed_record_ids"],
        "mismatched_record_ids": [row["record_id"] for row in mismatches],
        "mismatches": mismatches,
        "max_probability_deviation": largest,
        "tolerance": tolerance,
        "registration": review["registration"],
        "comparison": "probabilities_within_absolute_tolerance_labels_and_evidence_sets_exact",
    }


def inspect_return_checkpoint(
    path: Path | None,
    dataset: ReturnDataset,
    model_revision: str,
    predictions_path: Path,
) -> dict[str, Any]:
    if path is None:
        return {
            "status": "not_supplied",
            "candidate_eligible": False,
            "missing": ["responsible_party_checkpoint"],
        }
    manifest = strict_json(path.read_bytes())
    if not isinstance(manifest, dict):
        raise C.ProtocolError("model_return_protocol_invalid")
    policy = {
        "training_partitions": ["train"],
        "selection_partition": "dev",
        "test_used_for_selection": False,
    }
    if any(key in manifest and manifest[key] != value for key, value in policy.items()):
        raise C.ProtocolError("model_return_selection_contaminated", status=403)
    try:
        validate_return_identity(manifest)
    except C.ProtocolError as error:
        if error.code not in {"model_return_incomplete", "model_return_identity_incomplete"}:
            raise
        return {"status": "incomplete", "candidate_eligible": False, "missing": [error.code]}
    if (
        manifest["dataset_id"] != dataset.dataset_id
        or manifest["dataset_manifest_sha256"] != dataset.manifest_hash
        or manifest["model_revision"] != model_revision
    ):
        raise C.ProtocolError("return_checkpoint_identity_mismatch")
    if not manifest.get("checkpoint_files"):
        return {
            "status": "incomplete",
            "candidate_eligible": False,
            "missing": ["checkpoint_files"],
        }
    files = file_map(manifest["checkpoint_files"])
    for name, checksum in files.items():
        verify_file(path.parent, C.FileRef(path=name, sha256=checksum))
    missing = ["supported_checkpoint_validation", "independent_training_execution_evidence"]
    for field in ("training_notes_file", "predictions_file"):
        name = manifest[field]
        if name not in files:
            missing.append(field)
    if manifest["predictions_file"] in files:
        import hashlib

        if (
            hashlib.sha256(predictions_path.read_bytes()).hexdigest()
            != files[manifest["predictions_file"]]
        ):
            raise C.ProtocolError("return_checkpoint_predictions_mismatch")
    return {
        "status": "declared_files_checked",
        "candidate_eligible": False,
        "missing": missing,
        "producer_commands_executed": False,
    }


def verify_return(
    dataset_root: Path,
    dataset_hash: str,
    predictions_path: Path,
    *,
    partition: str = "dev",
    checkpoint_manifest: Path | None = None,
    registry_root: Path | None = None,
    registration_path: str | None = None,
    registration_hash: str | None = None,
) -> dict[str, Any]:
    dataset = load_return_dataset(dataset_root, dataset_hash, partition)
    returned = unique_records(json_lines(predictions_path.read_bytes()))
    if set(returned) != {row.record_id for row in dataset.examples}:
        raise C.ProtocolError("return_prediction_record_set_mismatch")
    grades = []
    revisions = set()
    format_errors = []
    predictions: dict[str, ReturnedPrediction] = {}
    for row in dataset.examples:
        try:
            value = parse_returned(returned[row.record_id])
            revisions.add(value.model_revision)
            prediction = value.checked_prediction(row)
            predictions[row.record_id] = value
            grades.append(grade(row, prediction))
        except (ValidationError, C.ProtocolError) as error:
            code = getattr(error, "code", "return_prediction_schema_invalid")
            format_errors.append({"record_id": row.record_id, "error_code": code})
            failed = grade(row, None)
            failed["error_code"] = code
            grades.append(failed)
    if len(revisions) > 1:
        raise C.ProtocolError("return_prediction_revision_mismatch")
    languages = {}
    for language in ("zh", "en"):
        subset = [row for row in grades if row["language"] == language]
        metrics = summarize(subset, "relation")
        languages[language] = {
            "status": "recomputed" if subset else "blocked_missing_language",
            "metrics": metrics,
            "counts": {key: metrics[key] for key in ("format_failures", "abstentions", "coverage")},
        }
    revision = next(iter(revisions), None)
    if format_errors:
        checkpoint = {"status": "blocked_invalid_return", "candidate_eligible": False}
        reload = {"status": "blocked_invalid_return"}
    else:
        checkpoint = inspect_return_checkpoint(
            checkpoint_manifest, dataset, revision, predictions_path
        )
        reload = reload_return(
            dataset, predictions, registry_root, registration_path, registration_hash
        )
    rejected = (
        bool(format_errors)
        or reload["status"] == "producer_mismatch"
        or reload.get("reload_predictions_identical") is False
    )
    mechanism = reload.get("registration", {}).get("scope") == "synthetic_fixture"
    return {
        "protocol": "rolecraft-label-evidence-v2",
        "status": "rejected" if rejected else "partial",
        "task_type": "relation",
        # The product passes the given candidate evidence; retrieval is not part of this review.
        "evaluation_setting": "given_evidence_only",
        "retrieval_setting": "not_evaluated",
        "dataset_id": dataset.dataset_id,
        "dataset_manifest_sha256": dataset.manifest_hash,
        "model_revision": revision,
        "format_errors": format_errors,
        "languages": languages,
        "graded_records": grades,
        "checkpoint": checkpoint,
        "reload": reload,
        "training": {
            "status": "mechanism_only" if mechanism else "not_verified",
            "performed_by_verifier": False,
        },
        "scope": "synthetic_fixture" if dataset.fixture else "external_candidate",
        "quality_validated": False,
        "mode": "advisory",
        "affects_score": False,
        "held_out_test_opened": False,
        "tolerance": reload.get("tolerance"),
    }
