"""Synthetic responsible-party receipts through the production dataset CLI."""

import json
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import JsonValue

from career_lab.contracts.v2 import Executor, FileRef, digest
from career_lab.datasets.v3.attestation import parse_receipt
from career_lab.datasets.v3.common import json_bytes, sha
from career_lab.datasets.v3.export import export_snapshot
from career_lab.datasets.v3.labeling import AnnotationBatch, LabelResult

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "unit"))
from test_w07_pipeline import FakeModel, make_case  # noqa: E402

ORDERS = {
    "relation": ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"],
    "criterion": ["MET", "PARTIAL", "NOT_MET", "INSUFFICIENT", "NOT_APPLICABLE"],
    "trajectory": ["diagnosed", "no_issue", "insufficient"],
    "acquisition": ["effective", "ineffective", "undetermined"],
}


class JointEvidenceModel(FakeModel):
    """Controlled provider output requiring both candidate facts together."""

    def __call__(self, request: dict[str, JsonValue]) -> LabelResult:
        response = super().__call__(request)
        body = json.loads(response.raw_output)
        body.update(evidence_ids=["e1", "e2"], acceptable_evidence_sets=[["e1", "e2"]])
        return replace(response, raw_output=json.dumps(body))


def cli(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "career_lab.datasets.v3", *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )


