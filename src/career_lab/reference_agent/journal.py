"""Atomic run checkpoint and per-run lock. No credentials are serialized."""
import fcntl
import json
import os
from pathlib import Path
from contextlib import contextmanager
from career_lab.contracts.v2 import canonical, digest
from .ports import PortError


class RunJournal:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "checkpoint.json"

    @contextmanager
    def locked(self):
        with (self.root / "run.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise PortError("run_already_active") from None
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def load(self):
        if not self.path.exists():
            return None
        raw = json.loads(self.path.read_text())
        if raw.get("checkpoint_hash") != digest(raw.get("state")):
            raise PortError("checkpoint_hash_mismatch")
        return raw["state"]

    def save(self, state):
        record = {"state": state, "checkpoint_hash": digest(state)}
        tmp = self.root / "checkpoint.tmp"
        with tmp.open("w") as f:
            f.write(canonical(record) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        fd = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def export(self, state):
        """Derived views can be rebuilt after a crash; checkpoint is authoritative."""
        for name, value in {
            "manifest.json": state["manifest"], "steps.json": state["steps"],
            "observations.json": state["observations"], "belief.json": state["belief"],
            "decision-points.json": state["decisions"], "errors.json": state["errors"],
            "result.json": {k: state.get(k) for k in (
                "run_id", "status", "reason_code", "started_at", "finished_at",
                "model_calls", "charged_tokens", "action_attempts", "polls", "evaluation",
                "reconcile_attempts", "pending",
            )},
        }.items():
            (self.root / name).write_text(canonical(value) + "\n")
