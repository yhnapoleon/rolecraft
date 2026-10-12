"""MODEL-01, encoder return v3 (ENC-*) and its runtime pin (RT-02..04), without torch.

Registration never imports torch: it reads the installed encoder runtime versions from
package metadata. The static returns here are deliberately not loadable neural models.
"""

import importlib.metadata
import json
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts.v2.core import FileRef, ProtocolError, digest
from career_lab.models.v3 import registry_cli
from career_lab.models.v3.bundle import json_bytes, sha
from career_lab.models.v3.registry import (
    describe_registration,
    inference_runtime,
    load_registration,
    register_bundle,
)
from scripts.regression.published import write_catalog
from tests.regression.conftest import PublishedSession
from tests.unit.test_w08_models import examples

ENCODER_RUNTIME = ("torch", "transformers", "tokenizers", "safetensors")
# The encoder extra as locked in pyproject.toml and uv.lock (local labels such as +cpu aside).
LOCKED_RUNTIME = {"torch": "2.8.0", "transformers": "4.57.1", "tokenizers": "0.22.2", "safetensors": "0.6.2"}
# Metadata-only distributions for the locked encoder extra (pyproject + uv.lock); no code.
DECLARED_RUNTIME = Path(__file__).with_name("encoder_runtime_metadata")


def declare_encoder_runtime() -> None:
    """Let a default (no-extra) test environment register static encoder returns.

    Registration pins torch/transformers/tokenizers/safetensors versions by metadata.
    The declaration is appended to sys.path, so a real installation is always found
    first; torch stays unimportable where it is absent, so loading still reports
    missing dependencies.
    """
    if str(DECLARED_RUNTIME) not in sys.path:
        sys.path.append(str(DECLARED_RUNTIME))


def without_runtime(monkeypatch: pytest.MonkeyPatch, missing: set[str]) -> None:
    """The environment no longer has these encoder runtime packages installed."""
    real = importlib.metadata.version

    def version(name: str) -> str:
        if name in missing:
            raise importlib.metadata.PackageNotFoundError(name)
        return real(name)

    monkeypatch.setattr(importlib.metadata, "version", version)


def runtime_upgrade(root: Path, name: str) -> Path:
    """Another installed version of one encoder runtime package, found before the current one."""
    info = root / f"{name}-99.0.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 99.0\n")
    return root


def v1_registration(registry: Path, root: Path, ref: FileRef, scope: str) -> FileRef:
    """A registration exactly as advisory-encoder-registration-v1 (eb494c0) published it."""
    manifest = json.loads((root / ref.path).read_bytes())
    files = dict(manifest["checkpoint_files"]) | {ref.path: ref.sha256}
    identity = {
        "protocol": "advisory-encoder-registration-v1",
        "kind": "huggingface_encoder",
        "bundle": ref.model_dump(mode="json"),
        "scope": scope,
        "inference_runtime": inference_runtime(),
        "files": files,
    }
    entry = identity | {
        "id": "encoder-" + digest(identity)[:32],
        "task_type": "relation",
        "labels": ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"],
        "model_revision": manifest["model_revision"],
        "source_revision": json.loads((root / "checkpoint.json").read_bytes())["source_revision"],
        "mode": "advisory",
        "affects_score": False,
        "quality_validated": False,
    }
    target = registry / entry["id"]
    for name in files:
        (target / "artifact" / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target / "artifact" / name)
    raw = json_bytes(entry)
    (target / "registration.json").write_bytes(raw)
    return FileRef(path=entry["id"] + "/registration.json", sha256=sha(raw))


def configure(monkeypatch: pytest.MonkeyPatch, root: Path, registry: Path, ref: FileRef) -> None:
    """Serve/worker configuration for one registration (read once at app assembly)."""
    monkeypatch.setenv("CAREER_LAB_MODEL_REGISTRY", str(registry))
    monkeypatch.setenv("CAREER_LAB_MODEL_REGISTRATION", ref.model_dump_json())
    monkeypatch.setenv("CAREER_LAB_MODEL_JOURNAL", str(root / "journal"))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_CATALOG", str(write_catalog(root / "catalog.json")))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(root / "archive"))


@contextmanager
def runtime_app(root: Path) -> Iterator[tuple[FastAPI, TestClient]]:
    """The normal API with its worker queue on one SQLite database under ``root``."""
    app = create_runtime_app("sqlite:///" + str(root / "session.db"), provider="local")
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield app, client
    finally:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()


