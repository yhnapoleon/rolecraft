"""RET-01..06 through the formal CLI; synthetic inputs prove mechanisms only."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from career_lab.contracts import v2 as C
from career_lab.models.v3.bundle import json_bytes, save_bundle, sha
from career_lab.models.v3.encoder import AttentionEncoder
from career_lab.models.v3.ensemble import select_alpha
from career_lab.models.v3.fusion_bundle import save_fusion_bundle
from career_lab.models.v3.linear import LinearCandidate
from career_lab.models.v3.registration import RegistrationSummary
from career_lab.models.v3.registry import load_registration, register_bundle
from career_lab.models.v3.return_data import load_return_dataset
from career_lab.models.v3.return_verification import inspect_return_checkpoint
from tests.unit.test_w08_encoder_registration import (
    deny_encoder_imports,
    encoder_return,
    write_manifest,
)
from tests.unit.test_w08_models import examples


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


@pytest.mark.parametrize(
    "case", ["manifest_test", "test_flag", "metadata_test", "unknown_partition"]
)
def test_ret_03_rejects_shared_held_out_audit_before_reading_labels(
    return_case,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    root, _, predictions = return_case
    path = root / "dataset-manifest.json"
    manifest = json.loads(path.read_text())
    if case == "manifest_test":
        manifest["splits"]["test"] = {"records": 1, "language": {"en": 1}}
    elif case == "test_flag":
        manifest["test_included"] = True
    else:
        metadata = root / "audit/metadata.jsonl"
        rows = [json.loads(line) for line in metadata.read_text().splitlines()]
        rows[0]["split"] = "test" if case == "metadata_test" else "unknown"
        metadata.write_text("".join(json.dumps(row) + "\n" for row in rows))
    path.write_text(json.dumps(manifest))
    checksum = reseal_dataset(root)
    opened = []
    original = Path.read_bytes

    def recording_read(target: Path) -> bytes:
        opened.append(target.resolve())
        return original(target)

    monkeypatch.setattr(Path, "read_bytes", recording_read)
    code, result = invoke((root, checksum, predictions), capsys)
    assert code == 2
    assert result["error"] in {
        "return_held_out_bundle_forbidden",
        "return_shared_annotation_partition_forbidden",
    }
    assert (root / "audit/original-annotations.jsonl").resolve() not in opened


def rewrite_predictions(path: Path, change) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    change(rows)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return rows


def test_pred_01_v3_relation_rows_parse_like_v2_rows_in_one_file(return_case, capsys) -> None:
    _, _, path = return_case
    code, baseline = invoke(return_case, capsys)
    assert code == 0

    def mixed(rows: list[dict]) -> None:
        for row in rows[::2]:
            row["return_schema_version"] = 3

    rows = rewrite_predictions(path, mixed)
    assert {row["return_schema_version"] for row in rows} == {2, 3}
    code, result = invoke(return_case, capsys)
    assert code == 0, result
    assert result["format_errors"] == []
    assert result["graded_records"] == baseline["graded_records"]
    assert result["languages"] == baseline["languages"]
    assert result["task_type"] == "relation"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (
            lambda row: row.update(return_schema_version=3, task_type="criterion"),
            "return_task_type_unsupported",
        ),
        (
            lambda row: row.update(return_schema_version=3, task_type="judge"),
            "return_task_type_unsupported",
        ),
        (lambda row: row.pop("return_schema_version"), "return_schema_version_required"),
        (lambda row: row.update(return_schema_version=4), "return_schema_version_unsupported"),
        (lambda row: row.update(return_schema_version=3.0), "return_schema_version_unsupported"),
    ],
    ids=["criterion", "unknown-task", "missing-version", "version-4", "float-version"],
)
def test_pred_01_unknown_task_or_missing_version_is_rejected_per_record(
    return_case, capsys, change, code
) -> None:
    _, _, path = return_case
    rows = rewrite_predictions(path, lambda rows: change(rows[0]))
    status, result = invoke(return_case, capsys)
    assert status == 2
    assert result["status"] == "rejected"
    assert result["format_errors"] == [{"record_id": rows[0]["record_id"], "error_code": code}]
    assert result["languages"]["en"]["metrics"]["format_failures"] == 1


# Fixed-weight registrations: constructed, never fitted; scope is always synthetic_fixture.
LINEAR_VOCABULARY = {": 2": 0, ": 1": 1, "bud": 2, "unr": 3, "ver": 4, "n": 5}


def linear_bundle(root: Path, coef, intercept, evidence_coef) -> tuple[Path, C.FileRef]:
    config = {
        "preprocessing_revision": "historical-time-v1",
        "kind": "linear",
        "task_type": "relation",
        "seed": 5002,
        "max_features": len(LINEAR_VOCABULARY),
        "vocabulary": LINEAR_VOCABULARY,
        "evidence_threshold": 0.5,
        "labels": ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"],
        "training_report": {"scope": "synthetic_fixed_weights", "fit_performed": False},
    }
    arrays = {
        "coef": np.array(coef, dtype=float),
        "intercept": np.array(intercept, dtype=float),
        "evidence_coef": np.array(evidence_coef, dtype=float),
        "evidence_intercept": np.array([-0.2]),
        "idf": np.ones(len(LINEAR_VOCABULARY)),
    }
    model = LinearCandidate.restore(config, arrays)
    data = root / "source"
    data.mkdir(parents=True, exist_ok=True)
    release = json_bytes({"fixture": True, "scope": "synthetic_fixed_weights_no_training"})
    split = json_bytes({"fixture": True, "scope": "synthetic_no_held_out_data"})
    (data / "release.json").write_bytes(release)
    (data / "split.json").write_bytes(split)
    ref = save_bundle(
        model,
        root / "bundle",
        source_root=data,
        training_release=C.FileRef(path="release.json", sha256=sha(release)),
        split_manifest=C.FileRef(path="split.json", sha256=sha(split)),
        source=C.SourceIdentity(base_commit="a" * 40, source_digest=C.digest("synthetic-no-fit")),
    )
    return root / "bundle", ref


# Columns follow LINEAR_VOCABULARY: rows are SUPPORTED, CONTRADICTED, INSUFFICIENT.
LEFT_WEIGHTS = (
    [
        [3.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 3.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 3.0, 0.0, 0.0, 0.0],
    ],
    [0.0, 0.0, 0.0],
    [4.0, 4.0, -4.0, -4.0, 0.0, 0.0],
)
RIGHT_WEIGHTS = (
    [
        [2.0, 1.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
    ],
    [0.0, 0.0, 0.5],
    [2.0, 0.0, -2.0, -3.0, 0.0, 0.0],
)


def register(registry: Path, root: Path, ref: C.FileRef) -> C.FileRef:
    return register_bundle(registry, root, ref, scope="synthetic_fixture")


def linear_registration(tmp_path: Path) -> tuple[Path, C.FileRef]:
    root, ref = linear_bundle(tmp_path / "linear", *RIGHT_WEIGHTS)
    return tmp_path / "registry", register(tmp_path / "registry", root, ref)


def attention_registration(tmp_path: Path) -> tuple[Path, C.FileRef]:
    model = AttentionEncoder(variant="pack", dimension=4)
    model.initialize(examples("train", 1))
    model.revision = "synthetic-seeded-attention-no-fit"
    model.training_report = {"scope": "synthetic_seeded_weights", "fit_performed": False}
    data = tmp_path / "attention-source"
    data.mkdir(parents=True)
    release = json_bytes({"fixture": True, "scope": "synthetic_seeded_weights_no_training"})
    (data / "release.json").write_bytes(release)
    ref = save_bundle(
        model,
        tmp_path / "attention",
        source_root=data,
        training_release=C.FileRef(path="release.json", sha256=sha(release)),
        split_manifest=C.FileRef(path="release.json", sha256=sha(release)),
        source=C.SourceIdentity(base_commit="a" * 40, source_digest=C.digest("synthetic-no-fit")),
    )
    return tmp_path / "registry", register(tmp_path / "registry", tmp_path / "attention", ref)


def model_predictions(registry: Path, ref: C.FileRef, inputs_path: Path) -> list[dict]:
    model, _ = load_registration(registry, ref)
    output = []
    for row in [json.loads(line) for line in inputs_path.read_text().splitlines()]:
        item = C.RelationInput.model_validate(row["model_input"])
        prediction = model.predict(item)
        output.append(
            {
                "return_schema_version": 3,
                "record_id": row["record_id"],
                "input_hash": row["input_hash"],
                "model_revision": prediction.model_revision,
                "task_type": "relation",
                "status": prediction.status,
                "probabilities": list(prediction.probabilities)
                if prediction.probabilities is not None
                else None,
                "label": prediction.label,
                "evidence_ids": list(prediction.evidence_ids),
                "evidence_bindings": [
                    {"candidate_id": c.id, "candidate_sha256": C.digest(c)}
                    for c in item.evidence.candidate_evidence
                    if c.id in prediction.evidence_ids
                ],
                "reason": prediction.reason_code or "synthetic reload",
            }
        )
    return output


def write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def shift(row: dict, delta: float) -> None:
    """Move probability mass between the two least likely labels; the argmax stays."""
    order = sorted(range(3), key=lambda i: row["probabilities"][i])
    row["probabilities"][order[0]] += delta
    row["probabilities"][order[1]] -= delta


def registration_args(registry: Path, ref: C.FileRef) -> tuple[str, ...]:
    return (
        "--registry",
        str(registry),
        "--registration-path",
        ref.path,
        "--registration-hash",
        ref.sha256,
    )


@pytest.mark.parametrize(
    ("build", "absolute", "basis", "inside", "outside"),
    [
        (linear_registration, 1e-6, "linear", 4e-7, 4e-6),
        (attention_registration, 1e-4, "encoder", 4e-5, 4e-4),
    ],
    ids=["linear", "encoder"],
)
def test_tol_01_probabilities_within_tolerance_match_and_beyond_are_rejected(
    return_case, capsys, tmp_path, build, absolute, basis, inside, outside
) -> None:
    root, _, path = return_case
    registry, ref = build(tmp_path / "model")
    exact = model_predictions(registry, ref, root / "data/dev.inputs.jsonl")
    assert all(row["status"] == "ok" for row in exact)
    near = json.loads(json.dumps(exact))
    shift(near[0], inside)
    write_rows(path, near)
    code, result = invoke(return_case, capsys, *registration_args(registry, ref))
    assert code == 0, result
    assert result["reload"]["status"] == "matched"
    assert result["tolerance"] == result["reload"]["tolerance"]
    assert result["tolerance"]["absolute"] == absolute
    assert result["tolerance"]["basis"] == basis
    assert result["reload"]["max_probability_deviation"] == pytest.approx(inside, rel=0.05)
    assert result["reload"]["mismatched_record_ids"] == []

    far = json.loads(json.dumps(exact))
    shift(far[1], outside)
    write_rows(path, far)
    code, result = invoke(return_case, capsys, *registration_args(registry, ref))
    assert code == 2
    assert result["status"] == "rejected"
    assert result["reload"]["status"] == "producer_mismatch"
    assert result["reload"]["mismatched_record_ids"] == [far[1]["record_id"]]
    assert result["reload"]["mismatches"] == [
        {"record_id": far[1]["record_id"], "fields": ["probabilities"]}
    ]
    assert result["reload"]["max_probability_deviation"] == pytest.approx(outside, rel=0.05)


def test_tol_01_evidence_sets_must_match_exactly_even_within_tolerance(
    return_case, capsys, tmp_path
) -> None:
    root, _, path = return_case
    registry, ref = linear_registration(tmp_path / "model")
    rows = model_predictions(registry, ref, root / "data/dev.inputs.jsonl")
    inputs = [
        json.loads(line) for line in (root / "data/dev.inputs.jsonl").read_text().splitlines()
    ]
    target = next(
        index
        for index, row in enumerate(rows)
        if row["label"] in {"SUPPORTED", "CONTRADICTED"} or row["evidence_ids"]
    )
    candidates = inputs[target]["model_input"]["evidence"]["candidate_evidence"]
    chosen = [c for c in candidates if c["id"] not in rows[target]["evidence_ids"]][:1] or [
        candidates[0]
    ]
    if chosen[0]["id"] in rows[target]["evidence_ids"]:
        chosen = [c for c in candidates if c["id"] != chosen[0]["id"]][:1]
    rows[target]["evidence_ids"] = [chosen[0]["id"]]
    rows[target]["evidence_bindings"] = [
        {"candidate_id": chosen[0]["id"], "candidate_sha256": C.digest(chosen[0])}
    ]
    write_rows(path, rows)
    code, result = invoke(return_case, capsys, *registration_args(registry, ref))
    assert code == 2
    assert result["reload"]["status"] == "producer_mismatch"
    assert result["reload"]["mismatches"] == [
        {"record_id": rows[target]["record_id"], "fields": ["evidence_ids"]}
    ]
    assert result["reload"]["max_probability_deviation"] == 0


def test_crv_03_format_abstention_and_coverage_counts_are_reported_per_language(
    return_case, capsys
) -> None:
    root, _, path = return_case
    metadata = root / "audit/metadata.jsonl"
    rows = [json.loads(line) for line in metadata.read_text().splitlines()]
    rows[2]["language"] = "zh"
    write_rows(metadata, rows)
    manifest_path = root / "dataset-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["splits"]["dev"]["language"] = {"en": 2, "zh": 1}
    manifest_path.write_text(json.dumps(manifest))
    checksum = reseal_dataset(root)

    def outcomes(predictions: list[dict]) -> None:
        predictions[0].update(
            status="abstained",
            probabilities=None,
            label=None,
            evidence_ids=[],
            evidence_bindings=[],
            reason="synthetic abstention",
        )
        predictions[2]["probabilities"] = [0.5, 0.5, 0.5]

    rewrite_predictions(path, outcomes)
    code, result = invoke((root, checksum, path), capsys)
    assert code == 2 and result["status"] == "rejected"
    assert result["evaluation_setting"] == "given_evidence_only"
    assert result["retrieval_setting"] == "not_evaluated"
    assert result["languages"]["en"]["counts"] == {
        "format_failures": 0,
        "abstentions": 1,
        "coverage": 0.5,
    }
    assert result["languages"]["zh"]["counts"] == {
        "format_failures": 1,
        "abstentions": 0,
        "coverage": 0.0,
    }
    assert result["languages"]["zh"]["status"] == "recomputed"


def test_crv_03_missing_language_stays_blocked_with_empty_counts(return_case, capsys) -> None:
    code, result = invoke(return_case, capsys)
    assert code == 0
    assert result["languages"]["zh"]["status"] == "blocked_missing_language"
    assert result["languages"]["zh"]["counts"] == {
        "format_failures": 0,
        "abstentions": 0,
        "coverage": None,
    }
    assert result["evaluation_setting"] == "given_evidence_only"


def fusion_registration(tmp_path: Path, alpha: float, threshold: float) -> tuple[Path, C.FileRef]:
    """A registered NumPy fusion of the two fixed linear bundles (same release and source)."""
    left_root, left_ref = linear_bundle(tmp_path / "left", *LEFT_WEIGHTS)
    right_root, right_ref = linear_bundle(tmp_path / "right", *RIGHT_WEIGHTS)
    target = tmp_path / f"fusion-{alpha}-{threshold}"
    ref = save_fusion_bundle(
        target,
        left_root=left_root,
        left_ref=left_ref,
        right_root=right_root,
        right_ref=right_ref,
        alpha=alpha,
        threshold=threshold,
    )
    return tmp_path / "registry", register(tmp_path / "registry", target, ref)


def producer_selection(registry: Path, ref: C.FileRef, checksum: str, **changes) -> dict:
    """The responsible party's dev grid, computed with the published fusion rule."""
    model, _ = load_registration(registry, ref)
    rows = examples("dev", 1)
    result = select_alpha(rows, model.left, model.right)
    record = {
        "protocol": "rolecraft-fusion-selection-v1",
        "task_type": "relation",
        "dataset_id": "synthetic-return",
        "dataset_manifest_sha256": checksum,
        "selection_split": "dev",
        "test_used_for_selection": False,
        "components": {
            "left": {"model_revision": model.left.revision, "artifact_kind": "linear"},
            "right": {"model_revision": model.right.revision, "artifact_kind": "linear"},
        },
        "alpha_grid": [0, 0.25, 0.5, 0.75, 1],
        "evidence_threshold_grid": [0.25, 0.5, 0.75],
        "selected": {"alpha": result["alpha"], "evidence_threshold": result["evidence_threshold"]},
        "points": [
            {
                "alpha": point["alpha"],
                "evidence_threshold": point["threshold"],
                "metrics": {
                    key: point["metrics"][key]
                    for key in (
                        "count",
                        "macro_f1",
                        "mean_evidence_f1",
                        "joint_correctness",
                        "evidence_denominator",
                        "joint_denominator",
                    )
                },
            }
            for point in result["grid"]
        ],
        "fusion_gain_observed": result["fusion_gain_observed"],
        "dev_input_hashes": result["dev_input_hashes"],
    }
    return record | changes


