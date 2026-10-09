"""RET-01..06 through the formal CLI; synthetic inputs prove mechanisms only."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from career_lab.contracts import v2 as C


def test_verify_return_cli_help_names_input_boundaries() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "career_lab.models.v3.registry_cli", "verify-return", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--dataset-root" in result.stdout
    assert "--predictions" in result.stdout


@pytest.fixture
def return_case(tmp_path: Path) -> tuple[Path, str, Path]:
    from tests.unit.test_w08_models import examples

    rows = examples("dev", 1)
    inputs, labels, annotations, metadata, predictions = [], [], [], [], []
    for row in rows:
        item = row.item.model_dump(mode="json")
        gold = row.annotation.final
        inputs.append(
            {"record_id": row.record_id, "input_hash": C.digest(item), "model_input": item}
        )
        label = gold.model_dump(mode="json", exclude={"schema_version"})
        label.update(
            record_id=row.record_id,
            input_hash=C.digest(item),
            label_tier="G0",
            label_index=["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"].index(gold.label),
            verifier_id=row.annotation.verifier_id,
        )
        labels.append(label)
        annotations.append(row.annotation.model_dump(mode="json"))
        metadata.append(
            {
                "record_id": row.record_id,
                "input_hash": C.digest(item),
                "language": "en",
                "split": "dev",
                "bucket": "fixture",
                "lineage": {"structure_id": row.structure_id, "component_id": row.component_id},
            }
        )
        predictions.append(
            {
                "return_schema_version": 2,
                "record_id": row.record_id,
                "input_hash": C.digest(item),
                "model_revision": "format-example",
                "task_type": "relation",
                "status": "ok",
                "probabilities": [float(i == label["label_index"]) for i in range(3)],
                "label": gold.label,
                "evidence_ids": list(gold.evidence_ids),
                "evidence_bindings": [
                    {"candidate_id": c.id, "candidate_sha256": C.digest(c)}
                    for c in row.item.evidence.candidate_evidence
                    if c.id in gold.evidence_ids
                ],
                "reason": "Synthetic format example",
            }
        )
    files = {}
    for name, values in {
        "data/dev.inputs.jsonl": inputs,
        "data/dev.labels.jsonl": labels,
        "audit/original-annotations.jsonl": annotations,
        "audit/metadata.jsonl": metadata,
    }.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in values))
        files[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {
        "schema_version": 1,
        "dataset_id": "synthetic-return",
        "status": "FIXTURE_ONLY_NOT_FINAL_TRAINING_DATA",
        "task_type": "relation",
        "label_order": ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"],
        "splits": {"dev": {"records": 3, "language": {"en": 3, "zh": 0}}},
        "files": files,
    }
    path = tmp_path / "dataset-manifest.json"
    path.write_text(json.dumps(manifest))
    output = tmp_path / "predictions.jsonl"
    output.write_text("".join(json.dumps(row) + "\n" for row in predictions))
    return tmp_path, hashlib.sha256(path.read_bytes()).hexdigest(), output


def invoke(
    case: tuple[Path, str, Path], capsys: pytest.CaptureFixture[str], *extra: str
) -> tuple[int, dict]:
    from career_lab.models.v3.registry_cli import main

    root, checksum, predictions = case
    code = main(
        [
            "verify-return",
            "--dataset-root",
            str(root),
            "--dataset-hash",
            checksum,
            "--predictions",
            str(predictions),
            *extra,
        ]
    )
    return code, json.loads(capsys.readouterr().out)


def test_ret_04_reports_each_language_without_promoting_fixture(return_case, capsys) -> None:
    code, result = invoke(return_case, capsys)
    assert code == 0
    assert result["languages"]["en"]["metrics"]["count"] == 3
    assert result["languages"]["en"]["metrics"]["macro_f1"] == 1
    assert result["languages"]["zh"]["status"] == "blocked_missing_language"
    assert result["reload"]["status"] == "blocked_missing_registration"
    assert result["quality_validated"] is False
    assert result["training"]["status"] == "not_verified"
    assert result["status"] == "partial"


def test_ret_05_reloads_registered_artifact_and_rejects_unrelated_predictions(
    return_case,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "unit"))
    from test_w08_registration import registered

    (tmp_path / "model").mkdir()
    _, _, ref = registered(tmp_path / "model")
    code, result = invoke(
        return_case,
        capsys,
        "--registry",
        str(tmp_path / "model/registry"),
        "--registration-path",
        ref.path,
        "--registration-hash",
        ref.sha256,
    )
    assert code == 2
    assert result["reload"]["status"] == "producer_mismatch"
    assert len(result["reload"]["mismatched_record_ids"]) == 3
    assert result["reload"]["reload_predictions_identical"] is True
    assert result["training"]["status"] == "mechanism_only"


@pytest.mark.parametrize(
    "change",
    [
        {"test_used_for_selection": True},
        {"selection_partition": "test"},
        {"training_partitions": ["train", "test"]},
    ],
)
def test_ret_03_rejects_test_selection_even_without_checkpoint_loading(
    return_case, capsys, change
) -> None:
    root, checksum, _ = return_case
    manifest = {
        "template": False,
        "completed": True,
        "return_protocol": "rolecraft-label-evidence-v2",
        "task_type": "relation",
        "label_order": ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"],
        "dataset_id": "synthetic-return",
        "dataset_manifest_sha256": checksum,
        "model_revision": "format-example",
        "framework": "synthetic",
        "framework_version": "1",
        "evidence_selection_implemented": True,
        "evidence_selection_required": True,
        "training_partitions": ["train"],
        "selection_partition": "dev",
        "test_used_for_selection": False,
        "load_and_predict_command": "metadata only, never execute",
        "training_notes_file": "notes.md",
        "predictions_file": "predictions.jsonl",
        "checkpoint_files": {},
    } | change
    path = root / "checkpoint-manifest.json"
    path.write_text(json.dumps(manifest))
    code, result = invoke(return_case, capsys, "--checkpoint-manifest", str(path))
    assert code == 2
    assert result["error"] == "model_return_selection_contaminated"


@pytest.mark.parametrize(
    "change",
    [
        {"probabilities": [1.000004, 0.0, 0.0], "label": "SUPPORTED"},
        {"return_schema_version": 2.0},
        {"evidence_bindings": [{"candidate_id": "e1", "candidate_sha256": "0" * 64}]},
    ],
)
def test_ret_05_invalid_output_is_rejected_and_counted_by_language(
    return_case, capsys, change
) -> None:
    _, _, path = return_case
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0].update(change)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    code, result = invoke(return_case, capsys)
    assert code == 2
    assert result["status"] == "rejected"
    assert result["languages"]["en"]["metrics"]["format_failures"] == 1
    assert result["languages"]["en"]["metrics"]["count"] == 3
    assert result["languages"]["en"]["metrics"]["coverage"] == pytest.approx(2 / 3)
    assert result["format_errors"][0]["record_id"] == rows[0]["record_id"]


def reseal_dataset(root: Path) -> str:
    path = root / "dataset-manifest.json"
    manifest = json.loads(path.read_text())
    for name, entry in manifest["files"].items():
        entry["sha256"] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_ret_02_all_candidates_are_not_joint_correct_and_label_only_is_excluded(
    return_case, capsys
) -> None:
    root, _, prediction_path = return_case
    for name, nested in (
        ("data/dev.labels.jsonl", False),
        ("audit/original-annotations.jsonl", True),
    ):
        path = root / name
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        target = rows[0]["final"] if nested else rows[0]
        target.update(
            evidence_evaluable=False,
            acceptable_evidence_sets=[],
            evidence_ids=[],
            missing_reason="Synthetic label-only check",
        )
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    checksum = reseal_dataset(root)
    inputs = [
        json.loads(line) for line in (root / "data/dev.inputs.jsonl").read_text().splitlines()
    ]
    predictions = [json.loads(line) for line in prediction_path.read_text().splitlines()]
    for prediction, row in zip(predictions, inputs, strict=True):
        candidates = row["model_input"]["evidence"]["candidate_evidence"]
        prediction["evidence_ids"] = [c["id"] for c in candidates]
        prediction["evidence_bindings"] = [
            {"candidate_id": c["id"], "candidate_sha256": C.digest(c)} for c in candidates
        ]
    prediction_path.write_text("".join(json.dumps(row) + "\n" for row in predictions))
    code, result = invoke((root, checksum, prediction_path), capsys)
    assert code == 0
    metrics = result["languages"]["en"]["metrics"]
    assert metrics["macro_f1"] == 1
    assert metrics["joint_denominator"] == metrics["evidence_denominator"] == 2
    assert metrics["joint_correctness"] == 0
    assert metrics["mean_evidence_f1"] == pytest.approx(1 / 3)


def test_ret_01_uncompleted_checkpoint_does_not_claim_training(return_case, capsys) -> None:
    root, _, _ = return_case
    path = root / "incomplete.json"
    path.write_text(
        json.dumps(
            {
                "template": True,
                "completed": False,
                "return_protocol": "rolecraft-label-evidence-v2",
                "task_type": "relation",
                "label_order": ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"],
            }
        )
    )
    code, result = invoke(return_case, capsys, "--checkpoint-manifest", str(path))
    assert code == 0 and result["status"] == "partial"
    assert result["checkpoint"]["candidate_eligible"] is False
    assert result["checkpoint"]["missing"] == ["model_return_incomplete"]
    assert result["training"] == {"status": "not_verified", "performed_by_verifier": False}


def test_ret_06_mechanical_reload_matches_without_claiming_real_training(
    return_case,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "unit"))
    from test_w08_registration import registered

    from career_lab.models.v3.registry import load_registration

    model_root = tmp_path / "model"
    model_root.mkdir()
    _, _, ref = registered(model_root)
    model, _ = load_registration(model_root / "registry", ref)
    root, _, path = return_case
    output = []
    for row in [
        json.loads(line) for line in (root / "data/dev.inputs.jsonl").read_text().splitlines()
    ]:
        item = C.RelationInput.model_validate(row["model_input"])
        prediction = model.predict(item)
        output.append(
            {
                "return_schema_version": 2,
                "record_id": row["record_id"],
                "input_hash": row["input_hash"],
                "model_revision": prediction.model_revision,
                "task_type": "relation",
                "status": prediction.status,
                "probabilities": prediction.probabilities,
                "label": prediction.label,
                "evidence_ids": prediction.evidence_ids,
                "evidence_bindings": [
                    {"candidate_id": c.id, "candidate_sha256": C.digest(c)}
                    for c in item.evidence.candidate_evidence
                    if c.id in prediction.evidence_ids
                ],
                "reason": prediction.reason_code,
            }
        )
    path.write_text("".join(json.dumps(row) + "\n" for row in output))
    original = path.read_bytes()
    args = (
        "--registry",
        str(model_root / "registry"),
        "--registration-path",
        ref.path,
        "--registration-hash",
        ref.sha256,
    )
    code, result = invoke(return_case, capsys, *args)
    assert code == 0
    assert result["reload"]["status"] == "matched"
    assert result["reload"]["reload_predictions_identical"] is True
    assert result["training"]["status"] == "mechanism_only"
    assert result["quality_validated"] is False
    assert result["languages"]["en"]["metrics"]["macro_f1"] == pytest.approx(1 / 6)
    assert result["languages"]["en"]["metrics"]["joint_correctness"] == 0
    assert path.read_bytes() == original
    entry = json.loads((model_root / "registry" / ref.path).read_text())
    artifact = model_root / "registry" / ref.path.rsplit("/", 1)[0] / "artifact"
    target = next(name for name in entry["files"] if name.endswith(".npz"))
    (artifact / target).write_bytes(b"changed after registration")
    code, result = invoke(return_case, capsys, *args)
    assert code == 2 and result["error"] == "file_hash_mismatch"
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "change", [[], {"files": []}, {"splits": {"dev": {"records": 3, "language": []}}}]
)
def test_return_dataset_shapes_have_stable_cli_errors(return_case, capsys, change) -> None:
    root, _, predictions = return_case
    path = root / "dataset-manifest.json"
    old = json.loads(path.read_text())
    value = old | change if isinstance(change, dict) else change
    path.write_text(json.dumps(value))
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    code, result = invoke((root, checksum, predictions), capsys)
    assert code == 2 and result["error"] == "return_dataset_protocol_invalid"


def test_return_duplicate_json_identity_is_rejected(return_case, capsys) -> None:
    _, _, path = return_case
    lines = path.read_text().splitlines()
    lines[0] = '{"input_hash":"' + "0" * 64 + '",' + lines[0][1:]
    path.write_text("\n".join(lines) + "\n")
    code, result = invoke(return_case, capsys)
    assert code == 2 and result["error"] == "return_duplicate_json_key"


def test_ret_06_arbitrary_file_declaration_is_not_checkpoint_eligibility(
    return_case, capsys
) -> None:
    root, checksum, _ = return_case
    (root / "README.md").write_text("This is not a model")
    manifest = {
        "template": False,
        "completed": True,
        "return_protocol": "rolecraft-label-evidence-v2",
        "task_type": "relation",
        "label_order": ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"],
        "dataset_id": "synthetic-return",
        "dataset_manifest_sha256": checksum,
        "model_revision": "format-example",
        "framework": "synthetic",
        "framework_version": "1",
        "evidence_selection_implemented": True,
        "evidence_selection_required": True,
        "training_partitions": ["train"],
        "selection_partition": "dev",
        "test_used_for_selection": False,
        "load_and_predict_command": "must never execute",
        "training_notes_file": "missing-notes.md",
        "predictions_file": "missing-predictions.jsonl",
        "checkpoint_files": {
            "README.md": hashlib.sha256((root / "README.md").read_bytes()).hexdigest()
        },
    }
    path = root / "checkpoint-manifest.json"
    path.write_text(json.dumps(manifest))
    code, result = invoke(return_case, capsys, "--checkpoint-manifest", str(path))
    assert code == 0
    assert result["checkpoint"]["candidate_eligible"] is False
    assert set(result["checkpoint"]["missing"]) >= {
        "training_notes_file",
        "predictions_file",
        "supported_checkpoint_validation",
    }


def test_ret_04_chinese_fixture_is_reported_separately(return_case, capsys) -> None:
    root, _, predictions = return_case
    path = root / "audit/metadata.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        row["language"] = "zh"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    path = root / "dataset-manifest.json"
    manifest = json.loads(path.read_text())
    manifest["splits"]["dev"]["language"] = {"zh": 3, "en": 0}
    path.write_text(json.dumps(manifest))
    code, result = invoke((root, reseal_dataset(root), predictions), capsys)
    assert code == 0
    assert result["languages"]["zh"]["metrics"]["count"] == 3
    assert result["languages"]["en"]["status"] == "blocked_missing_language"
    assert result["scope"] == "synthetic_fixture"
    assert result["quality_validated"] is False
