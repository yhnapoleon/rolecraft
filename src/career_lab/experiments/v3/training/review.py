"""Independent recomputation for already-trained registered artifacts; no fit or selection."""
import json
from career_lab.contracts.v2.core import ProtocolError, digest
from career_lab.models.v3.registry import load_registration, public_registration
from career_lab.models.v3.core import Prediction, LABELS
from career_lab.models.v3.bundle import json_bytes
from .metrics import grade, summarize


def review_registered(registry_root, registration_ref, examples, *, producer_predictions=None):
    rows = list(examples)
    if not rows:
        raise ProtocolError("review_records_required")
    if len({row.record_id for row in rows}) != len(rows):
        raise ProtocolError("review_duplicate_record")
    # Held-out campaigns remain separately authorized by the existing freeze path.
    if any(row.split not in {"train", "dev", "regression"} for row in rows):
        raise ProtocolError("review_held_out_campaign_required")
    model, entry = load_registration(registry_root, registration_ref)
    loaded_again, second_entry = load_registration(registry_root, registration_ref)
    if entry != second_entry:
        raise ProtocolError("review_registration_changed")
    grades, predictions, mismatches, failures, reload_skipped = [], [], [], [], []
    expected = None
    if producer_predictions is not None:
        expected = {r["record_id"]: r["prediction"] for r in producer_predictions}
        if len(expected) != len(producer_predictions) or set(expected) != {r.record_id for r in rows}:
            raise ProtocolError("review_producer_record_set_mismatch")
    for row in rows:
        row.validate()
        if row.item.task_type != entry["task_type"]:
            raise ProtocolError("review_task_mismatch")
        failure_kind = None
        try:
            first = model.predict(row.item).validate(row.item)
            if first.model_revision != entry["model_revision"]:
                raise ProtocolError("review_model_revision_mismatch")
        except (ProtocolError, OSError, TimeoutError) as error:
            code = getattr(error, "code", type(error).__name__)
            failure_kind = "protocol" if isinstance(error, ProtocolError) else "infrastructure"
            first = Prediction(row.item.task_type, row.annotation.input_hash, entry["model_revision"],
                               "failed", None, None, reason_code=code)
            failures.append({"record_id": row.record_id, "kind": failure_kind, "code": code})
            reload_skipped.append(row.record_id)
        if failure_kind is None:
            second = loaded_again.predict(row.item).validate(row.item)
            if second.model_revision != entry["model_revision"]:
                raise ProtocolError("review_model_revision_mismatch")
            if first.as_dict() != second.as_dict():
                raise ProtocolError("model_reload_prediction_mismatch")
        actual = json.loads(json_bytes(first.as_dict()))
        if expected is not None:
            produced = expected[row.record_id]
            if (produced.get("labels") != list(LABELS[row.item.task_type])
                    or produced.get("mode") != "advisory" or produced.get("affects_score") is not False):
                raise ProtocolError("review_producer_label_or_mode_mismatch")
            raw = {k: produced.get(k) for k in Prediction.__dataclass_fields__}
            Prediction(**raw).validate(row.item)
            if produced != actual:
                mismatches.append(row.record_id)
        graded = grade(row, first)
        if failure_kind is not None:
            graded["failure_kind"] = failure_kind
        grades.append(graded)
        predictions.append({"record_id": row.record_id, "prediction": actual})
    task = entry["task_type"]
    languages = {}
    for language in ("zh", "en"):
        subset = [r for r in grades if r["language"] == language]
        languages[language] = {"status": "recomputed" if subset else "blocked_missing_language",
                               "metrics": summarize(subset, task)}
    return {"protocol": "w08-return-review-v1", "registration": public_registration(entry),
            "input_set_digest": digest(sorted((r.record_id, r.annotation.input_hash) for r in rows)),
            "reload_predictions_identical": not reload_skipped,
            "reload_skipped_failed_record_ids": reload_skipped, "failures": failures,
            "metrics": summarize(grades, task),
            "languages": languages, "other_languages": sorted({r.language for r in rows} - {"zh", "en"}),
            "producer_comparison": {"status": "not_supplied" if expected is None else "mismatch" if mismatches else "matched",
                                     "mismatched_record_ids": mismatches},
            "predictions": predictions, "graded_records": grades,
            "scope": entry["scope"], "quality_validated": False,
            "mode": "advisory", "affects_score": False,
            "training_performed": False, "held_out_test_opened": False,
            "limits": ["Metrics are recomputed observations, not automatic adoption or model-quality acceptance",
                       "Synthetic fixtures prove mechanisms only; real bilingual product calls are separate"]}
