"""Fusion registrations: two registered returns plus the producer's dev selection record.

A fusion references its components by registration file (id + sha256) and never copies
their weights; its artifact holds only the ``rolecraft-fusion-selection-v1`` record.
Components may be any mix of linear returns and encoder returns built on one dataset;
W01 ModelBundle fusions keep their own ``save_fusion_bundle`` path. Registration checks
the selection record's identity and structure; recomputing its dev metrics is the return
verifier's job. Nothing here fits, selects or scores.
"""

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from career_lab.contracts.v2.core import FileRef, ProtocolError, digest, read_file

from .bundle import sha
from .core import LABELS
from .ensemble import FusionCandidate
from .registration import RegistrationProtocol, RegistrationSummary, publish_registration

PROTOCOL = "advisory-fusion-registration-v1"
SELECTION_PROTOCOL = "rolecraft-fusion-selection-v1"
KIND = "probability_fusion"
SELECTION_FILE = "fusion-selection.json"
SCOPES = {"synthetic_fixture", "external_candidate"}
COMPONENT_KINDS = {"linear", "huggingface_encoder"}
ALPHA_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
SELECTION_KEYS = {
    "protocol",
    "task_type",
    "dataset_id",
    "dataset_manifest_sha256",
    "selection_split",
    "test_used_for_selection",
    "components",
    "alpha_grid",
    "evidence_threshold_grid",
    "selected",
    "points",
    "fusion_gain_observed",
    "dev_input_hashes",
}
METRIC_FRACTIONS = ("macro_f1", "mean_evidence_f1", "joint_correctness")
METRIC_COUNTS = ("count", "evidence_denominator", "joint_denominator")
_HEX64 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class ComponentRegistry:
    """How a fusion reaches the registrations it composes; ``registry`` supplies it.

    Injected rather than imported so the registry's protocol table can include fusions.
    """

    describe: Callable[[Path, FileRef], RegistrationSummary]
    load: Callable[[Path, FileRef], tuple[Any, dict[str, Any]]]
    runtime: Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class _Component:
    role: str
    ref: FileRef
    summary: RegistrationSummary
    kind: str
    dataset: dict[str, Any]


@dataclass(frozen=True)
class _Selection:
    alpha: float
    threshold: float
    gain: bool


def model_revision(left: str, right: str, alpha: float, threshold: float) -> str:
    """Revision of the fused predictor; producers stamp fused dev rows with it."""
    return "fusion-return:" + digest(
        {
            "left": left,
            "right": right,
            "alpha": float(alpha),
            "evidence_threshold": float(threshold),
        }
    )


def _component(root: Path, role: str, ref: FileRef, components: ComponentRegistry) -> _Component:
    """A verified component; its registration publishes its kind and data identity."""
    summary = components.describe(root, ref)
    if summary.kind not in COMPONENT_KINDS:
        raise ProtocolError("fusion_component_kind_unsupported")
    if summary.task_type != "relation" or summary.labels != LABELS["relation"]:
        raise ProtocolError("fusion_component_task_mismatch")
    if summary.dataset is None:
        raise ProtocolError("fusion_component_dataset_unknown")
    return _Component(role, ref, summary, summary.kind, dict(summary.dataset))


def _components(
    root: Path, left_ref: FileRef, right_ref: FileRef, scope: str, components: ComponentRegistry
) -> tuple[_Component, _Component]:
    if left_ref.path == right_ref.path:
        raise ProtocolError("fusion_components_identical")
    left = _component(root, "left", left_ref, components)
    right = _component(root, "right", right_ref, components)
    if left.summary.id == right.summary.id:
        raise ProtocolError("fusion_components_identical")
    if any(
        left.dataset[key] != right.dataset[key] for key in ("dataset_id", "dataset_manifest_sha256")
    ):
        raise ProtocolError("fusion_component_data_mismatch")
    if scope != "synthetic_fixture" and "synthetic_fixture" in {
        left.summary.scope,
        right.summary.scope,
    }:
        raise ProtocolError("fusion_scope_exceeds_components")
    return left, right


