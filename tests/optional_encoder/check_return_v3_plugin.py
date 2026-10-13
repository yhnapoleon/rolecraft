"""The encoder reference script, used the way a producer would, against our own receiver.

    UV_PROJECT_ENVIRONMENT=<encoder venv> uv sync --locked --extra encoder
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 <encoder venv>/bin/python -m pytest -q \\
      tests/optional_encoder/check_return_v3_plugin.py

PLUG-02..05: ``export_hf_return.py predict`` rows reload as ``matched`` in ``verify-return``,
abstain exactly where our loader abstains, ``seal`` names the artifact roles validate-handoff
needs, and the ``XLMRobertaForSequenceClassification`` recipe yields a loadable encoder. Tiny
random local weights only; no download and no model-quality claim.
"""

import json
import socket
from pathlib import Path
from typing import Any

import pytest
import torch
from transformers import (
    AutoModel,
    AutoTokenizer,
    XLMRobertaConfig,
    XLMRobertaForSequenceClassification,
    XLMRobertaModel,
)

from career_lab.contracts.v2.core import FileRef, digest
from career_lab.contracts.v2.data import RelationInput
from career_lab.contracts.v2.evaluation import EvidencePackageV2
from career_lab.models.v3.bundle import json_bytes
from career_lab.models.v3.huggingface import HuggingFaceCandidate
from career_lab.models.v3.registry import load_registration, register_bundle
from tests.integration.test_held_out_test import (
    TRAIN_DEV,
    V3Package,
    build_package,
    jsonl,
    validate,
    verify,
    write_jsonl,
)
from tests.optional_encoder.check_encoder_v3 import (
    TINY_LIMIT,
    VARIANTS,
    export,
    producer_files,
    run_export,
)
from tests.optional_encoder.tiny_return import SOURCE_REVISION, tiny_candidate, tiny_encoder_source
from tests.support.linear_return import golden_rows
from tests.unit.test_w08_models import examples


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("optional encoder checks must remain offline")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    torch.set_num_threads(1)


def producer_return(
    tmp_path: Path, variant: str, *, threshold: float, max_tokens: str = TINY_LIMIT
) -> Path:
    """What a producer exports: a tiny encoder fine-tuned one epoch, then ``export``."""
    source = tmp_path / "source"
    candidate = tiny_candidate(source, tiny_encoder_source(source), variant=variant)
    candidate.fit(examples(), epochs=1, learning_rate=0.001)
    encoder, heads, report = producer_files(candidate, tmp_path / "producer")
    out = tmp_path / "return"
    export(
        "export",
        "--encoder-dir",
        str(encoder),
        "--heads",
        str(heads),
        "--training-report",
        str(report),
        "--variant",
        variant,
        "--source-revision",
        SOURCE_REVISION,
        "--max-tokens",
        max_tokens,
        "--evidence-threshold",
        str(threshold),
        "--out",
        str(out),
    )
    return out


def predict(root: Path, inputs: Path, out: Path, *extra: str) -> dict[str, Any]:
    return export(
        "predict", "--root", str(root), "--inputs", str(inputs), "--out", str(out), *extra
    )


def seal_and_register(root: Path, package: V3Package, registry: Path) -> FileRef:
    (root / "training-notes.md").write_text("Tiny random BERT, one epoch; mechanism only.\n")
    sealed = export(
        "seal",
        "--root",
        str(root),
        "--dataset-manifest",
        str(package.root / "dataset-manifest.json"),
        "--label-tier",
        "G2v",
    )
    ref = FileRef(path=sealed["bundle_path"], sha256=sealed["bundle_hash"])
    return register_bundle(registry, root, ref, scope="synthetic_fixture")


def registration_args(registry: Path, ref: FileRef) -> list[str]:
    return [
        "--registry",
        str(registry),
        "--registration-path",
        ref.path,
        "--registration-hash",
        ref.sha256,
    ]