def write_jsonl(path: Path, rows: list[dict[str, JsonValue]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(json_bytes(row) for row in rows))


def jsonl(path: Path) -> list[dict[str, JsonValue]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def seal_package(root: Path) -> None:
    inputs = jsonl(root / "data/train.inputs.jsonl")
    labels = jsonl(root / "data/train.labels.jsonl")
    metadata = jsonl(root / "audit/metadata.jsonl")
    counts = {
        "records": len(inputs),
        "labels": dict(Counter(row["label"] for row in labels)),
        "language": dict(Counter(row["language"] for row in metadata)),
        "label_tiers": dict(Counter(row["label_tier"] for row in labels)),
        "evidence_evaluable": sum(row["evidence_evaluable"] for row in labels),
        "label_only": sum(not row["evidence_evaluable"] for row in labels),
    }
    card = {"protocol": "dataset-card-v1", "splits": {"train": counts}}
    (root / "data_card.md").write_text(
        "# Synthetic mechanism fixture\n\n```json\n" + json.dumps(card) + "\n```\n"
    )
    split = {row["record_id"]: row["split"] for row in metadata}
    (root / "audit/split.json").write_bytes(json_bytes(split))
    manifest = {
        "schema_version": 1,
        "dataset_id": "responsible-party-mechanism-fixture",
        "status": "FIXTURE_ONLY_NOT_FINAL_TRAINING_DATA",
        "annotation_version": "handoff-fixture-v1",
        "label_orders": {
            ("trajectory_diagnosis" if k == "trajectory" else k): v for k, v in ORDERS.items()
        },
        "splits": {"train": counts},
        "split_manifest": "audit/split.json",
    }
    manifest["files"] = {
        str(path.relative_to(root)): {"sha256": sha(path.read_bytes()), "size": path.stat().st_size}
        for path in root.rglob("*")
        if path.is_file() and path.name != "dataset-manifest.json"
    }
    (root / "dataset-manifest.json").write_bytes(json_bytes(manifest))


def package(
    tmp_path: Path,
    language: str,
    cases: tuple[tuple[str, str], ...],
    model_provider: FakeModel | None = None,
) -> Path:
    root = tmp_path / "handoff"
    root.mkdir()
    inputs, labels, metadata, annotations = [], [], [], []
    for name, family in cases:
        source = tmp_path / ("source-" + name)
        source.mkdir()
        snapshot, units, _ = make_case(source)
        exported = export_snapshot(snapshot, [unit for unit in units if unit.family == family])
        record = exported.records[0]
        ref = FileRef(
            path=f"sources/{name}/source.json", sha256=sha((source / "source.json").read_bytes())
        )
        destination = root / "audit" / ref.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((source / "source.json").read_bytes())
        record = record.model_copy(
            update={
                "record_id": name,
                "language": language,
                "provenance": record.provenance.model_copy(update={"actual_sources": (ref,)}),
            }
        )
        batch = AnnotationBatch.create(
            source / "batch",
            [record],
            annotation_version="handoff-fixture-v1",
            executor=Executor(id="fixture-agent", kind="external_agent"),
            source_root=root / "audit",
            policies={ref.path: {"sha256": ref.sha256, "review_status": "approved"}},
        )
        provider = model_provider or (JointEvidenceModel() if name == "good" else FakeModel())
        annotation = batch.run(provider)["annotations"][0]
        assert annotation.status == "accepted" and annotation.label_tier == "G2v"
        inputs.append(
            {
                "record_id": name,
                "input_hash": record.input_hash,
                "model_input": record.model_input.model_dump(mode="json"),
            }
        )
        labels.append(
            {
                **annotation.final.model_dump(mode="json"),
                "record_id": name,
                "input_hash": record.input_hash,
                "label_tier": annotation.label_tier,
                "annotation_version": annotation.annotation_version,
                "label_index": ORDERS[family].index(annotation.final.label),
            }
        )
        record = record.model_copy(update={"label_tier": annotation.label_tier})
        metadata.append(
            {
                "record_id": name,
                "input_hash": record.input_hash,
                "language": language,
                "bucket": record.bucket,
                "split": record.split,
                "connected_component_id": record.lineage.component_id,
                "lineage": record.lineage.model_dump(mode="json"),
                "provenance": record.provenance.model_dump(mode="json"),
                "packaged_sources": [{"path": "audit/" + ref.path, "sha256": ref.sha256}],
            }
        )
        annotations.append(annotation.model_dump(mode="json"))
        for path, raw in batch.artifacts().items():
            destination = root / "audit" / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
    write_jsonl(root / "data/train.inputs.jsonl", inputs)
    write_jsonl(root / "data/train.labels.jsonl", labels)
    write_jsonl(root / "audit/metadata.jsonl", metadata)
    write_jsonl(root / "audit/original-annotations.jsonl", annotations)
    seal_package(root)
    return root


@pytest.mark.parametrize("language", ["zh", "en"])
def test_data_01_evidence_and_applicability_are_checked_per_record(
    tmp_path: Path, language: str
) -> None:
    root = package(
        tmp_path,
        language,
        (
            ("good", "relation"),
            ("bad-evidence", "relation"),
            ("bad-set", "relation"),
            ("bad-applicability", "criterion"),
        ),
    )
    labels = jsonl(root / "data/train.labels.jsonl")
    labels[1]["evidence_ids"] = ["not-in-the-candidates"]
    labels[2]["evidence_ids"] = ["e2"]
    labels[3].update(label="MET", label_index=0, applicability="not_applicable")
    write_jsonl(root / "data/train.labels.jsonl", labels)
    seal_package(root)
    response = cli("validate-handoff", "--package", root, "--output", tmp_path / "review")
    assert response.returncode == 2, response.stdout + response.stderr
    assert response.stdout.strip(), response.stderr
    report = json.loads(response.stdout)
    outcomes = {row["record_id"]: row for row in report["records"]}
    assert outcomes["good"]["status"] == "accept"
    assert outcomes["good"]["normalized_decision"]["acceptable_evidence_sets"] == [["e1", "e2"]]
    for name, reason in (
        ("bad-evidence", "annotation_invalid_reference"),
        ("bad-set", "final_evidence_not_an_acceptable_target"),
        ("bad-applicability", "annotation_applicability_mismatch"),
    ):
        assert outcomes[name]["status"] == "quarantine"
        assert reason in outcomes[name]["reasons"]
    assert report["training_ready"] is False


@pytest.mark.parametrize("language", ["zh", "en"])
def test_data_02_redundant_supersets_share_public_consensus_key(
    tmp_path: Path, language: str
) -> None:
    root = package(tmp_path, language, (("normalization", "relation"),))
    labels = jsonl(root / "data/train.labels.jsonl")
    labels[0]["acceptable_evidence_sets"] = [["e1"], ["e1", "e2"]]
    write_jsonl(root / "data/train.labels.jsonl", labels)
    seal_package(root)
    response = cli("validate-handoff", "--package", root, "--output", tmp_path / "review")
    report = json.loads(response.stdout)
    assert response.returncode == 0, report
    result = report["records"][0]
    assert result["status"] == "accept"
    assert result["normalized_decision"]["acceptable_evidence_sets"] == [["e1"]]


@pytest.mark.parametrize("language", ["zh", "en"])
def test_data_03_self_declared_authority_and_label_only_remain_pending(
    tmp_path: Path, language: str
) -> None:
    root = package(tmp_path, language, (("real-g0", "relation"), ("real-label-only", "relation")))
    metadata = jsonl(root / "audit/metadata.jsonl")
    labels = jsonl(root / "data/train.labels.jsonl")
    for meta in metadata:
        meta["bucket"] = "env_run"
        meta["provenance"]["transformations"] = []
        ref = meta["packaged_sources"][0]
        source = root / ref["path"]
        body = json.loads(source.read_bytes()) | {"origin": "env_run"}
        source.write_bytes(json_bytes(body))
        ref["sha256"] = sha(source.read_bytes())
        meta["provenance"]["actual_sources"][0]["sha256"] = ref["sha256"]
    labels[0].update(label_tier="G0", verifier_id="w07-numeric-grammar-v1")
    labels[1].update(
        evidence_evaluable=False,
        evidence_ids=[],
        acceptable_evidence_sets=[],
        missing_reason="producer says label-only",
    )
    write_jsonl(root / "audit/metadata.jsonl", metadata)
    write_jsonl(root / "data/train.labels.jsonl", labels)
    seal_package(root)
    response = cli("validate-handoff", "--package", root, "--output", tmp_path / "review")
    assert response.returncode == 2
    report = json.loads(response.stdout)
    for result in report["records"]:
        assert result["status"] == "pending", result
        assert "authoritative_source_reader_required" in result["reasons"]
        assert result["accepted_label_tier"] is None
    assert "label_only_semantic_review_required" in report["records"][1]["reasons"]
    assert report["training_ready"] is False


def test_packaged_source_mapping_is_verified(tmp_path: Path) -> None:
    root = package(tmp_path, "en", (("mapped", "relation"),))
    metadata = jsonl(root / "audit/metadata.jsonl")
    metadata[0]["packaged_sources"][0]["sha256"] = "0" * 64
    write_jsonl(root / "audit/metadata.jsonl", metadata)
    seal_package(root)
    response = cli("validate-handoff", "--package", root, "--output", tmp_path / "review")
    assert response.returncode == 2
    assert json.loads(response.stdout)["records"][0]["status"] == "quarantine"


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("fault", ["copied", "empty", "failed", "missing-proof", "human-tier"])
def test_data_04_independent_raw_calls_required(tmp_path: Path, language: str, fault: str) -> None:
    root = package(tmp_path, language, (("independent", "relation"),))
    annotations = jsonl(root / "audit/original-annotations.jsonl")
    annotation = annotations[0]
    if fault == "copied":
        annotation["passes"][1]["invocation_id"] = annotation["passes"][0]["invocation_id"]
    elif fault in {"empty", "failed"}:
        annotation["passes"][1].update(status=fault, raw_output=None, decision=None)
        annotation.update(status="pending", label_tier="G2", final=None)
    elif fault == "missing-proof":
        # A declared successful pass without the original received bytes is not proof.
        (root / "audit/labels/passes" / (annotation["passes"][1]["id"] + ".json")).unlink()
    else:
        annotation["label_tier"] = "G1"
    write_jsonl(root / "audit/original-annotations.jsonl", annotations)
    seal_package(root)
    response = cli("validate-handoff", "--package", root, "--output", tmp_path / "review")
    assert response.returncode == 2
    result = json.loads(response.stdout)["records"][0]
    assert result["status"] == "pending", result
    assert result["accepted_label_tier"] is None
    assert result["normalized_decision"] is None


@pytest.mark.parametrize("language", ["zh", "en"])
def test_data_05_recovery_is_idempotent_and_conflicts_do_not_overwrite(
    tmp_path: Path, language: str
) -> None:
    root = package(tmp_path, language, (("recover", "relation"),))
    out = tmp_path / "review"
    first = cli("validate-handoff", "--package", root, "--output", out)
    assert first.returncode == 0, first.stdout
    original = (out / "report.json").read_bytes()
    again = cli("validate-handoff", "--package", root, "--output", out)
    assert again.returncode == 0, again.stdout
    assert again.stdout == first.stdout
    assert (out / "report.json").read_bytes() == original
    labels = jsonl(root / "data/train.labels.jsonl")
    labels[0]["annotation_version"] = "changed-version"
    write_jsonl(root / "data/train.labels.jsonl", labels)
    seal_package(root)
    changed = cli("validate-handoff", "--package", root, "--output", out)
    assert changed.returncode == 2
    assert json.loads(changed.stdout)["error"] == "handoff_review_conflict"
    assert (out / "report.json").read_bytes() == original


@pytest.mark.parametrize("fault", ["extra", "symlink", "count", "card", "split", "nested-output"])
def test_data_05_complete_package_boundary(tmp_path: Path, fault: str) -> None:
    root = package(tmp_path, "en", (("boundary", "relation"),))
    out = tmp_path / "review"
    if fault == "extra":
        (root / "unlisted.txt").write_text("unexpected file")
    elif fault == "symlink":
        (root / "extra-link").symlink_to(root / "data/train.inputs.jsonl")
    elif fault == "count":
        path = root / "dataset-manifest.json"
        data = json.loads(path.read_bytes())
        data["splits"]["train"]["records"] = 2
        path.write_bytes(json_bytes(data))
    elif fault == "card":
        path = root / "data_card.md"
        path.write_text(path.read_text().replace('"records": 1', '"records": 99'))
        manifest_path = root / "dataset-manifest.json"
        data = json.loads(manifest_path.read_bytes())
        data["files"]["data_card.md"] = {
            "sha256": sha(path.read_bytes()),
            "size": path.stat().st_size,
        }
        manifest_path.write_bytes(json_bytes(data))
    elif fault == "split":
        path = root / "audit/split.json"
        path.write_bytes(json_bytes({"boundary": "dev"}))
        manifest_path = root / "dataset-manifest.json"
        data = json.loads(manifest_path.read_bytes())
        data["files"]["audit/split.json"] = {
            "sha256": sha(path.read_bytes()),
            "size": path.stat().st_size,
        }
        manifest_path.write_bytes(json_bytes(data))
    else:
        out = root / "review"
    response = cli("validate-handoff", "--package", root, "--output", out)
    assert response.returncode == 2, response.stdout
    assert not out.exists()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_data_02_independent_passes_with_redundant_alternative_reach_consensus(
    tmp_path: Path, language: str
) -> None:
    root = package(tmp_path, language, (("two-pass", "relation"),))
    annotations = jsonl(root / "audit/original-annotations.jsonl")
    annotation = annotations[0]
    second_path = root / "audit/labels/passes" / (annotation["passes"][1]["id"] + ".json")
    stored = json.loads(second_path.read_bytes())
    decision = json.loads(stored["receipt"]["raw_output"])
    decision["acceptable_evidence_sets"] = [["e1"], ["e1", "e2"]]
    stored["receipt"]["raw_output"] = json.dumps(decision)
    stored["receipt_hash"] = digest(stored["receipt"])
    parsed, _, _ = parse_receipt(stored["request"], stored["receipt"])
    stored["pass"] = parsed.model_dump(mode="json")
    second_path.write_bytes(json_bytes(stored))
    annotation["passes"][1] = stored["pass"]
    annotation.update(status="disputed", final=None, label_tier="G2")
    write_jsonl(root / "audit/original-annotations.jsonl", annotations)
    seal_package(root)
    response = cli("validate-handoff", "--package", root, "--output", tmp_path / "review")
    assert response.returncode == 0, response.stdout
    result = json.loads(response.stdout)["records"][0]
    assert result["accepted_label_tier"] == "G2v"
    assert result["normalized_decision"]["acceptable_evidence_sets"] == [["e1"]]
    # Raw producer bytes remain untouched by review normalization.
    assert json.loads(second_path.read_bytes())["receipt"]["raw_output"] == json.dumps(decision)


def test_data_05_unknown_attempt_is_query_only_until_explicit_retry(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    snapshot, units, policies = make_case(source)
    records = export_snapshot(snapshot, units[:1]).records
    batch = AnnotationBatch.create(
        source / "batch",
        records,
        annotation_version="recovery-fixture",
        executor=Executor(id="fixture-agent", kind="external_agent"),
        source_root=source,
        policies=policies,
    )
    args = (
        "label",
        "issue",
        "--batch",
        batch.path,
        "--record-id",
        records[0].record_id,
        "--phase",
        1,
    )
    first = cli(*args)
    assert first.returncode == 0
    assert json.loads(first.stdout)["attempt"] == 1
    unknown = cli(*args)
    assert unknown.returncode == 2
    assert json.loads(unknown.stdout)["error"] == "dispatch_outcome_unknown"
    status = cli("label", "status", "--batch", batch.path)
    assert json.loads(status.stdout)["usage"]["attempts"] == 1
    retry = cli(*args, "--retry-unknown")
    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert json.loads(retry.stdout)["attempt"] == 2
    assert json.loads(retry.stdout)["request_id"] != json.loads(first.stdout)["request_id"]


class InvalidSelectionModel(FakeModel):
    def __call__(self, request: dict[str, JsonValue]) -> LabelResult:
        response = super().__call__(request)
        decision = json.loads(response.raw_output)
        payload = request["model_input"]
        target = (
            payload["steps"][0]["id"]
            if payload["task_type"] == "trajectory_diagnosis"
            else payload["candidates"][1]["id"]
        )
        decision.update(
            evidence_evaluable=True, evidence_ids=[], acceptable_evidence_sets=[[target]]
        )
        return replace(response, raw_output=json.dumps(decision))


@pytest.mark.parametrize("family", ["trajectory", "acquisition"])
def test_data_01_all_families_require_an_acceptable_selected_set(
    tmp_path: Path, family: str
) -> None:
    root = package(
        tmp_path, "en", (("other-family", family),), model_provider=InvalidSelectionModel()
    )
    response = cli("validate-handoff", "--package", root, "--output", tmp_path / "review")
    assert response.returncode == 2
    result = json.loads(response.stdout)["records"][0]
    assert result["status"] == "quarantine"
    assert result["reasons"] == ["final_evidence_not_an_acceptable_target"]


def test_data_05_invalid_card_shape_is_a_safe_json_error(tmp_path: Path) -> None:
    root = package(tmp_path, "en", (("card-shape", "relation"),))
    path = root / "data_card.md"
    path.write_text('```json\n{"splits": []}\n```\n')
    manifest_path = root / "dataset-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"]["data_card.md"] = {
        "sha256": sha(path.read_bytes()),
        "size": path.stat().st_size,
    }
    manifest_path.write_bytes(json_bytes(manifest))
    response = cli("validate-handoff", "--package", root, "--output", tmp_path / "review")
    assert response.returncode == 2
    assert json.loads(response.stdout)["error"] == "handoff_data_card_invalid"
    assert "Traceback" not in response.stderr


class AcquisitionEvidenceModel(FakeModel):
    def __call__(self, request: dict[str, JsonValue]) -> LabelResult:
        response = super().__call__(request)
        decision = json.loads(response.raw_output)
        decision.update(
            evidence_evaluable=True, evidence_ids=["a1"], acceptable_evidence_sets=[["a1"]]
        )
        return replace(response, raw_output=json.dumps(decision))


def test_data_01_normalization_never_repairs_an_invalid_selection(tmp_path: Path) -> None:
    root = package(
        tmp_path, "en", (("selection", "acquisition"),), model_provider=AcquisitionEvidenceModel()
    )
    labels = jsonl(root / "data/train.labels.jsonl")
    labels[0]["evidence_ids"] = ["a1", "a2"]
    write_jsonl(root / "data/train.labels.jsonl", labels)
    seal_package(root)
    response = cli("validate-handoff", "--package", root, "--output", tmp_path / "review")
    assert response.returncode == 2, response.stdout
    row = json.loads(response.stdout)["records"][0]
    assert row["status"] == "quarantine"
    assert row["reasons"] == ["final_evidence_not_an_acceptable_target"]
