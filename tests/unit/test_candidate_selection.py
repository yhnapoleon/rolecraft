import hashlib
import json

import pytest

from career_lab.registry.models import register_candidate, select_deployment, verify_record


def test_registry_checks_identity_and_artifact_drift(tmp_path):
    artifact = tmp_path / "model.bin"
    artifact.write_bytes(b"example-artifact")
    manifest = tmp_path / "model.json"
    manifest.write_text(json.dumps({"file": "model.bin", "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(), "revision": "model-v1", "dataset_hash": "d", "name": "linear"}))
    run = tmp_path / "run"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"dataset_hash": "d", "grader": "v1", "config": {"candidate": "model-v1", "split": "dev", "prompt_version": "v1"}}))
    (run / "metrics.json").write_text(json.dumps({"overall": {"accuracy": .8, "macro_f1": .8, "false_deduction": .1, "joint_correctness": .7}}))
    record = register_candidate(manifest, run / "manifest.json", rubric_hash="rubric-1")
    assert record["evaluation_scope"] == "dev"
    with pytest.raises(ValueError, match="deployment"):
        select_deployment([record], record["id"], "highest dev score")
    artifact.write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash"):
        verify_record(record, "rubric-1")


def test_wrong_dataset_or_rubric_not_verified(tmp_path):
    with pytest.raises(ValueError, match="rubric"):
        verify_record({"rubric_hash": "old"}, "new")
