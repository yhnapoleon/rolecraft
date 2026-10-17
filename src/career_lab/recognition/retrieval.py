"""C2 retrieval over evidence units: BM25, e5 dense cosine, and reciprocal rank fusion.

BM25 reuses the product tokenizer (``assistant/retrieval.tokens``: Chinese bigrams and
Latin words) with a light English stemmer (strip s / ed / ing). Dense retrieval uses the
shared ``Embedder``; RRF fuses the two ranks with k = 60. Without the embedder, ``dense``
and ``rrf`` degrade to BM25 and the result is marked ``fallback``.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from career_lab.assistant.retrieval import tokens as product_tokens

Method = Literal["bm25", "dense", "rrf"]
RRF_K = 60
K1, B = 1.2, 0.75


def stem(token: str) -> str:
    if not token.isascii() or len(token) <= 3:
        return token
    for suffix in ("ing", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    return token


def tokens(text: str) -> list[str]:
    return [stem(t) for t in product_tokens(text)]


def bm25(query: str, texts: Sequence[str]) -> np.ndarray:
    """Okapi BM25 scores of every text for ``query``."""
    if not texts:
        return np.zeros(0)
    bags = [Counter(tokens(t)) for t in texts]
    lengths = np.array([sum(b.values()) for b in bags], dtype=float)
    average = lengths.mean() or 1.0
    terms = set(tokens(query))
    n = len(bags)
    scores = np.zeros(n)
    for term in terms:
        df = sum(term in b for b in bags)
        if df == 0:
            continue
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
        freq = np.array([b[term] for b in bags], dtype=float)
        scores += idf * freq * (K1 + 1) / (freq + K1 * (1 - B + B * lengths / average))
    return scores


def bm25_normalized(query: str, texts: Sequence[str]) -> np.ndarray:
    """BM25 divided by the query's self-score bound, so 1.0 means every term matched well."""
    raw = bm25(query, texts)
    terms = set(tokens(query))
    if not terms or not len(raw):
        return raw
    n = len(texts)
    bound = sum(math.log(1 + (n - 0.5) / 1.5) * (K1 + 1) / (1 + K1) for _ in terms)
    return np.clip(raw / max(bound, 1e-9), 0.0, 1.0)


@dataclass(frozen=True)
class Hit:
    index: int
    score: float
    rank: int
    method: str
    bm25: float
    dense: float | None


def _ranks(scores: np.ndarray) -> np.ndarray:
    order = np.argsort(-scores, kind="stable")
    ranks = np.empty(len(scores), dtype=int)
    ranks[order] = np.arange(1, len(scores) + 1)
    return ranks


def dense_scores(query: str, texts: Sequence[str]) -> np.ndarray | None:
    from career_lab.recognition.embedder import Embedder

    embedder = Embedder.get()
    if embedder is None or not texts:
        return None
    q = embedder.encode([query], "query")[0]
    return embedder.encode(list(texts), "passage") @ q


def search(
    query: str, texts: Sequence[str], *, k: int = 5, method: Method = "rrf"
) -> tuple[list[Hit], str, bool]:
    """Top-k hits, the method actually used, and whether it fell back to BM25."""
    if not texts:
        return [], method, False
    lexical = bm25_normalized(query, texts)
    dense = dense_scores(query, texts) if method in {"dense", "rrf"} else None
    fallback = method != "bm25" and dense is None
    used = "bm25" if dense is None else method
    if used == "bm25":
        fused = lexical
    elif used == "dense":
        fused = dense
    else:
        fused = 1.0 / (RRF_K + _ranks(lexical)) + 1.0 / (RRF_K + _ranks(dense))
        # Units with neither lexical nor meaningful dense evidence stay last.
        fused = np.where((lexical > 0) | (dense > 0), fused, 0.0)
    order = np.argsort(-fused, kind="stable")[:k]
    hits = [
        Hit(
            index=int(i),
            score=float(fused[i]),
            rank=r + 1,
            method=used,
            bm25=float(lexical[i]),
            dense=None if dense is None else float(dense[i]),
        )
        for r, i in enumerate(order)
    ]
    return hits, used, fallback


def rank_texts(query: str, texts: Sequence[str], *, method: Method = "rrf") -> list[int]:
    hits, _, _ = search(query, texts, k=len(texts), method=method)
    return [h.index for h in hits]