def open_session(app: FastAPI, client: TestClient, language: str) -> PublishedSession:
    made = client.post(
        "/sessions",
        json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
    )
    assert made.status_code == 200, made.text
    body = made.json()
    return PublishedSession(
        app, client, body["session_id"], {"Authorization": "Bearer " + body["token"]}, language
    )


def review(
    session: PublishedSession, request_id: str, work: dict[str, object]
) -> tuple[str, dict]:
    """Submit the work for review, run the worker once and read the feedback."""
    transaction = session.send(
        "reviews",
        request_id,
        "reviews.create",
        {
            "subjects": [work],
            "scope": [],
            "purpose": "commitment",
            "decision": "defer_with_conditions",
        },
    )
    session.run_job()
    feedback = "feedback/" + transaction["result"]["review"]["object_id"]
    response = session.get(feedback)
    assert response.status_code == 200, response.text
    return feedback, response.json()


def register_cli(registry: Path, root: Path, ref: FileRef, scope: str, capsys) -> tuple[int, dict]:
    code = registry_cli.main(
        [
            "register",
            "--registry",
            str(registry),
            "--bundle-root",
            str(root),
            "--bundle-path",
            ref.path,
            "--bundle-hash",
            ref.sha256,
            "--scope",
            scope,
        ]
    )
    return code, json.loads(capsys.readouterr().out)


def encoder_return(root: Path) -> FileRef:
    """Static synthetic file inventory; deliberately not a loadable neural model."""
    declare_encoder_runtime()
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
    root = tmp_path / "producer"
    ref = encoder_return(root)
    # The CLI in a fresh interpreter, with the same declared runtime as this process.
    entry = (
        "import sys; sys.path.append(sys.argv.pop(1)); "
        "from career_lab.models.v3.registry_cli import main; raise SystemExit(main())"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            entry,
            str(DECLARED_RUNTIME),
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


@pytest.mark.parametrize("missing", ENCODER_RUNTIME)
def test_rt_03_registration_without_the_encoder_runtime_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, missing: str
) -> None:
    root = tmp_path / "producer"
    ref = encoder_return(root)
    without_runtime(monkeypatch, {missing})
    code, result = register_cli(tmp_path / "registry", root, ref, "synthetic_fixture", capsys)
    assert code == 2
    assert result["error"] == "encoder_runtime_unavailable"
    assert not list((tmp_path / "registry").glob("encoder-*"))


@pytest.mark.parametrize("changed", ENCODER_RUNTIME)
def test_rt_02_a_changed_encoder_runtime_version_refuses_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, changed: str
) -> None:
    root = tmp_path / "producer"
    ref = encoder_return(root)
    registry = tmp_path / "registry"
    code, result = register_cli(registry, root, ref, "synthetic_fixture", capsys)
    assert code == 0, result
    registration = FileRef.model_validate(result["registration"])
    entry = json.loads((registry / registration.path).read_bytes())
    assert entry["protocol"] == "advisory-encoder-registration-v2"
    assert {k: v.split("+")[0] for k, v in entry["encoder_runtime"].items()} == LOCKED_RUNTIME
    monkeypatch.syspath_prepend(str(runtime_upgrade(tmp_path / "upgraded", changed)))
    for read in (load_registration, describe_registration):
        with pytest.raises(ProtocolError) as error:
            read(registry, registration)
        assert error.value.code == "registered_inference_runtime_changed"
    item = tmp_path / "input.json"
    item.write_text(examples("dev")[0].item.model_dump_json())
    code = registry_cli.main(
        [
            "predict",
            "--registry",
            str(registry),
            "--registration-path",
            registration.path,
            "--registration-hash",
            registration.sha256,
            "--journal",
            str(tmp_path / "journal"),
            "--request-id",
            "after-upgrade",
            "--input",
            str(item),
            "--language",
            "en",
            "--allow-synthetic",
        ]
    )
    assert code == 2
    assert json.loads(capsys.readouterr().out)["error"] == "registered_inference_runtime_changed"
    assert not (tmp_path / "journal").exists()


