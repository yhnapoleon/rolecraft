"""C4 out-of-scope detection (Mahalanobis distance on e5 vectors) and answer drift.

Weights: ``$CAREER_LAB_RECOGNIZERS/scope-mahalanobis-v1/`` holds one fit per
``<scenario>/<language>/<scope_on|scope_off>`` key::

    fits.json        {"<key>": {"threshold": 2.8, "dims": 384, "n": 160,
                                "drift_mean": 0.05, "drift_std": 0.03}}
    <key>.npz        mean (d,), precision (d, d)   (key with "/" replaced by "__")

Fit: in-domain unit vectors plus in-domain paraphrased questions, Ledoit-Wolf shrinkage,
threshold at 95 % TPR on dev (``experiments/recognition/scope``). The score is the
Mahalanobis distance divided by sqrt(d), so thresholds read near 1-3. Without weights the
label follows the rule outcome (``no_retrieval_hit`` means out of scope), ``fallback``.
"""

from __future__ import annotations

import json
from functools import lru_cache

import numpy as np

from career_lab.recognition import registry
from career_lab.recognition.base import FALLBACK_REVISION, record, stopwatch

ID = "scope-mahalanobis-v1"
DRIFT_ID = "drift-cosine-v1"


def fit_key(scenario: str, language: str, scope_filter: bool) -> str:
    return f"{scenario}/{language}/{'scope_on' if scope_filter else 'scope_off'}"


@lru_cache(maxsize=1)
def _fits() -> tuple[dict, str] | None:
    entry = registry.get(ID)
    if entry is None:
        return None
    path = entry.path / "fits.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8")), entry.revision


@lru_cache(maxsize=32)
def _arrays(key: str):
    entry = registry.get(ID)
    data = np.load(entry.path / (key.replace("/", "__") + ".npz"))
    return data["mean"], data["precision"]


def distance(vector: np.ndarray, mean: np.ndarray, precision: np.ndarray) -> float:
    delta = vector - mean
    return float(np.sqrt(max(delta @ precision @ delta, 0.0)) / np.sqrt(len(mean)))


def detect(
    query: str,
    *,
    scenario: str,
    language: str,
    scope_filter: bool,
    rule_hit: bool,
    as_of=None,
):
    """Return (label, record). ``rule_hit`` is the product's own retrieval outcome."""
    key = fit_key(scenario, language, scope_filter)
    with stopwatch() as clock:
        fits = _fits()
        found = None
        if fits is not None and key in fits[0]:
            from career_lab.recognition.embedder import Embedder

            embedder = Embedder.get()
            if embedder is not None:
                mean, precision = _arrays(key)
                vector = embedder.encode([query], "query")[0]
                found = (distance(vector, mean, precision), fits[0][key], fits[1])
    if found is None:
        label = "in" if rule_hit else "out"
        return label, record(
            ID,
            FALLBACK_REVISION,
            "scope",
            {"query": query, "fit_key": key},
            label=label,
            outputs={"fit_key": key, "rule": "no_retrieval_hit"},
            as_of=as_of,
            duration_ms=clock.ms,
        )
    score, fit, revision = found
    threshold = float(fit["threshold"])
    label = "out" if score > threshold else "in"
    return label, record(
        ID,
        revision,
        "scope",
        {"query": query, "fit_key": key},
        label=label,
        score=score,
        threshold=threshold,
        outputs={"fit_key": key, "rule_hit": rule_hit},
        as_of=as_of,
        duration_ms=clock.ms,
    )


def drift(
    query: str,
    before: str,
    after: str,
    *,
    scenario: str,
    language: str,
    scope_filter: bool,
    as_of=None,
):
    """Cosine distance between two answers to the same question across an index refresh."""
    from career_lab.recognition.embedder import Embedder

    key = fit_key(scenario, language, scope_filter)
    with stopwatch() as clock:
        embedder = Embedder.get()
        fits = _fits()
        if embedder is None:
            changed = before.strip() != after.strip()
            return record(
                DRIFT_ID,
                FALLBACK_REVISION,
                "drift",
                {"query": query, "before": before, "after": after},
                label="changed" if changed else "same",
                outputs={"drift_anomaly": changed, "rule": "text_changed"},
                as_of=as_of,
                duration_ms=clock.ms,
            )
        a, b = embedder.encode([before or " ", after or " "], "passage")
        value = float(1.0 - a @ b)
        fit = (fits[0].get(key) if fits else None) or {}
        mean, std = float(fit.get("drift_mean", 0.05)), float(fit.get("drift_std", 0.03))
        threshold = mean + 2 * std
    anomaly = value > threshold
    return record(
        DRIFT_ID,
        embedder.revision,
        "drift",
        {"query": query, "before": before, "after": after},
        label="anomaly" if anomaly else "normal",
        score=value,
        threshold=threshold,
        outputs={"drift_anomaly": anomaly, "fit_key": key},
        as_of=as_of,
        duration_ms=clock.ms,
        fallback=not fit,
    )
