"""Producer-trained TF-IDF + logistic regression returns (``rolecraft-linear-return-v1``).

A return is a fixture v2 outer manifest plus ``linear/model.json`` and ``linear/arrays.npz``.
The loader rebuilds scikit-learn's ``TfidfVectorizer`` from declared parameters only
(built-in analyzers, no callables or pickles) and predicts with the product feature text
``rolecraft-linear-text-v1`` (``linear.text`` / ``linear.pair_text``). Registration never
fits, imports producer code or executes producer commands.
"""

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from career_lab.contracts.v2.core import FileRef, ProtocolError, digest, read_file

from .bundle import sha
from .core import LABELS, UNLIMITED, abstention, checked_input, input_problem, prediction, softmax
from .encoder_artifact import file_map, validate_return_identity
from .linear import pair_text, text
from .registration import RegistrationProtocol, RegistrationSummary, publish_registration

ARTIFACT_KIND = "linear"
ARTIFACT_PROTOCOL = "rolecraft-linear-return-v1"
PROTOCOL = "advisory-linear-registration-v1"
TEXT_TEMPLATE = "rolecraft-linear-text-v1"
MODEL_FILE = "linear/model.json"
ARRAYS_FILE = "linear/arrays.npz"
SCOPES = {"synthetic_fixture", "external_candidate"}
LABEL_TIERS = ("G0", "G1", "G2", "G2v")
# Known fixture handoff manifests; their data can only back synthetic registrations.
FIXTURE_DATASET_MANIFESTS = {"5c8f0d5be05e3b39c1599e7fd3a92e46e413dc571248c59f827818f5ee231858"}
SIZE_LIMIT = 64 * 1024 * 1024
DEFAULT_TOKEN_PATTERN = r"(?u)\b\w\w+\b"
VECTORIZER_KEYS = {
    "analyzer",
    "ngram_range",
    "lowercase",
    "sublinear_tf",
    "norm",
    "smooth_idf",
    "use_idf",
    "vocabulary",
}


def model_revision(model_sha: str, arrays_sha: str, dataset_sha: str) -> str:
    return "linear-return:" + digest(
        {
            "model_json_sha256": model_sha,
            "arrays_npz_sha256": arrays_sha,
            "dataset_manifest_sha256": dataset_sha,
        }
    )


def _vectorizer(spec: Any) -> TfidfVectorizer:
    if not isinstance(spec, dict) or not VECTORIZER_KEYS <= set(spec) <= VECTORIZER_KEYS | {
        "token_pattern"
    }:
        raise ProtocolError("linear_vectorizer_unsupported")
    if spec.get("token_pattern", DEFAULT_TOKEN_PATTERN) != DEFAULT_TOKEN_PATTERN:
        raise ProtocolError("linear_vectorizer_unsupported")
    ngram, norm = spec["ngram_range"], spec["norm"]
    if (
        not isinstance(spec["analyzer"], str)
        or spec["analyzer"] not in {"char", "char_wb", "word"}
        or not isinstance(ngram, list)
        or len(ngram) != 2
        or any(type(n) is not int for n in ngram)
        or not 1 <= ngram[0] <= ngram[1] <= 16
        or (norm is not None and (not isinstance(norm, str) or norm not in {"l1", "l2"}))
        or any(
            type(spec[name]) is not bool
            for name in ("lowercase", "sublinear_tf", "smooth_idf", "use_idf")
        )
    ):
        raise ProtocolError("linear_vectorizer_unsupported")
    vocabulary = spec["vocabulary"]
    if (
        not isinstance(vocabulary, dict)
        or not vocabulary
        or any(not isinstance(term, str) or not term for term in vocabulary)
        or any(type(index) is not int for index in vocabulary.values())
        or sorted(vocabulary.values()) != list(range(len(vocabulary)))
    ):
        raise ProtocolError("linear_vocabulary_invalid")
    return TfidfVectorizer(
        analyzer=spec["analyzer"],
        ngram_range=tuple(ngram),
        lowercase=spec["lowercase"],
        sublinear_tf=spec["sublinear_tf"],
        norm=spec["norm"],
        smooth_idf=spec["smooth_idf"],
        use_idf=spec["use_idf"],
        vocabulary=vocabulary,
    )


