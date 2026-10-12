"""v3 split-sealed data packages and the one-time held-out test opening, through the CLIs.

Every package here is a synthetic mechanism sample: constructed records, controlled
annotation doubles and fixed-weight registrations. Nothing proves training or quality.
"""

import json
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import JsonValue

from career_lab.contracts import v2 as C
from career_lab.contracts.v2.core import Executor, VersionPoint
from career_lab.contracts.v2.data import Lineage, Provenance, RelationInput
from career_lab.datasets.v3.common import json_bytes, sha
from career_lab.datasets.v3.export import ExportUnit, FrozenSnapshot, SourceObject, export_snapshot
from career_lab.datasets.v3.labeling import AnnotationBatch
from career_lab.experiments.v3.training.freeze import freeze_selection
from career_lab.models.v3.held_out import prepare_test_freeze, review_policy_bytes
from tests.integration.test_model_return_verification import (
    LEFT_WEIGHTS,
    linear_bundle,
    linear_registration,
    model_predictions,
    register,
)
from tests.unit.test_w07_pipeline import BASE, FakeModel
from tests.unit.test_w07_pipeline import package as evidence_package

ROOT = Path(__file__).resolve().parents[2]
LAYOUT = "rolecraft-dataset-split-sealed-v1"
RELATION = ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"]
SYNTHETIC_STATUS = "SYNTHETIC_MECHANISM_SAMPLE_NOT_TRAINING_DATA"
# (split, language, label): two languages in every split, both relation directions in dev.
RECORDS = (
    ("train", "zh", "SUPPORTED"),
    ("train", "en", "CONTRADICTED"),
    ("dev", "zh", "SUPPORTED"),
    ("dev", "en", "SUPPORTED"),
    ("dev", "zh", "CONTRADICTED"),
    ("dev", "en", "CONTRADICTED"),
    ("test", "zh", "SUPPORTED"),
    ("test", "en", "CONTRADICTED"),
)
# Distinct wording per record, so the shared quality audit sees no cross-split duplicates.
NOTES = {
    "en": (
        "weekly report archived by finance",
        "vendor contract renewal still pending",
        "incident retrospective scheduled for friday",
        "pilot cohort expanded to a second region",
        "support backlog cleared after the migration",
        "pricing experiment paused by legal review",
        "onboarding survey reached its target sample",
        "security review approved the new connector",
    ),
    "zh": (
        "财务部已经归档本周周报",
        "供应商合同续签仍在等待",
        "周五安排了事故复盘会议",
        "试点队列扩展到第二个区域",
        "迁移完成后客服积压已清空",
        "法务评审暂停了定价实验",
        "入职问卷达到了目标样本量",
        "安全评审批准了新的连接器",
    ),
}


def claim(language: str, index: int) -> str:
    limit = 20 + 7 * index
    if language == "zh":
        return f"第{index}项服务的容量不超过{limit}"
    return f"service {index} keeps capacity below {limit}"


@dataclass(frozen=True)
class V3Package:
    root: Path
    checksum: str


