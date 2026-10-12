"""FUS-01..05: fusion registrations built from two registered returns plus a dev selection.

Components are synthetic linear returns and the static encoder-return inventory; no model
here is trained for quality. Encoder prediction is covered by the explicit optional check
``tests/optional_encoder/check_fusion_registration.py``.
"""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from career_lab.contracts.v2.core import FileRef
from career_lab.models.v3 import registry_cli
from tests.support.linear_return import (
    DELETE,
    LABELS,
    feedback_report,
    golden_rows,
    json_bytes,
    selection_record,
    sha,
    write_linear_return,
)
from tests.support.model_assembly import fixed_linear_bundle
from tests.unit.test_w08_encoder_registration import encoder_return

FIXTURE_DATASET = {"dataset_id": "rolecraft-fixture-20261007-v2", "dataset_sha": "f" * 64}


def cli(capsys: pytest.CaptureFixture[str], *argv: object) -> tuple[int, dict]:
    code = registry_cli.main([str(value) for value in argv])
    return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


class Registry:
    """The registry CLI over one registry directory."""

    def __init__(self, root: Path, capsys: pytest.CaptureFixture[str]) -> None:
        self.root, self.capsys = root, capsys

    def register(self, source: Path, ref: FileRef, scope: str = "synthetic_fixture") -> dict:
        code, out = cli(
            self.capsys,
            "register",
            "--registry",
            self.root,
            "--bundle-root",
            source,
            "--bundle-path",
            ref.path,
            "--bundle-hash",
            ref.sha256,
            "--scope",
            scope,
        )
        assert code == 0, out
        return out["registration"]

    def describe(self, registration: dict) -> tuple[int, dict]:
        return cli(
            self.capsys,
            "describe",
            "--registry",
            self.root,
            "--registration-path",
            registration["path"],
            "--registration-hash",
            registration["sha256"],
        )

    def fuse(
        self,
        left: dict,
        right: dict,
        selection: dict[str, Any],
        scope: str = "synthetic_fixture",
    ) -> tuple[int, dict]:
        path = self.root.parent / "fusion-selection.json"
        path.write_text(json.dumps(selection, indent=2))
        return cli(
            self.capsys,
            "register-fusion",
            "--registry",
            self.root,
            "--left-path",
            left["path"],
            "--left-hash",
            left["sha256"],
            "--right-path",
            right["path"],
            "--right-hash",
            right["sha256"],
            "--selection",
            path,
            "--scope",
            scope,
        )

    def predict(self, registration: dict, model_input: dict, request: str) -> tuple[int, dict]:
        item = self.root.parent / (request + ".json")
        item.write_text(json.dumps(model_input, ensure_ascii=False))
        return cli(
            self.capsys,
            "predict",
            "--registry",
            self.root,
            "--registration-path",
            registration["path"],
            "--registration-hash",
            registration["sha256"],
            "--journal",
            self.root.parent / "journal",
            "--request-id",
            request,
            "--input",
            item,
            "--language",
            "en",
            "--allow-synthetic",
        )


