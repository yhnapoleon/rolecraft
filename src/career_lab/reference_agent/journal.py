"""Migrate the reference runner's locked, atomic intent checkpoint to current types."""

import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import JsonValue

from career_lab.contracts.v2.core import ProtocolError, canonical, digest


class RunJournal:
    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = root
        self.path = root / "checkpoint.json"

    @contextmanager
    def locked(self) -> Iterator[None]:
        descriptor = os.open(self.root / "run.lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(descriptor, "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ProtocolError("run_already_active", status=409) from None
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def load(self) -> dict[str, JsonValue] | None:
        if not self.path.exists():
            return None
        record = json.loads(self.path.read_bytes())
        if not isinstance(record, dict) or record.get("checkpoint_hash") != digest(
            record.get("state")
        ):
            raise ProtocolError("checkpoint_hash_mismatch", status=409)
        if not isinstance(record.get("state"), dict):
            raise ProtocolError("checkpoint_invalid")
        return record["state"]

    def save(self, state: dict[str, JsonValue]) -> None:
        temporary = self.root / "checkpoint.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(canonical({"state": state, "checkpoint_hash": digest(state)}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)
        descriptor = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