def _arrays(raw: bytes) -> dict[str, np.ndarray]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            expanded = sum(i.file_size for i in archive.infolist())
    except (OSError, zipfile.BadZipFile) as error:
        raise ProtocolError("linear_return_arrays_invalid") from error
    if expanded > SIZE_LIMIT:
        raise ProtocolError("linear_return_too_large")
    try:
        with np.load(io.BytesIO(raw), allow_pickle=False) as archive:
            arrays = {key: archive[key] for key in archive.files}
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        raise ProtocolError("linear_return_arrays_invalid") from error
    if any(array.dtype.kind != "f" for array in arrays.values()):
        raise ProtocolError("linear_return_arrays_invalid")
    return {key: array.astype(np.float64) for key, array in arrays.items()}


def _fitted(vectorizer: TfidfVectorizer, idf: np.ndarray | None) -> TfidfVectorizer:
    if idf is None:
        # With a fixed vocabulary and use_idf=false fitting learns nothing; it only marks
        # the vectorizer usable for transform.
        return vectorizer.fit([""])
    vectorizer.idf_ = idf
    return vectorizer


class LinearReturnModel:
    """Relation classifier and pair evidence head rebuilt from a verified linear return."""

    kind = ARTIFACT_KIND
    task_type = "relation"

    def __init__(self, model: dict[str, Any], arrays: dict[str, np.ndarray], revision: str):
        if model.get("text_template") != TEXT_TEMPLATE:
            raise ProtocolError("linear_text_template_unsupported")
        classifier = model.get("classifier")
        if classifier != {"kind": "multinomial_logistic", "label_order": list(LABELS["relation"])}:
            raise ProtocolError("linear_return_labels_invalid")
        head = model.get("evidence_head")
        if head is None:
            raise ProtocolError("linear_return_evidence_head_required")
        threshold = head.get("threshold") if isinstance(head, dict) else None
        if (
            not isinstance(head, dict)
            or set(head) != {"kind", "vectorizer", "threshold"}
            or head["kind"] != "pair_logistic"
            or type(threshold) not in {int, float}
            or not 0 <= threshold <= 1
        ):
            raise ProtocolError("linear_evidence_head_unsupported")
        if set(model) - {"text_template", "vectorizer", "classifier", "evidence_head", "training"}:
            raise ProtocolError("linear_return_model_invalid")
        main = _vectorizer(model.get("vectorizer"))
        shared = head["vectorizer"] == "shared"
        evidence = main if shared else _vectorizer(head["vectorizer"])
        n, k = len(main.vocabulary), len(LABELS["relation"])
        n_evidence = len(evidence.vocabulary)
        shapes = {
            "coef": (k, n),
            "intercept": (k,),
            "evidence_coef": (n_evidence,),
            "evidence_intercept": (1,),
        }
        if main.use_idf:
            shapes["idf"] = (n,)
        if not shared and evidence.use_idf:
            shapes["evidence_idf"] = (n_evidence,)
        if set(arrays) != set(shapes):
            raise ProtocolError("linear_return_arrays_invalid")
        if any(arrays[name].shape != shape for name, shape in shapes.items()):
            raise ProtocolError("linear_return_array_shape_invalid")
        if any(not np.isfinite(array).all() for array in arrays.values()):
            raise ProtocolError("linear_return_array_values_invalid")
        self.vectorizer = _fitted(main, arrays.get("idf"))
        self.evidence_vectorizer = (
            self.vectorizer if shared else _fitted(evidence, arrays.get("evidence_idf"))
        )
        self.coef, self.intercept = arrays["coef"], arrays["intercept"]
        self.evidence_coef = arrays["evidence_coef"]
        self.evidence_intercept = float(arrays["evidence_intercept"][0])
        self.evidence_threshold = float(threshold)
        self.revision = revision

    def measure(self, item):
        """TF-IDF has no token budget."""
        checked_input(item)
        return UNLIMITED

    def predict(self, item):
        item = checked_input(item)
        if item.task_type != self.task_type:
            raise ProtocolError("candidate_task_mismatch")
        if input_problem(item):
            return abstention(item, self.revision, input_problem(item))
        probs = softmax(
            np.asarray(self.vectorizer.transform([text(item)]) @ self.coef.T)[0] + self.intercept
        )
        candidates = item.evidence.candidate_evidence
        scores = []
        if candidates:
            logits = (
                np.asarray(
                    self.evidence_vectorizer.transform([pair_text(item, c) for c in candidates])
                    @ self.evidence_coef
                ).reshape(-1)
                + self.evidence_intercept
            )
            scores = 1 / (1 + np.exp(-np.clip(logits, -50, 50)))
        return prediction(item, self.revision, probs, scores, self.evidence_threshold)


