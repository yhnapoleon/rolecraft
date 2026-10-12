"""Tiny, loadable encoder returns for optional checks (needs the encoder extra; no download).

A randomly initialised BERT of about 10 KB stands in for a pretrained encoder; the
returns are synthetic mechanisms, never model-quality evidence. Lines that need a real
encoder registration (fusion components, sentence measuring) build one with
``tiny_encoder_return``; registering it still needs ``scope="synthetic_fixture"``.
"""

import json
from pathlib import Path
from typing import Any

import torch
from transformers import BertConfig, BertModel, BertTokenizerFast

from career_lab.contracts.v2.core import FileRef
from career_lab.models.v3.bundle import json_bytes, sha
from career_lab.models.v3.huggingface import HuggingFaceCandidate
from tests.unit.test_w08_models import examples

SOURCE_REVISION = "a" * 40
VOCABULARY = (
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
)
SYNTHETIC_DATASET = {
    "dataset_id": "rolecraft-synthetic-test-examples",
    "dataset_manifest_sha256": "e" * 64,
}


def tiny_encoder_source(root: Path) -> FileRef:
    """A random BERT and tokenizer saved locally, with the local file manifest loading needs."""
    root.mkdir(parents=True)
    (root / "vocab.txt").write_text("\n".join(VOCABULARY) + "\n")
    BertTokenizerFast(vocab_file=str(root / "vocab.txt"), model_max_length=256).save_pretrained(
        root
    )
    torch.manual_seed(5002)
    config = BertConfig(
        vocab_size=len(VOCABULARY),
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
            "source_revision": SOURCE_REVISION,
            "weights_stage": "synthetic_random_initialization",
            "files": files,
        }
    )
    (root / "local-files.json").write_bytes(raw)
    return FileRef(path="local-files.json", sha256=sha(raw))


def tiny_candidate(source: Path, ref: FileRef, **settings: Any) -> HuggingFaceCandidate:
    return HuggingFaceCandidate(
        source, revision=SOURCE_REVISION, checkpoint_manifest=ref, **settings
    )


def seal(root: Path, model_revision: str, dataset: dict[str, Any] | None = None) -> FileRef:
    """Write the fixture v2 outer manifest over every file of a saved checkpoint."""
    stage = json.loads((root / "encoder/local-files.json").read_bytes())["weights_stage"]
    untrained = stage == "pretrained_untrained_heads"
    files = {
        path.relative_to(root).as_posix(): sha(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "checkpoint-manifest.json"
    }
    manifest = {
        "template": False,
        "completed": not untrained,
        "return_protocol": "rolecraft-label-evidence-v2",
        "artifact_kind": "huggingface_encoder",
        "artifact_protocol": "rolecraft-encoder-return-v3",
        "model_revision": model_revision,
        "framework": "pytorch",
        "framework_version": torch.__version__,
        "task_type": "relation",
        "label_order": ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT"],
        **(SYNTHETIC_DATASET if dataset is None else dataset),
        "training_partitions": [] if untrained else ["train"],
        "selection_partition": None if untrained else "dev",
        "test_used_for_selection": False,
        "evidence_selection_implemented": True,
        "evidence_selection_required": True,
        "checkpoint_files": files,
        "load_and_predict_command": "not executed: RoleCraft registers and loads it",
        "training_notes_file": "training-notes.md",
        "predictions_file": "predictions.dev.jsonl",
    } | ({"weights_stage": stage} if untrained else {})
    raw = json_bytes(manifest)
    (root / "checkpoint-manifest.json").write_bytes(raw)
    return FileRef(path="checkpoint-manifest.json", sha256=sha(raw))


def tiny_encoder_return(
    root: Path,
    *,
    variant: str = "pair",
    weights_stage: str = "supervised_finetuned",
    dataset: dict[str, Any] | None = None,
    **settings: Any,
) -> FileRef:
    """Save a tiny v3 return at ``root`` (must not exist) and return its outer manifest ref.

    ``supervised_finetuned`` runs one optimisation epoch on the synthetic test examples;
    ``pretrained_untrained_heads`` keeps the seeded heads. ``dataset`` declares the data
    identity (``dataset_id``, ``dataset_manifest_sha256``, optional ``label_tiers``).
    """
    root.parent.mkdir(parents=True, exist_ok=True)
    source = root.parent / (root.name + "-source")
    candidate = tiny_candidate(source, tiny_encoder_source(source), variant=variant, **settings)
    if weights_stage == "pretrained_untrained_heads":
        candidate.mark_untrained_heads()
    else:
        candidate.fit(examples(), epochs=1, learning_rate=0.001)
    candidate.save_checkpoint(root)
    (root / "training-notes.md").write_text(
        "Synthetic tiny random BERT; mechanism only, not a trained or pretrained model.\n"
    )
    return seal(root, candidate.revision, dataset)
