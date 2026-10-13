#!/usr/bin/env python3
"""RoleCraft encoder return v3: export a trained encoder, predict as RoleCraft does, seal.

Runs in the producer's own environment (Python 3.10+, torch, transformers, numpy,
safetensors; transformers installs the last two). It never imports RoleCraft and never
downloads: every path is local. Specification: ../encoder-return.md. Run ``export`` and
``predict`` on CPU under the product's pinned versions (torch 2.8.0, transformers 4.57.1,
tokenizers 0.22.2, safetensors 0.6.2); both print whether the installed set matches.

    python export_hf_return.py export --encoder-dir ENCODER --heads HEADS.pt \\
        --training-report REPORT.json --variant pair --source-revision BASE_REVISION \\
        --out RETURN                                  # --max-tokens defaults to 512
    python export_hf_return.py predict --root RETURN --inputs data/dev.inputs.jsonl \\
        --labels data/dev.labels.jsonl --out RETURN/predictions.dev.jsonl
    # write RETURN/training-notes.md, then
    python export_hf_return.py seal --root RETURN --dataset-manifest dataset-manifest.json
    # after the freeze: test rows go outside the sealed return
    python export_hf_return.py predict --root RETURN --inputs data/test.inputs.jsonl \\
        --out predictions.test.jsonl

``export`` writes checkpoint.json, heads.npz and encoder/ (with encoder/local-files.json)
and prints the model_revision that every prediction row must carry. ``predict`` loads the
return the way RoleCraft's loader does and writes v3 prediction rows with the same
abstentions, pooling, aggregation and evidence threshold. ``seal`` writes
checkpoint-manifest.json over every file in RETURN, artifact roles included. The functions
after_weights, model_revision, aggregate_pairs, input_problem and write_heads are the
specification's definitions.
"""

import argparse
import hashlib
import importlib.metadata
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
TIME_POLICY = "historical-evidence-time-v1"
# The inference runtime RoleCraft pins in every encoder registration (encoder-return.md §11).
PRODUCT_RUNTIME = {
    "torch": "2.8.0",
    "transformers": "4.57.1",
    "tokenizers": "0.22.2",
    "safetensors": "0.6.2",
}


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


