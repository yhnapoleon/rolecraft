#!/usr/bin/env python3
"""RoleCraft encoder return v3: export a trained encoder, then seal the return manifest.

Runs in the producer's own training environment (Python 3.10+, torch, transformers,
numpy, safetensors; transformers installs the last two). It never imports RoleCraft and
never downloads: every path is local. Specification: ../encoder-return.md.

    python export_hf_return.py export --encoder-dir ENCODER --heads HEADS.pt \\
        --training-report REPORT.json --variant pair --source-revision BASE_REVISION \\
        --out RETURN
    # add RETURN/training-notes.md and RETURN/predictions.dev.jsonl, then
    python export_hf_return.py seal --root RETURN --dataset-manifest dataset-manifest.json

``export`` writes checkpoint.json, heads.npz and encoder/ (with encoder/local-files.json)
and prints the model_revision that every prediction row must carry. ``seal`` writes
checkpoint-manifest.json over every file in RETURN. The functions after_weights,
model_revision, aggregate_pairs and write_heads are the specification's definitions.
"""

import argparse
import hashlib
import io
import json
import math
import re
import shutil
import sys
import zipfile
from pathlib import Path

import numpy as np
import torch
from safetensors.torch import load_file
from transformers import AutoModel, AutoTokenizer

RETURN_PROTOCOL = "rolecraft-label-evidence-v2"
ARTIFACT_PROTOCOL = "rolecraft-encoder-return-v3"
RELATION_LABELS = ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT")
PAIR_LABELS = ("SUPPORTS", "CONTRADICTS", "UNRELATED")
VARIANTS = ("pack", "pair", "pair_aggregate")
WEIGHTS_STAGES = ("supervised_finetuned", "pretrained_untrained_heads")
LABEL_TIERS = ("G0", "G1", "G2", "G2v")
ENCODER_SUFFIXES = {".json", ".safetensors", ".model", ".txt", ".md"}
MANIFEST = "checkpoint-manifest.json"


class ExportError(Exception):
    """A return that does not meet the specification; nothing usable was written."""


def canonical_json(value) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def json_file(value) -> bytes:
    """checkpoint.json, local-files.json and the manifest: canonical JSON plus a newline."""
    return canonical_json(value) + b"\n"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def encoder_inputs(model_input: dict) -> tuple[str, list[str]]:
    """rolecraft-encoder-text-v1: the query and one body per candidate, from model_input.

    Train and predict on exactly these strings; RoleCraft encodes the same ones.
    """
    evidence = model_input["evidence"]
    scope = evidence.get("rule_context", {}).get("evidence_time_context", {})
    query = (
        f"{evidence['purpose']}\n{evidence['claim']}\n"
        f"reference time {evidence['as_of']['business_seq']}; "
        f"temporal scope {scope.get('status', 'undetermined')}"
    )
    bodies = []
    for candidate in evidence["candidate_evidence"]:
        ref = candidate["ref"]
        until = "open" if ref.get("valid_until_seq") is None else ref["valid_until_seq"]
        bodies.append(
            f"{candidate['text']}\nobserved {ref['observed_at_seq']}; "
            f"valid from {ref['valid_from_seq']}; valid until {until}"
        )
    return query, bodies


def pack_text(bodies: list[str]) -> tuple[str, list[tuple[int, int]]]:
    """pack: the text_pair is every body followed by a newline; spans are body offsets."""
    text, spans = "", []
    for body in bodies:
        spans.append((len(text), len(text) + len(body)))
        text += body + "\n"
    return text, spans


def after_weights(modules) -> str:
    """SHA-256 over (prefix, module) pairs in order; each state_dict sorted by name.

    Per tensor: UTF-8 of prefix + name + str(dtype) + str(tuple(shape)), then the
    tensor cast to float32, C-contiguous, as native (little-endian) bytes.
    """
    digest = hashlib.sha256()
    for prefix, module in modules:
        for name, tensor in sorted(module.state_dict().items()):
            value = tensor.detach().cpu().contiguous()
            digest.update((prefix + name + str(value.dtype) + str(tuple(value.shape))).encode())
            digest.update(value.float().numpy().tobytes())
    return digest.hexdigest()


