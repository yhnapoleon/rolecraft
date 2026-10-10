"""MODEL-01: identity-only registration never requires optional inference dependencies."""

import json
from pathlib import Path
from typing import Any

import pytest

from career_lab.contracts.v2.core import FileRef, ProtocolError
from career_lab.models.v3.bundle import json_bytes, sha
from career_lab.models.v3.registry import load_registration, register_bundle


def encoder_return(root: Path) -> FileRef:
    """Static synthetic file inventory; deliberately not a loadable neural model."""
    encoder = root / "encoder"
    encoder.mkdir(parents=True)
    files = {
        "config.json": b"{}",
        "model.safetensors": b"synthetic weights",
        "tokenizer.json": b"{}",
    }
    for name, raw in files.items():
        (encoder / name).write_bytes(raw)
    local = {
        "protocol": "w08-hf-local-files-v1",
        "source_revision": "a" * 40,
        "weights_stage": "supervised_finetuned",
        "derived_from": "b" * 64,
        "files": {name: sha(raw) for name, raw in files.items()},
    }
    (encoder / "local-files.json").write_bytes(json_bytes(local))
    (root / "heads.npz").write_bytes(b"synthetic head inventory")
    config = {
        "source_revision": "a" * 40,
        "model_revision": "hf-finetuned:" + "a" * 40 + ":" + "c" * 64,
        "task_type": "relation",
        "variant": "pair",
        "max_tokens": 128,
        "seed": 5002,
        "training_report": {
            "source_revision": "a" * 40,
            "fit_split": "train",
            "before_weights": "b" * 64,
            "after_weights": "c" * 64,
            "encoder_before": "d" * 64,
            "encoder_after": "e" * 64,
        },
        "files": {
            p.relative_to(root).as_posix(): sha(p.read_bytes())
            for p in root.rglob("*")
            if p.is_file()
        },
    }
    (root / "checkpoint.json").write_bytes(json_bytes(config))
    manifest = {
        "template": False,
        "completed": True,
        "return_protocol": "rolecraft-label-evidence-v2",
        "model_revision": config["model_revision"],
        "framework": "pytorch",
        "framework_version": "synthetic-inventory",
        "task_type": "relation",
        "label_order": ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"],
        "dataset_id": "rolecraft-fixture-20261007-v2",
        "dataset_manifest_sha256": "f" * 64,
        "training_partitions": ["train"],
        "selection_partition": "dev",
        "test_used_for_selection": False,
        "evidence_selection_implemented": True,
        "evidence_selection_required": True,
        "checkpoint_files": {
            p.relative_to(root).as_posix(): sha(p.read_bytes())
            for p in root.rglob("*")
            if p.is_file()
        },
        "load_and_predict_command": "python -m career_lab.models.v3.registry_cli predict",
        "training_notes_file": "notes.md",
        "predictions_file": "predictions.dev.jsonl",
    }
    return write_manifest(root, manifest)


def write_manifest(root: Path, manifest: dict[str, Any]) -> FileRef:
    raw = json_bytes(manifest)
    (root / "checkpoint-manifest.json").write_bytes(raw)
    return FileRef(path="checkpoint-manifest.json", sha256=sha(raw))


def test_model_01_encoder_registration_is_portable_without_dependencies(tmp_path: Path) -> None:
    root = tmp_path / "producer"
    ref = encoder_return(root)
    registry = tmp_path / "registry"
    registration = register_bundle(registry, root, ref, scope="synthetic_fixture")
    entry = json.loads((registry / registration.path).read_bytes())
    assert entry["kind"] == "huggingface_encoder"
    assert entry["task_type"] == "relation"
    assert entry["labels"] == ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"]
    assert entry["quality_validated"] is False and entry["affects_score"] is False
    assert register_bundle(registry, root, ref, scope="synthetic_fixture") == registration
    (root / "encoder/model.safetensors").write_bytes(b"producer changed")
    assert (registry / registration.path).parent.joinpath(
        "artifact/encoder/model.safetensors"
    ).read_bytes() == b"synthetic weights"


def test_encoder_load_reports_missing_optional_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    root = tmp_path / "producer"
    ref = encoder_return(root)
    registry = tmp_path / "registry"
    registration = register_bundle(registry, root, ref, scope="synthetic_fixture")
    original_import = builtins.__import__

    def without_encoder(name: str, *args: Any, **kwargs: Any) -> Any:
        if name in {"torch", "transformers"}:
            raise ImportError("controlled missing optional dependency")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_encoder)
    with pytest.raises(ProtocolError) as error:
        load_registration(registry, registration)
    assert error.value.code == "pretrained_encoder_dependencies_unavailable"
    assert error.value.status == 503


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        (
            "label_order",
            ["INSUFFICIENT", "CONTRADICTED", "SUPPORTED"],
            "model_return_task_or_labels_invalid",
        ),
        ("task_type", "criterion", "model_return_task_or_labels_invalid"),
        ("completed", False, "model_return_incomplete"),
        ("template", True, "model_return_incomplete"),
        ("evidence_selection_implemented", False, "model_return_incomplete"),
        ("test_used_for_selection", True, "model_return_selection_contaminated"),
    ],
)
def test_encoder_registration_rejects_invalid_return_identity(
    tmp_path: Path, field: str, value: Any, code: str
) -> None:
    root = tmp_path / "producer"
    encoder_return(root)
    manifest = json.loads((root / "checkpoint-manifest.json").read_bytes())
    manifest[field] = value
    with pytest.raises(ProtocolError) as error:
        register_bundle(
            tmp_path / "registry", root, write_manifest(root, manifest), scope="synthetic_fixture"
        )
    assert error.value.code == code
    assert not (tmp_path / "registry").exists()