def fusion_case(return_case, tmp_path: Path, alpha: float, threshold: float, **changes):
    root, checksum, path = return_case
    registry, ref = fusion_registration(tmp_path / "model", alpha, threshold)
    write_rows(path, model_predictions(registry, ref, root / "data/dev.inputs.jsonl"))
    selection = tmp_path / "fusion-selection.json"
    selection.write_text(json.dumps(producer_selection(registry, ref, checksum, **changes)))
    return registry, ref, selection


def test_fsel_01_selection_recomputed_on_registered_components_matches(
    return_case, capsys, tmp_path
) -> None:
    registry, ref, selection = fusion_case(return_case, tmp_path, 0.25, 0.5)
    record = json.loads(selection.read_text())
    # Worked example: at alpha 0 the left model calls the INSUFFICIENT record CONTRADICTED;
    # mixing in a quarter of the right model fixes it, so 0.25 beats both endpoints.
    assert record["selected"] == {"alpha": 0.25, "evidence_threshold": 0.5}
    code, result = invoke(
        return_case, capsys, *registration_args(registry, ref), "--fusion-selection", str(selection)
    )
    assert code == 0, result
    fusion = result["fusion_selection"]
    assert fusion["status"] == "matched" and fusion["reasons"] == []
    assert fusion["policy"] == "joint-first-dev-v1"
    assert fusion["recomputed"]["selected"] == {"alpha": 0.25, "evidence_threshold": 0.5}
    assert fusion["recomputed"]["fusion_gain_observed"] is True
    assert fusion["mismatched_points"] == []
    assert result["reload"]["status"] == "matched"


