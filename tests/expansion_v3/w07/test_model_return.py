"""Fixture-v2 return envelopes; no model loading or quality assertion."""

import json
from pathlib import Path

import pytest
from test_handoff import cli, jsonl, package, seal_package, write_jsonl

from career_lab.contracts.v2.core import digest
from career_lab.datasets.v3.common import json_bytes, sha


def model_return(tmp_path: Path, language: str, family: str = "relation") -> tuple[Path, Path]:
    root = package(tmp_path, language, (("return", family),))
    for suffix in ("inputs", "labels"):
        (root / f"data/train.{suffix}.jsonl").rename(root / f"data/dev.{suffix}.jsonl")
    metadata = jsonl(root / "audit/metadata.jsonl")
    metadata[0]["split"] = "dev"
    write_jsonl(root / "audit/metadata.jsonl", metadata)
    # Seal using the test helper, then explicitly describe the dev-only review sample.
    for suffix in ("inputs", "labels"):
        (root / f"data/train.{suffix}.jsonl").write_bytes(
            (root / f"data/dev.{suffix}.jsonl").read_bytes()
        )
    seal_package(root)
    manifest = json.loads((root / "dataset-manifest.json").read_bytes())
    manifest["splits"] = {"dev": manifest["splits"]["train"]}
    card = {"protocol": "dataset-card-v1", "splits": manifest["splits"]}
    (root / "data_card.md").write_text("# Mechanism only\n```json\n" + json.dumps(card) + "\n```\n")
    for suffix in ("inputs", "labels"):
        name = f"data/train.{suffix}.jsonl"
        (root / name).unlink()
        del manifest["files"][name]
    manifest["files"]["data_card.md"] = {
        "sha256": sha((root / "data_card.md").read_bytes()),
        "size": (root / "data_card.md").stat().st_size,
    }
    (root / "dataset-manifest.json").write_bytes(json_bytes(manifest))
    out = tmp_path / "model-return"
    out.mkdir()
    files = {
        "weights.bin": b"synthetic checkpoint bytes",
        "settings.json": b"{}",
        "vocabulary.txt": b"synthetic tokenizer",
    }
    for name, raw in files.items():
        (out / name).write_bytes(raw)
    (out / "notes.md").write_text("Fixture bytes only; no training occurred.")
    row = jsonl(root / "data/dev.inputs.jsonl")[0]
    candidate = row["model_input"]["evidence"]["candidate_evidence"][0]
    prediction = {
        "return_schema_version": 2,
        "record_id": row["record_id"],
        "input_hash": row["input_hash"],
        "model_revision": "synthetic-return-v1",
        "task_type": "relation",
        "status": "ok",
        "probabilities": [0.8, 0.1, 0.1],
        "label": "SUPPORTED",
        "evidence_ids": [candidate["id"]],
        "evidence_bindings": [
            {"candidate_id": candidate["id"], "candidate_sha256": digest(candidate)}
        ],
    }
    write_jsonl(out / "predictions.jsonl", [prediction])
    checkpoint = {
        "template": False,
        "completed": True,
        "model_revision": "synthetic-return-v1",
        "framework": "synthetic",
        "framework_version": "1",
        "task_type": "relation",
        "label_order": ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"],
        "dataset_id": manifest["dataset_id"],
        "dataset_manifest_sha256": sha((root / "dataset-manifest.json").read_bytes()),
        "training_partitions": ["train"],
        "selection_partition": "dev",
        "test_used_for_selection": False,
        "evidence_selection_implemented": True,
        "evidence_selection_required": True,
        "checkpoint_files": {name: sha(raw) for name, raw in files.items()},
        "load_and_predict_command": "not-executed-fixture-command",
        "training_notes_file": "notes.md",
        "predictions_file": "predictions.jsonl",
        "return_protocol": "rolecraft-label-evidence-v2",
        "artifact_roles": {
            "checkpoint": ["weights.bin"],
            "config": ["settings.json"],
            "tokenizer": ["vocabulary.txt"],
        },
    }
    path = out / "checkpoint-manifest.json"
    path.write_bytes(json_bytes(checkpoint))
    return root, path


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize(
    "fault",
    [
        None,
        "checkpoint",
        "config",
        "tokenizer",
        "order",
        "input",
        "candidate",
        "coverage",
        "revision",
        "template",
    ],
)
def test_data_01_model_return_identity(tmp_path: Path, language: str, fault: str | None) -> None:
    root, checkpoint = model_return(tmp_path, language)
    if fault in {"checkpoint", "config", "tokenizer"}:
        manifest = json.loads(checkpoint.read_bytes())
        path = checkpoint.parent / manifest["artifact_roles"][fault][0]
        path.write_bytes(b"drift")
    elif fault in {"order", "template"}:
        manifest = json.loads(checkpoint.read_bytes())
        if fault == "order":
            manifest["label_order"].reverse()
        else:
            manifest["template"] = True
        checkpoint.write_bytes(json_bytes(manifest))
    elif fault is not None:
        path = checkpoint.parent / "predictions.jsonl"
        predictions = jsonl(path)
        if fault == "input":
            predictions[0]["input_hash"] = "0" * 64
        elif fault == "candidate":
            predictions[0]["evidence_bindings"][0]["candidate_sha256"] = "0" * 64
        elif fault == "coverage":
            predictions = []
        else:
            predictions[0]["model_revision"] = "other"
        write_jsonl(path, predictions)
    response = cli(
        "validate-handoff",
        "--package",
        root,
        "--checkpoint-manifest",
        checkpoint,
        "--output",
        tmp_path / "review",
    )
    assert response.stdout.strip(), response.stderr
    report = json.loads(response.stdout)
    if fault:
        assert response.returncode == 2, report
    else:
        assert response.returncode == 0, report
        assert report["model_return"]["format_valid"] is True
        assert report["model_return"]["model_loaded"] is False
        assert report["model_return"]["quality_verified"] is False
        assert report["training_ready"] is False