@pytest.mark.parametrize("variant", VARIANTS)
def test_plug_02_reference_predictions_reload_as_matched_in_verify_return(
    tmp_path: Path, variant: str
) -> None:
    """160 C5: the producer's dev rows from the reference ``predict`` are what our loader
    reproduces (labels, statuses and evidence exact, probabilities within 1e-4)."""
    package = build_package(tmp_path, TRAIN_DEV)
    threshold = 0.5 if variant == "pair_aggregate" else 0.05
    root = producer_return(tmp_path, variant, threshold=threshold)
    summary = predict(
        root,
        package.root / "data/dev.inputs.jsonl",
        root / "predictions.dev.jsonl",
        "--labels",
        str(package.root / "data/dev.labels.jsonl"),
    )
    assert summary["rows"] == 4 and summary["evidence_missing"] == []
    assert summary["device"] == "cpu" and summary["dtype"] == "float32"
    rows = jsonl(root / "predictions.dev.jsonl")
    assert {row["return_schema_version"] for row in rows} == {3}
    assert {row["model_revision"] for row in rows} == {summary["model_revision"]}
    registry = tmp_path / "registry"
    ref = seal_and_register(root, package, registry)
    code, report = verify(
        package,
        root / "predictions.dev.jsonl",
        "--checkpoint-manifest",
        root / "checkpoint-manifest.json",
        *registration_args(registry, ref),
    )
    assert code == 0, report
    assert report["format_errors"] == []
    assert report["reload"]["status"] == "matched", report["reload"]
    assert report["reload"]["max_probability_deviation"] <= 1e-4
    assert report["tolerance"]["absolute"] == 1e-4


def model_input(item: RelationInput, **changes: Any) -> dict[str, Any]:
    """``item`` with evidence fields changed and its inner input hash recomputed."""
    body = item.evidence.model_dump(mode="json", exclude={"input_hash"}) | changes
    package = EvidencePackageV2(**body, input_hash=digest(body))
    return RelationInput(evidence=package).model_dump(mode="json")


def abstention_inputs(path: Path) -> list[dict[str, Any]]:
    """Every abstention our loader applies, next to ordinary dev and golden inputs."""
    item = examples("dev")[0].item
    context = item.evidence.rule_context["evidence_time_context"]
    cases = {
        "input-missing": model_input(item, completeness="missing"),
        "input-text-overflow": model_input(item, completeness="text_overflow"),
        "empty-claim": model_input(item, claim="   "),
        "scope-undetermined": model_input(item, rule_context={}),
        "reference-mismatch": model_input(
            item, rule_context={"evidence_time_context": context | {"reference_seq": 1}}
        ),
        "validity-unknown": model_input(
            item, rule_context={"evidence_time_context": context | {"validity_known_ids": ["e1"]}}
        ),
    }
    rows = [
        {"record_id": row.record_id, "input_hash": digest(row.item), "model_input": row.item}
        for row in examples("dev", 2)
    ]
    rows = [row | {"model_input": row["model_input"].model_dump(mode="json")} for row in rows]
    rows += [
        {
            "record_id": row["sample"],
            "input_hash": row["input_hash"],
            "model_input": row["model_input"],
        }
        for row in golden_rows()
    ]
    rows += [
        {
            "record_id": name,
            "input_hash": digest(RelationInput.model_validate(raw)),
            "model_input": raw,
        }
        for name, raw in cases.items()
    ]
    write_jsonl(path, rows)
    return rows


@pytest.mark.parametrize(
    ("variant", "limit"),
    [("pack", TINY_LIMIT), ("pair", TINY_LIMIT), ("pair_aggregate", TINY_LIMIT), ("pair", "16")],
)
def test_plug_03_reference_predict_abstains_exactly_where_our_loader_does(
    tmp_path: Path, variant: str, limit: str
) -> None:
    """160 C4: incomplete input, empty claim, undetermined time scope or validity, no
    candidates and inputs over ``max_tokens`` abstain with our reason codes, in our order."""
    threshold = 0.5 if variant == "pair_aggregate" else 0.05
    root = producer_return(tmp_path, variant, threshold=threshold, max_tokens=limit)
    records = abstention_inputs(tmp_path / "inputs.jsonl")
    summary = predict(root, tmp_path / "inputs.jsonl", tmp_path / "rows.jsonl")
    produced = {row["record_id"]: row for row in jsonl(tmp_path / "rows.jsonl")}
    model = HuggingFaceCandidate.load_checkpoint(root)
    reasons = set()
    for record in records:
        ours = model.predict(RelationInput.model_validate(record["model_input"]))
        theirs = produced[record["record_id"]]
        assert theirs["input_hash"] == record["input_hash"] == ours.input_hash
        assert theirs["model_revision"] == ours.model_revision == summary["model_revision"]
        assert (theirs["status"], theirs["label"]) == (ours.status, ours.label), record["record_id"]
        assert set(theirs["evidence_ids"]) == set(ours.evidence_ids), record["record_id"]
        if ours.status == "ok":
            assert theirs["probabilities"] == pytest.approx(ours.probabilities, abs=1e-4)
        else:
            assert theirs["reason"] == ours.reason_code and theirs["probabilities"] is None
            reasons.add(ours.reason_code)
    expected = {
        "input_missing",
        "input_text_overflow",
        "empty_claim",
        "temporal_scope_undetermined",
        "temporal_reference_mismatch",
        "evidence_validity_undetermined",
        "no_candidate_evidence",
    }
    if limit == "16":
        expected.add("encoder_input_truncated")
        assert summary["statuses"] == {"abstained": len(records)}
    assert reasons == expected
    assert summary["abstentions"] == {
        code: sum(1 for row in produced.values() if row["reason"] == code and row["status"] != "ok")
        for code in expected
    }