@pytest.fixture
def registry(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Registry:
    return Registry(tmp_path / "registry", capsys)


def linear(registry: Registry, name: str, scope: str = "synthetic_fixture", **changes) -> dict:
    root = registry.root.parent / name
    return registry.register(root, write_linear_return(root, **changes), scope)


def described(registry: Registry, registration: dict) -> dict:
    code, identity = registry.describe(registration)
    assert code == 0, identity
    return identity


def second_weights() -> dict:
    return {"intercept": np.array([-0.4, 0.6, 0.1]), "evidence_intercept": np.array([0.2])}


def sample(name: str) -> dict:
    return next(row for row in golden_rows() if row["sample"] == name)["model_input"]


# FUS-01 ------------------------------------------------------------------------------


def test_fus_01_linear_and_encoder_returns_form_a_heterogeneous_fusion(
    registry: Registry,
) -> None:
    left = linear(registry, "linear", **FIXTURE_DATASET, label_tiers=["G0"])
    encoder_ref = encoder_return(registry.root.parent / "encoder")
    right = registry.register(registry.root.parent / "encoder", encoder_ref)
    left_identity, right_identity = described(registry, left), described(registry, right)
    # The encoder registration publishes its own kind and data identity (146, protocol v2).
    assert right_identity["kind"] == "huggingface_encoder"
    assert right_identity["dataset"] == {
        "dataset_id": "rolecraft-fixture-20261007-v2",
        "dataset_manifest_sha256": "f" * 64,
        "label_tiers": [],
    }
    code, out = registry.fuse(
        left, right, selection_record(left_identity, right_identity, alpha=0.25)
    )
    assert code == 0, out
    fusion = out["registration"]
    assert fusion["path"].startswith("fusion-")
    identity = described(registry, fusion)
    assert identity["kind"] == "probability_fusion"
    assert identity["scope"] == "synthetic_fixture" and identity["quality_validated"] is False
    assert identity["dataset"] == {
        "dataset_id": "rolecraft-fixture-20261007-v2",
        "dataset_manifest_sha256": "f" * 64,
        "label_tiers": ["G0"],
    }
    assert identity["components"] == [
        {
            "role": "left",
            "id": left_identity["id"],
            "kind": "linear",
            "model_revision": left_identity["model_revision"],
            "alpha": 0.75,
        },
        {
            "role": "right",
            "id": right_identity["id"],
            "kind": "huggingface_encoder",
            "model_revision": right_identity["model_revision"],
            "alpha": 0.25,
        },
    ]
    assert identity["fusion"] == {
        "alpha": 0.25,
        "evidence_threshold": 0.5,
        "fusion_gain_observed": True,
    }
    entry = json.loads((registry.root / fusion["path"]).read_bytes())
    assert sorted(path.name for path in (registry.root / entry["id"] / "artifact").iterdir()) == [
        "fusion-selection.json"
    ]


def test_fus_01_linear_fusion_predicts_the_declared_blend(registry: Registry) -> None:
    left = linear(registry, "left")
    right = linear(registry, "right", arrays=second_weights())
    left_identity, right_identity = described(registry, left), described(registry, right)
    selection = selection_record(left_identity, right_identity, alpha=0.75, threshold=0.25)
    code, out = registry.fuse(left, right, selection)
    assert code == 0, out
    model_input = sample("synthetic-zh-open-validity")
    parts = [registry.predict(r, model_input, "part-" + n) for n, r in (("l", left), ("r", right))]
    assert all(code == 0 for code, _ in parts)
    (_, a), (_, b) = parts
    code, fused = registry.predict(out["registration"], model_input, "fused")
    assert code == 0, fused
    prediction = fused["prediction"]
    expected = 0.25 * np.array(a["prediction"]["probabilities"]) + 0.75 * np.array(
        b["prediction"]["probabilities"]
    )
    assert np.allclose(prediction["probabilities"], expected, rtol=0, atol=1e-12)
    scores = {
        key: 0.25 * value + 0.75 * dict(b["prediction"]["evidence_probabilities"])[key]
        for key, value in a["prediction"]["evidence_probabilities"]
    }
    assert prediction["evidence_ids"] == [key for key, value in scores.items() if value >= 0.25]
    assert (
        prediction["model_revision"] == described(registry, out["registration"])["model_revision"]
    )
    assert prediction["model_revision"].startswith("fusion-return:")


@pytest.mark.parametrize(
    "case",
    ["w01_bundle_component", "fusion_component", "identical_components", "external_over_synthetic"],
)
def test_fus_01_only_distinct_registered_returns_compose_within_their_scope(
    registry: Registry, case: str
) -> None:
    left = linear(registry, "left", dataset_id="team-relations", dataset_sha="e" * 64)
    right = linear(
        registry,
        "right",
        dataset_id="team-relations",
        dataset_sha="e" * 64,
        arrays=second_weights(),
    )
    scope, expected = "synthetic_fixture", "fusion_component_kind_unsupported"
    if case == "w01_bundle_component":
        bundle_root, bundle_ref = fixed_linear_bundle(registry.root.parent / "w01", fixture=True)
        right = registry.register(bundle_root, bundle_ref)
    elif case == "fusion_component":
        identities = described(registry, left), described(registry, right)
        code, out = registry.fuse(left, right, selection_record(*identities))
        assert code == 0, out
        right = out["registration"]
    elif case == "identical_components":
        right, expected = left, "fusion_components_identical"
    else:
        scope, expected = "external_candidate", "fusion_scope_exceeds_components"
    left_identity = described(registry, left)
    right_identity = dict(
        described(registry, right), kind="linear", dataset=left_identity["dataset"]
    )
    code, out = registry.fuse(left, right, selection_record(left_identity, right_identity), scope)
    assert (code, out.get("error")) == (2, expected)
    assert len(list(registry.root.glob("fusion-*"))) == (case == "fusion_component")


@pytest.mark.parametrize("language", ["zh", "en"])
def test_fus_01_normal_feedback_names_both_fusion_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registry: Registry, language: str
) -> None:
    left = linear(registry, "left", label_tiers=["G2v"])
    right = linear(registry, "right", arrays=second_weights(), label_tiers=["G2v"])
    identities = described(registry, left), described(registry, right)
    code, out = registry.fuse(left, right, selection_record(*identities, alpha=0.5))
    assert code == 0, out
    fusion = FileRef.model_validate(out["registration"])
    report = feedback_report(tmp_path, monkeypatch, language, registry.root, fusion)
    (advice,) = report["model_advice"]
    assert advice["status"] == "synthetic_mechanism_only" and advice["affects_score"] is False
    identity = advice["registration"]
    assert identity["kind"] == "probability_fusion"
    assert [(c["role"], c["id"], c["kind"]) for c in identity["components"]] == [
        ("left", identities[0]["id"], "linear"),
        ("right", identities[1]["id"], "linear"),
    ]
    assert identity["fusion"]["alpha"] == 0.5
    assert identity["dataset"]["label_tiers"] == ["G2v"]
    assert report["provenance"]["registered_model"] == identity


