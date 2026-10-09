"""One explicit invocation per request ID; recovery only reads durable outcomes."""

from pathlib import Path
import json
import os
import time

from career_lab.contracts.v2.core import FileRef, ProtocolError, digest
from .bundle import json_bytes
from .core import checked_input, Prediction
from .registry import load_registration, public_registration
from .temporal import legal_evidence_ids


def _atomic(path, value):
    temporary = path.with_name(path.name + ".writing")
    with temporary.open("xb") as stream:
        stream.write(json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class RegisteredAdvisory:
    """Server-owned adapter; authorization and real UI request IDs remain the host's job.

    No network retries, training or automatic retry of interrupted pending calls.
    Journal stores hashes and public predictions, never model inputs or gold.
    """

    def __init__(self, registry_root, registration_ref, journal_root, *, allow_synthetic=False):
        self.registry_root = Path(registry_root)
        self.ref = FileRef.model_validate(registration_ref)
        self.journal_root = Path(journal_root)
        self.allow_synthetic = allow_synthetic

    def _path(self, request_id):
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 200:
            raise ProtocolError("advisory_request_identity_required")
        return self.journal_root / digest(request_id)

    def recover(self, request_id):
        path = self._path(request_id)
        if not path.is_dir():
            raise ProtocolError("advisory_request_not_found", status=404)
        result = path / "outcome.json"
        if result.is_file():
            return json.loads(result.read_bytes())
        return {
            "request_id": request_id,
            "status": "unconfirmed",
            "mode": "advisory",
            "affects_score": False,
            "retry_allowed_only_as_explicit_new_request": True,
        }

    def predict(self, item, *, request_id, work_language, retry_of=None):
        if work_language not in {"zh", "en"}:
            raise ProtocolError("advisory_work_language_required")
        item = checked_input(item)
        binding = {
            "request_id": request_id,
            "input_hash": digest(item),
            "registration": self.ref.model_dump(mode="json"),
            "work_language": work_language,
            "retry_of": retry_of,
        }
        path = self._path(request_id)
        if path.exists():
            source = path / "request.json"
            if not source.is_file():
                return self.recover(request_id)
            if json.loads(source.read_bytes()) != binding:
                raise ProtocolError("advisory_request_id_reused", status=409)
            return self.recover(request_id)
        if retry_of is not None:
            if retry_of == request_id:
                raise ProtocolError("retry_requires_new_request_id")
            prior = self.recover(retry_of)
            if prior["status"] not in {"failed", "unconfirmed"}:
                raise ProtocolError("advisory_retry_not_available")
            prior_file = self._path(retry_of) / "request.json"
            if not prior_file.is_file():
                raise ProtocolError("retry_original_binding_unavailable")
            prior_binding = json.loads(prior_file.read_bytes())
            if any(
                prior_binding[key] != binding[key]
                for key in ("input_hash", "registration", "work_language")
            ):
                raise ProtocolError("retry_original_binding_mismatch")
        model, entry = load_registration(self.registry_root, self.ref)
        if item.task_type != entry["task_type"]:
            raise ProtocolError("registered_model_task_mismatch")
        if entry["scope"] == "synthetic_fixture" and not self.allow_synthetic:
            raise ProtocolError("synthetic_model_not_product_ready")
        self.journal_root.mkdir(parents=True, exist_ok=True)
        try:
            path.mkdir()
        except FileExistsError:
            source = path / "request.json"
            if source.is_file() and json.loads(source.read_bytes()) != binding:
                raise ProtocolError("advisory_request_id_reused", status=409)
            return self.recover(request_id)
        _atomic(path / "request.json", binding)
        started = time.perf_counter()
        base = {
            "request_id": request_id,
            "input_hash": binding["input_hash"],
            "work_language": work_language,
            "registration": public_registration(entry),
            "mode": "advisory",
            "affects_score": False,
            "quality_validated": False,
            "semantic_status": "synthetic_mechanism_only"
            if entry["scope"] == "synthetic_fixture"
            else "model_loaded_quality_unverified",
            "automatic_retries": 0,
            "retry_of": retry_of,
        }
        try:
            prediction = model.predict(item)
            prediction.validate(item)
            if prediction.model_revision != entry["model_revision"]:
                raise ProtocolError("advisory_model_revision_mismatch")
            result = base | {
                "status": "failed" if prediction.status == "failed" else "completed",
                "prediction": prediction.as_dict(),
            }
            if prediction.status == "failed":
                result.update(failure_kind="model_adapter", error_code=prediction.reason_code)
        except (ProtocolError, OSError, TimeoutError) as error:
            result = base | {
                "status": "failed",
                "prediction": None,
                "failure_kind": "protocol"
                if isinstance(error, ProtocolError)
                else "infrastructure",
                "error_code": getattr(error, "code", type(error).__name__),
            }
        except Exception as error:
            result = base | {
                "status": "failed",
                "prediction": None,
                "failure_kind": "programming",
                "error_code": type(error).__name__,
            }
            result["elapsed_seconds"] = time.perf_counter() - started
            result["public_prediction"] = to_public_prediction(result, item).model_dump(mode="json")
            _atomic(path / "outcome.json", result)
            raise
        result["elapsed_seconds"] = time.perf_counter() - started
        result["public_prediction"] = to_public_prediction(result, item).model_dump(mode="json")
        result = json.loads(json_bytes(result))
        _atomic(path / "outcome.json", result)
        return result


def to_public_prediction(outcome, item):
    """Existing shared protocol DTO projection. Fixture predictions never become product advice."""
    from career_lab.contracts.v2.research import ModelPrediction

    item = checked_input(item)
    if outcome.get("status") not in {"completed", "failed"}:
        raise ProtocolError("advisory_result_unconfirmed")
    if outcome.get("input_hash") != digest(item):
        raise ProtocolError("advisory_result_input_mismatch")
    identity = outcome["registration"]
    base = {
        "task_type": item.task_type,
        "input_hash": digest(item),
        "model_revision": identity["model_revision"],
        "labels": tuple(identity["labels"]),
    }
    if identity["scope"] == "synthetic_fixture":
        return ModelPrediction(
            **base, status="unavailable", error_code="synthetic_model_not_product_ready"
        )
    raw = outcome.get("prediction")
    if outcome["status"] == "completed" and raw is not None:
        prediction = Prediction(
            **{k: raw.get(k) for k in Prediction.__dataclass_fields__}
        ).validate(item)
        if prediction.model_revision != identity["model_revision"]:
            raise ProtocolError("advisory_model_revision_mismatch")
        if prediction.status == "ok":
            try:
                allowed = legal_evidence_ids(item)
            except ProtocolError as error:
                return ModelPrediction(**base, status="invalid", error_code=error.code)
            if set(prediction.evidence_ids) - allowed:
                return ModelPrediction(**base, status="invalid", error_code="invalid_evidence_time")
        return ModelPrediction(
            **base,
            status="success" if prediction.status == "ok" else "unavailable",
            probabilities=prediction.probabilities if prediction.status == "ok" else None,
            evidence_ids=prediction.evidence_ids,
            error_code=prediction.reason_code,
        )
    status = (
        "timeout"
        if outcome.get("error_code") == "TimeoutError"
        else "invalid"
        if outcome.get("failure_kind") == "protocol"
        else "unavailable"
    )
    return ModelPrediction(
        **base, status=status, error_code=outcome.get("error_code", "model_unavailable")
    )
