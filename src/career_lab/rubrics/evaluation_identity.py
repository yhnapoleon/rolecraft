"""Registered evaluation semantics, independent of implementation file layout."""

import hashlib
import json
from pathlib import Path

from career_lab.contracts.v2 import ProtocolError

EVALUATION_VERSION = "feedback-rubric-v2-c2.1"
# The owner-approved final rubric; only an explicit rebind installs it for new sessions.
FINAL_EVALUATION_VERSION = "feedback-rubric-v2-final.1"
REGISTRY = Path(__file__).resolve().parents[3] / "configs/evaluation/versions.json"
# Registered definition artifacts resolve beside the registry entry point, never from a
# relocated copy of the implementation modules.
FINAL_DEFINITIONS = Path(__file__).resolve().parent / "v4/definitions"


def registered(version: str = EVALUATION_VERSION) -> dict[str, object]:
    entry = json.loads(REGISTRY.read_text())["versions"].get(version)
    if entry is None:
        raise ProtocolError("evaluation_version_unsupported", status=409)
    return entry


def rules_identity(
    rules_revision: str, rubric_revision: str, version: str = EVALUATION_VERSION
) -> dict[str, object]:
    entry = registered(version)
    return {
        "evaluation_version": version,
        "revision": rules_revision,
        "rubric_revision": rubric_revision,
        "model_retries": 0,
        "comparison_baseline_sha256": entry["comparison_baseline_sha256"],
        "engine_baseline_sha256": entry["engine_baseline_sha256"],
    }


def validate_rules(
    raw: bytes, expected: dict[str, object], version: str = EVALUATION_VERSION
) -> None:
    """Accept the exact registered legacy artifact or the current semantic description."""
    document = json.loads(raw)
    if document == expected:
        return
    if hashlib.sha256(raw).hexdigest() in registered(version).get("legacy_rules_sha256", []):
        return
    raise ProtocolError("rubric_candidate_version_mismatch")