def test_encoder_registration_rejects_hash_drift_and_fixture_promotion(tmp_path: Path) -> None:
    root = tmp_path / "producer"
    ref = encoder_return(root)
    with pytest.raises(ProtocolError) as error:
        register_bundle(tmp_path / "registry", root, ref, scope="external_candidate")
    assert error.value.code == "fixture_cannot_be_registered_as_external"
    (root / "heads.npz").write_bytes(b"modified heads")
    with pytest.raises(ProtocolError) as error:
        register_bundle(tmp_path / "registry", root, ref, scope="synthetic_fixture")
    assert error.value.code == "file_hash_mismatch"


def rehash_return(root: Path) -> FileRef:
    """Rebind an explicitly synthetic negative-test inventory, never a frozen return."""
    local_path = root / "encoder/local-files.json"
    local = json.loads(local_path.read_bytes())
    local["files"] = {name: sha((root / "encoder" / name).read_bytes()) for name in local["files"]}
    local_path.write_bytes(json_bytes(local))
    config_path = root / "checkpoint.json"
    config = json.loads(config_path.read_bytes())
    config["files"] = {name: sha((root / name).read_bytes()) for name in config["files"]}
    config_path.write_bytes(json_bytes(config))
    manifest = json.loads((root / "checkpoint-manifest.json").read_bytes())
    manifest["checkpoint_files"] = {
        name: sha((root / name).read_bytes()) for name in manifest["checkpoint_files"]
    }
    return write_manifest(root, manifest)


def test_encoder_registration_rejects_training_source_disagreement(tmp_path: Path) -> None:
    root = tmp_path / "producer"
    encoder_return(root)
    path = root / "checkpoint.json"
    config = json.loads(path.read_bytes())
    config["training_report"]["source_revision"] = "b" * 40
    path.write_bytes(json_bytes(config))
    ref = rehash_return(root)
    with pytest.raises(ProtocolError) as error:
        register_bundle(tmp_path / "registry", root, ref, scope="synthetic_fixture")
    assert error.value.code == "checkpoint_training_identity_mismatch"


@pytest.mark.parametrize(
    "field,value", [("weights_stage", "pretrained"), ("source_revision", "b" * 40)]
)
def test_encoder_registration_rejects_wrong_weight_stage_or_source(
    tmp_path: Path, field: str, value: str
) -> None:
    root = tmp_path / "producer"
    encoder_return(root)
    path = root / "encoder/local-files.json"
    local = json.loads(path.read_bytes())
    local[field] = value
    path.write_bytes(json_bytes(local))
    with pytest.raises(ProtocolError) as error:
        register_bundle(tmp_path / "registry", root, rehash_return(root), scope="synthetic_fixture")
    assert error.value.code == "local_checkpoint_revision_or_stage_invalid"


def test_encoder_registration_copies_weights_above_numpy_limit(tmp_path: Path) -> None:
    root = tmp_path / "producer"
    encoder_return(root)
    weight = root / "encoder/model.safetensors"
    with weight.open("wb") as stream:
        stream.truncate(65 * 1024 * 1024)
    registry = tmp_path / "registry"
    ref = register_bundle(registry, root, rehash_return(root), scope="synthetic_fixture")
    copied = (registry / ref.path).parent / "artifact/encoder/model.safetensors"
    assert copied.stat().st_size == 65 * 1024 * 1024
    weight.write_bytes(b"producer changed")
    assert copied.stat().st_size == 65 * 1024 * 1024


def test_encoder_registration_cli_accepts_return_manifest(tmp_path: Path) -> None:
    import subprocess
    import sys

    root = tmp_path / "producer"
    ref = encoder_return(root)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "career_lab.models.v3.registry_cli",
            "register",
            "--registry",
            str(tmp_path / "registry"),
            "--bundle-root",
            str(root),
            "--bundle-path",
            ref.path,
            "--bundle-hash",
            ref.sha256,
            "--scope",
            "synthetic_fixture",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    value = json.loads(result.stdout)
    assert value["training_performed"] is False
    assert value["quality_validated"] is False
    assert value["registration"]["path"].endswith("/registration.json")


def test_encoder_registered_artifact_drift_is_rejected_before_loading(tmp_path: Path) -> None:
    root = tmp_path / "producer"
    ref = encoder_return(root)
    registry = tmp_path / "registry"
    registration = register_bundle(registry, root, ref, scope="synthetic_fixture")
    artifact = (registry / registration.path).parent / "artifact"
    (artifact / "heads.npz").write_bytes(b"drift")
    with pytest.raises(ProtocolError) as error:
        load_registration(registry, registration)
    assert error.value.code == "file_hash_mismatch"