def write_jsonl(path: Path, rows: list[dict[str, JsonValue]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(json_bytes(row) for row in rows))


def jsonl(path: Path) -> list[dict[str, JsonValue]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def split_files(split: str) -> dict[str, str]:
    return {
        "inputs": f"data/{split}.inputs.jsonl",
        "labels": f"data/{split}.labels.jsonl",
        "annotations": f"audit/{split}/annotations.jsonl",
        "metadata": f"audit/{split}/metadata.jsonl",
    }


def relation_record(work: Path, root: Path, name: str, split: str, language: str, label: str):
    """One exported relation record with a G2v annotation from a controlled double."""
    session = "session-" + name
    point = VersionPoint(business_seq=4, workspace_revision=2, storage_revision=7)
    refs = [
        C.EvidenceRefV2(
            session_id=session, kind="document", object_id=f"{name}-{i}", version=1, observed_at_seq=1
        )
        for i in (1, 2)
    ]
    index = int(name.rsplit("-", 1)[1])
    evidence = evidence_package(
        "relation",
        claim=claim(language, index),
        refs=refs,
        point=point,
        candidate_evidence=[
            C.CandidateEvidenceV2(
                id="answer-supported",
                text=json.dumps({"service": index, "capacity": 20 + 7 * index}),
                ref=refs[0],
            ).model_dump(mode="json"),
            C.CandidateEvidenceV2(
                id="candidate2", text=NOTES[language][index], ref=refs[1]
            ).model_dump(mode="json"),
        ],
    )
    sources = tuple(
        SourceObject(
            C.ObjectRef.model_validate(
                {k: c.ref.model_dump(mode="json")[k] for k in C.ObjectRef.model_fields}
            ),
            c.text,
            VersionPoint(business_seq=1, workspace_revision=0, storage_revision=1),
            ("learner",),
            validity_known=True,
        )
        for c in evidence.candidate_evidence
    )
    body = json_bytes({"origin": "unit-fixture", "session": session, "test_double": True})
    source_ref = C.FileRef(path=f"sources/{name}/source.json", sha256=sha(body))
    audit = root / "audit" / split
    (audit / source_ref.path).parent.mkdir(parents=True, exist_ok=True)
    (audit / source_ref.path).write_bytes(body)
    identity = C.SourceIdentity(base_commit=BASE, source_digest=C.digest("fixture-source"))
    provenance = Provenance(
        command="synthetic v3 mechanism sample; not a business execution",
        source=identity,
        executor=Executor(id="fixture-system", kind="system"),
        actual_sources=(source_ref,),
        captured_at="2026-10-12T00:00:00Z",
    )
    lineage = Lineage(
        structure_id="structure-" + split,
        component_id="component-" + name,
        session_id=session,
        run_id="run-" + name,
        fact_root_ids=("root-" + name,),
    )
    # Our labeling refuses test records; the sample's test labels are made as dev and moved.
    labeled_split = "dev" if split == "test" else split
    unit = ExportUnit(
        "relation",
        RelationInput(evidence=evidence),
        lineage,
        provenance,
        split=labeled_split,
        language=language,
        evaluation_time_known=True,
    )
    snapshot = FrozenSnapshot(session, "learner", point, sources, identity.source_digest, "fixture")
    record = export_snapshot(snapshot, [unit]).records[0]
    record = record.model_copy(update={"record_id": name})
    batch = AnnotationBatch.create(
        work / ("batch-" + name),
        [record],
        annotation_version="handoff-fixture-v1",
        executor=Executor(id="fixture-agent", kind="external_agent"),
        source_root=audit,
        policies={source_ref.path: {"sha256": source_ref.sha256, "review_status": "approved"}},
    )
    annotation = batch.run(FakeModel({1: label, 2: label, 3: label}))["annotations"][0]
    assert annotation.status == "accepted" and annotation.label_tier == "G2v"
    for path, raw in batch.artifacts().items():
        target = audit / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    final = annotation.final
    return (
        {
            "record_id": name,
            "input_hash": record.input_hash,
            "model_input": record.model_input.model_dump(mode="json"),
        },
        {
            **final.model_dump(mode="json"),
            "record_id": name,
            "input_hash": record.input_hash,
            "label_tier": annotation.label_tier,
            "annotation_version": annotation.annotation_version,
            "label_index": RELATION.index(final.label),
        },
        annotation.model_dump(mode="json"),
        {
            "record_id": name,
            "input_hash": record.input_hash,
            "language": language,
            "bucket": record.bucket,
            "split": split,
            "connected_component_id": record.lineage.component_id,
            "lineage": record.lineage.model_dump(mode="json"),
            "provenance": record.provenance.model_dump(mode="json"),
            "packaged_sources": [
                {"path": f"audit/{split}/{source_ref.path}", "sha256": source_ref.sha256}
            ],
        },
    )


def counts(labels: list[dict], metadata: list[dict]) -> dict[str, JsonValue]:
    return {
        "records": len(labels),
        "labels": dict(Counter(row["label"] for row in labels)),
        "language": dict(Counter(row["language"] for row in metadata)),
        "evidence_evaluable": sum(row["evidence_evaluable"] for row in labels),
        "label_only": sum(not row["evidence_evaluable"] for row in labels),
        "label_tiers": dict(Counter(row["label_tier"] for row in labels)),
    }


def file_identity(root: Path, name: str) -> dict[str, JsonValue]:
    path = root / name
    return {"sha256": sha(path.read_bytes()), "size": path.stat().st_size}


def seal(
    root: Path,
    *,
    status: str = SYNTHETIC_STATUS,
    test_sealed: bool = True,
    declared: dict[str, dict] | None = None,
) -> str:
    """Producer side: rewrite the card and manifest from the files on disk.

    ``declared`` overrides a split's counts (used when its label bytes are deliberately
    unreadable). Returns the manifest SHA-256.
    """
    splits = {}
    for split in ("train", "dev", "test"):
        names = split_files(split)
        if not (root / names["inputs"]).exists():
            continue
        if declared and split in declared:
            split_counts = declared[split]
        else:
            split_counts = counts(jsonl(root / names["labels"]), jsonl(root / names["metadata"]))
        owned = sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
            and (
                path.relative_to(root).as_posix().startswith(f"data/{split}.")
                or path.relative_to(root).as_posix().startswith(f"audit/{split}/")
            )
        )
        splits[split] = split_counts | {
            "files": {name: file_identity(root, name) for name in owned}
        }
    card = {
        "protocol": "dataset-card-v1",
        "splits": {s: {k: v for k, v in c.items() if k != "files"} for s, c in splits.items()},
    }
    (root / "data_card.md").write_text(
        "# Synthetic v3 mechanism sample\n\n```json\n" + json.dumps(card) + "\n```\n"
    )
    manifest = {
        "schema_version": 1,
        "layout": LAYOUT,
        "dataset_id": "rolecraft-synthetic-v3-mechanism",
        "status": status,
        "annotation_version": "handoff-fixture-v1",
        "task_type": "relation",
        "label_order": RELATION,
        "label_orders": {"relation": RELATION},
        "test_sealed": test_sealed and "test" in splits,
        "splits": splits,
        "files": {"data_card.md": file_identity(root, "data_card.md")},
    }
    (root / "dataset-manifest.json").write_bytes(json_bytes(manifest))
    return sha((root / "dataset-manifest.json").read_bytes())


def build_package(tmp_path: Path, records=RECORDS) -> V3Package:
    root = tmp_path / "v3-package"
    work = tmp_path / "work"
    rows: dict[str, list[list[dict]]] = {}
    for index, (split, language, label) in enumerate(records):
        name = f"{split}-{language}-{index}"
        made = relation_record(work, root, name, split, language, label)
        for kind, row in zip(("inputs", "labels", "annotations", "metadata"), made, strict=True):
            rows.setdefault(split, [[], [], [], []])[
                ("inputs", "labels", "annotations", "metadata").index(kind)
            ].append(row)
    for split, (inputs, labels, annotations, metadata) in rows.items():
        names = split_files(split)
        write_jsonl(root / names["inputs"], inputs)
        write_jsonl(root / names["labels"], labels)
        write_jsonl(root / names["annotations"], annotations)
        write_jsonl(root / names["metadata"], metadata)
    return V3Package(root, seal(root))


def run_module(module: str, *args: object, audit_log: Path | None = None):
    """Run a production CLI in a fresh interpreter; optionally record every file opened."""
    if audit_log is None:
        command = [sys.executable, "-m", module, *map(str, args)]
    else:
        hook = (
            "import os, runpy, sys\n"
            f"log = open({str(audit_log)!r}, 'a', encoding='utf-8')\n"
            "def record(event, values):\n"
            "    if event == 'open' and isinstance(values[0], (str, bytes, os.PathLike)):\n"
            "        log.write(os.path.realpath(os.fsdecode(values[0])) + '\\n'); log.flush()\n"
            "sys.addaudithook(record)\n"
            f"sys.argv = [{module!r}, *sys.argv[1:]]\n"
            f"runpy.run_module({module!r}, run_name='__main__', alter_sys=True)\n"
        )
        command = [sys.executable, "-c", hook, *map(str, args)]
    return subprocess.run(command, capture_output=True, text=True, check=False, cwd=ROOT)


def opened_paths(audit_log: Path) -> set[Path]:
    return {Path(line) for line in audit_log.read_text().splitlines()} if audit_log.exists() else set()


def held_out_files(package: V3Package) -> set[Path]:
    root = package.root.resolve()
    return {
        path.resolve()
        for path in root.rglob("*")
        if path.is_file()
        and (
            path.relative_to(root).as_posix().startswith("data/test.")
            or path.relative_to(root).as_posix().startswith("audit/test/")
        )
    }


def gold_predictions(package: V3Package, split: str, path: Path) -> Path:
    """Producer side: a format sample built from the split's own labels (not a model)."""
    names = split_files(split)
    labels = {row["record_id"]: row for row in jsonl(package.root / names["labels"])}
    rows = []
    for row in jsonl(package.root / names["inputs"]):
        label = labels[row["record_id"]]
        candidates = row["model_input"]["evidence"]["candidate_evidence"]
        rows.append(
            {
                "return_schema_version": 3,
                "record_id": row["record_id"],
                "input_hash": row["input_hash"],
                "model_revision": "format-example",
                "task_type": "relation",
                "status": "ok",
                "probabilities": [float(i == label["label_index"]) for i in range(3)],
                "label": label["label"],
                "evidence_ids": list(label["evidence_ids"]),
                "evidence_bindings": [
                    {"candidate_id": c["id"], "candidate_sha256": C.digest(c)}
                    for c in candidates
                    if c["id"] in label["evidence_ids"]
                ],
                "reason": "synthetic format sample from labels",
            }
        )
    write_jsonl(path, rows)
    return path


REGISTRY_CLI = "career_lab.models.v3.registry_cli"


def verify(package: V3Package, predictions: Path, *extra: object, audit_log: Path | None = None):
    response = run_module(
        REGISTRY_CLI,
        "verify-return",
        "--dataset-root",
        package.root,
        "--dataset-hash",
        package.checksum,
        "--predictions",
        predictions,
        *extra,
        audit_log=audit_log,
    )
    assert response.stdout.strip(), response.stderr
    return response.returncode, json.loads(response.stdout)


def test_held_01_v3_dev_review_never_opens_a_test_file(tmp_path: Path) -> None:
    package = build_package(tmp_path)
    predictions = gold_predictions(package, "dev", tmp_path / "predictions.dev.jsonl")
    log = tmp_path / "opened.log"
    code, report = verify(package, predictions, audit_log=log)
    assert code == 0, report
    assert report["status"] == "partial"
    assert report["layout"] == LAYOUT
    assert report["split"] == "dev"
    assert report["held_out_test_opened"] is False and report["opened"] is None
    for language in ("zh", "en"):
        assert report["languages"][language]["status"] == "recomputed"
        assert report["languages"][language]["metrics"]["count"] == 2
        assert report["languages"][language]["metrics"]["joint_correctness"] == 1
    opened = opened_paths(log)
    root = package.root.resolve()
    assert {root / name for name in split_files("dev").values()} <= opened
    assert not opened & held_out_files(package)
    assert not opened & {root / name for name in split_files("train").values()}


@pytest.mark.parametrize(
    ("fault", "code"),
    [
        ("test_file_in_dev", "dataset_split_file_outside_partition"),
        ("split_file_at_top_level", "dataset_split_file_not_isolated"),
        ("test_not_sealed", "dataset_test_split_must_be_sealed"),
        ("missing_split_file", "dataset_split_files_incomplete"),
    ],
)
def test_held_01_v3_structure_is_checked_before_any_split_file_is_read(
    tmp_path: Path, fault: str, code: str
) -> None:
    package = build_package(tmp_path)
    manifest_path = package.root / "dataset-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if fault == "test_file_in_dev":
        name = "data/test.labels.jsonl"
        manifest["splits"]["dev"]["files"][name] = manifest["splits"]["test"]["files"].pop(name)
    elif fault == "split_file_at_top_level":
        name = "data/test.labels.jsonl"
        manifest["files"][name] = manifest["splits"]["test"]["files"].pop(name)
    elif fault == "test_not_sealed":
        manifest["test_sealed"] = False
    else:
        manifest["splits"]["dev"]["files"].pop("audit/dev/annotations.jsonl")
    manifest_path.write_bytes(json_bytes(manifest))
    package = V3Package(package.root, sha(manifest_path.read_bytes()))
    predictions = gold_predictions(package, "dev", tmp_path / "predictions.dev.jsonl")
    log = tmp_path / "opened.log"
    status, report = verify(package, predictions, audit_log=log)
    assert status == 2
    assert report["error"] == code
    root = package.root.resolve()
    split_paths = {
        root / name for split in ("train", "dev", "test") for name in split_files(split).values()
    }
    assert not opened_paths(log) & (split_paths | held_out_files(package))


DATASETS_CLI = "career_lab.datasets.v3"
TRAIN_DEV = tuple(row for row in RECORDS if row[0] != "test")


def validate(package_root: Path, output: Path, *extra: object, audit_log: Path | None = None):
    response = run_module(
        DATASETS_CLI,
        "validate-handoff",
        "--package",
        package_root,
        "--output",
        output,
        *extra,
        audit_log=audit_log,
    )
    assert response.stdout.strip(), response.stderr
    return response.returncode, json.loads(response.stdout)


def test_data_06_v3_train_and_dev_align_per_split_and_trace_both_passes_by_language(
    tmp_path: Path,
) -> None:
    package = build_package(tmp_path, TRAIN_DEV)
    code, report = validate(package.root, tmp_path / "review")
    assert code == 0, report
    assert report["layout"] == LAYOUT
    assert report["sealed_test"] is None
    assert {row["status"] for row in report["records"]} == {"accept"}
    assert report["counts"] == {"accept": len(TRAIN_DEV)}
    assert report["training_ready"] is False
    trace = report["annotation_trace"]
    expected = {
        language: sorted(
            f"{split}-{lang}-{index}"
            for index, (split, lang, _) in enumerate(TRAIN_DEV)
            if lang == language
        )
        for language in ("zh", "en")
    }
    assert {language: [row["record_id"] for row in rows] for language, rows in trace.items()} == (
        expected
    )
    for language, rows in trace.items():
        split_of = {f"{s}-{lang}-{i}": s for i, (s, lang, _) in enumerate(TRAIN_DEV)}
        for row in rows:
            split = split_of[row["record_id"]]
            assert row["split"] == split and row["language"] == language
            assert row["label_tier"] == "G2v" and row["status"] == "accept"
            inputs = {r["record_id"]: r for r in jsonl(package.root / f"data/{split}.inputs.jsonl")}
            assert row["input_hash"] == inputs[row["record_id"]]["input_hash"]
            assert [p["prompt_revision"] for p in row["passes"]] == [
                "w07-review-a-v1",
                "w07-review-b-v1",
            ]
            for item in row["passes"]:
                assert item["input_hash"] == row["input_hash"]
                assert item["model_revision"] == "test-double-model-v1"
                assert item["evidence_order"] and item["invocation_id"]
                artifact = package.root / item["artifact"]["path"]
                assert item["artifact"]["path"].startswith(f"audit/{split}/labels/passes/")
                assert item["artifact"]["sha256"] == sha(artifact.read_bytes())
                stored = json.loads(artifact.read_bytes())["pass"]
                assert stored["id"] == item["id"] and stored["input_hash"] == row["input_hash"]
                assert item["raw_output_sha256"] == sha(stored["raw_output"].encode())


@pytest.mark.parametrize(
    ("fault", "outcome"),
    [
        ("label_hash", ("dev-en-3", "quarantine", "handoff_label_identity_mismatch")),
        ("pass_in_other_split", ("dev-zh-2", "pending", None)),
        ("source_in_other_split", ("dev-en-5", "quarantine", "handoff_source_outside_split")),
        ("card_label_tiers", ("error", "handoff_data_card_mismatch")),
        ("metadata_split", ("error", "handoff_split_mismatch")),
        ("tiers_missing", ("error", "handoff_label_tiers_required")),
    ],
)
def test_data_06_v3_misalignment_is_reported_per_record_or_per_package(
    tmp_path: Path, fault: str, outcome: tuple
) -> None:
    package = build_package(tmp_path, TRAIN_DEV)
    root = package.root
    declared = None
    if fault == "label_hash":
        labels = jsonl(root / "data/dev.labels.jsonl")
        labels[1]["input_hash"] = "0" * 64
        write_jsonl(root / "data/dev.labels.jsonl", labels)
    elif fault == "pass_in_other_split":
        annotation = next(
            row for row in jsonl(root / "audit/dev/annotations.jsonl") if row["record_id"] == "dev-zh-2"
        )
        moved = annotation["passes"][1]["id"] + ".json"
        (root / "audit/dev/labels/passes" / moved).rename(root / "audit/train/labels/passes" / moved)
    elif fault == "source_in_other_split":
        metadata = jsonl(root / "audit/dev/metadata.jsonl")
        row = next(m for m in metadata if m["record_id"] == "dev-en-5")
        target = root / "audit/train/sources/dev-en-5/source.json"
        target.parent.mkdir(parents=True)
        (root / "audit/dev/sources/dev-en-5/source.json").rename(target)
        row["packaged_sources"][0]["path"] = "audit/train/sources/dev-en-5/source.json"
        write_jsonl(root / "audit/dev/metadata.jsonl", metadata)
    elif fault == "metadata_split":
        metadata = jsonl(root / "audit/dev/metadata.jsonl")
        metadata[0]["split"] = "train"
        write_jsonl(root / "audit/dev/metadata.jsonl", metadata)
    elif fault in {"card_label_tiers", "tiers_missing"}:
        declared = {
            split: counts(
                jsonl(root / f"data/{split}.labels.jsonl"),
                jsonl(root / f"audit/{split}/metadata.jsonl"),
            )
            for split in ("train", "dev")
        }
        if fault == "card_label_tiers":
            declared["dev"]["label_tiers"] = {"G0": 4}
        else:
            del declared["dev"]["label_tiers"]
    checksum = seal(root, declared=declared)
    assert checksum
    if fault == "card_label_tiers":
        # The manifest keeps the true counts; only the card disagrees.
        manifest_path = root / "dataset-manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["splits"]["dev"]["label_tiers"] = {"G2v": 4}
        manifest_path.write_bytes(json_bytes(manifest))
    code, report = validate(root, tmp_path / "review")
    assert code == 2
    if outcome[0] == "error":
        assert report["error"] == outcome[1]
        return
    record_id, status, reason = outcome
    result = {row["record_id"]: row for row in report["records"]}[record_id]
    assert result["status"] == status, result
    if reason:
        assert reason in result["reasons"]
    others = [row for row in report["records"] if row["record_id"] != record_id]
    assert {row["status"] for row in others} == {"accept"}


def unreadable_test_payloads(package: V3Package) -> str:
    """Replace every sealed test payload except metadata with non-JSON bytes; reseal.

    A reviewer that parsed any of them would fail; the declared counts stay the producer's.
    """
    root = package.root
    declared = counts(
        jsonl(root / "data/test.labels.jsonl"), jsonl(root / "audit/test/metadata.jsonl")
    )
    names = split_files("test")
    for kind in ("inputs", "labels", "annotations"):
        path = root / names[kind]
        lines = path.read_text().splitlines()
        path.write_text("".join(f"sealed {kind} line {i} {{not json\n" for i in range(len(lines))))
    for path in (root / "audit/test/labels/passes").iterdir():
        path.write_text("sealed call record {not json")
    return seal(root, declared={"test": declared})


def test_seal_01_sealed_test_is_checked_by_hash_count_and_structure_without_parsing_labels(
    tmp_path: Path,
) -> None:
    package = build_package(tmp_path)
    checksum = unreadable_test_payloads(package)
    code, report = validate(package.root, tmp_path / "review")
    assert code == 0, report
    assert checksum == sha((package.root / "dataset-manifest.json").read_bytes())
    assert {row["record_id"].split("-")[0] for row in report["records"]} == {"train", "dev"}
    assert {row["status"] for row in report["records"]} == {"accept"}
    sealed = report["sealed_test"]
    assert sealed["split"] == "test" and sealed["records"] == 2
    assert sealed["labels_parsed"] is False and sealed["inputs_parsed"] is False
    assert sealed["verified"] == [
        "file_hashes",
        "line_counts",
        "metadata_split",
        "language_counts",
        "record_and_input_isolation",
        "component_and_structure_isolation",
    ]
    assert sealed["declared_only"] == ["labels", "label_tiers", "evidence_evaluable", "label_only"]
    manifest = json.loads((package.root / "dataset-manifest.json").read_bytes())
    assert sealed["files"] == {
        name: entry["sha256"] for name, entry in manifest["splits"]["test"]["files"].items()
    }
    assert all(row["split"] != "test" for rows in report["annotation_trace"].values() for row in rows)


@pytest.mark.parametrize(
    ("fault", "code"),
    [
        ("line_count", "handoff_sealed_count_mismatch"),
        ("component", "handoff_component_cross_split"),
        ("structure", "handoff_structure_cross_split"),
        ("record_id", "handoff_record_cross_split"),
        ("language", "handoff_count_mismatch"),
        ("source_split", "handoff_source_outside_split"),
        ("bytes", "file_hash_mismatch"),
    ],
)
def test_seal_01_sealed_test_isolation_faults_are_rejected(
    tmp_path: Path, fault: str, code: str
) -> None:
    package = build_package(tmp_path)
    unreadable_test_payloads(package)
    root = package.root
    metadata_path = root / "audit/test/metadata.jsonl"
    metadata = jsonl(metadata_path)
    dev = jsonl(root / "audit/dev/metadata.jsonl")
    if fault == "line_count":
        path = root / "data/test.labels.jsonl"
        path.write_text("".join(path.read_text().splitlines(keepends=True)[:1]))
    elif fault == "component":
        metadata[0]["connected_component_id"] = dev[0]["connected_component_id"]
    elif fault == "structure":
        metadata[0]["lineage"]["structure_id"] = dev[0]["lineage"]["structure_id"]
    elif fault == "record_id":
        metadata[0]["record_id"] = dev[0]["record_id"]
    elif fault == "language":
        metadata[0]["language"] = "en" if metadata[0]["language"] == "zh" else "zh"
    elif fault == "source_split":
        metadata[0]["packaged_sources"][0]["path"] = dev[0]["packaged_sources"][0]["path"]
    write_jsonl(metadata_path, metadata)
    if fault != "bytes":
        manifest = json.loads((root / "dataset-manifest.json").read_bytes())
        declared = {
            k: v for k, v in manifest["splits"]["test"].items() if k != "files"
        }
        seal(root, declared={"test": declared})
    else:
        path = root / "data/test.labels.jsonl"
        path.write_bytes(path.read_bytes().replace(b"line 0", b"line 9"))
    status, report = validate(root, tmp_path / "review")
    assert status == 2
    assert report["error"] == code


def test_seal_01_record_level_test_review_needs_the_approved_opening(tmp_path: Path) -> None:
    package = build_package(tmp_path)
    unreadable_test_payloads(package)
    manifest = tmp_path / "return" / "checkpoint-manifest.json"
    manifest.parent.mkdir()
    manifest.write_text("{}")
    status, report = validate(
        package.root, tmp_path / "review", "--split", "test", "--checkpoint-manifest", manifest
    )
    assert status == 2
    assert report["error"] == "held_out_test_sealed"
    assert not (tmp_path / "review").exists()


@dataclass(frozen=True)
class Opening:
    """Everything one approved test opening needs, as the coordinator would prepare it."""

    package: V3Package
    registry: Path
    registration: C.FileRef
    checkpoint: Path
    predictions: Path
    freeze: Path
    campaign: Path
    ledger: Path

    def args(self, **overrides: object) -> list[str]:
        values: dict[str, object] = {
            "--partition": "test",
            "--checkpoint-manifest": self.checkpoint,
            "--registry": self.registry,
            "--registration-path": self.registration.path,
            "--registration-hash": self.registration.sha256,
            "--freeze": self.freeze,
            "--freeze-hash": sha(self.freeze.read_bytes()),
            "--campaign": self.campaign,
            "--campaign-hash": sha(self.campaign.read_bytes()),
            "--ledger": self.ledger,
            "--operator": "coordinator-147",
        }
        values.update(overrides)
        return [str(item) for key, value in values.items() if value is not None for item in (key, value)]

    @property
    def record(self) -> Path:
        return self.ledger / self.package.checksum / "test.json"


def checkpoint_manifest(path: Path, package: V3Package, model_revision: str, **changes) -> Path:
    """The responsible party's declaration: dev selection, no test use."""
    manifest = {
        "template": False,
        "completed": True,
        "return_protocol": "rolecraft-label-evidence-v2",
        "task_type": "relation",
        "label_order": RELATION,
        "dataset_id": "rolecraft-synthetic-v3-mechanism",
        "dataset_manifest_sha256": package.checksum,
        "model_revision": model_revision,
        "framework": "synthetic",
        "framework_version": "1",
        "evidence_selection_implemented": True,
        "evidence_selection_required": True,
        "training_partitions": ["train"],
        "selection_partition": "dev",
        "test_used_for_selection": False,
        "load_and_predict_command": "metadata only, never executed",
        "training_notes_file": "notes.md",
        "predictions_file": "predictions.dev.jsonl",
        "checkpoint_files": {},
    } | changes
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(manifest))
    return path


