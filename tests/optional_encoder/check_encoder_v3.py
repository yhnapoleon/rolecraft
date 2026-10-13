"""Encoder return v3 with real (tiny, random, local) weights: run explicitly with the extra.

    uv sync --locked --extra encoder
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m pytest -q \\
      tests/optional_encoder/check_encoder_v3.py

Covers ENC-01, ENC-02, ENC-03, ENC-05, ENC-07 and MEASURE-02 through the reference
export script, registration, loading, prediction and normal feedback over HTTP. No Hub
request, no download; nothing here is model-quality evidence.
"""

import importlib.util
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import torch

from career_lab.contracts.v2.core import FileRef, ProtocolError
from career_lab.models.v3.advisory import RegisteredAdvisory
from career_lab.models.v3.core import prediction
from career_lab.models.v3.huggingface import aggregate_pairs, encoder_texts, pack_text
from career_lab.models.v3.registry import describe_registration, load_registration, register_bundle
from tests.optional_encoder.tiny_return import (
    SOURCE_REVISION,
    seal,
    tiny_candidate,
    tiny_encoder_return,
    tiny_encoder_source,
)
from tests.unit.test_w08_encoder_registration import (
    AGGREGATE_EXAMPLES,
    REPOSITORY,
    configure,
    open_session,
    review,
    runtime_app,
)
from tests.unit.test_w08_models import examples

EXPORT = REPOSITORY / "docs/data/return-v3/reference/export_hf_return.py"
VARIANTS = ("pack", "pair", "pair_aggregate")
# The tiny BERT's tokenizer and position limit; the export default (512) is XLM-R base's.
TINY_LIMIT = "256"
FIXTURE = {
    "dataset_id": "rolecraft-fixture-20261007-v2",
    "dataset_manifest_sha256": "5c8f0d5be05e3b39c1599e7fd3a92e46e413dc571248c59f827818f5ee231858",
}


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("optional encoder checks must remain offline")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    torch.set_num_threads(1)


def run_export(*arguments: str) -> subprocess.CompletedProcess:
    """The reference export script in its own interpreter, as a producer would run it."""
    environment = os.environ | {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    environment.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, str(EXPORT), *arguments],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        cwd=EXPORT.parent,
    )