def model_revision(fields: dict) -> str:
    """hf-encoder-v3: + SHA-256 of the canonical JSON of the revision fields."""
    names = (
        "after_weights",
        "evidence_threshold",
        "max_tokens",
        "pooling",
        "source_revision",
        "task_type",
        "variant",
        "weights_stage",
    )
    return (
        "hf-encoder-v3:" + hashlib.sha256(canonical_json({n: fields[n] for n in names})).hexdigest()
    )


def aggregate_pairs(pair_probabilities, threshold):
    """pair_aggregate v1, as the specification states it (section 5).

    pair_probabilities: one (SUPPORTS, CONTRADICTS, UNRELATED) softmax row per candidate,
    in candidate order. Returns relation probabilities (SUPPORTED, CONTRADICTED,
    INSUFFICIENT) and per-candidate evidence scores; evidence = scores >= threshold.
    """
    pairs = np.asarray(pair_probabilities, dtype=float)
    supports, contradicts = pairs[:, 0], pairs[:, 1]
    if (contradicts >= threshold).any():
        decided, confidence, scores = 1, contradicts.max(), contradicts
    elif (supports >= threshold).any():
        decided, confidence, scores = 0, supports.max(), supports
    else:
        strongest = max(supports.max(), contradicts.max())
        decided, confidence, scores = 2, 1 - strongest, np.maximum(supports, contradicts)
    probabilities = np.full(3, (1 - confidence) / 4)
    probabilities[decided] = (1 + confidence) / 2
    return probabilities, scores


def write_heads(path: Path, arrays: dict) -> None:
    """heads.npz with sorted members, fixed timestamps and attributes, no compression."""
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(arrays):
            buffer = io.BytesIO()
            np.lib.format.write_array(
                buffer, np.ascontiguousarray(arrays[name]), allow_pickle=False
            )
            member = zipfile.ZipInfo(name + ".npy", date_time=(1980, 1, 1, 0, 0, 0))
            member.create_system = 3
            member.external_attr = 0o644 << 16
            archive.writestr(member, buffer.getvalue())


def head_modules(variant: str, hidden: int, seed: int):
    """The variant's heads, created in this order right after torch.manual_seed(seed)."""
    torch.manual_seed(seed)
    if variant == "pair_aggregate":
        return [("pair.", torch.nn.Linear(hidden, len(PAIR_LABELS)))]
    relation = torch.nn.Linear(hidden, len(RELATION_LABELS))
    selector = torch.nn.Linear(2 * hidden, 1)
    return [("relation.", relation), ("selector.", selector)]


def read_heads(path: Path) -> dict:
    if path.suffix == ".safetensors":
        return load_file(str(path))
    if path.suffix == ".npz":
        with np.load(path, allow_pickle=False) as archive:
            return {name: torch.from_numpy(archive[name]) for name in archive.files}
    return torch.load(path, map_location="cpu", weights_only=True)


def encoder_files(directory: Path, *, delivered: bool) -> list[Path]:
    """Files of a save_pretrained directory; ``delivered`` ones are copied into the return.

    Delivered encoders must be safetensors-only; a base encoder that is re-saved (untrained
    heads) may also hold other formats, which are ignored.
    """
    found = []
    for path in sorted(directory.rglob("*")):
        name = path.relative_to(directory).as_posix()
        if not path.is_file() or name == "local-files.json":
            continue
        if path.suffix in ENCODER_SUFFIXES:
            found.append(path)
        elif delivered:
            raise ExportError(
                f"{name}: only {sorted(ENCODER_SUFFIXES)} files are accepted; "
                "save the encoder with save_pretrained(..., safe_serialization=True)"
            )
    names = {path.relative_to(directory).as_posix() for path in found}
    if "config.json" not in names or not any(name.endswith(".safetensors") for name in names):
        raise ExportError("the encoder directory needs config.json and safetensors weights")
    return found


def check_settings(args) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_revision):
        raise ExportError("--source-revision must be the 40-hex revision of the base encoder")
    if not (math.isfinite(args.evidence_threshold) and 0 < args.evidence_threshold < 1):
        raise ExportError("--evidence-threshold must lie strictly between 0 and 1")
    if args.max_tokens < 4:
        raise ExportError("--max-tokens must be at least 4")
    untrained = args.weights_stage == "pretrained_untrained_heads"
    if untrained and (args.heads or args.training_report):
        raise ExportError("untrained heads come from --seed; give no --heads or report")
    if not untrained and not (args.heads and args.training_report):
        raise ExportError("a fine-tuned return needs --heads and --training-report")


