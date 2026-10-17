"""Shared sentence embedder for C2 retrieval and C4 scope: ``intfloat/multilingual-e5-small``.

Loaded from ``$CAREER_LAB_RECOGNIZERS/retrieval-e5`` (a local Hugging Face checkout) with
mean pooling and L2 normalisation; ``query: `` / ``passage: `` prefixes as the model card
asks. Needs torch and transformers (the ``encoder`` extra, i.e. ``.venv-encoder``); without
them, or without the directory, ``Embedder.get()`` returns ``None`` and callers fall back
to BM25. Vectors are cached in memory by text digest.
"""

from __future__ import annotations

import hashlib
import os
import threading
from typing import Literal

import numpy as np

from career_lab.recognition import registry

ID = "retrieval-e5"
_LOCK = threading.Lock()
_INSTANCE: Embedder | None | bool = False  # False = not tried yet


class Embedder:
    dimension = 384

    def __init__(self, path) -> None:
        os.environ.setdefault("USE_TF", "0")
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
        import torch
        from transformers import AutoModel, AutoTokenizer

        torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(str(path))
        self.model = AutoModel.from_pretrained(str(path)).eval()
        entry = registry.get(ID)
        self.revision = entry.revision if entry is not None else "unhashed"
        self.cache: dict[str, np.ndarray] = {}

    @classmethod
    def get(cls) -> Embedder | None:
        global _INSTANCE
        if _INSTANCE is False:
            with _LOCK:
                if _INSTANCE is False:
                    entry = registry.get(ID)
                    try:
                        _INSTANCE = cls(entry.path) if entry is not None else None
                    except Exception:  # noqa: BLE001 - missing torch or broken checkout
                        _INSTANCE = None
        return _INSTANCE or None

    def encode(
        self, texts: list[str], kind: Literal["query", "passage"] = "passage", batch: int = 32
    ) -> np.ndarray:
        prefix = "query: " if kind == "query" else "passage: "
        keys = [hashlib.sha1((prefix + t).encode()).hexdigest() for t in texts]
        # Length-sorted batches keep padding (and CPU time) small.
        missing = sorted(
            {i for i, k in enumerate(keys) if k not in self.cache}, key=lambda i: len(texts[i])
        )
        for begin in range(0, len(missing), batch):
            chunk = missing[begin : begin + batch]
            encoded = self.tokenizer(
                [prefix + texts[i] for i in chunk],
                padding=True,
                truncation=True,
                max_length=256,
                return_tensors="pt",
            )
            with _LOCK, self.torch.inference_mode():
                hidden = self.model(**encoded).last_hidden_state
                mask = encoded["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
                pooled = self.torch.nn.functional.normalize(pooled, p=2, dim=1)
            for i, vector in zip(chunk, pooled.cpu().numpy(), strict=False):
                self.cache[keys[i]] = vector.astype(np.float32)
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        return np.stack([self.cache[k] for k in keys])
