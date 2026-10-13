"""The v3 return package used end to end the way the responsible party would (161).

PLUG-06: one approval opens the sealed test once per candidate, a fusion included, through
the declaration manifest test-opening-v1.md asks for. PLUG-07: the linear reference export
writes the training-notes template and test rows in the dev format. Synthetic mechanism
samples only (constructed or fixture-fitted weights); nothing here is quality evidence.
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from career_lab.contracts import v2 as C
from career_lab.models.v3.bundle import json_bytes, sha
from career_lab.models.v3.held_out import prepare_test_freeze
from career_lab.models.v3.registry import describe_registration, register_bundle, register_fusion
from tests.integration.test_fusion_registration import second_weights
from tests.integration.test_held_out_test import (
    LOCK,
    SOURCE_RECORD,
    V3Package,
    build_package,
    jsonl,
    validate,
    verify,
    write_jsonl,
)
from tests.integration.test_linear_return import fitted_mechanism
from tests.integration.test_model_return_verification import model_predictions
from tests.support.linear_return import (
    ALPHA_GRID,
    reference_module,
    selection_record,
    write_linear_return,
)
from tests.unit.test_w08_models import examples

DATASET_ID = "rolecraft-synthetic-v3-mechanism"
RELATION = ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"]
# Registration checks the selection record's structure only; verify-return recomputes metrics.
PLACEHOLDER_METRICS = {
    "count": 4,
    "macro_f1": 0.5,
    "mean_evidence_f1": 0.4,
    "joint_correctness": 0.3,
    "evidence_denominator": 4,
    "joint_denominator": 4,
}


def fusion_declaration(root: Path, package: V3Package, revision: str, selection: Path) -> Path:
    """The fusion's checkpoint-manifest.json as test-opening-v1.md section 2.3 writes it:
    the producer's own selection declaration for the fused revision; no weights."""
    root.mkdir(parents=True)
    (root / "fusion-selection.json").write_bytes(selection.read_bytes())
    (root / "training-notes.md").write_text("Fusion of two registered components; dev only.\n")
    manifest = {
        "template": False,
        "completed": True,
        "return_protocol": "rolecraft-label-evidence-v2",
        "artifact_kind": "probability_fusion",
        "model_revision": revision,
        "framework": "rolecraft-probability-fusion",
        "framework_version": "1",
        "task_type": "relation",
        "label_order": RELATION,
        "dataset_id": DATASET_ID,
        "dataset_manifest_sha256": package.checksum,
        "training_partitions": ["train"],
        "selection_partition": "dev",
        "test_used_for_selection": False,
        "evidence_selection_implemented": True,
        "evidence_selection_required": True,
        "checkpoint_files": {
            name: sha((root / name).read_bytes())
            for name in ("fusion-selection.json", "training-notes.md")
        },
        "load_and_predict_command": "not executed: RoleCraft builds the fusion from its registry",
        "training_notes_file": "training-notes.md",
        "predictions_file": "predictions.dev.jsonl",
    }
    (root / "checkpoint-manifest.json").write_bytes(json_bytes(manifest))
    return root / "checkpoint-manifest.json"


def freeze(
    tmp_path: Path, name: str, package: V3Package, registry: Path, ref: C.FileRef, manifest: Path
):
    return prepare_test_freeze(
        tmp_path / ("freeze-" + name),
        dataset_root=package.root,
        dataset_hash=package.checksum,
        registry_root=registry,
        registration=ref,
        checkpoint_manifest=manifest,
        source=C.SourceIdentity(
            base_commit="b" * 40,
            source_digest=C.digest("synthetic producer source"),
            overlay=C.FileRef(path="source/freeze-record.json", sha256=sha(SOURCE_RECORD)),
            dependency_locks=(C.FileRef(path="source/requirements.lock", sha256=sha(LOCK)),),
        ),
        source_files={"source/freeze-record.json": SOURCE_RECORD, "source/requirements.lock": LOCK},
        candidate_id="candidate-" + name,
        budget=C.Budget(model_calls=0, actions=0, wall_seconds=600),
    )


