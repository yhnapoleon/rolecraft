"""Independent return metrics. A format example never proves training or product quality."""

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from career_lab.contracts import v2 as C
from career_lab.experiments.v3.training.metrics import grade, summarize
from career_lab.experiments.v3.training.review import review_registered

from .encoder_artifact import file_map, validate_return_identity, verify_file
from .return_data import ReturnDataset, json_lines, load_return_dataset, strict_json, unique_records
from .return_predictions import ReturnedPrediction


def reload_return(
    dataset: ReturnDataset,
    returned: dict[str, ReturnedPrediction],
    registry_root: Path | None,
    registration_path: str | None,
    registration_hash: str | None,
) -> dict[str, Any]:
    if registry_root is None and registration_path is None and registration_hash is None:
        return {"status": "blocked_missing_registration"}
    if registry_root is None or registration_path is None or registration_hash is None:
        raise C.ProtocolError("return_registration_identity_required")
    review = review_registered(
        registry_root,
        C.FileRef(path=registration_path, sha256=registration_hash),
        dataset.examples,
    )
    mismatches = []
    for entry in review["predictions"]:
        actual = entry["prediction"]
        expected = returned[entry["record_id"]]
        same = all(
            actual[key] == getattr(expected, key)
            for key in (
                "input_hash",
                "model_revision",
                "task_type",
                "status",
                "label",
                "probabilities",
            )
        ) and set(actual["evidence_ids"]) == set(expected.evidence_ids)
        if not same:
            mismatches.append(entry["record_id"])
    return {
        "status": "producer_mismatch" if mismatches else "matched",
        "reload_predictions_identical": review["reload_predictions_identical"],
        "reload_skipped_failed_record_ids": review["reload_skipped_failed_record_ids"],
        "mismatched_record_ids": mismatches,
        "registration": review["registration"],
        "comparison": "exact_probabilities_labels_and_evidence_sets",
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
            value = ReturnedPrediction.model_validate(returned[row.record_id])
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
        languages[language] = {
            "status": "recomputed" if subset else "blocked_missing_language",
            "metrics": summarize(subset, "relation"),
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
    }
