"""C1 inference for the recognition layer: the trained XLM-R ``pair_aggregate`` model on CPU.

``CAREER_LAB_RELATION_ENCODER=<dir>`` names the output of
``experiments/recognition/relation/train_c1.py`` (``encoder/``, ``heads.npz``, ``c1.json``,
``temperature.json``, ``lift.json``). Text and aggregation follow the encoder-return v3
specification exactly (``rolecraft-encoder-text-v1``, aggregation rule v1), so the same
weights can also be exported through ``docs/data/return-v3/reference/export_hf_return.py``
and registered for the product's model-advice slot.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from career_lab.models.v3.huggingface import aggregate_pairs
from career_lab.recognition.relation import ENCODER_ID, LABELS, Judgement

_LOCK = threading.Lock()


class EncoderRelation:
    def __init__(self, path: str | Path) -> None:
        os.environ.setdefault("USE_TF", "0")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        import torch
        from transformers import AutoModel, AutoTokenizer

        root = Path(path)
        self.torch = torch
        self.config = json.loads((root / "c1.json").read_text(encoding="utf-8"))
        temperature = root / "temperature.json"
        self.temperature = (
            float(json.loads(temperature.read_text(encoding="utf-8"))["temperature"])
            if temperature.is_file()
            else 1.0
        )
        self.threshold = float(self.config.get("evidence_threshold", 0.5))
        self.max_tokens = int(self.config.get("max_tokens", 256))
        self.tokenizer = AutoTokenizer.from_pretrained(str(root / "encoder"), use_fast=True)
        self.encoder = (
            AutoModel.from_pretrained(str(root / "encoder"), use_safetensors=True)
            .to(device="cpu", dtype=torch.float32)
            .eval()
        )
        with np.load(root / "heads.npz", allow_pickle=False) as heads:
            self.weight = torch.from_numpy(heads["pair.weight"]).float()
            self.bias = torch.from_numpy(heads["pair.bias"]).float()
        self.revision = hashlib.sha256((root / "heads.npz").read_bytes()).hexdigest()[:12]

    def pair_probabilities(self, query: str, bodies: Sequence[str]) -> np.ndarray:
        torch = self.torch
        encoded = self.tokenizer(
            [query] * len(bodies),
            list(bodies),
            padding=True,
            truncation="only_second",
            max_length=self.max_tokens,
            return_tensors="pt",
        )
        with _LOCK, torch.inference_mode():
            hidden = self.encoder(**encoded).last_hidden_state
            mask = encoded["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            logits = pooled @ self.weight.T + self.bias
            return torch.softmax(logits / self.temperature, dim=-1).numpy()

    def judge(
        self,
        claim: str,
        candidates: Sequence[tuple],
        *,
        language: str = "zh",
        as_of: int = 0,
        purpose: str = "commitment",
    ) -> Judgement:
        """``candidates``: (id, text) or (id, text, observed, valid_from, valid_until)."""
        query = f"{purpose}\n{claim}\nreference time {as_of}; temporal scope known"
        bodies = []
        for c in candidates:
            observed, valid_from, valid_until = (c[2], c[3], c[4]) if len(c) >= 5 else (0, 0, None)
            until = "open" if valid_until is None else valid_until
            bodies.append(
                f"{c[1]}\nobserved {observed}; valid from {valid_from}; valid until {until}"
            )
        pairs = self.pair_probabilities(query, bodies)
        probabilities, scores = aggregate_pairs(pairs, self.threshold)
        probabilities = np.asarray(probabilities, dtype=float)
        label = LABELS[int(np.argmax(probabilities))]
        evidence = tuple(
            c[0] for c, s in zip(candidates, scores) if s >= self.threshold
        ) if label != "insufficient" else ()
        return Judgement(
            label=label,
            probabilities={name: float(p) for name, p in zip(LABELS, probabilities)},
            evidence_ids=evidence,
            recognizer_id=ENCODER_ID,
            revision=self.revision,
            fallback=False,
            reason="pair_aggregate",
        )