def opening_args(prepared, ref: C.FileRef, registry: Path, manifest: Path) -> list[Any]:
    freeze_path = prepared.root / prepared.freeze.path
    campaign = prepared.root / "campaign.json"
    return [
        "--partition",
        "test",
        "--checkpoint-manifest",
        manifest,
        "--registry",
        registry,
        "--registration-path",
        ref.path,
        "--registration-hash",
        ref.sha256,
        "--freeze",
        freeze_path,
        "--freeze-hash",
        sha(freeze_path.read_bytes()),
        "--campaign",
        campaign,
        "--campaign-hash",
        sha(campaign.read_bytes()),
        "--operator",
        "coordinator-161",
    ]


def test_plug_06_one_approval_opens_the_test_once_per_candidate_fusion_included(
    tmp_path: Path,
) -> None:
    """160 ④: two components and their fusion, each frozen in its own directory and listed
    in one campaign, open the sealed test once each; any second opening is refused."""
    package = build_package(tmp_path)
    registry = tmp_path / "registry"
    dataset = {"dataset_id": DATASET_ID, "dataset_sha": package.checksum}
    candidates: dict[str, tuple[C.FileRef, Path]] = {}
    # Threshold 0 selects every candidate, so no supported or contradicted test row lacks
    # evidence (that would be a format error, not what this test is about).
    head = {"kind": "pair_logistic", "vectorizer": "shared", "threshold": 0.0}
    for name, arrays in (("left", None), ("right", second_weights())):
        root = tmp_path / name
        ref = register_bundle(
            registry,
            root,
            write_linear_return(root, arrays=arrays, model={"evidence_head": head}, **dataset),
            scope="synthetic_fixture",
        )
        candidates[name] = (ref, root / "checkpoint-manifest.json")
    identities = [describe_registration(registry, ref).identity() for ref, _ in candidates.values()]
    points = [
        {"alpha": alpha, "evidence_threshold": 0.0, "metrics": PLACEHOLDER_METRICS}
        for alpha in ALPHA_GRID
    ]
    record = selection_record(
        *identities, threshold=0.0, evidence_threshold_grid=[0.0], points=points
    )
    selection = tmp_path / "selection.json"
    selection.write_bytes(json_bytes(record))
    fused = register_fusion(
        registry,
        candidates["left"][0],
        candidates["right"][0],
        selection,
        scope="synthetic_fixture",
    )
    revision = describe_registration(registry, fused).model_revision
    candidates["fusion"] = (
        fused,
        fusion_declaration(tmp_path / "fusion-return", package, revision, selection),
    )
    prepared, rows = {}, {}
    for name, (ref, manifest) in candidates.items():
        prepared[name] = freeze(tmp_path, name, package, registry, ref, manifest)
        rows[name] = tmp_path / f"{name}.test.jsonl"
        write_jsonl(
            rows[name], model_predictions(registry, ref, package.root / "data/test.inputs.jsonl")
        )
    # One user confirmation: one campaign naming all three, the same bytes in each freeze.
    campaign = json_bytes(
        C.TestCampaign(
            id="one-approval-161",
            candidates=tuple(item.candidate for item in prepared.values()),
            split_manifest=C.FileRef(path="dataset-manifest.json", sha256=package.checksum),
            frozen_at="2026-10-13T08:00:00Z",
            opened_at="2026-10-13T09:00:00Z",
            output_audience=("coordinator",),
        )
    )
    for item in prepared.values():
        (item.root / "campaign.json").write_bytes(campaign)
    records = {}
    for name, (ref, manifest) in candidates.items():
        code, report = verify(
            package, rows[name], *opening_args(prepared[name], ref, registry, manifest)
        )
        assert code == 0, (name, report)
        assert report["held_out_test_opened"] is True and report["reload"]["status"] == "matched"
        records[name] = report["opened"]
    assert {record["candidate_id"] for record in records.values()} == {
        "candidate-left",
        "candidate-right",
        "candidate-fusion",
    }
    assert {record["campaign_sha256"] for record in records.values()} == {sha(campaign)}
    assert records["fusion"]["registration"]["path"] == fused.path
    for name, (ref, manifest) in candidates.items():
        code, again = verify(
            package, rows[name], *opening_args(prepared[name], ref, registry, manifest)
        )
        assert code == 2 and again["error"] == "held_out_test_already_opened", name


