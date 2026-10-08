"""Execution provenance is evidence, never an admission allowlist for content."""

import hashlib
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


class CodeIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["clean", "modified", "not_recorded"] = "not_recorded"
    commit: str | None = None
    snapshot: str | None = None


class FeedbackProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: CodeIdentity
    evaluation_version: str
    rules_version: str
    prompt_version: str
    provider: str
    model: str
    retries: Literal[0] = 0


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)


def source_snapshot(root: Path) -> str:
    """Hash executable inputs without storing paths, content, or credentials in feedback."""
    paths = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    snapshot = hashlib.sha256()
    for name in sorted(set(paths.split(b"\0")) - {b""}):
        relative = name.decode()
        if not (relative.startswith("src/") and relative.endswith(".py")):
            if relative not in {"pyproject.toml", "uv.lock"}:
                continue
        path = root / relative
        snapshot.update(name + b"\0")
        snapshot.update(
            hashlib.sha256(path.read_bytes()).digest() if path.is_file() else b"missing"
        )
    return snapshot.hexdigest()


@lru_cache(maxsize=1)
def execution_identity() -> CodeIdentity:
    root = Path(__file__).resolve().parents[4]
    try:
        commit = _git(root, "rev-parse", "HEAD").decode().strip()
        modified = bool(_git(root, "status", "--porcelain", "--untracked-files=normal").strip())
        return CodeIdentity(
            status="modified" if modified else "clean",
            commit=commit,
            snapshot=source_snapshot(root),
        )
    except (OSError, subprocess.CalledProcessError):
        return CodeIdentity()


def require_execution_snapshot(identity: CodeIdentity) -> None:
    """A running producer must restart after executable inputs change on disk."""
    from career_lab.contracts.v2.core import ProtocolError

    if identity.snapshot is None:
        return
    root = Path(__file__).resolve().parents[4]
    if source_snapshot(root) != identity.snapshot:
        raise ProtocolError("execution_restart_required", status=503)
