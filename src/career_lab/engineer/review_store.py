"""Private immutable review artifacts with exact byte validation."""

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from career_lab.contracts import v2 as C
from career_lab.contracts.v2.engineer import EngineerRegressionReport, EngineerReviewInput
from career_lab.runtime.file_lock import flock, funlock

from .files import check_directory, encode, file_ref, publish

REPORT_MEMBERS = {
    "report.json",
    "baseline-results.json",
    "candidate-results.json",
    "config-diff.json",
}


def save_report(root: Path, files: dict[str, bytes]) -> None:
    indexed = dict(files)
    indexed["index.json"] = encode({name: file_ref(name, raw) for name, raw in files.items()})
    publish(root, indexed)


def load_report(root: Path, inputs: EngineerReviewInput) -> EngineerRegressionReport:
    try:
        raw = (root / "index.json").read_bytes()
        index = json.loads(raw)
        if not isinstance(index, dict) or set(index) != REPORT_MEMBERS:
            raise ValueError("unexpected review member")
        refs = {name: C.FileRef.model_validate(ref) for name, ref in index.items()}
        if any(name != ref.path for name, ref in refs.items()):
            raise ValueError("review member name mismatch")
        files = {name: C.read_file(root, ref) for name, ref in refs.items()}
        check_directory(root, {**files, "index.json": raw})
        report = EngineerRegressionReport.model_validate_json(files["report.json"])
        if report.input != inputs or report.id != "review-" + C.digest(inputs):
            raise ValueError("review identity mismatch")
        return report
    except (OSError, ValueError):
        raise C.ProtocolError("engineer_review_changed", status=409) from None


@contextmanager
def review_lock(root: Path, identity: str) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Windows has no POSIX mode bits (directories always read 0o777), so only the link check
    # applies there.
    if root.is_symlink() or (os.name != "nt" and root.stat().st_mode & 0o077):
        raise C.ProtocolError("engineer_private_store_permissions", status=403)
    locks = root / ".locks"
    locks.mkdir(exist_ok=True, mode=0o700)
    if locks.is_symlink():
        raise C.ProtocolError("engineer_private_store_permissions", status=403)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(locks / (identity + ".lock"), flags, 0o600)
    with os.fdopen(fd, "w") as stream:
        try:
            flock(stream, blocking=False)
        except BlockingIOError:
            raise C.ProtocolError("engineer_review_busy", status=409) from None
        try:
            yield
        finally:
            funlock(stream)
