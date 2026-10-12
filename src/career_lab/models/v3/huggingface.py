"""Optional local-only pretrained encoder adapter; never silently downloads/falls back.

API reference: https://huggingface.co/docs/transformers/main_classes/model
Dependency/weight availability is a separate check from having this source file.
The checkpoint layout it writes and reads is ``docs/data/return-v3/encoder-return.md``.
"""

import hashlib
import io
import json
import re
import time
import zipfile
from pathlib import Path

import numpy as np

from career_lab.contracts.v2.core import FileRef, ProtocolError, canonical, digest, read_file

from .core import (
    LABELS,
    InputSize,
    abstention,
    checked_input,
    evidence_target,
    input_problem,
    prediction,
    training_examples,
)
from .encoder_artifact import (
    LEGACY_EVIDENCE_THRESHOLD,
    PAIR_LABELS,
    VARIANTS,
    checkpoint_settings,
    model_revision_v3,
    validate_training_identity,
    verify_encoder_files,
)
from .temporal import temporal_text

RELATION = LABELS["relation"]


def aggregate_pairs(pair_probabilities, threshold):
    """pair_aggregate v1: per-pair (SUPPORTS, CONTRADICTS, UNRELATED) to one relation.

    Any contradiction at or over ``threshold`` decides CONTRADICTED and cites every such
    candidate; otherwise any support decides SUPPORTED and cites those; otherwise
    INSUFFICIENT with no evidence. Unrelated pairs never count as support. With the
    decision's confidence m (the strongest deciding pair, or for INSUFFICIENT one minus
    the strongest support or contradiction), the decided relation gets (1 + m) / 2 and
    each other relation (1 - m) / 4. Returns those probabilities and per-candidate
    evidence scores whose ``>= threshold`` set is exactly the cited evidence.
    """
    pairs = np.asarray(pair_probabilities, dtype=float)
    if pairs.ndim != 2 or pairs.shape[1] != 3 or not len(pairs) or not np.isfinite(pairs).all():
        raise ProtocolError("invalid_pair_probabilities")
    supports, contradicts = pairs[:, 0], pairs[:, 1]
    if (contradicts >= threshold).any():
        decided, confidence, scores = 1, contradicts.max(), contradicts
    elif (supports >= threshold).any():
        decided, confidence, scores = 0, supports.max(), supports
    else:
        strongest = max(supports.max(), contradicts.max())
        decided, confidence, scores = 2, 1 - strongest, np.maximum(supports, contradicts)
    probabilities = np.full(len(RELATION), (1 - confidence) / 4)
    probabilities[decided] = (1 + confidence) / 2
    return probabilities, scores


def pair_targets(row):
    """Per-candidate pair labels a relation gold implies, or None when it names none.

    Candidates in the gold evidence take the relation's pair label; all others are
    UNRELATED. A label-only SUPPORTED/CONTRADICTED row does not say which pair.
    """
    target = evidence_target(row)
    label = row.annotation.final.label
    candidates = row.item.evidence.candidate_evidence
    unrelated = PAIR_LABELS.index("UNRELATED")
    if target is None:
        return [unrelated] * len(candidates) if label == "INSUFFICIENT" else None
    decided = {"SUPPORTED": "SUPPORTS", "CONTRADICTED": "CONTRADICTS"}.get(label)
    return [
        PAIR_LABELS.index(decided) if decided and candidate.id in target else unrelated
        for candidate in candidates
    ]


def encoder_texts(item):
    """The query and one body per candidate (``rolecraft-encoder-text-v1``).

    query = purpose, claim and the reference time line; body = candidate text and its
    validity line, each joined by newlines. Only these model_input fields are read.
    """
    candidates = item.evidence.candidate_evidence
    if not candidates:
        raise ProtocolError("no_candidate_evidence")
    query = item.evidence.purpose + "\n" + item.evidence.claim + "\n" + temporal_text(item)
    return query, [c.text + "\n" + temporal_text(item, c) for c in candidates]