def test_rt_04_a_v1_registration_no_longer_serves_new_advice(tmp_path: Path, capsys) -> None:
    root = tmp_path / "producer"
    ref = encoder_return(root)
    registry = tmp_path / "registry"
    retired = v1_registration(registry, root, ref, "synthetic_fixture")
    for read in (load_registration, describe_registration):
        with pytest.raises(ProtocolError) as error:
            read(registry, retired)
        assert error.value.code == "encoder_registration_retired"
    item = tmp_path / "input.json"
    item.write_text(examples("dev")[0].item.model_dump_json())
    code = registry_cli.main(
        [
            "predict",
            "--registry",
            str(registry),
            "--registration-path",
            retired.path,
            "--registration-hash",
            retired.sha256,
            "--journal",
            str(tmp_path / "journal"),
            "--request-id",
            "retired",
            "--input",
            str(item),
            "--language",
            "en",
            "--allow-synthetic",
        ]
    )
    assert code == 2
    assert json.loads(capsys.readouterr().out)["error"] == "encoder_registration_retired"
    assert not (tmp_path / "journal").exists()
    # Re-registering the same return under the current protocol is the way forward.
    current = register_bundle(registry, root, ref, scope="synthetic_fixture")
    assert current != retired
    assert describe_registration(registry, current).weights_stage == "supervised_finetuned"


@pytest.mark.parametrize("language", ["zh", "en"])
def test_rt_04_feedback_recorded_before_stays_readable_and_v1_adds_no_advice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    root = tmp_path / "producer"
    ref = encoder_return(root)
    registry = tmp_path / "registry"
    current = register_bundle(registry, root, ref, scope="synthetic_fixture")
    configure(monkeypatch, tmp_path, registry, current)
    with runtime_app(tmp_path) as (app, client):
        session = open_session(app, client, language)
        work = session.work()
        earlier, recorded = review(session, "review-before", work)
    journal = sorted((tmp_path / "journal").rglob("*"))
    retired = v1_registration(registry, root, ref, "synthetic_fixture")
    configure(monkeypatch, tmp_path, registry, retired)
    with runtime_app(tmp_path) as (app, client):
        reopened = PublishedSession(app, client, session.session_id, session.headers, language)
        assert reopened.get(earlier).json() == recorded
        _, later = review(reopened, "review-after", work)
    advice = later["result"]["result"]["items"][0]["model_advice"][0]
    assert advice["status"] == "failed" and advice["registration"] is None
    assert advice["label"] is None and advice["evidence_ids"] == advice["citations"] == []
    assert sorted((tmp_path / "journal").rglob("*")) == journal


def deny_encoder_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    """torch and transformers cannot be imported, whatever metadata says."""
    import builtins

    real = builtins.__import__

    def without_encoder(name: str, *args: Any, **kwargs: Any) -> Any:
        if name in {"torch", "transformers"}:
            raise ImportError("controlled missing optional dependency")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_encoder)


@pytest.mark.parametrize("language", ["zh", "en"])
def test_enc_07_normal_feedback_names_kind_dataset_and_weights_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    root = tmp_path / "producer"
    encoder_return(root)
    manifest = json.loads((root / "checkpoint-manifest.json").read_bytes())
    manifest["label_tiers"] = ["G0"]
    ref = write_manifest(root, manifest)
    registry = tmp_path / "registry"
    registration = register_bundle(registry, root, ref, scope="synthetic_fixture")
    expected = {
        "id": registration.path.split("/")[0],
        "model_revision": manifest["model_revision"],
        "scope": "synthetic_fixture",
        "quality_validated": False,
        "kind": "huggingface_encoder",
        "dataset": {
            "dataset_id": "rolecraft-fixture-20261007-v2",
            "dataset_manifest_sha256": "f" * 64,
            "label_tiers": ["G0"],
        },
        "weights_stage": "supervised_finetuned",
    }
    assert json.loads(json.dumps(describe_registration(registry, registration).identity())) == (
        expected
    )
    configure(monkeypatch, tmp_path, registry, registration)
    deny_encoder_imports(monkeypatch)
    with runtime_app(tmp_path) as (app, client):
        session = open_session(app, client, language)
        _, feedback = review(session, "review-identity", session.work())
    report = feedback["result"]["result"]["items"][0]
    advice = report["model_advice"][0]
    assert advice["registration"] == expected
    assert report["provenance"]["registered_model"] == expected
    assert advice["status"] == "failed" and advice["label"] is None
    assert advice["error_code"] == "pretrained_encoder_dependencies_unavailable"
    assert advice["affects_score"] is False and advice["mode"] == "advisory"
