"""Shared helpers for the recognition experiments (E1-E10)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "releases"
RESULTS = Path(__file__).resolve().parent / "results"
RECOGNIZERS = Path(os.environ.get("CAREER_LAB_RECOGNIZERS", ROOT / "runs/local/recognizers"))


def jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def save(name: str, payload: dict[str, Any]) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{name}.json"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


def confusion(gold: list[str], pred: list[str], labels: list[str]) -> list[list[int]]:
    index = {label: i for i, label in enumerate(labels)}
    table = [[0] * len(labels) for _ in labels]
    for g, p in zip(gold, pred):
        if g in index and p in index:
            table[index[g]][index[p]] += 1
    return table


def per_class(gold: list[str], pred: list[str], labels: list[str]) -> dict[str, dict[str, float]]:
    out = {}
    for label in labels:
        tp = sum(g == label and p == label for g, p in zip(gold, pred))
        fp = sum(g != label and p == label for g, p in zip(gold, pred))
        fn = sum(g == label and p != label for g, p in zip(gold, pred))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        out[label] = {"precision": precision, "recall": recall, "f1": f1, "support": tp + fn}
    return out


def macro_f1(gold: list[str], pred: list[str], labels: list[str]) -> float:
    rows = per_class(gold, pred, labels)
    return sum(r["f1"] for r in rows.values()) / len(labels)


def register(recognizer_id: str, task: str) -> dict:
    os.environ.setdefault("CAREER_LAB_RECOGNIZERS", str(RECOGNIZERS))
    from career_lab.recognition.registry import add

    return add(recognizer_id, task, recognizer_id, ["zh", "en"])