def approve(freeze_root: Path, candidate: C.CampaignCandidate, package: V3Package, **changes) -> Path:
    """What the coordinator writes after the user confirms this one opening in chat."""
    campaign = C.TestCampaign(
        id="synthetic-campaign-147",
        candidates=(candidate,),
        split_manifest=C.FileRef(path="dataset-manifest.json", sha256=package.checksum),
        frozen_at="2026-10-12T08:00:00Z",
        opened_at="2026-10-12T09:00:00Z",
        output_audience=("coordinator",),
    ).model_copy(update=changes)
    path = freeze_root / "campaign.json"
    path.write_bytes(json_bytes(campaign))
    return path


def prepared_opening(tmp_path: Path, *, status: str = SYNTHETIC_STATUS, **campaign) -> Opening:
    package = build_package(tmp_path)
    if status != SYNTHETIC_STATUS:
        package = V3Package(package.root, seal(package.root, status=status))
    registry, registration = linear_registration(tmp_path / "model")
    predictions = tmp_path / "return" / "predictions.test.jsonl"
    predictions.parent.mkdir(parents=True, exist_ok=True)
    rows = model_predictions(registry, registration, package.root / "data/test.inputs.jsonl")
    write_jsonl(predictions, rows)
    checkpoint = checkpoint_manifest(
        tmp_path / "return" / "checkpoint-manifest.json", package, rows[0]["model_revision"]
    )
    prepared = prepare_test_freeze(
        tmp_path / "freeze",
        dataset_root=package.root,
        dataset_hash=package.checksum,
        registry_root=registry,
        registration=registration,
        checkpoint_manifest=checkpoint,
        source=C.SourceIdentity(
            base_commit="b" * 40,
            source_digest=C.digest("synthetic producer source"),
            overlay=C.FileRef(path="source/freeze-record.json", sha256=sha(SOURCE_RECORD)),
            dependency_locks=(C.FileRef(path="source/requirements.lock", sha256=sha(LOCK)),),
        ),
        source_files={"source/freeze-record.json": SOURCE_RECORD, "source/requirements.lock": LOCK},
        candidate_id="synthetic-candidate-147",
        budget=C.Budget(model_calls=0, actions=0, wall_seconds=600),
    )
    campaign_path = approve(prepared.root, prepared.candidate, package, **campaign)
    return Opening(
        package,
        registry,
        registration,
        checkpoint,
        predictions,
        prepared.root / prepared.freeze.path,
        campaign_path,
        tmp_path / "ledger",
    )