def linear_export(tmp_path: Path, package: V3Package) -> tuple[Any, dict, Path]:
    exporter = reference_module("export_sklearn_linear")
    objects = fitted_mechanism("shared_char_wb")
    target = tmp_path / "linear-return"
    exporter.export_linear_return(
        target,
        **objects,
        evidence_threshold=0.0,
        dataset_manifest=package.root / "dataset-manifest.json",
        dev_inputs=package.root / "data/dev.inputs.jsonl",
        training_notes_file="training-notes.md",
    )
    return exporter, objects, target


def test_plug_07_linear_export_writes_the_training_notes_template(tmp_path: Path) -> None:
    """160 C2: the export left training-notes.md to be hand-written; validate-handoff reads it."""
    package = build_package(tmp_path)
    _, _, target = linear_export(tmp_path, package)
    notes = (target / "training-notes.md").read_text(encoding="utf-8")
    for heading in ("model_revision", "dataset_manifest_sha256", "training_partitions"):
        assert heading in notes
    manifest = json.loads((target / "checkpoint-manifest.json").read_bytes())
    assert manifest["model_revision"] in notes
    code, report = validate(
        package.root,
        tmp_path / "review",
        "--checkpoint-manifest",
        target / "checkpoint-manifest.json",
    )
    assert code == 0, report
    assert report["model_return"]["format_valid"] is True


def test_plug_07_linear_test_rows_have_the_dev_format_and_open_the_test(tmp_path: Path) -> None:
    """The test entry writes rows like the dev rows (partition=test), outside the return."""
    package = build_package(tmp_path)
    exporter, objects, target = linear_export(tmp_path, package)
    with pytest.raises(exporter.ExportError, match="prediction_output_inside_return"):
        exporter.write_predictions(
            target,
            **objects,
            inputs=package.root / "data/test.inputs.jsonl",
            output=target / "predictions.test.jsonl",
        )
    assert not (target / "predictions.test.jsonl").exists()
    rows_path = tmp_path / "predictions.test.jsonl"
    summary = exporter.write_predictions(
        target, **objects, inputs=package.root / "data/test.inputs.jsonl", output=rows_path
    )
    rows, dev = jsonl(rows_path), jsonl(target / "predictions.dev.jsonl")
    assert summary["predictions"] == len(rows) == 2
    assert {tuple(sorted(row)) for row in rows} == {tuple(sorted(row)) for row in dev}
    assert {row["model_revision"] for row in rows} == {row["model_revision"] for row in dev}
    registry = tmp_path / "registry"
    manifest = target / "checkpoint-manifest.json"
    ref = register_bundle(
        registry,
        target,
        C.FileRef(path="checkpoint-manifest.json", sha256=sha(manifest.read_bytes())),
        scope="synthetic_fixture",
    )
    prepared = freeze(tmp_path, "linear", package, registry, ref, manifest)
    (prepared.root / "campaign.json").write_bytes(
        json_bytes(
            C.TestCampaign(
                id="linear-161",
                candidates=(prepared.candidate,),
                split_manifest=C.FileRef(path="dataset-manifest.json", sha256=package.checksum),
                frozen_at="2026-10-13T08:00:00Z",
                opened_at="2026-10-13T09:00:00Z",
                output_audience=("coordinator",),
            )
        )
    )
    code, report = verify(package, rows_path, *opening_args(prepared, ref, registry, manifest))
    assert code == 0, report
    assert report["split"] == "test" and report["reload"]["status"] == "matched"
    assert report["reload"]["max_probability_deviation"] <= 1e-6


def independent_head(objects: dict) -> dict:
    """The shared mechanism with an evidence head on its own word vocabulary, idf included."""
    reference = reference_module("linear_text_v1")
    rows = examples("train", 2)
    pairs, gold = [], []
    for row in rows:
        item = row.item.model_dump(mode="json")
        for candidate in item["evidence"]["candidate_evidence"]:
            pairs.append(reference.pair_text(item, candidate))
            gold.append(int(candidate["id"] in row.annotation.final.evidence_ids))
    vectorizer = TfidfVectorizer(analyzer="word", ngram_range=(1, 2))
    classifier = LogisticRegression(max_iter=500, random_state=5002)
    classifier.fit(vectorizer.fit_transform(pairs), gold)
    return objects | {"evidence_vectorizer": vectorizer, "evidence_classifier": classifier}