def test_plug_03_reference_predict_names_the_rows_our_format_check_rejects(
    tmp_path: Path,
) -> None:
    """``evidence_missing``: a supported or contradicted row without evidence where the gold is
    evidence-evaluable fails our format check; ``predict --labels`` lists exactly those."""
    package = build_package(tmp_path, TRAIN_DEV)
    root = producer_return(tmp_path, "pair", threshold=0.999)
    rows_path = tmp_path / "rows.jsonl"
    summary = predict(
        root,
        package.root / "data/dev.inputs.jsonl",
        rows_path,
        "--labels",
        str(package.root / "data/dev.labels.jsonl"),
    )
    code, report = verify(package, rows_path)
    rejected = {
        row["record_id"]
        for row in report["format_errors"]
        if row["error_code"] == "return_evidence_selection_required"
    }
    assert rejected and summary["evidence_missing"] == sorted(rejected)
    assert code == 2


def test_plug_03_reference_predict_never_writes_into_a_sealed_return(tmp_path: Path) -> None:
    package = build_package(tmp_path, TRAIN_DEV)
    root = producer_return(tmp_path, "pair", threshold=0.05)
    predict(root, package.root / "data/dev.inputs.jsonl", root / "predictions.dev.jsonl")
    seal_and_register(root, package, tmp_path / "registry")
    refused = run_export(
        "predict",
        "--root",
        str(root),
        "--inputs",
        str(package.root / "data/dev.inputs.jsonl"),
        "--out",
        str(root / "predictions.test.jsonl"),
    )
    assert refused.returncode == 2 and "sealed" in refused.stderr
    assert not (root / "predictions.test.jsonl").exists()


def test_plug_04_sealed_encoder_returns_name_the_roles_validate_handoff_needs(
    tmp_path: Path,
) -> None:
    """160 C6: validate-handoff requires ``artifact_roles`` for every non-linear return; the
    reference ``seal`` now writes them, so our joint check does not send the return back."""
    package = build_package(tmp_path, TRAIN_DEV)
    root = producer_return(tmp_path, "pair", threshold=0.05)
    predict(
        root,
        package.root / "data/dev.inputs.jsonl",
        root / "predictions.dev.jsonl",
        "--labels",
        str(package.root / "data/dev.labels.jsonl"),
    )
    seal_and_register(root, package, tmp_path / "registry")
    manifest = json.loads((root / "checkpoint-manifest.json").read_bytes())
    assert manifest["artifact_roles"] == {
        "checkpoint": ["heads.npz", "encoder/model.safetensors"],
        "config": ["checkpoint.json", "encoder/config.json"],
        "tokenizer": [
            "encoder/tokenizer.json",
            "encoder/tokenizer_config.json",
            "encoder/vocab.txt",
        ],
    }
    code, report = validate(
        package.root,
        tmp_path / "review",
        "--checkpoint-manifest",
        root / "checkpoint-manifest.json",
    )
    assert code == 0, report
    model = report["model_return"]
    assert model["format_valid"] is True and model["artifact_kind"] == "huggingface_encoder"
    assert model["artifact_roles"] == manifest["artifact_roles"]
    # The same return sealed without the roles is what 160 found: sent back.
    del manifest["artifact_roles"]
    (root / "checkpoint-manifest.json").write_bytes(json_bytes(manifest))
    code, report = validate(
        package.root, tmp_path / "again", "--checkpoint-manifest", root / "checkpoint-manifest.json"
    )
    assert code == 2 and report["error"] == "handoff_model_artifact_roles_required"