@pytest.mark.parametrize(
    ("alpha", "change", "reasons"),
    [
        (
            0.0,
            {"selected": {"alpha": 0, "evidence_threshold": 0.5}, "fusion_gain_observed": False},
            ["fusion_selection_selected_mismatch"],
        ),
        (
            0.0,
            {"selected": {"alpha": 0, "evidence_threshold": 0.5}, "fusion_gain_observed": True},
            ["fusion_selection_selected_mismatch", "fusion_gain_claimed_at_endpoint"],
        ),
        (0.25, {"test_used_for_selection": True}, ["fusion_selection_contaminated"]),
        (0.25, {"dev_input_hashes": ["0" * 64]}, ["fusion_selection_dev_inputs_mismatch"]),
        (0.25, {"dataset_manifest_sha256": "0" * 64}, ["fusion_selection_dataset_mismatch"]),
    ],
    ids=["other-point", "endpoint-gain", "test-used", "dev-inputs", "dataset"],
)
def test_fsel_01_selection_that_disagrees_with_recomputation_is_rejected(
    return_case, capsys, tmp_path, alpha, change, reasons
) -> None:
    registry, ref, selection = fusion_case(return_case, tmp_path, alpha, 0.5, **change)
    code, result = invoke(
        return_case, capsys, *registration_args(registry, ref), "--fusion-selection", str(selection)
    )
    assert code == 2
    assert result["status"] == "rejected"
    assert result["fusion_selection"]["status"] == "rejected"
    assert result["fusion_selection"]["reasons"] == reasons