# FUS-02 ------------------------------------------------------------------------------


def test_fus_02_components_trained_on_different_data_are_refused(registry: Registry) -> None:
    left = linear(registry, "left", dataset_sha="d" * 64)
    right = linear(registry, "right", dataset_sha="e" * 64, arrays=second_weights())
    identities = described(registry, left), described(registry, right)
    code, out = registry.fuse(left, right, selection_record(*identities))
    assert (code, out["error"]) == (2, "fusion_component_data_mismatch")
    assert not list(registry.root.glob("fusion-*"))


@pytest.mark.parametrize(
    "change",
    [{"dataset_manifest_sha256": "0" * 64}, {"dataset_id": "another-release"}],
    ids=["manifest_sha", "dataset_id"],
)
def test_fus_02_selection_on_other_data_is_refused(registry: Registry, change: dict) -> None:
    left = linear(registry, "left")
    right = linear(registry, "right", arrays=second_weights())
    identities = described(registry, left), described(registry, right)
    code, out = registry.fuse(left, right, selection_record(*identities, **change))
    assert (code, out["error"]) == (2, "fusion_selection_dataset_mismatch")


# FUS-03 ------------------------------------------------------------------------------


def points(**metrics: Any) -> list[dict]:
    record = selection_record(
        {
            "dataset": {"dataset_id": "x", "dataset_manifest_sha256": "0" * 64},
            "model_revision": "a",
            "kind": "linear",
        },
        {"model_revision": "b", "kind": "linear"},
    )
    return [p | {"metrics": p["metrics"] | metrics} for p in record["points"]]


FUS_03_CASES = {
    "alpha_off_grid": (
        {"selected": {"alpha": 0.3, "evidence_threshold": 0.5}},
        "fusion_selection_alpha_invalid",
    ),
    "threshold_off_grid": (
        {"selected": {"alpha": 0.5, "evidence_threshold": 0.6}},
        "fusion_selection_alpha_invalid",
    ),
    "alpha_grid_changed": ({"alpha_grid": [0.0, 0.5, 1.0]}, "fusion_selection_grid_invalid"),
    "threshold_grid_duplicate": (
        {"evidence_threshold_grid": [0.5, 0.5]},
        "fusion_selection_grid_invalid",
    ),
    "points_missing": ({"points": []}, "fusion_selection_grid_invalid"),
    "metric_out_of_range": ({"points": points(macro_f1=1.5)}, "fusion_selection_metrics_invalid"),
    "selected_on_test": ({"selection_split": "test"}, "fusion_selection_contaminated"),
    "test_used": ({"test_used_for_selection": True}, "fusion_selection_contaminated"),
    "test_flag_missing": ({"test_used_for_selection": DELETE}, "fusion_selection_contaminated"),
    "unknown_protocol": (
        {"protocol": "rolecraft-fusion-selection-v0"},
        "fusion_selection_protocol_invalid",
    ),
    "unknown_field": (
        {"test_metrics": {"joint_correctness": 1.0}},
        "fusion_selection_protocol_invalid",
    ),
    "dev_hashes_missing": ({"dev_input_hashes": []}, "fusion_selection_protocol_invalid"),
    "component_revision": ({}, "fusion_selection_component_mismatch"),
    "component_kind": ({}, "fusion_selection_component_mismatch"),
}


@pytest.mark.parametrize("case", sorted(FUS_03_CASES))
def test_fus_03_selection_records_off_grid_or_using_test_are_refused(
    registry: Registry, case: str
) -> None:
    left = linear(registry, "left")
    right = linear(registry, "right", arrays=second_weights())
    identities = described(registry, left), described(registry, right)
    changes, expected = FUS_03_CASES[case]
    record = selection_record(*identities, **changes)
    if case == "component_revision":
        record["components"]["left"]["model_revision"] = "linear-return:" + "0" * 64
    if case == "component_kind":
        record["components"]["right"]["artifact_kind"] = "huggingface_encoder"
    code, out = registry.fuse(left, right, record)
    assert (code, out["error"]) == (2, expected)
    assert not list(registry.root.glob("fusion-*"))


# FUS-04 ------------------------------------------------------------------------------