SOURCE_RECORD = json_bytes({"producer": "synthetic", "note": "constructed, no training"})
LOCK = b"synthetic==1\n"


def test_held_04_first_approved_opening_is_recorded_before_test_is_read(tmp_path: Path) -> None:
    opening = prepared_opening(tmp_path)
    log = tmp_path / "opened.log"
    code, report = verify(opening.package, opening.predictions, *opening.args(), audit_log=log)
    assert code == 0, report
    assert report["split"] == "test" and report["held_out_test_opened"] is True
    assert report["status"] == "partial"
    assert report["scope"] == "synthetic_fixture" and report["quality_validated"] is False
    assert report["reload"]["status"] == "matched"
    for language in ("zh", "en"):
        assert report["languages"][language]["status"] == "recomputed"
        assert report["languages"][language]["metrics"]["count"] == 1
    record = json.loads(opening.record.read_bytes())
    assert report["opened"] == record
    assert record["protocol"] == "rolecraft-held-out-test-opening-v1"
    assert record["dataset_manifest_sha256"] == opening.package.checksum
    assert record["campaign"] == {
        "id": "synthetic-campaign-147",
        "path": "campaign.json",
        "sha256": sha(opening.campaign.read_bytes()),
    }
    assert record["candidate_id"] == "synthetic-candidate-147"
    assert record["freeze"]["sha256"] == sha(opening.freeze.read_bytes())
    assert record["freeze"]["id"] == json.loads(opening.freeze.read_bytes())["id"]
    assert record["registration"]["path"] == opening.registration.path
    assert record["registration"]["sha256"] == opening.registration.sha256
    assert record["registration"]["id"] == report["reload"]["registration"]["id"]
    assert record["operator"] == "coordinator-147"
    assert len(record["verifier_source_digest"]) == 64 and record["opened_at"]
    # The record exists before any test file is read: the first test open follows it.
    order = [line for line in log.read_text().splitlines()]
    first_test = min(order.index(str(path)) for path in held_out_files(opening.package) if str(path) in order)
    assert str(opening.record.resolve()) in order[:first_test]