def export(args) -> dict:
    check_settings(args)
    out = Path(args.out)
    if out.exists():
        raise ExportError(f"{out} exists; a return is written once")
    source = Path(args.encoder_dir)
    untrained = args.weights_stage == "pretrained_untrained_heads"
    files = encoder_files(source, delivered=not untrained)
    options = {"local_files_only": True, "trust_remote_code": False}
    torch.manual_seed(args.seed)
    encoder, loading = AutoModel.from_pretrained(
        str(source), use_safetensors=True, output_loading_info=True, **options
    )
    encoder = encoder.to(device="cpu", dtype=torch.float32)
    tokenizer = AutoTokenizer.from_pretrained(str(source), use_fast=True, **options)
    limits = [tokenizer.model_max_length, getattr(encoder.config, "max_position_embeddings", None)]
    if any(isinstance(limit, int) and args.max_tokens > limit for limit in limits):
        raise ExportError("--max-tokens exceeds the tokenizer or position limit")
    heads = head_modules(args.variant, encoder.config.hidden_size, args.seed)
    if untrained:
        report = {
            "training_kind": "none",
            "source_revision": args.source_revision,
            "seed": args.seed,
        }
    else:
        if loading["missing_keys"]:
            raise ExportError(
                "encoder weights missing from the directory: "
                f"{loading['missing_keys'][:5]}; save the complete fine-tuned encoder"
            )
        state = read_heads(Path(args.heads))
        expected = {prefix + key for prefix, module in heads for key in module.state_dict()}
        if set(state) != expected:
            raise ExportError(f"head state must hold exactly {sorted(expected)}")
        for prefix, module in heads:
            module.load_state_dict(
                {key: state[prefix + key] for key in module.state_dict()}, strict=True
            )
        report = json.loads(Path(args.training_report).read_text())
        if report.get("fit_split") != "train" or report.get("training_kind") in {None, "", "none"}:
            raise ExportError("the training report needs fit_split=train and its training_kind")
    after = after_weights([("encoder.", encoder), *heads])
    for field, value in (("source_revision", args.source_revision), ("after_weights", after)):
        if report.get(field, value) != value:
            raise ExportError(f"training report {field} disagrees with the delivered model")
        report[field] = value
    encoder_root = out / "encoder"
    if untrained:
        encoder.save_pretrained(encoder_root, safe_serialization=True)
        tokenizer.save_pretrained(encoder_root)
    else:
        for path in files:
            target = encoder_root / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    write_heads(
        out / "heads.npz",
        {
            prefix + key: tensor.detach().cpu().numpy()
            for prefix, module in heads
            for key, tensor in module.state_dict().items()
        },
    )
    local = {
        "protocol": "w08-hf-local-files-v1",
        "source_revision": args.source_revision,
        "weights_stage": args.weights_stage,
        "files": {
            p.relative_to(encoder_root).as_posix(): sha256_file(p)
            for p in sorted(encoder_root.rglob("*"))
            if p.is_file()
        },
    }
    if args.derived_from:
        local["derived_from"] = args.derived_from
    (encoder_root / "local-files.json").write_bytes(json_file(local))
    settings = {
        "evidence_threshold": args.evidence_threshold,
        "max_tokens": args.max_tokens,
        "pooling": "mean",
        "source_revision": args.source_revision,
        "task_type": "relation",
        "variant": args.variant,
    }
    revision = model_revision(
        settings | {"after_weights": after, "weights_stage": args.weights_stage}
    )
    config = settings | {
        "checkpoint_schema_version": 3,
        "seed": args.seed,
        "model_revision": revision,
        "training_report": report,
        "files": {
            p.relative_to(out).as_posix(): sha256_file(p)
            for p in sorted(out.rglob("*"))
            if p.is_file()
        },
    }
    if args.variant == "pair_aggregate":
        config["pair_label_order"] = list(PAIR_LABELS)
    (out / "checkpoint.json").write_bytes(json_file(config))
    return {
        "out": str(out),
        "model_revision": revision,
        "after_weights": after,
        "weights_stage": args.weights_stage,
        "variant": args.variant,
    }