def _number(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


def _fraction(value: Any) -> bool:
    return _number(value) and 0 <= value <= 1


def _metrics(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {*METRIC_FRACTIONS, *METRIC_COUNTS}
        and all(value[k] is None or _fraction(value[k]) for k in METRIC_FRACTIONS)
        and all(type(value[k]) is int and value[k] >= 0 for k in METRIC_COUNTS)
    )


def _selection(raw: bytes, left: _Component, right: _Component) -> _Selection:
    try:
        record = json.loads(raw)
    except ValueError as error:
        raise ProtocolError("fusion_selection_protocol_invalid") from error
    if not isinstance(record, dict):
        raise ProtocolError("fusion_selection_protocol_invalid")
    if record.get("selection_split") != "dev" or record.get("test_used_for_selection") is not False:
        raise ProtocolError("fusion_selection_contaminated", status=403)
    if (
        set(record) != SELECTION_KEYS
        or record["protocol"] != SELECTION_PROTOCOL
        or record["task_type"] != "relation"
    ):
        raise ProtocolError("fusion_selection_protocol_invalid")
    if (
        record["dataset_id"] != left.dataset["dataset_id"]
        or record["dataset_manifest_sha256"] != left.dataset["dataset_manifest_sha256"]
    ):
        raise ProtocolError("fusion_selection_dataset_mismatch")
    if record["components"] != {
        c.role: {"model_revision": c.summary.model_revision, "artifact_kind": c.kind}
        for c in (left, right)
    }:
        raise ProtocolError("fusion_selection_component_mismatch")
    alphas, thresholds = record["alpha_grid"], record["evidence_threshold_grid"]
    if (
        not isinstance(alphas, list)
        or not all(_number(a) for a in alphas)
        or tuple(float(a) for a in alphas) != ALPHA_GRID
        or not isinstance(thresholds, list)
        or not thresholds
        or not all(_fraction(t) for t in thresholds)
        or len({float(t) for t in thresholds}) != len(thresholds)
    ):
        raise ProtocolError("fusion_selection_grid_invalid")
    points = record["points"]
    grid = {(a, float(t)) for a in ALPHA_GRID for t in thresholds}
    if (
        not isinstance(points, list)
        or len(points) != len(grid)
        or any(
            not isinstance(p, dict)
            or set(p) != {"alpha", "evidence_threshold", "metrics"}
            or not _number(p["alpha"])
            or not _number(p["evidence_threshold"])
            for p in points
        )
        or {(float(p["alpha"]), float(p["evidence_threshold"])) for p in points} != grid
    ):
        raise ProtocolError("fusion_selection_grid_invalid")
    if not all(_metrics(p["metrics"]) for p in points):
        raise ProtocolError("fusion_selection_metrics_invalid")
    selected = record["selected"]
    if (
        not isinstance(selected, dict)
        or set(selected) != {"alpha", "evidence_threshold"}
        or not _number(selected["alpha"])
        or not _number(selected["evidence_threshold"])
        or (float(selected["alpha"]), float(selected["evidence_threshold"])) not in grid
    ):
        raise ProtocolError("fusion_selection_alpha_invalid")
    alpha, threshold = float(selected["alpha"]), float(selected["evidence_threshold"])
    gain = record["fusion_gain_observed"]
    if type(gain) is not bool:
        raise ProtocolError("fusion_selection_protocol_invalid")
    if gain and alpha in (0.0, 1.0):
        raise ProtocolError("fusion_selection_gain_claim_invalid")
    hashes = record["dev_input_hashes"]
    if (
        not isinstance(hashes, list)
        or not hashes
        or len(set(hashes)) != len(hashes)
        or not all(isinstance(h, str) and _HEX64.fullmatch(h) for h in hashes)
    ):
        raise ProtocolError("fusion_selection_protocol_invalid")
    return _Selection(alpha, threshold, gain)


def _entry(
    left: _Component,
    right: _Component,
    selection_ref: FileRef,
    selection: _Selection,
    scope: str,
    runtime: dict[str, Any],
) -> dict[str, Any]:
    identity = {
        "protocol": PROTOCOL,
        "kind": KIND,
        "scope": scope,
        "components": [
            {
                "role": c.role,
                "registration": c.ref.model_dump(mode="json"),
                "id": c.summary.id,
                "kind": c.kind,
                "model_revision": c.summary.model_revision,
            }
            for c in (left, right)
        ],
        "selection": selection_ref.model_dump(mode="json"),
        "inference_runtime": runtime,
    }
    tiers = sorted({*left.dataset.get("label_tiers", ()), *right.dataset.get("label_tiers", ())})
    return identity | {
        "id": "fusion-" + digest(identity)[:32],
        "task_type": "relation",
        "labels": list(LABELS["relation"]),
        "model_revision": model_revision(
            left.summary.model_revision,
            right.summary.model_revision,
            selection.alpha,
            selection.threshold,
        ),
        "dataset": {
            "dataset_id": left.dataset["dataset_id"],
            "dataset_manifest_sha256": left.dataset["dataset_manifest_sha256"],
            "label_tiers": tiers,
        },
        "fusion": {
            "alpha": selection.alpha,
            "evidence_threshold": selection.threshold,
            "fusion_gain_observed": selection.gain,
        },
        "mode": "advisory",
        "affects_score": False,
        "quality_validated": False,
    }


def register(
    registry_root: Path,
    left_ref: FileRef,
    right_ref: FileRef,
    selection_file: Path,
    *,
    scope: str,
    components: ComponentRegistry,
) -> FileRef:
    if scope not in SCOPES:
        raise ProtocolError("registration_scope_required")
    root = Path(registry_root).resolve()
    left, right = _components(root, left_ref, right_ref, scope, components)
    raw = Path(selection_file).read_bytes()
    selection = _selection(raw, left, right)
    selection_ref = FileRef(path=SELECTION_FILE, sha256=sha(raw))
    entry = _entry(left, right, selection_ref, selection, scope, components.runtime())

    def write_artifact(target: Path) -> None:
        target.mkdir(parents=True)
        (target / SELECTION_FILE).write_bytes(raw)

    return publish_registration(
        root,
        entry,
        write_artifact,
        lambda ref: _verified(root, ref, components.runtime(), components)[0],
    )


def _verified(
    root: Path, ref: FileRef, runtime: dict[str, Any], components: ComponentRegistry
) -> tuple[dict[str, Any], tuple[_Component, _Component]]:
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
            for key in ("protocol", "kind", "scope", "components", "selection", "inference_runtime")
        }
        expected = "fusion-" + digest(identity)[:32]
        if entry.get("id") != expected or ref.path != expected + "/registration.json":
            raise ProtocolError("model_registration_identity_mismatch")
        if entry["inference_runtime"] != runtime:
            raise ProtocolError("registered_inference_runtime_changed")
        selection_ref = FileRef.model_validate(entry["selection"])
        raw = read_file(root / expected / "artifact", selection_ref)
        recorded = {c["role"]: c for c in entry["components"]}
        left, right = _components(
            root,
            FileRef.model_validate(recorded["left"]["registration"]),
            FileRef.model_validate(recorded["right"]["registration"]),
            entry["scope"],
            components,
        )
    except (KeyError, TypeError) as error:
        raise ProtocolError("model_registration_identity_mismatch") from error
    for component in (left, right):
        if (component.summary.id, component.kind, component.summary.model_revision) != tuple(
            recorded[component.role][key] for key in ("id", "kind", "model_revision")
        ):
            raise ProtocolError("fusion_component_identity_mismatch")
    rebuilt = _entry(
        left, right, selection_ref, _selection(raw, left, right), entry["scope"], runtime
    )
    if rebuilt != entry:
        raise ProtocolError("registered_model_identity_mismatch")
    return entry, (left, right)