def test_held_05_second_opening_is_refused_before_any_test_byte_is_read(tmp_path: Path) -> None:
    opening = prepared_opening(tmp_path)
    code, first = verify(opening.package, opening.predictions, *opening.args())
    assert code == 0, first
    recorded = opening.record.read_bytes()
    log = tmp_path / "second.log"
    code, second = verify(opening.package, opening.predictions, *opening.args(), audit_log=log)
    assert code == 2
    assert second["error"] == "held_out_test_already_opened" and second["status"] == 403
    assert not opened_paths(log) & held_out_files(opening.package)
    assert opening.record.read_bytes() == recorded
    # A different operator or a new campaign file does not reopen the same dataset either.
    other = approve(opening.campaign.parent, json_candidate(opening), opening.package, id="again")
    code, third = verify(
        opening.package,
        opening.predictions,
        *opening.args(**{"--operator": "someone-else", "--campaign": other}),
        audit_log=log,
    )
    assert code == 2 and third["error"] == "held_out_test_already_opened"
    assert not opened_paths(log) & held_out_files(opening.package)


def json_candidate(opening: Opening) -> C.CampaignCandidate:
    campaign = C.TestCampaign.model_validate_json(opening.campaign.read_bytes())
    return campaign.candidates[0]


def test_held_05_a_failed_review_after_opening_keeps_the_record_and_is_not_retried(
    tmp_path: Path,
) -> None:
    opening = prepared_opening(tmp_path)
    rows = jsonl(opening.predictions)
    rows[0]["probabilities"] = [0.9, 0.9, 0.9]
    write_jsonl(opening.predictions, rows)
    code, report = verify(opening.package, opening.predictions, *opening.args())
    assert code == 2
    assert report["status"] == "rejected" and report["held_out_test_opened"] is True
    assert report["format_errors"][0]["record_id"] == rows[0]["record_id"]
    assert opening.record.is_file()
    write_jsonl(opening.predictions, jsonl(opening.predictions))
    code, again = verify(opening.package, opening.predictions, *opening.args())
    assert code == 2 and again["error"] == "held_out_test_already_opened"