def test_fsel_01_a_changed_point_metric_is_located(return_case, capsys, tmp_path) -> None:
    registry, ref, selection = fusion_case(return_case, tmp_path, 0.25, 0.5)
    record = json.loads(selection.read_text())
    point = next(
        p for p in record["points"] if (p["alpha"], p["evidence_threshold"]) == (0.5, 0.75)
    )
    point["metrics"]["macro_f1"] = 0.9
    point["metrics"]["joint_denominator"] += 1
    selection.write_text(json.dumps(record))
    code, result = invoke(
        return_case, capsys, *registration_args(registry, ref), "--fusion-selection", str(selection)
    )
    assert code == 2
    assert result["fusion_selection"]["reasons"] == ["fusion_selection_point_mismatch"]
    assert result["fusion_selection"]["mismatched_points"] == [
        {"alpha": 0.5, "evidence_threshold": 0.75, "fields": ["macro_f1", "joint_denominator"]}
    ]


def test_fsel_01_needs_a_registered_fusion(return_case, capsys, tmp_path) -> None:
    registry, ref, selection = fusion_case(return_case, tmp_path, 0.25, 0.5)
    code, result = invoke(return_case, capsys, "--fusion-selection", str(selection))
    assert code == 2 and result["error"] == "fusion_selection_requires_registration"
    other_registry, other = linear_registration(tmp_path / "single")
    code, result = invoke(
        return_case,
        capsys,
        *registration_args(other_registry, other),
        "--fusion-selection",
        str(selection),
    )
    assert code == 2 and result["error"] == "fusion_selection_requires_fusion_registration"


