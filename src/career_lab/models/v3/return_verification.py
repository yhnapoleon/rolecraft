"""Independent return metrics. A format example never proves training or product quality."""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from career_lab.contracts import v2 as C
from career_lab.experiments.v3.training.metrics import grade, summarize
from career_lab.experiments.v3.training.review import review_registered
from career_lab.experiments.v3.training.selection import SelectionPolicy

from .bundle import sha
from .encoder_artifact import (
    file_map,
    validate_encoder_return_identity,
    validate_return_identity,
    verify_file,
)
from .ensemble import select_alpha
from .held_out import HeldOutOpening, HeldOutRequest, open_held_out_test
from .registration import RegistrationSummary
from .registry import describe_registration, load_registration
from .return_data import ReturnDataset, json_lines, load_return_dataset, strict_json, unique_records
from .return_predictions import (
    ReturnedPrediction,
    compare_prediction,
    comparison_tolerance,
    parse_returned,
)


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
    ref = C.FileRef(path=registration_path, sha256=registration_hash)
    try:
        review = review_registered(
            registry_root, ref, dataset.examples, held_out_opening=held_out_opening
        )
    except C.ProtocolError as error:
        if error.code != RUNTIME_UNAVAILABLE or held_out_opening is not None:
            raise
        return {
            "status": "blocked_encoder_runtime_unavailable",
            "registration": describe_registration(registry_root, ref).identity(),
            "tolerance": None,
            "mismatched_record_ids": [],
            "comparison": "not_run_optional_encoder_runtime_missing",
        }
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


TRAINED_DECLARATION = {
    "training_partitions": ["train"],
    "selection_partition": "dev",
    "test_used_for_selection": False,
}
# The encoder return's untrained-heads stage declares that nothing was trained or selected
# (docs/data/return-v3/encoder-return.md); only a synthetic registration may use it, and the
# encoder protocol's own check decides whether the declaration is exact.
UNTRAINED_STAGE = "pretrained_untrained_heads"
# Loading an encoder needs the optional extra; without it a dev review reports the reload
# as blocked (a test opening checks loading before its record instead).
RUNTIME_UNAVAILABLE = "pretrained_encoder_dependencies_unavailable"


def untrained_heads(registration: RegistrationSummary | None) -> bool:
    return (
        registration is not None
        and registration.scope == "synthetic_fixture"
        and registration.weights_stage == UNTRAINED_STAGE
    )


def inspect_return_checkpoint(
    path: Path | None,
    dataset: ReturnDataset,
    model_revision: str,
    predictions_path: Path,
    *,
    registration: RegistrationSummary | None = None,
) -> dict[str, Any]:
    """Declared files only. ``predictions_file`` names the dev predictions, so a test
    review does not compare it with the test predictions it was given.

    The selection declaration must be the trained one, except that a synthetic registration
    of untrained heads must carry exactly the encoder protocol's untrained-heads declaration
    (``validate_encoder_return_identity``) instead."""
    if path is None:
        return {
            "status": "not_supplied",
            "candidate_eligible": False,
            "missing": ["responsible_party_checkpoint"],
        }
    manifest = strict_json(path.read_bytes())
    if not isinstance(manifest, dict):
        raise C.ProtocolError("model_return_protocol_invalid")
    untrained = untrained_heads(registration)
    if untrained:
        if manifest.get("weights_stage") != UNTRAINED_STAGE:
            raise C.ProtocolError("return_checkpoint_identity_mismatch")
        validate_encoder_return_identity(manifest, scope=registration.scope)
    elif any(
        key in manifest and manifest[key] != value for key, value in TRAINED_DECLARATION.items()
    ):
        raise C.ProtocolError("model_return_selection_contaminated", status=403)
    else:
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
    if manifest["predictions_file"] in files and dataset.split == "dev":
        if sha(predictions_path.read_bytes()) != files[manifest["predictions_file"]]:
            raise C.ProtocolError("return_checkpoint_predictions_mismatch")
    if untrained:
        return {
            "status": "untrained_heads_declared",
            "candidate_eligible": False,
            "weights_stage": UNTRAINED_STAGE,
            "missing": ["supervised_training", *missing[1:]],
            "producer_commands_executed": False,
        }
    return {
        "status": "declared_files_checked",
        "candidate_eligible": False,
        "missing": missing,
        "producer_commands_executed": False,
    }


SELECTION_PROTOCOL = "rolecraft-fusion-selection-v1"
ALPHA_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
POINT_FRACTIONS = ("macro_f1", "mean_evidence_f1", "joint_correctness")
POINT_COUNTS = ("count", "evidence_denominator", "joint_denominator")


class FusionSelectionRecord(BaseModel):
    """``rolecraft-fusion-selection-v1`` (docs/data/return-v3/fusion-selection.md)."""

    model_config = ConfigDict(extra="forbid")
    protocol: str
    task_type: str
    dataset_id: str
    dataset_manifest_sha256: str
    selection_split: str
    test_used_for_selection: bool
    components: dict[str, dict[str, str]]
    alpha_grid: list[float]
    evidence_threshold_grid: list[float]
    selected: dict[str, float]
    points: list[dict[str, Any]]
    fusion_gain_observed: bool
    dev_input_hashes: list[str]


