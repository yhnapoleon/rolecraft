"""One explicit invocation per request ID; recovery only reads durable outcomes."""

import json
import os
import sys
import time
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from career_lab.contracts.v2.core import FileRef, ProtocolError, digest

from .bundle import json_bytes, sha
from .core import Prediction, abstention, checked_input
from .registry import load_registration, public_registration
from .temporal import legal_evidence_ids

# Reason recorded when a sentence is longer than the registered encoder accepts.
UNIT_EXCEEDS_ENCODER_LIMIT = "unit_exceeds_encoder_limit"


def _measured(model, item):
    """The model's input size, or None when it cannot encode the input at all.

    Such inputs go to the model's own prediction, which abstains with its own reason.
    """
    try:
        return model.measure(item)
    except ProtocolError:
        return None


# Files a full verification opened, collected for the current thread of control only.
_OPENED: ContextVar[set[str] | None] = ContextVar("registration_files_opened", default=None)
# Files up to this size are hashed again on every light check; larger ones are compared
# by size, mtime, ctime and inode, with the hash recorded when they were verified.
_REHASH_LIMIT = 1 << 20


def _note_open(event, args):
    """Audit hook: while a verification is collecting, remember each file path it opens."""
    if event != "open" or (opened := _OPENED.get()) is None:
        return
    try:
        if isinstance(args[0], (str, bytes, os.PathLike)):
            opened.add(os.path.abspath(os.fsdecode(args[0])))
    except Exception:  # an audit hook must never break the operation it observes
        return


sys.addaudithook(_note_open)


@dataclass(frozen=True)
class _Stamp:
    """One verified file: where it is, its stat identity and the hash it had."""

    path: Path
    size: int
    mtime_ns: int
    ctime_ns: int
    inode: int
    sha256: str


@dataclass(frozen=True)
class _Verified:
    files: tuple[_Stamp, ...]
    model: object
    entry: dict


def _stamps(registry_root, opened):
    """Stamps for the regular files under the registry that a verification opened."""
    root = Path(registry_root).resolve()
    stamps = []
    for name in sorted(opened):
        path = Path(name).resolve()
        if path.is_relative_to(root) and path.is_file():
            stat = path.stat()
            stamps.append(
                _Stamp(
                    path,
                    stat.st_size,
                    stat.st_mtime_ns,
                    stat.st_ctime_ns,
                    stat.st_ino,
                    sha(path.read_bytes()),
                )
            )
    return tuple(stamps)


def _unchanged(stamp):
    try:
        stat = stamp.path.stat()
        if (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino) != (
            stamp.size,
            stamp.mtime_ns,
            stamp.ctime_ns,
            stamp.inode,
        ):
            return False
        return stamp.size > _REHASH_LIMIT or sha(stamp.path.read_bytes()) == stamp.sha256
    except OSError:
        return False


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
        # The last fully verified load and the files it read.
        self._verified = None

    def _load(self):
        """The registered model, fully verified again unless the files it read are unchanged.

        A full ``load_registration`` records every file under the registry it opens, which
        for a fusion includes its component registrations and their weights. Later calls
        check exactly those files: size, mtime_ns, ctime_ns and inode, and the SHA-256 of
        files up to 1 MiB. Any difference, or a file gone, means full verification again,
        so drift reaches new feedback as ``model_files_changed``. A load during which one
        of those files changed is not cached.
        """
        cached = self._verified
        if cached is not None and all(_unchanged(stamp) for stamp in cached.files):
            return cached.model, cached.entry
        self._verified = None
        started = time.time_ns()
        opened = set()
        token = _OPENED.set(opened)
        try:
            model, entry = load_registration(self.registry_root, self.ref)
        finally:
            _OPENED.reset(token)
        try:
            files = _stamps(self.registry_root, opened)
        except OSError:
            files = ()
        if files and all(stamp.ctime_ns <= started for stamp in files):
            self._verified = _Verified(files, model, entry)
        return model, entry

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

    def predict(self, item, *, request_id, work_language, retry_of=None, enforce_input_limit=False):
        """Run one journaled prediction, or read back the one already recorded.

        With ``enforce_input_limit`` the loaded model first measures the input; an input
        over its token budget is recorded as abstained (``unit_exceeds_encoder_limit``)
        without being cut or predicted.
        """
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
        model, entry = self._load()
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
            size = _measured(model, item) if enforce_input_limit else None
            if size is not None:
                base["input_size"] = {"tokens": size.tokens, "limit": size.limit}
            prediction = (
                abstention(item, entry["model_revision"], UNIT_EXCEEDS_ENCODER_LIMIT)
                if size is not None and size.exceeds
                else model.predict(item)
            )
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


def to_public_prediction(outcome, item, *, mechanism=False):
    """Existing shared protocol DTO projection. Fixture predictions never become product advice.

    ``mechanism=True`` checks and projects a synthetic registration's prediction exactly
    like an external one, for display only as a labelled mechanism demonstration.
    """
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
    if identity["scope"] == "synthetic_fixture" and not mechanism:
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