@pytest.mark.parametrize("option", ["--confirm", "--force", "--yes", "--reopen", "--allow-reopen"])
def test_held_05_the_cli_has_no_confirmation_or_bypass_option(tmp_path: Path, option: str) -> None:
    opening = prepared_opening(tmp_path)
    response = run_module(
        REGISTRY_CLI,
        "verify-return",
        "--dataset-root",
        opening.package.root,
        "--dataset-hash",
        opening.package.checksum,
        "--predictions",
        opening.predictions,
        *opening.args(),
        option,
    )
    assert response.returncode == 2
    assert "unrecognized arguments" in response.stderr
    assert not opening.record.exists()
    help_text = run_module(REGISTRY_CLI, "verify-return", "--help").stdout
    assert all(word not in help_text for word in ("--confirm", "--force", "--yes", "--reopen"))


def refused(opening: Opening, tmp_path: Path, *args: str) -> dict:
    """Run an opening that must be refused: no record, no test file opened."""
    log = tmp_path / "refused.log"
    code, report = verify(opening.package, opening.predictions, *args, audit_log=log)
    assert code == 2, report
    assert not opening.record.exists()
    assert not opened_paths(log) & held_out_files(opening.package)
    return report


@pytest.mark.parametrize(
    "dropped",
    ["--freeze", "--freeze-hash", "--campaign", "--campaign-hash", "--ledger", "--operator",
     "--checkpoint-manifest", "--registration-hash"],
)
def test_held_02_test_without_freeze_or_campaign_is_refused(tmp_path: Path, dropped: str) -> None:
    opening = prepared_opening(tmp_path)
    report = refused(opening, tmp_path, *opening.args(**{dropped: None}))
    assert report["error"] == "held_out_test_authorization_required"
    assert report["status"] == 403 and dropped in report["message"]


