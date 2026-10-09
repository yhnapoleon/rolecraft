"""Registered evaluation semantics, independent of implementation file layout."""

import hashlib
import json
from pathlib import Path

from career_lab.contracts.v2 import ProtocolError

EVALUATION_VERSION = "feedback-rubric-v2-c2.1"
REGISTRY = Path(__file__).resolve().parents[3] / "configs/evaluation/versions.json"


def rules_identity(rules_revision: str, rubric_revision: str) -> dict[str, object]:
    entry = json.loads(REGISTRY.read_text())["versions"][EVALUATION_VERSION]
    return {
        "evaluation_version": EVALUATION_VERSION,
        "revision": rules_revision,
        "rubric_revision": rubric_revision,
        "model_retries": 0,
        "comparison_baseline_sha256": entry["comparison_baseline_sha256"],
        "engine_baseline_sha256": entry["engine_baseline_sha256"],
    }


def validate_rules(raw: bytes, expected: dict[str, object]) -> None:
    """Accept the exact registered legacy artifact or the current semantic description."""
    document = json.loads(raw)
    if document == expected:
        return
    entry = json.loads(REGISTRY.read_text())["versions"][EVALUATION_VERSION]
    if hashlib.sha256(raw).hexdigest() in entry.get("legacy_rules_sha256", []):
        return
    raise ProtocolError("rubric_candidate_version_mismatch")