# The untrained-heads declaration as the 146 export writes it (encoder-return.md §2).
UNTRAINED_HEADS = {
    "weights_stage": "pretrained_untrained_heads",
    "completed": False,
    "training_partitions": [],
    "selection_partition": None,
    "test_used_for_selection": False,
}


@pytest.mark.parametrize(
    ("scope", "stage", "change", "code"),
    [
        ("synthetic_fixture", "pretrained_untrained_heads", {}, None),
        (
            "external_candidate",
            "pretrained_untrained_heads",
            {},
            "model_return_selection_contaminated",
        ),
        ("synthetic_fixture", "supervised_finetuned", {}, "model_return_selection_contaminated"),
        ("synthetic_fixture", None, {}, "model_return_selection_contaminated"),
        (
            "synthetic_fixture",
            "pretrained_untrained_heads",
            {"selection_partition": "dev"},
            "untrained_heads_declaration_invalid",
        ),
        (
            "synthetic_fixture",
            "pretrained_untrained_heads",
            {"training_partitions": ["train"]},
            "untrained_heads_declaration_invalid",
        ),
        (
            "synthetic_fixture",
            "pretrained_untrained_heads",
            {"test_used_for_selection": True},
            "untrained_heads_declaration_invalid",
        ),
        (
            "synthetic_fixture",
            "pretrained_untrained_heads",
            {"completed": True},
            "untrained_heads_declaration_invalid",
        ),
        (
            "synthetic_fixture",
            "pretrained_untrained_heads",
            {"weights_stage": None},
            "return_checkpoint_identity_mismatch",
        ),
    ],
    ids=[
        "synthetic-untrained",
        "external",
        "finetuned",
        "no-stage",
        "dev-selection",
        "train-partition",
        "test-used",
        "claims-complete",
        "manifest-without-stage",
    ],
)
def test_ret_03_untrained_heads_may_declare_no_training_only_when_synthetic(
    return_case, tmp_path, scope, stage, change, code
) -> None:
    root, checksum, predictions = return_case
    dataset = load_return_dataset(root, checksum, "dev")
    manifest = (
        {
            "template": False,
            "return_protocol": "rolecraft-label-evidence-v2",
            "task_type": "relation",
            "label_order": ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"],
            "dataset_id": "synthetic-return",
            "dataset_manifest_sha256": checksum,
            "model_revision": "untrained-heads",
            "framework": "pytorch",
            "framework_version": "synthetic",
            "load_and_predict_command": "metadata only, never executed",
            "training_notes_file": "notes.md",
            "predictions_file": "predictions.dev.jsonl",
            "evidence_selection_implemented": True,
            "evidence_selection_required": True,
        }
        | UNTRAINED_HEADS
        | change
    )
    manifest = {
        key: value
        for key, value in manifest.items()
        if value is not None or key == "selection_partition"
    }
    (tmp_path / "weights.bin").write_bytes(b"pretrained weights, heads not trained")
    manifest["checkpoint_files"] = {"weights.bin": sha((tmp_path / "weights.bin").read_bytes())}
    path = tmp_path / "checkpoint-manifest.json"
    path.write_text(json.dumps(manifest))
    registration = RegistrationSummary(
        id="encoder-synthetic",
        scope=scope,
        model_revision="untrained-heads",
        task_type="relation",
        labels=("SUPPORTED", "CONTRADICTED", "INSUFFICIENT"),
        kind="huggingface_encoder",
        weights_stage=stage,
    )
    if code is None:
        result = inspect_return_checkpoint(
            path, dataset, "untrained-heads", predictions, registration=registration
        )
        assert result["status"] == "untrained_heads_declared"
        assert result["candidate_eligible"] is False
        assert result["weights_stage"] == "pretrained_untrained_heads"
    else:
        with pytest.raises(C.ProtocolError) as error:
            inspect_return_checkpoint(
                path, dataset, "untrained-heads", predictions, registration=registration
            )
        assert error.value.code == code
    # Without a registration nothing is relaxed.
    with pytest.raises(C.ProtocolError) as error:
        inspect_return_checkpoint(path, dataset, "untrained-heads", predictions)
    assert error.value.code == "model_return_selection_contaminated"


