"""Private on-disk indexes and atomic file publication; no public wire schema."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import to_jsonable_python

from career_lab.contracts import v2 as C
from career_lab.datasets.v3.common import immutable_directory


class PackSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bindings: C.SessionBindings
    as_of: C.VersionPoint


class PackIndex(BaseModel):
    """On-disk member index, not a new public business contract."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1, 2]
    kind: Literal["engineer_baseline_pack"]
    source: PackSource
    work_language: Literal["zh", "en"]
    pack: C.FileRef
    config: C.FileRef
    tests: tuple[C.FileRef, ...] = Field(min_length=1, max_length=100)
    materials: C.FileRef
    public_probes: C.FileRef
    guide: C.FileRef
    tool_versions: dict[str, str] | None = None
    template_version: str | None = None

    @model_validator(mode="after")
    def require_versions(self) -> Self:
        if self.schema_version == 2 and (
            not self.tool_versions
            or not self.tool_versions.get("career-lab-engineer")
            or not self.template_version
        ):
            raise ValueError("package tool and template versions are required")
        return self


def encode(value: Any) -> bytes:
    return (C.canonical(to_jsonable_python(value)) + "\n").encode("utf-8")


def file_ref(name: str, raw: bytes) -> C.FileRef:
    return C.FileRef(path=name, sha256=hashlib.sha256(raw).hexdigest())


def check_directory(root: Path, files: dict[str, bytes]) -> None:
    root = Path(root)
    if root.is_symlink() or not root.is_dir() or {p.name for p in root.iterdir()} != set(files):
        raise C.ProtocolError("engineer_pack_changed", status=409)
    if any(
        (root / name).is_symlink()
        or not (root / name).is_file()
        or (root / name).read_bytes() != raw
        for name, raw in files.items()
    ):
        raise C.ProtocolError("engineer_pack_changed", status=409)


def publish(root: Path, files: dict[str, bytes]) -> None:
    """Build off to the side and rename once; an existing package is never overwritten."""
    root = Path(root).absolute()
    if root.exists() or root.is_symlink():
        check_directory(root, files)
        return
    try:
        with immutable_directory(root) as stage:
            stage.chmod(0o700)
            for name, raw in files.items():
                with (stage / name).open("xb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
    except C.ProtocolError as error:
        if error.code != "immutable_output_exists":
            raise
        check_directory(root, files)


def retained_documentation(root: Path) -> tuple[PackIndex, C.EngineerPack, bytes]:
    index = PackIndex.model_validate_json((root / "index.json").read_bytes())
    pack = C.EngineerPack.model_validate_json(C.read_file(root, index.pack))
    return index, pack, C.read_file(root, index.guide)


RetainedDocumentation = tuple[PackIndex, C.EngineerPack, bytes]