def shifted(objects: dict, name: str, attribute: str) -> dict:
    """A copy of the exported objects with one fitted array moved by one."""
    changed = copy.deepcopy(objects)
    target = changed[name]
    setattr(target, attribute, getattr(target, attribute) + 1.0)
    return changed


# (independent evidence head, objects transform, field the refusal names)
TAMPERED = {
    "coef": (False, lambda o: shifted(o, "classifier", "coef_"), "coef"),
    "intercept": (False, lambda o: shifted(o, "classifier", "intercept_"), "intercept"),
    "evidence-coef": (False, lambda o: shifted(o, "evidence_classifier", "coef_"), "evidence_coef"),
    "evidence-intercept": (
        False,
        lambda o: shifted(o, "evidence_classifier", "intercept_"),
        "evidence_intercept",
    ),
    "idf": (False, lambda o: shifted(o, "vectorizer", "idf_"), "idf"),
    "evidence-idf": (True, lambda o: shifted(o, "evidence_vectorizer", "idf_"), "evidence_idf"),
    "head-declared-shared": (
        False,
        lambda o: o | {"evidence_vectorizer": copy.deepcopy(o["vectorizer"])},
        "evidence_vectorizer",
    ),
    "head-declared-independent": (
        True,
        lambda o: o | {"evidence_vectorizer": None},
        "evidence_vectorizer",
    ),
}


@pytest.mark.parametrize("case", sorted(TAMPERED))
def test_plug_07_test_rows_need_the_exported_objects_and_write_nothing_otherwise(
    tmp_path: Path, case: str
) -> None:
    """162 P2-2: every array and the evidence head's vectorizer are checked before any row is
    written, so a mismatch cannot spend a one-time test opening."""
    package = build_package(tmp_path)
    exporter = reference_module("export_sklearn_linear")
    independent, transform, field = TAMPERED[case]
    objects = fitted_mechanism("shared_char_wb")
    if independent:
        objects = independent_head(objects)
    target = tmp_path / "linear-return"
    exporter.export_linear_return(
        target,
        **objects,
        evidence_threshold=0.0,
        dataset_manifest=package.root / "dataset-manifest.json",
        dev_inputs=package.root / "data/dev.inputs.jsonl",
        training_notes_file="training-notes.md",
    )
    output = tmp_path / "predictions.test.jsonl"
    with pytest.raises(exporter.ExportError, match=f"linear_objects_not_exported: {field} "):
        exporter.write_predictions(
            target,
            **transform(objects),
            inputs=package.root / "data/test.inputs.jsonl",
            output=output,
        )
    assert not output.exists()
    # The untouched objects still write the rows.
    exporter.write_predictions(
        target, **objects, inputs=package.root / "data/test.inputs.jsonl", output=output
    )
    assert len(jsonl(output)) == 2


@pytest.mark.parametrize(
    "name",
    ["linear/model.json", "checkpoint-manifest.json", "predictions.dev.jsonl", "../notes.md", ""],
)
def test_plug_07_a_bad_training_notes_path_is_refused_before_anything_is_written(
    tmp_path: Path, name: str
) -> None:
    """162 P3-3: the notes path is checked first; it can neither overwrite a return member nor
    leave half a return directory behind."""
    package = build_package(tmp_path)
    exporter = reference_module("export_sklearn_linear")
    target = tmp_path / "linear-return"
    with pytest.raises(exporter.ExportError, match="training_notes_path_invalid"):
        exporter.export_linear_return(
            target,
            **fitted_mechanism("shared_char_wb"),
            evidence_threshold=0.0,
            dataset_manifest=package.root / "dataset-manifest.json",
            dev_inputs=package.root / "data/dev.inputs.jsonl",
            training_notes_file=name,
        )
    assert not target.exists() and not (tmp_path / "notes.md").exists()
