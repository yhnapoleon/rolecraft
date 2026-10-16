"""C6 cost-sensitive decision with a reject option, and the lift-ordered review queue.

``decide`` minimises expected cost over the three relation labels plus "defer" (send to a
person, fixed cost). Ties go to defer. Costs live in ``costs.json`` beside this file.
Temperature scaling and the lift curve come with the C1 registration (S6):
``temperature.json`` and ``lift.json`` in ``$CAREER_LAB_RELATION_ENCODER``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

LABELS = ("supported", "contradicted", "insufficient")


@lru_cache(maxsize=1)
def costs() -> dict:
    return json.loads((Path(__file__).with_name("costs.json")).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Decision:
    action: str  # "decide" | "defer"
    label: str | None
    expected_cost: float
    defer_cost: float
    costs: dict[str, float]


def decide(probabilities: dict[str, float]) -> Decision:
    table = costs()
    expected = {
        d: sum(probabilities.get(y, 0.0) * table["decide"][d][y] for y in LABELS) for d in LABELS
    }
    best = min(LABELS, key=lambda d: (expected[d], LABELS.index(d)))
    defer = float(table["defer"])
    if expected[best] >= defer:
        return Decision("defer", None, expected[best], defer, expected)
    return Decision("decide", best, expected[best], defer, expected)


@lru_cache(maxsize=1)
def lift() -> dict | None:
    """``{"top_fraction": 0.2, "error_coverage": 0.61}`` from dev, when registered."""
    root = os.environ.get("CAREER_LAB_RELATION_ENCODER")
    if not root or not (Path(root) / "lift.json").is_file():
        return None
    return json.loads((Path(root) / "lift.json").read_text(encoding="utf-8"))