@pytest.mark.parametrize(("alpha", "side"), [(0.0, "left"), (1.0, "right")])
def test_fus_04_endpoint_alpha_registers_without_fusion_gain(
    registry: Registry, alpha: float, side: str
) -> None:
    left = linear(registry, "left")
    right = linear(registry, "right", arrays=second_weights())
    identities = described(registry, left), described(registry, right)
    code, out = registry.fuse(left, right, selection_record(*identities, alpha=alpha, gain=False))
    assert code == 0, out
    fusion = described(registry, out["registration"])
    assert fusion["fusion"]["fusion_gain_observed"] is False
    model_input = sample("synthetic-en-capacity")
    code, part = registry.predict(left if side == "left" else right, model_input, "part")
    assert code == 0, part
    code, fused = registry.predict(out["registration"], model_input, "fused")
    assert code == 0, fused
    assert fused["prediction"]["probabilities"] == part["prediction"]["probabilities"]


@pytest.mark.parametrize("alpha", [0.0, 1.0])
def test_fus_04_endpoint_alpha_cannot_claim_fusion_gain(registry: Registry, alpha: float) -> None:
    left = linear(registry, "left")
    right = linear(registry, "right", arrays=second_weights())
    identities = described(registry, left), described(registry, right)
    code, out = registry.fuse(left, right, selection_record(*identities, alpha=alpha, gain=True))
    assert (code, out["error"]) == (2, "fusion_selection_gain_claim_invalid")


# FUS-05 ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("drift", "expected"),
    [
        ("component_weights", "file_hash_mismatch"),
        ("component_registration", "file_hash_mismatch"),
        ("component_removed", "file_missing"),
        ("selection_copy", "file_hash_mismatch"),
    ],
)
def test_fus_05_fusion_loading_fails_when_a_component_drifts(
    registry: Registry, drift: str, expected: str
) -> None:
    left = linear(registry, "left")
    right = linear(registry, "right", arrays=second_weights())
    identities = described(registry, left), described(registry, right)
    code, out = registry.fuse(left, right, selection_record(*identities))
    assert code == 0, out
    fusion = out["registration"]
    model_input = sample("synthetic-en-capacity")
    assert registry.predict(fusion, model_input, "before")[1]["status"] == "completed"
    left_dir = registry.root / left["path"].split("/")[0]
    fusion_dir = registry.root / fusion["path"].split("/")[0]
    if drift == "component_weights":
        (left_dir / "artifact/linear/arrays.npz").write_bytes(b"drifted weights")
    elif drift == "component_registration":
        entry = json.loads((left_dir / "registration.json").read_bytes())
        (left_dir / "registration.json").write_text(json.dumps(entry | {"labels": LABELS[::-1]}))
    elif drift == "component_removed":
        (left_dir / "registration.json").unlink()
    else:
        (fusion_dir / "artifact/fusion-selection.json").write_text("{}")
    code, result = registry.predict(fusion, model_input, "after")
    assert (code, result.get("error")) == (2, expected)
    code, result = registry.describe(fusion)
    assert (code, result.get("error")) == (2, expected)


def test_fus_05_drifted_component_shows_as_changed_files_in_new_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registry: Registry
) -> None:
    left = linear(registry, "left")
    right = linear(registry, "right", arrays=second_weights())
    identities = described(registry, left), described(registry, right)
    code, out = registry.fuse(left, right, selection_record(*identities))
    assert code == 0, out
    right_dir = registry.root / right["path"].split("/")[0]
    (right_dir / "artifact/linear/model.json").write_text("{}")
    fusion = FileRef.model_validate(out["registration"])
    report = feedback_report(tmp_path, monkeypatch, "en", registry.root, fusion)
    (advice,) = report["model_advice"]
    assert advice["status"] in {"failed", "unavailable"}
    assert advice["error_code"] == "model_files_changed"
    assert advice["label"] is None and advice["citations"] == []


@pytest.mark.parametrize("field", ["affects_score", "quality_validated"])
def test_fus_05_tampered_fusion_registration_cannot_promote_scoring_or_quality(
    registry: Registry, field: str
) -> None:
    left = linear(registry, "left")
    right = linear(registry, "right", arrays=second_weights())
    identities = described(registry, left), described(registry, right)
    code, out = registry.fuse(left, right, selection_record(*identities))
    assert code == 0, out
    path = registry.root / out["registration"]["path"]
    raw = json_bytes(json.loads(path.read_bytes()) | {field: True})
    path.write_bytes(raw)
    tampered = {"path": out["registration"]["path"], "sha256": sha(raw)}
    code, result = registry.describe(tampered)
    assert (code, result.get("error")) == (2, "registration_cannot_promote_scoring_or_quality")
    code, result = registry.predict(tampered, sample("synthetic-en-capacity"), "tampered")
    assert (code, result.get("error")) == (2, "registration_cannot_promote_scoring_or_quality")