def test_held_02_an_unapproved_campaign_cannot_open_test(tmp_path: Path) -> None:
    opening = prepared_opening(tmp_path, opened_at=None)
    report = refused(opening, tmp_path, *opening.args())
    assert report["error"] == "campaign_not_authorized" and report["status"] == 403


def test_held_02_a_v2_portable_package_has_no_test_to_open(tmp_path: Path) -> None:
    opening = prepared_opening(tmp_path)
    manifest_path = opening.package.root / "dataset-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest.pop("layout")
    manifest_path.write_bytes(json_bytes(manifest))
    package = V3Package(opening.package.root, sha(manifest_path.read_bytes()))
    log = tmp_path / "v2.log"
    code, report = verify(package, opening.predictions, *opening.args(), audit_log=log)
    assert code == 2 and report["error"] == "held_out_layout_required"
    assert not opened_paths(log) & held_out_files(package)


def manual_freeze(
    opening: Opening, root: Path, *, policy: bytes | None = None, fixture: bool = False
) -> tuple[Path, Path]:
    """A freeze built directly with the existing freeze protocol, to vary one pinned fact."""
    package = opening.package
    members = {
        "dataset-manifest.json": (package.root / "dataset-manifest.json").read_bytes(),
        opening.registration.path: (opening.registry / opening.registration.path).read_bytes(),
        "review-policy.json": policy
        if policy is not None
        else review_policy_bytes("rolecraft-synthetic-v3-mechanism", package.checksum),
        "checkpoint-manifest.json": opening.checkpoint.read_bytes(),
        "source/freeze-record.json": SOURCE_RECORD,
        "source/requirements.lock": LOCK,
    }
    refs = []
    for name, data in members.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)
        refs.append(C.FileRef(path=name, sha256=sha(data)))
    source = json_candidate(opening).source
    candidate = json_candidate(opening).model_copy(
        update={"evaluation": C.FileRef(path="review-policy.json", sha256=sha(members["review-policy.json"]))}
    )
    freeze_selection(
        root,
        "freeze.json",
        files=refs,
        source=source,
        selection={"selection_split": "dev"},
        split_manifest=C.FileRef(path="dataset-manifest.json", sha256=package.checksum),
        fixture=fixture,
        candidates=(candidate,),
    )
    return root / "freeze.json", approve(root, candidate, package)