@pytest.mark.parametrize("fault", ["duplicate", "nonfinite", "boolean-claim"])
def test_model_return_rejects_ambiguous_json_and_nonboolean_claims(
    tmp_path: Path, fault: str
) -> None:
    root, checkpoint = model_return(tmp_path, "en")
    if fault == "boolean-claim":
        raw = json.loads(checkpoint.read_bytes())
        raw["completed"] = 1
        checkpoint.write_bytes(json_bytes(raw))
    else:
        path = checkpoint.parent / "predictions.jsonl"
        raw = path.read_text()
        if fault == "duplicate":
            raw = raw.replace('"label":"SUPPORTED"', '"label":"CONTRADICTED","label":"SUPPORTED"')
        else:
            raw = raw.replace('"probabilities":[0.8,0.1,0.1]', '"probabilities":[NaN,0.1,0.1]')
        path.write_text(raw)
    response = cli(
        "validate-handoff",
        "--package",
        root,
        "--checkpoint-manifest",
        checkpoint,
        "--output",
        tmp_path / "review",
    )
    assert response.returncode == 2, response.stdout
    assert response.stdout.strip()


def test_data_01_model_return_cannot_cross_task_namespace(tmp_path: Path) -> None:
    root, checkpoint = model_return(tmp_path, "en", "criterion")
    response = cli(
        "validate-handoff",
        "--package",
        root,
        "--checkpoint-manifest",
        checkpoint,
        "--output",
        tmp_path / "review",
    )
    assert response.returncode == 2, response.stdout
    result = json.loads(response.stdout)["model_return"]["records"][0]
    assert result["status"] == "quarantine"
    assert "handoff_prediction_task_mismatch" in result["reasons"]


def test_data_01_input_bytes_cannot_keep_a_stale_hash_after_default_injection(
    tmp_path: Path,
) -> None:
    root, checkpoint = model_return(tmp_path, "en")
    path = root / "data/dev.inputs.jsonl"
    rows = jsonl(path)
    rows[0]["model_input"]["evidence"]["candidate_evidence"][0].pop("schema_version")
    write_jsonl(path, rows)
    manifest_path = root / "dataset-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"]["data/dev.inputs.jsonl"] = {
        "sha256": sha(path.read_bytes()),
        "size": path.stat().st_size,
    }
    manifest_path.write_bytes(json_bytes(manifest))
    model = json.loads(checkpoint.read_bytes())
    model["dataset_manifest_sha256"] = sha(manifest_path.read_bytes())
    checkpoint.write_bytes(json_bytes(model))
    response = cli(
        "validate-handoff",
        "--package",
        root,
        "--checkpoint-manifest",
        checkpoint,
        "--output",
        tmp_path / "review",
    )
    assert response.returncode == 2, response.stdout
