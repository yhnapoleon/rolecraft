"""Explicit optional CPU checks; no Hub requests or real model-quality claims.

Run this file explicitly with the encoder extra. Its filename keeps it outside
normal pytest discovery, so default product gates need no optional libraries.
"""

import json
import socket
from pathlib import Path

import pytest
import torch
from transformers import BertConfig, BertModel, BertTokenizerFast

from career_lab.contracts.v2.core import FileRef
from career_lab.models.v3.advisory import RegisteredAdvisory
from career_lab.models.v3.bundle import json_bytes, sha
from career_lab.models.v3.huggingface import HuggingFaceCandidate
from career_lab.models.v3.registry import load_registration, register_bundle
from tests.unit.test_w08_encoder_registration import encoder_return, write_manifest
from tests.unit.test_w08_models import examples


def local_encoder(root: Path) -> FileRef:
    root.mkdir()
    vocabulary = [
        "[PAD]",
        "[UNK]",
        "[CLS]",
        "[SEP]",
        "[MASK]",
        "capacity",
        "version",
        "budget",
        "reference",
        "time",
        "8",
        "12",
        "3",
        "2",
        "1",
        "0",
        "=",
        ">",
        "{",
        "}",
        ":",
        '"',
    ]
    (root / "vocab.txt").write_text("\n".join(vocabulary) + "\n")
    BertTokenizerFast(vocab_file=str(root / "vocab.txt"), model_max_length=256).save_pretrained(
        root
    )
    torch.manual_seed(5002)
    config = BertConfig(
        vocab_size=len(vocabulary),
        hidden_size=8,
        num_hidden_layers=1,
        num_attention_heads=2,
        intermediate_size=16,
        max_position_embeddings=256,
    )
    BertModel(config).save_pretrained(root, safe_serialization=True)
    files = {path.name: sha(path.read_bytes()) for path in root.iterdir() if path.is_file()}
    raw = json_bytes(
        {
            "protocol": "w08-hf-local-files-v1",
            "source_revision": "a" * 40,
            "weights_stage": "synthetic_random_initialization",
            "files": files,
        }
    )
    (root / "local-files.json").write_bytes(raw)
    return FileRef(path="local-files.json", sha256=sha(raw))


@pytest.mark.parametrize("variant", ["pair", "pack"])
def test_local_random_encoder_return_roundtrips_on_cpu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    def deny_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("optional encoder mechanism check must remain offline")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    torch.set_num_threads(1)
    source = tmp_path / "random-source"
    ref = local_encoder(source)
    candidate = HuggingFaceCandidate(
        source, revision="a" * 40, variant=variant, max_tokens=256, checkpoint_manifest=ref
    )
    report = candidate.fit(examples(), epochs=1, learning_rate=0.001)
    assert report["before_weights"] != report["after_weights"]
    assert report["encoder_before"] != report["encoder_after"]
    candidate.training_report.update(pretrained=False, scope="synthetic_random_fixture")
    checkpoint = tmp_path / "checkpoint"
    candidate.save_checkpoint(checkpoint)
    declaration = tmp_path / "declaration"
    encoder_return(declaration)
    manifest = json.loads((declaration / "checkpoint-manifest.json").read_bytes())
    manifest.update(
        model_revision=candidate.revision,
        framework_version=torch.__version__,
        checkpoint_files={
            p.relative_to(checkpoint).as_posix(): sha(p.read_bytes())
            for p in checkpoint.rglob("*")
            if p.is_file()
        },
    )
    returned = write_manifest(checkpoint, manifest)
    registry = tmp_path / "registry"
    registration = register_bundle(registry, checkpoint, returned, scope="synthetic_fixture")
    loaded, identity = load_registration(registry, registration)
    item = examples("dev")[0].item
    before = candidate.predict(item)
    after = loaded.predict(item)
    assert after == before
    assert after.status == "ok" and len(after.probabilities) == 3
    assert len(after.evidence_probabilities) == len(item.evidence.candidate_evidence)
    assert identity["kind"] == "huggingface_encoder"
    assert identity["quality_validated"] is False
    result = RegisteredAdvisory(
        registry, registration, tmp_path / "journal", allow_synthetic=True
    ).predict(item, request_id="local-mechanism", work_language="en")
    assert result["status"] == "completed"
    assert result["public_prediction"]["status"] == "unavailable"
    assert result["semantic_status"] == "synthetic_mechanism_only"
    assert sum(p.stat().st_size for p in checkpoint.rglob("*") if p.is_file()) < 200_000