def test_held_03_campaign_candidate_must_be_the_registration_under_test(tmp_path: Path) -> None:
    opening = prepared_opening(tmp_path)
    root, ref = linear_bundle(tmp_path / "other-model", *LEFT_WEIGHTS)
    other = register(opening.registry, root, ref)
    report = refused(
        opening,
        tmp_path,
        *opening.args(**{"--registration-path": other.path, "--registration-hash": other.sha256}),
    )
    assert report["error"] == "held_out_campaign_candidate_mismatch" and report["status"] == 403


def test_held_03_candidate_evaluation_must_be_the_review_policy(tmp_path: Path) -> None:
    opening = prepared_opening(tmp_path)
    wrong = review_policy_bytes("another-dataset", "0" * 64)
    freeze, campaign = manual_freeze(opening, tmp_path / "freeze-wrong-policy", policy=wrong)
    report = refused(
        opening,
        tmp_path,
        *opening.args(
            **{
                "--freeze": freeze,
                "--freeze-hash": sha(freeze.read_bytes()),
                "--campaign": campaign,
                "--campaign-hash": sha(campaign.read_bytes()),
            }
        ),
    )
    assert report["error"] == "held_out_review_policy_mismatch"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"framework_version": "2"}, "held_out_checkpoint_manifest_not_frozen"),
        ({"test_used_for_selection": True}, "model_return_selection_contaminated"),
        ({"selection_partition": "test"}, "model_return_selection_contaminated"),
    ],
)
def test_held_03_the_frozen_selection_declaration_is_the_one_supplied(
    tmp_path: Path, change: dict, code: str
) -> None:
    opening = prepared_opening(tmp_path)
    checkpoint_manifest(
        opening.checkpoint,
        opening.package,
        jsonl(opening.predictions)[0]["model_revision"],
        **change,
    )
    report = refused(opening, tmp_path, *opening.args())
    assert report["error"] == code and report["status"] == 403


def test_held_03_a_campaign_outside_the_freeze_root_is_refused(tmp_path: Path) -> None:
    opening = prepared_opening(tmp_path)
    moved = tmp_path / "elsewhere" / "campaign.json"
    moved.parent.mkdir()
    moved.write_bytes(opening.campaign.read_bytes())
    report = refused(opening, tmp_path, *opening.args(**{"--campaign": moved}))
    assert report["error"] == "held_out_campaign_outside_freeze_root"


def test_held_06_a_fixture_dataset_cannot_authorize_an_opening(tmp_path: Path) -> None:
    opening = prepared_opening(tmp_path, status="FIXTURE_ONLY_NOT_FINAL_TRAINING_DATA")
    frozen = json.loads(opening.freeze.read_bytes())
    assert frozen["fixture"] is True
    report = refused(opening, tmp_path, *opening.args())
    assert report["error"] == "fixture_cannot_authorize_confirmatory" and report["status"] == 403


def test_held_06_a_fixture_freeze_cannot_approve_even_a_real_package(tmp_path: Path) -> None:
    opening = prepared_opening(tmp_path)
    freeze, campaign = manual_freeze(opening, tmp_path / "fixture-freeze", fixture=True)
    report = refused(
        opening,
        tmp_path,
        *opening.args(
            **{
                "--freeze": freeze,
                "--freeze-hash": sha(freeze.read_bytes()),
                "--campaign": campaign,
                "--campaign-hash": sha(campaign.read_bytes()),
            }
        ),
    )
    assert report["error"] == "fixture_cannot_authorize_confirmatory"


def declared_model_return(tmp_path: Path, package: V3Package, version: int) -> Path:
    """A metadata-only model return over the v3 dev split (no model is loaded)."""
    out = tmp_path / f"model-return-v{version}"
    out.mkdir()
    files = {"weights.bin": b"synthetic bytes", "settings.json": b"{}", "vocab.txt": b"tokens"}
    for name, raw in files.items():
        (out / name).write_bytes(raw)
    (out / "notes.md").write_text("Constructed bytes only; no training occurred.")
    rows = jsonl(gold_predictions(package, "dev", out / "predictions.jsonl"))
    for row in rows:
        row["return_schema_version"] = version
        row["model_revision"] = "synthetic-return-v1"
    write_jsonl(out / "predictions.jsonl", rows)
    manifest = checkpoint_manifest(
        out / "checkpoint-manifest.json",
        package,
        "synthetic-return-v1",
        checkpoint_files={name: sha(raw) for name, raw in files.items()},
        predictions_file="predictions.jsonl",
        artifact_roles={
            "checkpoint": ["weights.bin"],
            "config": ["settings.json"],
            "tokenizer": ["vocab.txt"],
        },
    )
    return manifest


@pytest.mark.parametrize("version", [2, 3])
def test_pred_01_validate_handoff_reads_v2_and_v3_relation_rows_alike(
    tmp_path: Path, version: int
) -> None:
    package = build_package(tmp_path, TRAIN_DEV)
    manifest = declared_model_return(tmp_path, package, version)
    code, report = validate(
        package.root, tmp_path / "review", "--checkpoint-manifest", manifest, "--split", "dev"
    )
    assert code == 0, report
    assert report["model_return"]["format_valid"] is True
    assert {row["status"] for row in report["model_return"]["records"]} == {"accept"}