def pack_text(bodies):
    """pack: bodies each followed by a newline; character span of each body."""
    text, spans = "", []
    for body in bodies:
        spans.append((len(text), len(text) + len(body)))
        text += body + "\n"
    return text, spans


def json_file(value) -> bytes:
    """Canonical JSON (sorted keys, no spaces, UTF-8) and a newline."""
    return (canonical(value) + "\n").encode()


def write_heads(path, arrays) -> None:
    """``heads.npz`` with fixed member order, timestamps and attributes (byte-reproducible)."""
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


def dependencies():
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except ImportError as exc:
        raise ProtocolError("pretrained_encoder_dependencies_unavailable", status=503) from exc
    return torch, AutoModel, AutoTokenizer


def verify_local_checkpoint(local_dir, revision, manifest_ref):
    if manifest_ref is None:
        raise ProtocolError("verified_local_checkpoint_manifest_required")
    root = Path(local_dir)
    manifest = json.loads(read_file(root, manifest_ref))
    if (
        manifest.get("protocol") != "w08-hf-local-files-v1"
        or manifest.get("source_revision") != revision
    ):
        raise ProtocolError("local_checkpoint_revision_mismatch")
    files = verify_encoder_files(root, manifest.get("files"), manifest_ref.path)
    return manifest | {
        "verified_files_digest": digest(files),
        "manifest_sha256": manifest_ref.sha256,
    }