def _describe(
    root: Path, ref: FileRef, runtime: dict[str, Any], components: ComponentRegistry
) -> RegistrationSummary:
    """Verified summary; components are described, not loaded (no optional dependencies)."""
    entry, (left, right) = _verified(Path(root).resolve(), ref, runtime, components)
    alpha = entry["fusion"]["alpha"]
    weights = {"left": 1 - alpha, "right": alpha}
    return RegistrationSummary(
        id=entry["id"],
        scope=entry["scope"],
        model_revision=entry["model_revision"],
        task_type=entry["task_type"],
        labels=tuple(entry["labels"]),
        kind=KIND,
        dataset=entry["dataset"],
        components=tuple(
            {
                "role": c.role,
                "id": c.summary.id,
                "kind": c.kind,
                "model_revision": c.summary.model_revision,
                "alpha": weights[c.role],
            }
            for c in (left, right)
        ),
        fusion=entry["fusion"],
    )


def _load(
    root: Path, ref: FileRef, runtime: dict[str, Any], components: ComponentRegistry
) -> tuple[FusionCandidate, dict[str, Any]]:
    root = Path(root).resolve()
    entry, (left, right) = _verified(root, ref, runtime, components)
    left_model, _ = components.load(root, left.ref)
    right_model, _ = components.load(root, right.ref)
    model = FusionCandidate(
        left_model,
        right_model,
        entry["fusion"]["alpha"],
        entry["fusion"]["evidence_threshold"],
    )
    model.revision = entry["model_revision"]
    return model, entry


def protocol(components: ComponentRegistry) -> RegistrationProtocol:
    return RegistrationProtocol(
        handles=lambda entry: entry.get("protocol") == PROTOCOL,
        describe=lambda root, ref, runtime: _describe(root, ref, runtime, components),
        load=lambda root, ref, runtime: _load(root, ref, runtime, components),
    )