def test_ret_03_a_real_untrained_heads_encoder_return_passes_the_dev_check_only_when_synthetic(
    return_case, capsys, tmp_path, monkeypatch
) -> None:
    """146's export shape, registered for real; torch is absent, so reloading is blocked."""
    root, checksum, path = return_case
    producer = tmp_path / "encoder-return"
    ref = encoder_return(
        producer, weights_stage="pretrained_untrained_heads", dataset_id="synthetic-return"
    )
    manifest = json.loads((producer / ref.path).read_bytes())
    assert manifest["weights_stage"] == "pretrained_untrained_heads"
    manifest["dataset_manifest_sha256"] = checksum
    ref = write_manifest(producer, manifest)
    with pytest.raises(C.ProtocolError) as error:
        register_bundle(tmp_path / "external", producer, ref, scope="external_candidate")
    assert error.value.code == "untrained_heads_require_synthetic_scope"
    registry = tmp_path / "registry"
    registration = register_bundle(registry, producer, ref, scope="synthetic_fixture")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        row["model_revision"] = manifest["model_revision"]
    write_rows(path, rows)
    deny_encoder_imports(monkeypatch)
    checkpoint = producer / ref.path
    code, result = invoke(
        return_case,
        capsys,
        "--checkpoint-manifest",
        str(checkpoint),
        *registration_args(registry, registration),
    )
    assert code == 0, result
    assert result["status"] == "partial"
    assert result["checkpoint"]["status"] == "untrained_heads_declared"
    assert result["checkpoint"]["candidate_eligible"] is False
    assert result["reload"]["status"] == "blocked_encoder_runtime_unavailable"
    assert result["reload"]["registration"]["weights_stage"] == "pretrained_untrained_heads"
    assert result["training"]["status"] == "mechanism_only"
    assert result["scope"] == "synthetic_fixture" and result["quality_validated"] is False
    # The same declaration without its synthetic registration stays contaminated.
    code, result = invoke(return_case, capsys, "--checkpoint-manifest", str(checkpoint))
    assert code == 2 and result["error"] == "model_return_selection_contaminated"


