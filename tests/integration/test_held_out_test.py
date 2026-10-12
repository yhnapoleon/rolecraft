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