def tiny_xlmr_base(root: Path) -> Path:
    """A random tiny XLM-R saved like the published base checkpoint: pooler included."""
    tiny_encoder_source(root / "vocabulary")
    tokenizer = AutoTokenizer.from_pretrained(str(root / "vocabulary"), local_files_only=True)
    config = XLMRobertaConfig(
        vocab_size=tokenizer.vocab_size,
        hidden_size=8,
        num_hidden_layers=1,
        num_attention_heads=2,
        intermediate_size=16,
        max_position_embeddings=258,
        type_vocab_size=2,
        pad_token_id=tokenizer.pad_token_id,
    )
    torch.manual_seed(5002)
    base = root / "base"
    XLMRobertaModel(config).save_pretrained(base, safe_serialization=True)
    tokenizer.save_pretrained(base)
    return base


def head_state(path: Path, hidden: int) -> Path:
    torch.manual_seed(7)
    relation, selector = torch.nn.Linear(hidden, 3), torch.nn.Linear(2 * hidden, 1)
    heads = {"relation." + k: v for k, v in relation.state_dict().items()}
    heads |= {"selector." + k: v for k, v in selector.state_dict().items()}
    torch.save(heads, path)
    return path


def test_plug_05_sequence_classification_training_saves_into_the_return_layout(
    tmp_path: Path,
) -> None:
    """160 C5: ``XLMRobertaForSequenceClassification`` drops the pooler, so its own save is
    refused; the encoder-return recipe (base encoder + fine-tuned body) exports and loads."""
    base = tiny_xlmr_base(tmp_path)
    tokenizer = AutoTokenizer.from_pretrained(str(base), local_files_only=True)
    classifier = XLMRobertaForSequenceClassification.from_pretrained(
        str(base), num_labels=3, local_files_only=True
    )
    trained = tmp_path / "sequence-classification"
    classifier.save_pretrained(trained, safe_serialization=True)
    tokenizer.save_pretrained(trained)
    heads = head_state(tmp_path / "heads.pt", 8)
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"fit_split": "train", "training_kind": "synthetic_recipe"}))
    arguments = [
        "--heads",
        str(heads),
        "--training-report",
        str(report),
        "--variant",
        "pair",
        "--source-revision",
        SOURCE_REVISION,
        "--max-tokens",
        TINY_LIMIT,
    ]
    direct = run_export(
        "export", "--encoder-dir", str(trained), *arguments, "--out", str(tmp_path / "direct")
    )
    assert direct.returncode == 2 and "pooler" in direct.stderr
    assert "encoder-return.md section 6" in direct.stderr
    # The recipe: the base encoder (pooler included) takes the fine-tuned body.
    encoder = AutoModel.from_pretrained(str(base), local_files_only=True)
    missing, unexpected = encoder.load_state_dict(classifier.roberta.state_dict(), strict=False)
    assert set(missing) == {"pooler.dense.weight", "pooler.dense.bias"} and not unexpected
    recipe = tmp_path / "encoder"
    encoder.save_pretrained(recipe, safe_serialization=True)
    tokenizer.save_pretrained(recipe)
    root = tmp_path / "return"
    export("export", "--encoder-dir", str(recipe), *arguments, "--out", str(root))
    package = build_package(tmp_path, TRAIN_DEV)
    predict(root, package.root / "data/dev.inputs.jsonl", root / "predictions.dev.jsonl")
    registry = tmp_path / "registry"
    model, _ = load_registration(registry, seal_and_register(root, package, registry))
    rows = jsonl(root / "predictions.dev.jsonl")
    for row, record in zip(rows, jsonl(package.root / "data/dev.inputs.jsonl"), strict=True):
        ours = model.predict(RelationInput.model_validate(record["model_input"]))
        assert (row["status"], row["label"]) == (ours.status, ours.label)
        assert row["probabilities"] == pytest.approx(ours.probabilities, abs=1e-4)