def seal(args) -> dict:
    root = Path(args.root)
    config = json.loads((root / "checkpoint.json").read_text())
    stage = json.loads((root / "encoder/local-files.json").read_text())["weights_stage"]
    if args.dataset_manifest:
        path = Path(args.dataset_manifest)
        dataset = {
            "dataset_id": json.loads(path.read_text())["dataset_id"],
            "dataset_manifest_sha256": sha256_file(path),
        }
    elif args.dataset_id and args.dataset_manifest_sha256:
        dataset = {
            "dataset_id": args.dataset_id,
            "dataset_manifest_sha256": args.dataset_manifest_sha256,
        }
    else:
        raise ExportError("give --dataset-manifest, or --dataset-id and --dataset-manifest-sha256")
    if any(tier not in LABEL_TIERS for tier in args.label_tier):
        raise ExportError(f"label tiers are {LABEL_TIERS}")
    untrained = stage == "pretrained_untrained_heads"
    manifest = {
        "template": False,
        "completed": not untrained,
        "return_protocol": RETURN_PROTOCOL,
        "artifact_kind": "huggingface_encoder",
        "artifact_protocol": ARTIFACT_PROTOCOL,
        "model_revision": config["model_revision"],
        "framework": "pytorch",
        "framework_version": args.framework_version or torch.__version__,
        "task_type": "relation",
        "label_order": list(RELATION_LABELS),
        **dataset,
        "training_partitions": [] if untrained else ["train"],
        "selection_partition": None if untrained else "dev",
        "test_used_for_selection": False,
        "evidence_selection_implemented": True,
        "evidence_selection_required": True,
        "checkpoint_files": {
            p.relative_to(root).as_posix(): sha256_file(p)
            for p in sorted(root.rglob("*"))
            if p.is_file() and p.relative_to(root).as_posix() != MANIFEST
        },
        "load_and_predict_command": args.load_and_predict_command,
        "training_notes_file": args.training_notes,
        "predictions_file": args.predictions,
    }
    if args.label_tier:
        manifest["label_tiers"] = sorted(set(args.label_tier), key=LABEL_TIERS.index)
    if untrained:
        manifest["weights_stage"] = stage
    raw = json_file(manifest)
    (root / MANIFEST).write_bytes(raw)
    return {"bundle_path": MANIFEST, "bundle_hash": hashlib.sha256(raw).hexdigest()}


def parser() -> argparse.ArgumentParser:
    main = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = main.add_subparsers(dest="command", required=True)
    out = commands.add_parser("export", help="write the v3 checkpoint layout")
    out.add_argument("--encoder-dir", required=True, help="save_pretrained directory")
    out.add_argument("--variant", choices=VARIANTS, required=True)
    out.add_argument("--source-revision", required=True, help="40-hex base model revision")
    out.add_argument("--weights-stage", choices=WEIGHTS_STAGES, default=WEIGHTS_STAGES[0])
    out.add_argument("--heads", help="head state dict: .pt, .safetensors or .npz")
    out.add_argument("--training-report", help="JSON training report (fit_split=train)")
    out.add_argument("--max-tokens", type=int, default=256)
    out.add_argument("--evidence-threshold", type=float, default=0.5)
    out.add_argument("--seed", type=int, default=5002)
    out.add_argument("--derived-from", help="optional SHA-256 naming the base checkpoint files")
    out.add_argument("--out", required=True, help="new directory for the return")
    sealing = commands.add_parser("seal", help="write checkpoint-manifest.json")
    sealing.add_argument("--root", required=True)
    sealing.add_argument("--dataset-manifest", help="dataset-manifest.json the model used")
    sealing.add_argument("--dataset-id")
    sealing.add_argument("--dataset-manifest-sha256")
    sealing.add_argument("--label-tier", action="append", default=[], choices=LABEL_TIERS)
    sealing.add_argument("--framework-version")
    sealing.add_argument(
        "--load-and-predict-command",
        default="not executed by RoleCraft: it registers this return and loads it itself",
    )
    sealing.add_argument("--training-notes", default="training-notes.md")
    sealing.add_argument("--predictions", default="predictions.dev.jsonl")
    return main


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        result = export(args) if args.command == "export" else seal(args)
    except ExportError as error:
        print(f"export_hf_return: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