def point_key(alpha: Any, threshold: Any) -> tuple[float, float]:
    return float(alpha), float(threshold)


def differing_metrics(declared: dict[str, Any], recomputed: dict[str, Any]) -> list[str]:
    fields = []
    for key in (*POINT_FRACTIONS, *POINT_COUNTS):
        mine, theirs = recomputed[key], declared.get(key)
        if key in POINT_COUNTS:
            same = type(theirs) is int and theirs == mine
        elif mine is None or theirs is None:
            same = mine is None and theirs is None
        else:
            same = isinstance(theirs, (int, float)) and abs(mine - theirs) <= 1e-9
        if not same:
            fields.append(key)
    return fields


def registered_components(registry_root: Path, ref: C.FileRef, model: Any) -> dict[str, Any]:
    """Each side's revision and kind, as the registration publishes them."""
    summary = describe_registration(registry_root, ref)
    if summary.components:
        return {
            c["role"]: {"model_revision": c["model_revision"], "artifact_kind": c["kind"]}
            for c in summary.components
        }
    return {
        side: {
            "model_revision": getattr(model, side).revision,
            "artifact_kind": getattr(model, side).kind,
        }
        for side in ("left", "right")
    }


def recompute_fusion_selection(
    dataset: ReturnDataset, registry_root: Path, ref: C.FileRef, selection_path: Path
) -> dict[str, Any]:
    """Recompute the producer's dev grid on the registered components and compare.

    Uses the product's own fusion and dev selection rule (``ensemble.select_alpha``,
    ``joint-first-dev-v1``). Never reads test data and never selects anything new.
    """
    raw = selection_path.read_bytes()
    try:
        record = FusionSelectionRecord.model_validate(strict_json(raw))
    except ValidationError as error:
        raise C.ProtocolError("fusion_selection_protocol_invalid") from error
    if record.protocol != SELECTION_PROTOCOL or record.task_type != "relation":
        raise C.ProtocolError("fusion_selection_protocol_invalid")
    model, entry = load_registration(registry_root, ref)
    if not (hasattr(model, "left") and hasattr(model, "right")):
        raise C.ProtocolError("fusion_selection_requires_fusion_registration")
    reasons = []
    stored = entry.get("selection")
    if isinstance(stored, dict) and stored.get("sha256") != sha(raw):
        reasons.append("fusion_selection_not_registered")
    if record.selection_split != "dev" or record.test_used_for_selection is not False:
        reasons.append("fusion_selection_contaminated")
    if (record.dataset_id, record.dataset_manifest_sha256) != (
        dataset.dataset_id,
        dataset.manifest_hash,
    ):
        reasons.append("fusion_selection_dataset_mismatch")
    if sorted(record.dev_input_hashes) != sorted(
        row.annotation.input_hash for row in dataset.examples
    ):
        reasons.append("fusion_selection_dev_inputs_mismatch")
    if record.components != registered_components(registry_root, ref, model):
        reasons.append("fusion_selection_component_mismatch")
    thresholds = tuple(record.evidence_threshold_grid)
    declared = {point_key(p.get("alpha"), p.get("evidence_threshold")): p for p in record.points}
    grid = {(a, t) for a in ALPHA_GRID for t in thresholds}
    if (
        tuple(record.alpha_grid) != ALPHA_GRID
        or not thresholds
        or len(set(thresholds)) != len(thresholds)
        or any(not 0 <= t <= 1 for t in thresholds)
        or len(declared) != len(record.points)
        or set(declared) != grid
    ):
        reasons.append("fusion_selection_grid_invalid")
        return {
            "status": "rejected",
            "protocol": SELECTION_PROTOCOL,
            "reasons": reasons,
            "mismatched_points": [],
            "recomputed": None,
        }
    policy = SelectionPolicy(evidence_thresholds=thresholds, alpha_grid=ALPHA_GRID)
    result = select_alpha(dataset.examples, model.left, model.right, policy)
    recomputed = {point_key(p["alpha"], p["threshold"]): p["metrics"] for p in result["grid"]}
    mismatched = []
    for key in sorted(recomputed):
        fields = differing_metrics(declared[key].get("metrics") or {}, recomputed[key])
        if fields:
            mismatched.append({"alpha": key[0], "evidence_threshold": key[1], "fields": fields})
    if mismatched:
        reasons.append("fusion_selection_point_mismatch")
    selected = point_key(record.selected.get("alpha"), record.selected.get("evidence_threshold"))
    winner = (
        point_key(result["alpha"], result["evidence_threshold"])
        if result["alpha"] is not None
        else None
    )
    if selected != winner:
        reasons.append("fusion_selection_selected_mismatch")
    endpoint = selected[0] in (0.0, 1.0)
    best_endpoint = max(
        (recomputed[k]["joint_correctness"] or 0 for k in recomputed if k[0] in (0.0, 1.0)),
        default=0,
    )
    actual_gain = (
        selected in recomputed
        and not endpoint
        and (recomputed[selected]["joint_correctness"] or 0) > best_endpoint
    )
    if record.fusion_gain_observed and endpoint:
        reasons.append("fusion_gain_claimed_at_endpoint")
    elif record.fusion_gain_observed != actual_gain:
        reasons.append("fusion_gain_observed_mismatch")
    if point_key(model.alpha, model.threshold) != selected:
        reasons.append("fusion_selection_registration_mismatch")
    return {
        "status": "rejected" if reasons else "matched",
        "protocol": SELECTION_PROTOCOL,
        "policy": policy.version,
        "selected": {"alpha": selected[0], "evidence_threshold": selected[1]},
        "fusion_gain_observed": record.fusion_gain_observed,
        "recomputed": {
            "selected": {"alpha": winner[0], "evidence_threshold": winner[1]} if winner else None,
            "selection_status": result["selection_status"],
            "fusion_gain_observed": result["fusion_gain_observed"],
            "points": len(recomputed),
        },
        "mismatched_points": mismatched,
        "reasons": reasons,
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
    held_out: HeldOutRequest | None = None,
    fusion_selection: Path | None = None,
) -> dict[str, Any]:
    """Review returned predictions for ``dev``, or for ``test`` behind a recorded opening."""
    if fusion_selection is not None:
        if partition != "dev":
            raise C.ProtocolError("fusion_selection_dev_only", status=403)
        if registry_root is None or registration_path is None or registration_hash is None:
            raise C.ProtocolError("fusion_selection_requires_registration")
    # Read the producer's file before any opening, so a broken file cannot spend it.
    returned = unique_records(json_lines(predictions_path.read_bytes()))
    opening = None
    if partition == "test":
        registration = (
            C.FileRef(path=registration_path, sha256=registration_hash)
            if registration_path is not None and registration_hash is not None
            else None
        )
        opening = open_held_out_test(
            held_out or HeldOutRequest(),
            dataset_root=dataset_root,
            dataset_hash=dataset_hash,
            registry_root=registry_root,
            registration=registration,
            checkpoint_manifest=checkpoint_manifest,
            returned=returned,
        )
    elif held_out is not None:
        raise C.ProtocolError("held_out_arguments_require_test_partition")
    try:
        return review_partition(
            dataset_root,
            dataset_hash,
            predictions_path,
            returned,
            partition=partition,
            checkpoint_manifest=checkpoint_manifest,
            registry_root=registry_root,
            registration_path=registration_path,
            registration_hash=registration_hash,
            opening=opening,
            fusion_selection=fusion_selection,
        )
    except (ValueError, KeyError, TypeError, OSError) as error:
        if opening is not None:
            # The opening is spent; say which one, whatever went wrong after it.
            error.opened = opening.record
        raise


