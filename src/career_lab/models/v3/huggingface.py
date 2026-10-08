"""Optional local-only pretrained encoder adapter; never silently downloads/falls back.

API reference: https://huggingface.co/docs/transformers/main_classes/model
Dependency/weight availability is a separate check from having this source file.
"""

from pathlib import Path
import hashlib
import json
import re
import time
import numpy as np

from career_lab.contracts.v2.core import ProtocolError, FileRef, read_file, digest
from .temporal import temporal_text
from .core import (
    LABELS,
    training_examples,
    evidence_target,
    checked_input,
    input_problem,
    abstention,
    prediction,
)


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
    files = manifest.get("files")
    if (
        not isinstance(files, dict)
        or "config.json" not in files
        or not any(p.endswith(".safetensors") for p in files)
    ):
        raise ProtocolError("local_checkpoint_files_incomplete")
    for name, expected in files.items():
        if Path(name).suffix not in {".json", ".safetensors", ".model", ".txt", ".md"}:
            raise ProtocolError("checkpoint_file_type_not_allowed")
        read_file(root, FileRef(path=name, sha256=expected))
    actual = {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.relative_to(root).as_posix() != manifest_ref.path
    }
    if actual != set(files):
        raise ProtocolError("local_checkpoint_member_set_mismatch")
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
        seed=5002,
        checkpoint_manifest=None,
    ):
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ProtocolError("pinned_model_revision_required")
        if task_type not in LABELS or variant not in {"pack", "pair"}:
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
        self.relation = torch.nn.Linear(d, len(LABELS[task_type]))
        self.selector = torch.nn.Linear(2 * d, 1)
        self.revision = "local-pretrained-untrained-heads:" + revision
        self.training_report = None

    def _represent(self, item):
        candidates = item.evidence.candidate_evidence
        if not candidates:
            raise ProtocolError("no_candidate_evidence")
        query = item.evidence.purpose + "\n" + item.evidence.claim + "\n" + temporal_text(item)
        bodies = [c.text + "\n" + temporal_text(item, c) for c in candidates]
        if self.variant == "pack":
            if not self.tokenizer.is_fast:
                raise ProtocolError("pack_evidence_spans_require_fast_tokenizer")
            text = ""
            spans = []
            for body in bodies:
                start = len(text)
                text += body
                spans.append((start, len(text)))
                text += "\n"
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
            raise ProtocolError("encoder_input_truncated")
        hidden = self.encoder(**encoded).last_hidden_state
        mask = encoded["attention_mask"].unsqueeze(-1).to(hidden.dtype)
        pooled = (hidden * mask).sum(1) / mask.sum(1).clamp_min(1)
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
        modules = [
            ("encoder.", self.encoder),
            ("relation.", self.relation),
            ("selector.", self.selector),
        ]
        for _, module in modules:
            module.train()
        before = self._hash(modules)
        encoder_before = self._hash(modules[:1])
        optimizer = torch.optim.AdamW(
            [p for _, m in modules for p in m.parameters()], lr=learning_rate
        )
        start = time.perf_counter()
        losses = []
        for _ in range(epochs):
            epoch = []
            for row in rows:
                optimizer.zero_grad()
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
                    loss = loss + torch.nn.functional.binary_cross_entropy_with_logits(
                        evidence, y_ev
                    )
                if not torch.isfinite(loss):
                    raise ProtocolError("nonfinite_training_loss")
                loss.backward()
                torch.nn.utils.clip_grad_norm_([p for _, m in modules for p in m.parameters()], 1.0)
                optimizer.step()
                epoch.append(float(loss.detach()))
            losses.append(float(np.mean(epoch)))
        after = self._hash(modules)
        encoder_after = self._hash(modules[:1])
        if before == after or encoder_before == encoder_after:
            raise ProtocolError("encoder_parameters_not_updated")
        self.revision = "hf-finetuned:" + self.source_revision + ":" + after
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

    def predict(self, item):
        item = checked_input(item)
        if item.task_type != self.task_type:
            raise ProtocolError("candidate_task_mismatch")
        if input_problem(item):
            return abstention(item, self.revision, input_problem(item))
        if self.training_report is None:
            raise ProtocolError("encoder_heads_not_trained")
        for module in (self.encoder, self.relation, self.selector):
            module.eval()
        with self.torch.no_grad():
            try:
                relation, evidence = self._represent(item)
            except ProtocolError as exc:
                return abstention(item, self.revision, exc.code)
            p = self.torch.softmax(relation, dim=-1).cpu().numpy()
            e = self.torch.sigmoid(evidence).cpu().numpy()
        return prediction(item, self.revision, p, e)

    def save_checkpoint(self, target):
        """Optional backend checkpoint; W01 model-bundle registration stays separate."""
        if self.training_report is None:
            raise ProtocolError("model_not_trained")
        target = Path(target)
        if target.exists():
            raise ProtocolError("immutable_checkpoint_exists")
        target.mkdir(parents=True)
        try:
            self.encoder.save_pretrained(target / "encoder", safe_serialization=True)
            self.tokenizer.save_pretrained(target / "encoder")
            arrays = {
                prefix + key: t.detach().cpu().numpy()
                for prefix, m in (("relation.", self.relation), ("selector.", self.selector))
                for key, t in m.state_dict().items()
            }
            np.savez(target / "heads.npz", **arrays)
            encoder_root = target / "encoder"
            encoder_files = {
                p.relative_to(encoder_root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in encoder_root.rglob("*")
                if p.is_file()
            }
            local_manifest = {
                "protocol": "w08-hf-local-files-v1",
                "source_revision": self.source_revision,
                "weights_stage": "supervised_finetuned",
                "derived_from": self.checkpoint_identity["manifest_sha256"],
                "files": encoder_files,
            }
            (encoder_root / "local-files.json").write_text(
                json.dumps(local_manifest, ensure_ascii=False, sort_keys=True)
            )
            files = {
                p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in target.rglob("*")
                if p.is_file()
            }
            config = {
                "source_revision": self.source_revision,
                "task_type": self.task_type,
                "variant": self.variant,
                "max_tokens": self.max_tokens,
                "seed": self.seed,
                "model_revision": self.revision,
                "training_report": self.training_report,
                "files": files,
            }
            (target / "checkpoint.json").write_text(
                json.dumps(config, ensure_ascii=False, indent=2)
            )
        except Exception:
            # Preserve an explicit incomplete directory for diagnosis; never load it
            # as a successful checkpoint without the final manifest.
            raise

    @classmethod
    def load_checkpoint(cls, target):
        from career_lab.contracts.v2.core import FileRef, read_file

        target = Path(target)
        config = json.loads((target / "checkpoint.json").read_text())
        for name, sha in config["files"].items():
            read_file(target, FileRef(path=name, sha256=sha))
        local_ref = FileRef(
            path="local-files.json", sha256=config["files"]["encoder/local-files.json"]
        )
        obj = cls(
            target / "encoder",
            revision=config["source_revision"],
            task_type=config["task_type"],
            variant=config["variant"],
            max_tokens=config["max_tokens"],
            seed=config["seed"],
            checkpoint_manifest=local_ref,
        )
        with np.load(target / "heads.npz", allow_pickle=False) as archive:
            for prefix, module in (("relation.", obj.relation), ("selector.", obj.selector)):
                module.load_state_dict(
                    {k: obj.torch.from_numpy(archive[prefix + k]) for k in module.state_dict()},
                    strict=True,
                )
        obj.training_report = config["training_report"]
        obj.revision = config["model_revision"]
        after = obj._hash(
            [("encoder.", obj.encoder), ("relation.", obj.relation), ("selector.", obj.selector)]
        )
        if (
            after != obj.training_report["after_weights"]
            or obj.revision != "hf-finetuned:" + obj.source_revision + ":" + after
        ):
            raise ProtocolError("checkpoint_parameter_identity_mismatch")
        return obj