def test_tol_01_a_label_or_status_change_inside_the_tolerance_is_still_a_mismatch(
    return_case, capsys, tmp_path
) -> None:
    root, _, path = return_case
    # Near-uniform scores with a 1e-7 margin: moving 2e-7 of mass flips the argmax while every
    # probability stays well inside the 1e-6 linear tolerance.
    model_root, ref = linear_bundle(
        tmp_path / "near-tie",
        [[0.0] * 6, [0.0] * 6, [0.0] * 6],
        [0.0, 1e-7, 0.0],
        [0.0, 0.0, 0.0, 0.0, 6.0, 0.0],
    )
    registry = tmp_path / "registry"
    ref = register(registry, model_root, ref)
    exact = model_predictions(registry, ref, root / "data/dev.inputs.jsonl")
    assert {row["label"] for row in exact} == {"CONTRADICTED"}
    flipped = json.loads(json.dumps(exact))
    flipped[0]["probabilities"][1] -= 2e-7
    flipped[0]["probabilities"][0] += 2e-7
    flipped[0]["label"] = "SUPPORTED"
    flipped[1].update(
        status="abstained",
        probabilities=None,
        label=None,
        evidence_ids=[],
        evidence_bindings=[],
        reason="producer abstained",
    )
    write_rows(path, flipped)
    code, result = invoke(return_case, capsys, *registration_args(registry, ref))
    assert code == 2
    assert result["reload"]["max_probability_deviation"] < 1e-6
    assert result["reload"]["mismatches"] == [
        {"record_id": flipped[0]["record_id"], "fields": ["label"]},
        {
            "record_id": flipped[1]["record_id"],
            "fields": ["status", "label", "evidence_ids", "probabilities"],
        },
    ]