def review_partition(
    dataset_root: Path,
    dataset_hash: str,
    predictions_path: Path,
    returned: dict[str, dict[str, Any]],
    *,
    partition: str,
    checkpoint_manifest: Path | None,
    registry_root: Path | None,
    registration_path: str | None,
    registration_hash: str | None,
    opening: HeldOutOpening | None,
    fusion_selection: Path | None,
) -> dict[str, Any]:
    dataset = load_return_dataset(dataset_root, dataset_hash, partition, opening=opening)
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
        summary = (
            describe_registration(
                registry_root, C.FileRef(path=registration_path, sha256=registration_hash)
            )
            if registry_root is not None and registration_path and registration_hash
            else None
        )
        checkpoint = inspect_return_checkpoint(
            checkpoint_manifest, dataset, revision, predictions_path, registration=summary
        )
        reload = reload_return(
            dataset,
            predictions,
            registry_root,
            registration_path,
            registration_hash,
            held_out_opening=opening,
        )
    selection = (
        recompute_fusion_selection(
            dataset,
            registry_root,
            C.FileRef(path=registration_path, sha256=registration_hash),
            fusion_selection,
        )
        if fusion_selection is not None
        else None
    )
    rejected = (
        bool(format_errors)
        or reload["status"] == "producer_mismatch"
        or reload.get("reload_predictions_identical") is False
        or (selection is not None and selection["status"] == "rejected")
    )
    mechanism = reload.get("registration", {}).get("scope") == "synthetic_fixture"
    return {
        "protocol": "rolecraft-label-evidence-v2",
        "status": "rejected" if rejected else "partial",
        "task_type": "relation",
        "layout": dataset.layout,
        "split": dataset.split,
        "opened": opening.record if opening is not None else None,
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
        "scope": "synthetic_fixture" if dataset.synthetic or mechanism else "external_candidate",
        "quality_validated": False,
        "mode": "advisory",
        "affects_score": False,
        "held_out_test_opened": opening is not None,
        "tolerance": reload.get("tolerance"),
        "fusion_selection": selection,
    }