def export(*arguments: str) -> dict[str, Any]:
    result = run_export(*arguments)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def reference_module() -> Any:
    spec = importlib.util.spec_from_file_location("export_hf_return", EXPORT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def producer_files(candidate: Any, root: Path) -> tuple[Path, Path, Path]:
    """What a producer hands over: the fine-tuned encoder directory, head state and report."""
    encoder = root / "encoder"
    candidate.encoder.save_pretrained(encoder, safe_serialization=True)
    candidate.tokenizer.save_pretrained(encoder)
    heads = {
        prefix + name: tensor.detach().clone()
        for prefix, module in candidate.heads()
        for name, tensor in module.state_dict().items()
    }
    torch.save(heads, root / "heads.pt")
    (root / "training-report.json").write_text(json.dumps(candidate.training_report))
    return encoder, root / "heads.pt", root / "training-report.json"


def tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def dev_items() -> list[Any]:
    return [row.item for row in examples("dev")]


@pytest.mark.parametrize("variant", VARIANTS)
def test_enc_01_export_script_and_save_checkpoint_register_the_same_model(
    tmp_path: Path, variant: str
) -> None:
    source = tmp_path / "source"
    candidate = tiny_candidate(source, tiny_encoder_source(source), variant=variant)
    candidate.fit(examples(), epochs=1, learning_rate=0.001)
    candidate.save_checkpoint(tmp_path / "saved")
    encoder, heads, report = producer_files(candidate, tmp_path / "producer")
    result = export(
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
        TINY_LIMIT,
        "--derived-from",
        candidate.checkpoint_identity["manifest_sha256"],
        "--out",
        str(tmp_path / "exported"),
    )
    assert result["model_revision"] == candidate.revision
    assert tree(tmp_path / "exported") == tree(tmp_path / "saved")
    registry = tmp_path / "registry"
    registrations = []
    for name in ("saved", "exported"):
        sealed = export(
            "seal",
            "--root",
            str(tmp_path / name),
            "--dataset-id",
            "rolecraft-synthetic-test-examples",
            "--dataset-manifest-sha256",
            "e" * 64,
        )
        ref = FileRef(path=sealed["bundle_path"], sha256=sealed["bundle_hash"])
        registrations.append(
            register_bundle(registry, tmp_path / name, ref, scope="synthetic_fixture")
        )
    assert registrations[0] == registrations[1]
    loaded, _ = load_registration(registry, registrations[1])
    assert [loaded.predict(item) for item in dev_items()] == [
        candidate.predict(item) for item in dev_items()
    ]


def test_enc_01_export_refuses_inputs_that_do_not_match_the_delivered_model(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    candidate = tiny_candidate(source, tiny_encoder_source(source), variant="pair")
    candidate.fit(examples(), epochs=1, learning_rate=0.001)
    encoder, heads, report = producer_files(candidate, tmp_path / "producer")
    arguments = ["--variant", "pair", "--source-revision", SOURCE_REVISION]
    state = torch.load(heads, weights_only=True)
    torch.save({k: v for k, v in state.items() if k != "selector.bias"}, tmp_path / "short.pt")
    claimed = json.loads(report.read_text()) | {"after_weights": "0" * 64}
    (tmp_path / "claimed.json").write_text(json.dumps(claimed))
    pickled = tmp_path / "pickled"
    pickled.mkdir()
    for path in encoder.iterdir():
        (pickled / path.name).write_bytes(path.read_bytes())
    (pickled / "pytorch_model.bin").write_bytes(b"pickle")
    for case, (directory, head, training) in {
        "missing-head": (encoder, tmp_path / "short.pt", report),
        "report-disagrees": (encoder, heads, tmp_path / "claimed.json"),
        "pickled-weights": (pickled, heads, report),
    }.items():
        result = run_export(
            "export",
            "--encoder-dir",
            str(directory),
            "--heads",
            str(head),
            "--training-report",
            str(training),
            *arguments,
            "--out",
            str(tmp_path / case),
        )
        assert result.returncode == 2, (case, result.stdout + result.stderr)
        assert result.stderr.startswith("export_hf_return: ")
        assert not (tmp_path / case / "checkpoint.json").exists()
    low = run_export(
        "export",
        "--encoder-dir",
        str(source),
        "--weights-stage",
        "pretrained_untrained_heads",
        "--variant",
        "pair_aggregate",
        "--evidence-threshold",
        "0.3",
        *arguments[2:],
        "--out",
        str(tmp_path / "low-threshold"),
    )
    assert low.returncode == 2 and "at least 0.5" in low.stderr
    assert not (tmp_path / "low-threshold").exists()


def test_enc_01_reference_inputs_are_the_strings_the_product_encodes() -> None:
    module = reference_module()
    items = [row.item for split in ("train", "dev") for row in examples(split)]
    for item in items:
        query, bodies = module.encoder_inputs(item.model_dump(mode="json"))
        assert (query, bodies) == encoder_texts(item)
        assert module.pack_text(bodies) == pack_text(bodies)


def test_enc_02_reference_aggregation_follows_the_specification_examples() -> None:
    module = reference_module()
    for example in json.loads(AGGREGATE_EXAMPLES.read_text())["examples"]:
        if "refused" in example:
            with pytest.raises(ValueError):
                module.aggregate_pairs(example["pair_probabilities"], example["evidence_threshold"])
            continue
        probabilities, scores = module.aggregate_pairs(
            example["pair_probabilities"], example["evidence_threshold"]
        )
        assert probabilities == pytest.approx(example["probabilities"], abs=1e-12)
        assert scores == pytest.approx(example["evidence_scores"], abs=1e-12)


def test_enc_02_pair_aggregate_predictions_apply_the_rule_to_each_pair(tmp_path: Path) -> None:
    root = tmp_path / "return"
    ref = tiny_encoder_return(root, variant="pair_aggregate", evidence_threshold=0.6)
    registry = tmp_path / "registry"
    model, _ = load_registration(
        registry, register_bundle(registry, root, ref, scope="synthetic_fixture")
    )
    for item in dev_items():
        pairs = model.pair_judgements(item)
        assert pairs.shape == (len(item.evidence.candidate_evidence), 3)
        probabilities, scores = aggregate_pairs(pairs, 0.6)
        assert model.predict(item) == prediction(item, model.revision, probabilities, scores, 0.6)


def test_enc_03_the_declared_threshold_selects_the_evidence(tmp_path: Path) -> None:
    source = tmp_path / "source"
    candidate = tiny_candidate(source, tiny_encoder_source(source), variant="pair")
    candidate.fit(examples(), epochs=1, learning_rate=0.001)
    encoder, heads, report = producer_files(candidate, tmp_path / "producer")
    registry = tmp_path / "registry"
    models = {}
    for threshold in (0.05, 0.95):
        out = tmp_path / f"threshold-{threshold}"
        export(
            "export",
            "--encoder-dir",
            str(encoder),
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
            "--evidence-threshold",
            str(threshold),
            "--out",
            str(out),
        )
        sealed = export(
            "seal",
            "--root",
            str(out),
            "--dataset-id",
            "rolecraft-synthetic-test-examples",
            "--dataset-manifest-sha256",
            "e" * 64,
        )
        ref = FileRef(path=sealed["bundle_path"], sha256=sealed["bundle_hash"])
        models[threshold], _ = load_registration(
            registry, register_bundle(registry, out, ref, scope="synthetic_fixture")
        )
    assert models[0.05].revision != models[0.95].revision
    for item in dev_items():
        low, high = models[0.05].predict(item), models[0.95].predict(item)
        assert low.evidence_probabilities == high.evidence_probabilities
        for threshold, result in ((0.05, low), (0.95, high)):
            assert result.evidence_ids == tuple(
                key for key, score in result.evidence_probabilities if score >= threshold
            )
        assert set(high.evidence_ids) <= set(low.evidence_ids)
    assert any(
        len(models[0.05].predict(item).evidence_ids) > len(models[0.95].predict(item).evidence_ids)
        for item in dev_items()
    )


def test_enc_03_the_declared_token_limit_abstains_without_truncating(tmp_path: Path) -> None:
    root = tmp_path / "return"
    # Untrained heads: training itself could not encode these inputs within 8 tokens.
    ref = tiny_encoder_return(
        root, variant="pack", weights_stage="pretrained_untrained_heads", max_tokens=8
    )
    registry = tmp_path / "registry"
    model, _ = load_registration(
        registry, register_bundle(registry, root, ref, scope="synthetic_fixture")
    )
    item = dev_items()[0]
    size = model.measure(item)
    assert size.limit == 8 and size.exceeds
    result = model.predict(item)
    assert (result.status, result.reason_code) == ("abstained", "encoder_input_truncated")


def legacy_layout(saved: Path, out: Path) -> None:
    """Rewrite a v3 checkpoint the way eb494c0's save_checkpoint wrote checkpoints."""
    out.mkdir()
    for name, raw in tree(saved).items():
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(raw)
    config = json.loads((out / "checkpoint.json").read_bytes())
    after = config["training_report"]["after_weights"]
    legacy = {
        "source_revision": config["source_revision"],
        "task_type": config["task_type"],
        "variant": config["variant"],
        "max_tokens": config["max_tokens"],
        "seed": config["seed"],
        "model_revision": f"hf-finetuned:{config['source_revision']}:{after}",
        "training_report": config["training_report"],
        "files": config["files"],
    }
    (out / "checkpoint.json").write_text(json.dumps(legacy, ensure_ascii=False, indent=2))


@pytest.mark.parametrize("variant", ["pack", "pair"])
def test_enc_03_fixture_v2_era_checkpoints_load_with_the_fixed_threshold(
    tmp_path: Path, variant: str
) -> None:
    source = tmp_path / "source"
    candidate = tiny_candidate(source, tiny_encoder_source(source), variant=variant)
    candidate.fit(examples(), epochs=1, learning_rate=0.001)
    candidate.save_checkpoint(tmp_path / "saved")
    legacy_layout(tmp_path / "saved", tmp_path / "legacy")
    after = candidate.training_report["after_weights"]
    ref = seal(tmp_path / "legacy", f"hf-finetuned:{SOURCE_REVISION}:{after}")
    registry = tmp_path / "registry"
    model, entry = load_registration(
        registry, register_bundle(registry, tmp_path / "legacy", ref, scope="synthetic_fixture")
    )
    assert entry["evidence_threshold"] == 0.5 and model.evidence_threshold == 0.5
    for item in dev_items():
        expected = candidate.predict(item)
        actual = model.predict(item)
        assert actual.probabilities == expected.probabilities
        assert actual.evidence_probabilities == expected.evidence_probabilities
        assert actual.evidence_ids == tuple(
            key for key, score in actual.evidence_probabilities if score >= 0.5
        )


@pytest.mark.parametrize("variant", VARIANTS)
def test_enc_05_untrained_heads_predict_only_once_declared_and_export_identically(
    tmp_path: Path, variant: str
) -> None:
    source = tmp_path / "source"
    ref = tiny_encoder_source(source)
    candidate = tiny_candidate(source, ref, variant=variant)
    with pytest.raises(ProtocolError) as error:
        candidate.predict(dev_items()[0])
    assert error.value.code == "encoder_heads_not_trained"
    candidate.mark_untrained_heads()
    assert candidate.training_report["training_kind"] == "none"
    candidate.save_checkpoint(tmp_path / "saved")
    result = export(
        "export",
        "--encoder-dir",
        str(source),
        "--weights-stage",
        "pretrained_untrained_heads",
        "--variant",
        variant,
        "--source-revision",
        SOURCE_REVISION,
        "--max-tokens",
        TINY_LIMIT,
        "--derived-from",
        candidate.checkpoint_identity["manifest_sha256"],
        "--out",
        str(tmp_path / "exported"),
    )
    assert result["model_revision"] == candidate.revision
    assert tree(tmp_path / "exported") == tree(tmp_path / "saved")
    sealed = export(
        "seal",
        "--root",
        str(tmp_path / "exported"),
        "--dataset-id",
        FIXTURE["dataset_id"],
        "--dataset-manifest-sha256",
        FIXTURE["dataset_manifest_sha256"],
    )
    manifest = FileRef(path=sealed["bundle_path"], sha256=sealed["bundle_hash"])
    declared = json.loads((tmp_path / "exported/checkpoint-manifest.json").read_bytes())
    assert declared["completed"] is False and declared["training_partitions"] == []
    registry = tmp_path / "registry"
    with pytest.raises(ProtocolError) as error:
        register_bundle(registry, tmp_path / "exported", manifest, scope="external_candidate")
    assert error.value.code == "untrained_heads_require_synthetic_scope"
    registration = register_bundle(
        registry, tmp_path / "exported", manifest, scope="synthetic_fixture"
    )
    assert (
        describe_registration(registry, registration).weights_stage == "pretrained_untrained_heads"
    )
    outcome = RegisteredAdvisory(
        registry, registration, tmp_path / "journal", allow_synthetic=True
    ).predict(dev_items()[0], request_id="untrained", work_language="en")
    assert outcome["status"] == "completed"
    assert outcome["semantic_status"] == "synthetic_mechanism_only"


def test_measure_02_counts_the_tokens_prediction_encodes_without_a_forward_pass(
    tmp_path: Path,
) -> None:
    root = tmp_path / "return"
    ref = tiny_encoder_return(root, variant="pair", max_tokens=256)
    registry = tmp_path / "registry"
    model, _ = load_registration(
        registry, register_bundle(registry, root, ref, scope="synthetic_fixture")
    )
    calls = []
    hook = model.encoder.register_forward_hook(lambda *args: calls.append(1))
    item = dev_items()[0]
    size = model.measure(item)
    assert calls == []
    texts = [candidate.text for candidate in item.evidence.candidate_evidence]
    longest = max(
        len(model.tokenizer(item.evidence.purpose + "\n" + item.evidence.claim, text).input_ids)
        for text in texts
    )
    assert size.tokens >= longest and size.limit == 256 and not size.exceeds
    model.predict(item)
    assert calls
    hook.remove()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_enc_07_synthetic_encoder_advice_over_http_names_its_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    root = tmp_path / "return"
    dataset = FIXTURE | {"label_tiers": ["G0"]}
    ref = tiny_encoder_return(root, variant="pair_aggregate", dataset=dataset)
    registry = tmp_path / "registry"
    registration = register_bundle(registry, root, ref, scope="synthetic_fixture")
    configure(monkeypatch, tmp_path, registry, registration)
    with runtime_app(tmp_path) as (app, client):
        session = open_session(app, client, language)
        _, feedback = review(session, "review-encoder", session.work())
    report = feedback["result"]["result"]["items"][0]
    advice = report["model_advice"][0]
    assert advice["status"] == "synthetic_mechanism_only", advice
    identity = advice["registration"]
    assert identity["kind"] == "huggingface_encoder"
    assert identity["dataset"] == dataset
    assert identity["weights_stage"] == "supervised_finetuned"
    assert identity["scope"] == "synthetic_fixture" and identity["quality_validated"] is False
    assert advice["affects_score"] is False
    assert report["provenance"]["registered_model"] == identity
    # One journaled request per judged sentence of the work (148).
    assert len(list((tmp_path / "journal").glob("*/outcome.json"))) == len(advice["units"]) >= 1