def runtime() -> dict:
    """Installed inference libraries and whether they are the ones RoleCraft pins."""
    installed = {}
    for name in PRODUCT_RUNTIME:
        try:
            installed[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed[name] = None
    matches = installed == PRODUCT_RUNTIME
    if not matches:
        print(
            f"warning: installed {installed} differ from RoleCraft's {PRODUCT_RUNTIME}; "
            "after_weights and probabilities may not reproduce in RoleCraft",
            file=sys.stderr,
        )
    return {"installed": installed, "matches_product": matches}


def input_problem(model_input: dict):
    """Inputs RoleCraft abstains on before encoding; the reason is its reason code.

    Checked in this order: incomplete package, empty claim, undetermined temporal scope,
    reference time mismatch, candidate validity not known for every candidate.
    """
    package = model_input["evidence"]
    if package["completeness"] != "complete":
        return "input_" + package["completeness"]
    if not package["claim"].strip():
        return "empty_claim"
    context = package["rule_context"].get("evidence_time_context")
    if (
        not isinstance(context, dict)
        or context.get("policy") != TIME_POLICY
        or context.get("status") != "known"
    ):
        return "temporal_scope_undetermined"
    if context.get("reference_seq") != package["as_of"]["business_seq"]:
        return "temporal_reference_mismatch"
    known = context.get("validity_known_ids")
    expected = {c["id"] for c in package["candidate_evidence"]}
    if (
        not isinstance(known, list)
        or any(not isinstance(value, str) for value in known)
        or len(known) != len(set(known))
        or set(known) != expected
    ):
        return "evidence_validity_undetermined"
    return None


def input_failure(model_input: dict):
    """Inputs RoleCraft's loader refuses outright (a ``failed`` row), never predicts."""
    package = model_input["evidence"]
    sessions = {ref["session_id"] for ref in package["subjects"]} | {
        candidate["ref"]["session_id"] for candidate in package["candidate_evidence"]
    }
    if len(sessions) > 1:
        return "cross_session_model_input"
    return None if model_input.get("task_type") == "relation" else "candidate_task_mismatch"


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
    in candidate order; threshold at least 0.5. Returns relation probabilities
    (SUPPORTED, CONTRADICTED, INSUFFICIENT) and per-candidate evidence scores;
    evidence = scores >= threshold.
    """
    if not 0.5 <= threshold < 1:
        raise ValueError("pair_aggregate needs 0.5 <= evidence_threshold < 1")
    pairs = np.asarray(pair_probabilities, dtype=float)
    supports, contradicts, unrelated = pairs[:, 0], pairs[:, 1], pairs[:, 2]
    support = np.where(supports > unrelated, supports, 0.0)
    if (contradicts >= threshold).any():
        decided, confidence, scores = 1, contradicts.max(), contradicts
    elif (support >= threshold).any():
        decided, confidence, scores = 0, support.max(), support
    else:
        strongest = max(supports.max(), contradicts.max())
        decided, confidence, scores = 2, 1 - strongest, np.maximum(support, contradicts)
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
    if args.variant == "pair_aggregate" and args.evidence_threshold < 0.5:
        raise ExportError("pair_aggregate needs --evidence-threshold of at least 0.5")
    if args.max_tokens < 4:
        raise ExportError("--max-tokens must be at least 4")
    untrained = args.weights_stage == "pretrained_untrained_heads"
    if untrained and (args.heads or args.training_report):
        raise ExportError("untrained heads come from --seed; give no --heads or report")
    if not untrained and not (args.heads and args.training_report):
        raise ExportError("a fine-tuned return needs --heads and --training-report")


def export(args) -> dict:
    check_settings(args)
    environment = runtime()
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
    limit = min((value for value in limits if isinstance(value, int)), default=None)
    if limit is not None and args.max_tokens > limit:
        raise ExportError(
            f"--max-tokens {args.max_tokens} exceeds this encoder's tokenizer or position limit "
            f"{limit}; give --max-tokens {limit} or less (inputs over it abstain, never truncate)"
        )
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
                f"{loading['missing_keys'][:5]}; save the complete fine-tuned encoder "
                "(a sequence-classification model has no pooler: encoder-return.md section 6)"
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
        "max_tokens": args.max_tokens,
        "runtime": environment,
    }


class Abstain(Exception):
    """One record the loader abstains on; the message is its reason code."""


class Loaded:
    """A v3 return loaded the way RoleCraft's loader loads it (CPU, float32, eval mode)."""

    def __init__(self, root: Path):
        config = json.loads((root / "checkpoint.json").read_text())
        for name, checksum in config["files"].items():
            if sha256_file(root / name) != checksum:
                raise ExportError(f"{name}: SHA-256 differs from checkpoint.json")
        if config.get("pooling", "mean") != "mean" or config["variant"] not in VARIANTS:
            raise ExportError("only mean pooling and the pack, pair, pair_aggregate variants")
        self.variant = config["variant"]
        self.threshold = float(config.get("evidence_threshold", 0.5))
        self.max_tokens = config["max_tokens"]
        self.revision = config["model_revision"]
        options = {
            "revision": config["source_revision"],
            "local_files_only": True,
            "trust_remote_code": False,
            "token": False,
        }
        torch.manual_seed(config["seed"])
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(root / "encoder"), use_fast=True, **options
        )
        if not 4 <= self.max_tokens <= self.tokenizer.model_max_length:
            raise ExportError("max_tokens exceeds the tokenizer limit")
        self.encoder = AutoModel.from_pretrained(
            str(root / "encoder"), use_safetensors=True, **options
        ).to(device="cpu", dtype=torch.float32)
        self.heads = dict(
            head_modules(self.variant, self.encoder.config.hidden_size, config["seed"])
        )
        with np.load(root / "heads.npz", allow_pickle=False) as archive:
            for prefix, module in self.heads.items():
                module.load_state_dict(
                    {k: torch.from_numpy(archive[prefix + k]) for k in module.state_dict()},
                    strict=True,
                )
        modules = [("encoder.", self.encoder), *self.heads.items()]
        if after_weights(modules) != config["training_report"]["after_weights"]:
            raise ExportError(
                "after_weights differ from the training report: load under the pinned "
                "versions, with the complete encoder (pooler included) and float32 heads"
            )
        for _, module in modules:
            module.eval()

    def encode(self, query: str, bodies: list[str]):
        """Tokenize exactly as RoleCraft does; inputs over max_tokens abstain, never truncate."""
        if not bodies:
            raise Abstain("no_candidate_evidence")
        spans = sequence_ids = offsets = None
        if self.variant == "pack":
            if not self.tokenizer.is_fast:
                raise Abstain("pack_evidence_spans_require_fast_tokenizer")
            text, spans = pack_text(bodies)
            encoded = self.tokenizer(
                query,
                text_pair=text,
                padding=True,
                truncation=False,
                return_offsets_mapping=True,
                return_tensors="pt",
            )
            sequence_ids = encoded.sequence_ids(0)
            offsets = encoded.pop("offset_mapping")[0].tolist()
        else:
            encoded = self.tokenizer(
                [query] * len(bodies),
                text_pair=bodies,
                padding=True,
                truncation=False,
                return_tensors="pt",
            )
        if encoded["input_ids"].shape[1] > self.max_tokens:
            raise Abstain("encoder_input_truncated")
        return encoded, spans, sequence_ids, offsets

    def scores(self, model_input: dict):
        """Relation probabilities and per-candidate evidence scores (section 5)."""
        encoded, spans, sequence_ids, offsets = self.encode(*encoder_inputs(model_input))
        with torch.no_grad():
            hidden = self.encoder(**encoded).last_hidden_state
            mask = encoded["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp_min(1)
            if self.variant == "pair_aggregate":
                pairs = torch.softmax(self.heads["pair."](pooled), dim=-1).cpu().numpy()
                return aggregate_pairs(pairs, self.threshold)
            if self.variant == "pack":
                overall, vectors = pooled[0], []
                for start, end in spans:
                    indices = [
                        i
                        for i, ((a, b), sid) in enumerate(zip(offsets, sequence_ids, strict=True))
                        if sid == 1 and b > start and a < end
                    ]
                    if not indices:
                        raise Abstain("evidence_span_missing_or_truncated")
                    vectors.append(hidden[0, indices].mean(0))
                candidates = torch.stack(vectors)
            else:
                overall, candidates = pooled.mean(0), pooled
            pairs = torch.cat([candidates, overall.unsqueeze(0).expand_as(candidates)], dim=-1)
            relation = torch.softmax(self.heads["relation."](overall), dim=-1).cpu().numpy()
            evidence = torch.sigmoid(self.heads["selector."](pairs).squeeze(-1)).cpu().numpy()
        return relation, evidence

    def row(self, record: dict) -> dict:
        """One v3 prediction row for an ``*.inputs.jsonl`` record."""
        model_input = record["model_input"]
        row = {
            "return_schema_version": 3,
            "record_id": record["record_id"],
            "input_hash": record["input_hash"],
            "model_revision": self.revision,
            "task_type": "relation",
        }
        unsuccessful = {
            "probabilities": None,
            "label": None,
            "evidence_ids": [],
            "evidence_bindings": [],
        }
        failure = input_failure(model_input)
        if failure:
            return row | unsuccessful | {"status": "failed", "reason": failure}
        try:
            problem = input_problem(model_input)
            if problem:
                raise Abstain(problem)
            probabilities, scores = self.scores(model_input)
        except Abstain as abstention:
            return row | unsuccessful | {"status": "abstained", "reason": str(abstention)}
        probabilities = [float(value) for value in probabilities]
        candidates = model_input["evidence"]["candidate_evidence"]
        selected = [
            c for c, score in zip(candidates, scores, strict=True) if score >= self.threshold
        ]
        row |= {
            "status": "ok",
            "reason": None,
            "probabilities": probabilities,
            "label": RELATION_LABELS[int(np.argmax(probabilities))],
            "evidence_ids": [c["id"] for c in selected],
            "evidence_bindings": [
                {
                    "candidate_id": c["id"],
                    "candidate_sha256": hashlib.sha256(canonical_json(c)).hexdigest(),
                }
                for c in selected
            ],
        }
        if not selected:
            row["reason"] = "no candidate reached the evidence threshold"
        return row


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def predict(args) -> dict:
    """Write v3 rows for every input record, as RoleCraft's loader would predict them."""
    root, out = Path(args.root).resolve(), Path(args.out).resolve()
    if (root / MANIFEST).exists() and out.is_relative_to(root):
        raise ExportError(
            f"{root} is sealed ({MANIFEST} exists): write rows outside it, an unlisted file "
            "inside the return is refused"
        )
    if out.exists():
        raise ExportError(f"{out} exists; prediction rows are written once")
    environment = runtime()
    loaded = Loaded(root)
    records = read_jsonl(Path(args.inputs))
    rows = [loaded.row(record) for record in records]
    evaluable = {}
    if args.labels:
        evaluable = {
            label["record_id"]: label["evidence_evaluable"]
            for label in read_jsonl(Path(args.labels))
        }
    # verify-return refuses these (return_evidence_selection_required): a supported or
    # contradicted result without evidence where the gold evidence is evaluable.
    missing = sorted(
        row["record_id"]
        for row in rows
        if row["status"] == "ok"
        and row["label"] != "INSUFFICIENT"
        and not row["evidence_ids"]
        and evaluable.get(row["record_id"], not args.labels)
    )
    if missing:
        print(
            f"warning: {len(missing)} supported/contradicted rows select no evidence and "
            "fail RoleCraft's format check where the gold evidence is evaluable",
            file=sys.stderr,
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    statuses, abstentions = {}, {}
    for row in rows:
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
        if row["status"] != "ok":
            abstentions[row["reason"]] = abstentions.get(row["reason"], 0) + 1
    return {
        "out": str(out),
        "rows": len(rows),
        "model_revision": loaded.revision,
        "statuses": statuses,
        "abstentions": abstentions,
        "evidence_missing": missing,
        "device": "cpu",
        "dtype": "float32",
        "runtime": environment,
    }


def tokenizer_file(name: str) -> bool:
    """The registration's tokenizer test for a file directly under encoder/."""
    return "tokenizer" in name or name in {"vocab.txt", "sentencepiece.bpe.model"}


def artifact_roles(files: dict) -> dict:
    """Which listed files are the checkpoint, config and tokenizer (validate-handoff needs all
    three named explicitly: filenames never select a model or adapter on our side)."""
    encoder = sorted(name for name in files if name.startswith("encoder/"))
    return {
        "checkpoint": ["heads.npz", *(n for n in encoder if n.endswith(".safetensors"))],
        "config": ["checkpoint.json", "encoder/config.json"],
        "tokenizer": [n for n in encoder if tokenizer_file(n.removeprefix("encoder/"))],
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
    manifest["artifact_roles"] = artifact_roles(manifest["checkpoint_files"])
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
    out.add_argument(
        "--max-tokens", type=int, default=512, help="XLM-R base limit; never truncated"
    )
    out.add_argument("--evidence-threshold", type=float, default=0.5)
    out.add_argument("--seed", type=int, default=5002)
    out.add_argument("--derived-from", help="optional SHA-256 naming the base checkpoint files")
    out.add_argument("--out", required=True, help="new directory for the return")
    rows = commands.add_parser("predict", help="write v3 prediction rows as RoleCraft loads")
    rows.add_argument("--root", required=True, help="the exported return directory")
    rows.add_argument("--inputs", required=True, help="data/<split>.inputs.jsonl")
    rows.add_argument("--labels", help="data/<split>.labels.jsonl: names rows we would refuse")
    rows.add_argument("--out", required=True, help="new file; outside the return once sealed")
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
        result = {"export": export, "predict": predict, "seal": seal}[args.command](args)
    except ExportError as error:
        print(f"export_hf_return: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
