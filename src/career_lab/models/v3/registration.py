"""Registration primitives shared by every registration protocol.

A protocol owns its on-disk format; this module owns the immutable publish lifecycle,
the generic public summary and the small handler interface registries dispatch on.
"""

import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from career_lab.contracts.v2.core import FileRef, ProtocolError

from .bundle import json_bytes, sha, write_json


@dataclass(frozen=True)
class RegistrationSummary:
    """What a registration says about itself, after the protocol has verified it.

    ``task_type`` and ``labels`` are always known. The optional fields are published
    in the public identity only when a protocol records them, so registrations made
    before these fields existed keep their historical identity bytes.
    """

    id: str
    scope: str
    model_revision: str
    task_type: str
    labels: tuple[str, ...]
    kind: str | None = None
    criteria: tuple[str, ...] | None = None
    dataset: dict[str, Any] | None = None
    components: tuple[dict[str, Any], ...] | None = None
    fusion: dict[str, Any] | None = None
    weights_stage: str | None = None
    rubric_version: dict[str, Any] | None = None

    def identity(self) -> dict[str, Any]:
        """Fields for ``RegisteredModelIdentity``; relation and unset fields are omitted."""
        public: dict[str, Any] = {
            "id": self.id,
            "model_revision": self.model_revision,
            "scope": self.scope,
            "quality_validated": False,
        }
        if self.task_type != "relation":
            public["task_type"] = self.task_type
        optional = {
            "kind": self.kind,
            "criteria": self.criteria,
            "dataset": self.dataset,
            "components": self.components,
            "fusion": self.fusion,
            "weights_stage": self.weights_stage,
            "rubric_version": self.rubric_version,
        }
        return public | {name: value for name, value in optional.items() if value is not None}


@dataclass(frozen=True)
class RegistrationProtocol:
    """One registration format: recognise its entry, describe it, load its model.

    ``describe`` verifies identity and files without needing optional inference
    dependencies; ``load`` returns ``(model, entry)`` for prediction.
    """

    handles: Callable[[dict[str, Any]], bool]
    describe: Callable[[Path, FileRef, dict[str, Any]], RegistrationSummary]
    load: Callable[[Path, FileRef, dict[str, Any]], tuple[Any, dict[str, Any]]]


def publish_registration(
    registry_root: Path,
    entry: dict[str, Any],
    write_artifact: Callable[[Path], None],
    verify_existing: Callable[[FileRef], dict[str, Any]],
) -> FileRef:
    """One lock/stage/publish lifecycle for each supported artifact format."""
    registry_root = registry_root.resolve()
    registry_root.mkdir(parents=True, exist_ok=True)
    identifier = entry["id"]
    destination = registry_root / identifier
    lock = registry_root / (identifier + ".lock")
    try:
        lock.mkdir()
    except FileExistsError:
        raise ProtocolError("model_registration_busy", status=409) from None
    stage = None
    try:
        ref = FileRef(path=identifier + "/registration.json", sha256=sha(json_bytes(entry)))
        if destination.exists():
            if verify_existing(ref) != entry:
                raise ProtocolError("model_registration_drift")
            return ref
        stage = Path(tempfile.mkdtemp(prefix=".registration-", dir=registry_root))
        write_artifact(stage / "artifact")
        write_json(stage / "registration.json", entry)
        os.rename(stage, destination)
        stage = None
        return ref
    finally:
        if stage is not None:
            shutil.rmtree(stage)
        lock.rmdir()
