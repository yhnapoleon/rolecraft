"""Explicit current protocol inputs, separate from historical draft manifests."""

import json
from pathlib import Path

from career_lab.contracts.v2.core import ProtocolError
from career_lab.contracts.v2.research import RunManifest


def load_manifest(path: Path) -> RunManifest:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or value.get("schema_version") != 2:
        raise ProtocolError("run_protocol_unsupported")
    return RunManifest.model_validate(value)