def _manifest(root: Path, ref: FileRef) -> dict[str, Any]:
    manifest = json.loads(read_file(root, ref))
    if not isinstance(manifest, dict):
        raise ProtocolError("model_return_protocol_invalid")
    validate_return_identity(manifest)
    if (
        manifest.get("artifact_kind") != ARTIFACT_KIND
        or manifest.get("artifact_protocol") != ARTIFACT_PROTOCOL
    ):
        raise ProtocolError("linear_return_protocol_invalid")
    tiers = manifest.get("label_tiers", [])
    if (
        not isinstance(tiers, list)
        or len(set(tiers)) != len(tiers)
        or any(tier not in LABEL_TIERS for tier in tiers)
    ):
        raise ProtocolError("linear_return_label_tiers_invalid")
    return manifest


def _inspect(root: Path, ref: FileRef) -> tuple[LinearReturnModel, dict[str, Any], dict[str, str]]:
    """Verify one return directory and rebuild its model; returns (model, manifest, files)."""
    root = root.resolve()
    manifest = _manifest(root, ref)
    files = file_map(manifest.get("checkpoint_files"))
    if set(files) != {MODEL_FILE, ARRAYS_FILE}:
        raise ProtocolError("linear_return_member_set_mismatch")
    model_raw = read_file(root, FileRef(path=MODEL_FILE, sha256=files[MODEL_FILE]))
    arrays_raw = read_file(root, FileRef(path=ARRAYS_FILE, sha256=files[ARRAYS_FILE]))
    if len(model_raw) > SIZE_LIMIT or len(arrays_raw) > SIZE_LIMIT:
        raise ProtocolError("linear_return_too_large")
    try:
        model = json.loads(model_raw)
    except ValueError as error:
        raise ProtocolError("linear_return_model_invalid") from error
    if not isinstance(model, dict):
        raise ProtocolError("linear_return_model_invalid")
    revision = model_revision(sha(model_raw), sha(arrays_raw), manifest["dataset_manifest_sha256"])
    if manifest["model_revision"] != revision:
        raise ProtocolError("linear_return_revision_mismatch")
    loaded = LinearReturnModel(model, _arrays(arrays_raw), revision)
    return loaded, manifest, files | {ref.path: ref.sha256}


def _dataset(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataset_id": manifest["dataset_id"],
        "dataset_manifest_sha256": manifest["dataset_manifest_sha256"],
        "label_tiers": list(manifest.get("label_tiers", [])),
    }


def _fixture(manifest: dict[str, Any]) -> bool:
    return (
        "fixture" in manifest["dataset_id"].lower()
        or manifest["dataset_manifest_sha256"] in FIXTURE_DATASET_MANIFESTS
    )