class HuggingFaceCandidate:
    kind = "huggingface_encoder"

    def __init__(
        self,
        local_dir,
        *,
        revision,
        task_type="relation",
        variant="pair",
        max_tokens=256,
        evidence_threshold=LEGACY_EVIDENCE_THRESHOLD,
        seed=5002,
        checkpoint_manifest=None,
    ):
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ProtocolError("pinned_model_revision_required")
        if (
            task_type not in LABELS
            or variant not in VARIANTS
            or (variant == "pair_aggregate" and task_type != "relation")
            or isinstance(evidence_threshold, bool)
            or not 0 < evidence_threshold < 1
        ):
            raise ProtocolError("encoder_configuration_invalid")
        torch, AutoModel, AutoTokenizer = dependencies()
        local_dir = Path(local_dir)
        if not local_dir.is_dir():
            raise ProtocolError("local_pretrained_checkpoint_missing", status=503)
        verified = verify_local_checkpoint(local_dir, revision, checkpoint_manifest)
        self.checkpoint_identity = verified
        self.torch = torch
        self.task_type = task_type
        self.variant = variant
        self.max_tokens = max_tokens
        self.evidence_threshold = float(evidence_threshold)
        self.seed = seed
        self.source_revision = revision
        torch.manual_seed(seed)
        options = {
            "revision": revision,
            "local_files_only": True,
            "trust_remote_code": False,
            "token": False,
        }
        self.tokenizer = AutoTokenizer.from_pretrained(str(local_dir), use_fast=True, **options)
        if not 4 <= max_tokens <= self.tokenizer.model_max_length:
            raise ProtocolError("tokenizer_capacity_exceeded")
        self.encoder = AutoModel.from_pretrained(
            str(local_dir), use_safetensors=True, **options
        ).to(device="cpu", dtype=torch.float32)
        d = self.encoder.config.hidden_size
        # Heads come from the seed alone, whatever random state loading consumed.
        torch.manual_seed(seed)
        if variant == "pair_aggregate":
            self.pair = torch.nn.Linear(d, len(PAIR_LABELS))
        else:
            self.relation = torch.nn.Linear(d, len(LABELS[task_type]))
            self.selector = torch.nn.Linear(2 * d, 1)
        self.revision = "local-pretrained-untrained-heads:" + revision
        self.training_report = None
        self.weights_stage = None
        self.schema = 3

    def heads(self):
        """Head modules with the array-name prefixes of ``heads.npz``."""
        if self.variant == "pair_aggregate":
            return [("pair.", self.pair)]
        return [("relation.", self.relation), ("selector.", self.selector)]

    def _modules(self):
        return [("encoder.", self.encoder), *self.heads()]

    def _encode(self, item):
        """Tokenize exactly what prediction encodes; no forward pass."""
        query, bodies = encoder_texts(item)
        spans = []
        sequence_ids = offsets = None
        if self.variant == "pack":
            if not self.tokenizer.is_fast:
                raise ProtocolError("pack_evidence_spans_require_fast_tokenizer")
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
        return encoded, spans, sequence_ids, offsets

    def measure(self, item):
        """Batch sequence length prediction would encode, against ``max_tokens``."""
        encoded, *_ = self._encode(checked_input(item))
        return InputSize(int(encoded["input_ids"].shape[1]), self.max_tokens)

    def _hidden(self, item):
        encoded, spans, sequence_ids, offsets = self._encode(item)
        if encoded["input_ids"].shape[1] > self.max_tokens:
            raise ProtocolError("encoder_input_truncated")
        hidden = self.encoder(**encoded).last_hidden_state
        mask = encoded["attention_mask"].unsqueeze(-1).to(hidden.dtype)
        pooled = (hidden * mask).sum(1) / mask.sum(1).clamp_min(1)
        return hidden, pooled, spans, sequence_ids, offsets

    def _pair_logits(self, item):
        """pair_aggregate: one (SUPPORTS, CONTRADICTS, UNRELATED) logit row per candidate."""
        _, pooled, *_ = self._hidden(item)
        return self.pair(pooled)

    def _represent(self, item):
        hidden, pooled, spans, sequence_ids, offsets = self._hidden(item)
        if self.variant == "pack":
            global_rep = pooled[0]
            vectors = []
            for start, end in spans:
                indices = [
                    i
                    for i, ((a, b), sid) in enumerate(zip(offsets, sequence_ids, strict=True))
                    if sid == 1 and b > start and a < end
                ]
                if not indices:
                    raise ProtocolError("evidence_span_missing_or_truncated")
                vectors.append(hidden[0, indices].mean(0))
            candidates = self.torch.stack(vectors)
        else:
            global_rep = pooled.mean(0)
            candidates = pooled
        evidence_rep = self.torch.cat(
            [candidates, global_rep.unsqueeze(0).expand_as(candidates)], dim=-1
        )
        return self.relation(global_rep), self.selector(evidence_rep).squeeze(-1)

    def _hash(self, modules):
        h = hashlib.sha256()
        for prefix, module in modules:
            for name, tensor in sorted(module.state_dict().items()):
                t = tensor.detach().cpu().contiguous()
                h.update((prefix + name + str(t.dtype) + str(tuple(t.shape))).encode())
                h.update(t.float().numpy().tobytes())
        return h.hexdigest()

    def _v3_revision(self, after):
        return model_revision_v3(
            {
                "after_weights": after,
                "evidence_threshold": self.evidence_threshold,
                "max_tokens": self.max_tokens,
                "pooling": "mean",
                "source_revision": self.source_revision,
                "task_type": self.task_type,
                "variant": self.variant,
                "weights_stage": self.weights_stage,
            }
        )

    def _loss(self, row):
        torch = self.torch
        if self.variant == "pair_aggregate":
            targets = pair_targets(row)
            if targets is None:
                return None
            return torch.nn.functional.cross_entropy(
                self._pair_logits(row.item), torch.tensor(targets, dtype=torch.long)
            )
        relation, evidence = self._represent(row.item)
        y = torch.tensor(
            [LABELS[self.task_type].index(row.annotation.final.label)], dtype=torch.long
        )
        loss = torch.nn.functional.cross_entropy(relation.unsqueeze(0), y)
        target = evidence_target(row)
        if target is not None:
            y_ev = torch.tensor(
                [int(c.id in target) for c in row.item.evidence.candidate_evidence],
                dtype=torch.float32,
            )
            loss = loss + torch.nn.functional.binary_cross_entropy_with_logits(evidence, y_ev)
        return loss

    def fit(self, examples, *, epochs=1, learning_rate=2e-5):
        rows = training_examples(examples, self.task_type)
        if (
            type(epochs) is not int
            or epochs < 1
            or not np.isfinite(learning_rate)
            or learning_rate <= 0
        ):
            raise ProtocolError("training_hyperparameters_invalid")
        torch = self.torch
        modules = self._modules()
        parameters = [p for _, m in modules for p in m.parameters()]
        for _, module in modules:
            module.train()
        before = self._hash(modules)
        encoder_before = self._hash(modules[:1])
        optimizer = torch.optim.AdamW(parameters, lr=learning_rate)
        start = time.perf_counter()
        losses = []
        for _ in range(epochs):
            epoch = []
            for row in rows:
                optimizer.zero_grad()
                loss = self._loss(row)
                if loss is None:
                    continue
                if not torch.isfinite(loss):
                    raise ProtocolError("nonfinite_training_loss")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(parameters, 1.0)
                optimizer.step()
                epoch.append(float(loss.detach()))
            if not epoch:
                raise ProtocolError("training_targets_missing")
            losses.append(float(np.mean(epoch)))
        after = self._hash(modules)
        encoder_after = self._hash(modules[:1])
        if before == after or encoder_before == encoder_after:
            raise ProtocolError("encoder_parameters_not_updated")
        self.weights_stage = "supervised_finetuned"
        self.revision = self._v3_revision(after)
        self.training_report = {
            "backend": "huggingface",
            "source_revision": self.source_revision,
            "checkpoint_identity": self.checkpoint_identity,
            "pretrained": True,
            "training_kind": "supervised_encoder_finetuning",
            "variant": self.variant,
            "fit_split": "train",
            "seed": self.seed,
            "fit_seconds": time.perf_counter() - start,
            "epochs": epochs,
            "losses": losses,
            "before_weights": before,
            "after_weights": after,
            "encoder_before": encoder_before,
            "encoder_after": encoder_after,
            "device": "CPU",
            "train_records": len(rows),
            "train_ids": [r.record_id for r in rows],
            "input_hashes": [r.annotation.input_hash for r in rows],
        }
        return self.training_report

    def mark_untrained_heads(self):
        """Declare the seeded heads untrained (stage ``pretrained_untrained_heads``).

        Only this declaration lets untrained heads predict; such a checkpoint registers
        only as a synthetic mechanism.
        """
        if self.training_report is not None:
            raise ProtocolError("encoder_heads_already_declared")
        after = self._hash(self._modules())
        self.weights_stage = "pretrained_untrained_heads"
        self.revision = self._v3_revision(after)
        self.training_report = {
            "training_kind": "none",
            "source_revision": self.source_revision,
            "seed": self.seed,
            "after_weights": after,
        }
        return self.training_report

    def pair_judgements(self, item):
        """pair_aggregate: the (SUPPORTS, CONTRADICTS, UNRELATED) probabilities per candidate."""
        if self.variant != "pair_aggregate":
            raise ProtocolError("pair_judgements_require_pair_aggregate")
        item = checked_input(item)
        for _, module in self._modules():
            module.eval()
        with self.torch.no_grad():
            return self.torch.softmax(self._pair_logits(item), dim=-1).cpu().numpy()

    def predict(self, item):
        item = checked_input(item)
        if item.task_type != self.task_type:
            raise ProtocolError("candidate_task_mismatch")
        if input_problem(item):
            return abstention(item, self.revision, input_problem(item))
        if self.training_report is None:
            raise ProtocolError("encoder_heads_not_trained")
        for _, module in self._modules():
            module.eval()
        with self.torch.no_grad():
            try:
                if self.variant == "pair_aggregate":
                    pairs = self.torch.softmax(self._pair_logits(item), dim=-1).cpu().numpy()
                    p, e = aggregate_pairs(pairs, self.evidence_threshold)
                else:
                    relation, evidence = self._represent(item)
                    p = self.torch.softmax(relation, dim=-1).cpu().numpy()
                    e = self.torch.sigmoid(evidence).cpu().numpy()
            except ProtocolError as exc:
                return abstention(item, self.revision, exc.code)
        return prediction(item, self.revision, p, e, threshold=self.evidence_threshold)

    def save_checkpoint(self, target):
        """Write the v3 checkpoint layout; the outer return manifest is the producer's."""
        if self.training_report is None:
            raise ProtocolError("model_not_trained")
        target = Path(target)
        if target.exists():
            raise ProtocolError("immutable_checkpoint_exists")
        target.mkdir(parents=True)
        encoder_root = target / "encoder"
        self.encoder.save_pretrained(encoder_root, safe_serialization=True)
        self.tokenizer.save_pretrained(encoder_root)
        write_heads(
            target / "heads.npz",
            {
                prefix + key: tensor.detach().cpu().numpy()
                for prefix, module in self.heads()
                for key, tensor in module.state_dict().items()
            },
        )
        encoder_files = {
            p.relative_to(encoder_root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(encoder_root.rglob("*"))
            if p.is_file()
        }
        local_manifest = {
            "protocol": "w08-hf-local-files-v1",
            "source_revision": self.source_revision,
            "weights_stage": self.weights_stage,
            "derived_from": self.checkpoint_identity["manifest_sha256"],
            "files": encoder_files,
        }
        (encoder_root / "local-files.json").write_bytes(json_file(local_manifest))
        files = {
            p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(target.rglob("*"))
            if p.is_file()
        }
        config = {
            "checkpoint_schema_version": 3,
            "source_revision": self.source_revision,
            "task_type": self.task_type,
            "variant": self.variant,
            "pooling": "mean",
            "max_tokens": self.max_tokens,
            "evidence_threshold": self.evidence_threshold,
            "seed": self.seed,
            "model_revision": self.revision,
            "training_report": self.training_report,
            "files": files,
        }
        if self.variant == "pair_aggregate":
            config["pair_label_order"] = list(PAIR_LABELS)
        (target / "checkpoint.json").write_bytes(json_file(config))

    @classmethod
    def load_checkpoint(cls, target):
        """Load either checkpoint layout after re-hashing every file and every tensor."""
        target = Path(target)
        config = json.loads((target / "checkpoint.json").read_text())
        for name, sha in config["files"].items():
            read_file(target, FileRef(path=name, sha256=sha))
        settings = checkpoint_settings(config)
        local_ref = FileRef(
            path="local-files.json", sha256=config["files"]["encoder/local-files.json"]
        )
        obj = cls(
            target / "encoder",
            revision=config["source_revision"],
            task_type=config["task_type"],
            variant=settings.variant,
            max_tokens=settings.max_tokens,
            evidence_threshold=settings.evidence_threshold,
            seed=settings.seed,
            checkpoint_manifest=local_ref,
        )
        with np.load(target / "heads.npz", allow_pickle=False) as archive:
            for prefix, module in obj.heads():
                module.load_state_dict(
                    {k: obj.torch.from_numpy(archive[prefix + k]) for k in module.state_dict()},
                    strict=True,
                )
        obj.schema = settings.schema
        obj.weights_stage = obj.checkpoint_identity["weights_stage"]
        obj.training_report = config["training_report"]
        obj.revision = config["model_revision"]
        if obj._hash(obj._modules()) != obj.training_report["after_weights"]:
            raise ProtocolError("checkpoint_parameter_identity_mismatch")
        validate_training_identity(config, settings, obj.weights_stage)
        return obj