@pytest.mark.parametrize(
    ("alpha", "change", "reasons"),
    [
        (0.5, {}, ["fusion_selection_registration_mismatch"]),
        (0.25, {"fusion_gain_observed": False}, ["fusion_gain_observed_mismatch"]),
        (0.25, {"alpha_grid": [0, 0.5, 1]}, ["fusion_selection_grid_invalid"]),
    ],
    ids=["registered-alpha", "gain-claim", "grid"],
)
def test_fsel_01_registration_gain_and_grid_disagreements_are_named(
    return_case, capsys, tmp_path, alpha, change, reasons
) -> None:
    registry, ref, selection = fusion_case(return_case, tmp_path, alpha, 0.5, **change)
    code, result = invoke(
        return_case, capsys, *registration_args(registry, ref), "--fusion-selection", str(selection)
    )
    assert code == 2
    assert result["fusion_selection"]["reasons"] == reasons


def test_fsel_01_component_identity_must_be_the_registered_one(
    return_case, capsys, tmp_path
) -> None:
    registry, ref, selection = fusion_case(return_case, tmp_path, 0.25, 0.5)
    record = json.loads(selection.read_text())
    record["components"]["left"]["model_revision"] = "another-left-model"
    selection.write_text(json.dumps(record))
    code, result = invoke(
        return_case, capsys, *registration_args(registry, ref), "--fusion-selection", str(selection)
    )
    assert code == 2
    assert result["fusion_selection"]["reasons"] == ["fusion_selection_component_mismatch"]


@pytest.mark.parametrize(
    ("edit", "partition", "code"),
    [
        (
            lambda record: record.update(protocol="other"),
            "dev",
            "fusion_selection_protocol_invalid",
        ),
        (lambda record: record.update(extra=True), "dev", "fusion_selection_protocol_invalid"),
        (lambda record: None, "test", "fusion_selection_dev_only"),
    ],
    ids=["protocol", "unknown-key", "test-partition"],
)
def test_fsel_01_a_malformed_record_or_test_partition_is_refused(
    return_case, capsys, tmp_path, edit, partition, code
) -> None:
    registry, ref, selection = fusion_case(return_case, tmp_path, 0.25, 0.5)
    record = json.loads(selection.read_text())
    edit(record)
    selection.write_text(json.dumps(record))
    status, result = invoke(
        return_case,
        capsys,
        *registration_args(registry, ref),
        "--fusion-selection",
        str(selection),
        "--partition",
        partition,
    )
    assert status == 2 and result["error"] == code


@pytest.mark.parametrize(
    ("scope", "stage"),
    [("external_candidate", "supervised_finetuned"), ("synthetic_fixture", "supervised_finetuned")],
    ids=["external", "synthetic-trained"],
)
def test_ret_05_a_trained_encoder_that_cannot_reload_here_is_not_a_partial_review(
    return_case, capsys, tmp_path, monkeypatch, scope, stage
) -> None:
    """Only a synthetic untrained-heads registration may report its reload as blocked."""
    root, checksum, path = return_case
    producer = tmp_path / "encoder-return"
    ref = encoder_return(producer, weights_stage=stage, dataset_id="synthetic-return")
    manifest = json.loads((producer / ref.path).read_bytes())
    manifest["dataset_manifest_sha256"] = checksum
    ref = write_manifest(producer, manifest)
    registry = tmp_path / "registry"
    registration = register_bundle(registry, producer, ref, scope=scope)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        row["model_revision"] = manifest["model_revision"]
    write_rows(path, rows)
    deny_encoder_imports(monkeypatch)
    code, result = invoke(return_case, capsys, *registration_args(registry, registration))
    assert code == 2, result
    assert result["error"] == "pretrained_encoder_dependencies_unavailable"