def _entry(
    manifest: dict[str, Any], ref: FileRef, files: dict[str, str], scope: str, runtime: dict
) -> dict[str, Any]:
    identity = {
        "protocol": PROTOCOL,
        "kind": ARTIFACT_KIND,
        "bundle": ref.model_dump(mode="json"),
        "scope": scope,
        "inference_runtime": runtime,
        "files": dict(sorted(files.items())),
    }
    return identity | {
        "id": "linear-" + digest(identity)[:32],
        "task_type": "relation",
        "labels": list(LABELS["relation"]),
        "model_revision": manifest["model_revision"],
        "dataset": _dataset(manifest),
        "mode": "advisory",
        "affects_score": False,
        "quality_validated": False,
    }


def register_linear(
    registry_root: Path,
    return_root: Path,
    ref: FileRef,
    *,
    scope: str,
    runtime: dict[str, Any],
) -> FileRef:
    if scope not in SCOPES:
        raise ProtocolError("registration_scope_required")
    _, manifest, files = _inspect(Path(return_root), ref)
    if _fixture(manifest) and scope != "synthetic_fixture":
        raise ProtocolError("fixture_cannot_be_registered_as_external")
    entry = _entry(manifest, ref, files, scope, runtime)

    def write_artifact(target: Path) -> None:
        for name, checksum in files.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(read_file(Path(return_root), FileRef(path=name, sha256=checksum)))
        _, copied, copied_files = _inspect(target, ref)
        if _entry(copied, ref, copied_files, scope, runtime) != entry:
            raise ProtocolError("model_registration_drift")

    return publish_registration(
        Path(registry_root),
        entry,
        write_artifact,
        lambda registration: load(Path(registry_root), registration, runtime)[1],
    )


def load(root: Path, ref: FileRef, runtime: dict[str, Any]) -> tuple[LinearReturnModel, dict]:
    root = Path(root).resolve()
    entry = json.loads(read_file(root, ref))
    if entry.get("protocol") != PROTOCOL or entry.get("scope") not in SCOPES:
        raise ProtocolError("model_registration_protocol_invalid")
    if (
        entry.get("mode") != "advisory"
        or entry.get("affects_score") is not False
        or entry.get("quality_validated") is not False
    ):
        raise ProtocolError("registration_cannot_promote_scoring_or_quality")
    try:
        identity = {
            key: entry[key]
            for key in ("protocol", "kind", "bundle", "scope", "inference_runtime", "files")
        }
        expected = "linear-" + digest(identity)[:32]
        if entry.get("id") != expected or ref.path != expected + "/registration.json":
            raise ProtocolError("model_registration_identity_mismatch")
        if entry["inference_runtime"] != runtime:
            raise ProtocolError("registered_inference_runtime_changed")
        bundle = FileRef.model_validate(entry["bundle"])
        model, manifest, files = _inspect(root / expected / "artifact", bundle)
    except KeyError as error:
        raise ProtocolError("model_registration_identity_mismatch") from error
    if _entry(manifest, bundle, files, entry["scope"], runtime) != entry:
        raise ProtocolError("registered_model_identity_mismatch")
    return model, entry


def describe(root: Path, ref: FileRef, runtime: dict[str, Any]) -> RegistrationSummary:
    _, entry = load(root, ref, runtime)
    return RegistrationSummary(
        id=entry["id"],
        scope=entry["scope"],
        model_revision=entry["model_revision"],
        task_type=entry["task_type"],
        labels=tuple(entry["labels"]),
        kind=ARTIFACT_KIND,
        dataset=entry["dataset"],
    )


def is_linear_return(manifest: Any) -> bool:
    return isinstance(manifest, dict) and manifest.get("artifact_kind") == ARTIFACT_KIND


REGISTRATION = RegistrationProtocol(
    handles=lambda entry: entry.get("protocol") == PROTOCOL,
    describe=describe,
    load=load,
)
