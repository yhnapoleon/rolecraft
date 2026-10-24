"""Server-side engineer directory: one folder per session, readable after a restart.

Layout under the root (``CAREER_LAB_ENGINEER_ROOT``, default ``runs/local/engineer``):

- ``sessions/<session>/tickets/<ticket>/``: ``ticket.json``, ``seed-test.json`` (seeded
  tickets only), ``pack/`` (immutable task package), ``trials/``, ``reproductions/``,
  ``drafts/``, ``signoffs/``, ``submission-inputs/``;
- ``sessions/<session>/submissions/``: the immutable submission repository;
- ``public-reviews/<session>/<review>/report.json``: public reports;
- ``private-reviews/<session>/``: the private review store (owner-only, never served).

The directory itself is the index: records are JSON files listed by name. No response
contains a path; identifiers are checked against fixed patterns before any path is built.
"""

import fcntl
import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from career_lab.contracts import v2 as C

SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
RECORD_ID = re.compile(r"^(ticket|trial|draft|signoff|review)-[0-9a-f]{64}$")


def record_id(kind: str, value: Any) -> str:
    return kind + "-" + C.digest(value)


def checked(identifier: Any, kind: str, missing: str) -> str:
    if not isinstance(identifier, str) or not RECORD_ID.match(identifier):
        raise C.ProtocolError(missing, status=404)
    if not identifier.startswith(kind + "-"):
        raise C.ProtocolError(missing, status=404)
    return identifier


class EngineerStore:
    def __init__(self, root: Path):
        self.root = Path(root).absolute()

    def session(self, session_id: str) -> Path:
        if not SESSION_ID.match(session_id):
            raise C.ProtocolError("engineer_session_invalid", status=404)
        return self.root / "sessions" / session_id

    def tickets(self, session_id: str) -> Path:
        return self.session(session_id) / "tickets"

    def ticket(self, session_id: str, ticket_id: str) -> Path:
        return self.tickets(session_id) / checked(ticket_id, "ticket", "engineer_ticket_not_found")

    def submissions(self, session_id: str) -> Path:
        return self.session(session_id) / "submissions"

    def public_reviews(self, session_id: str) -> Path:
        self.session(session_id)
        return self.root / "public-reviews" / session_id

    def private_reviews(self, session_id: str) -> Path:
        self.session(session_id)
        path = self.root / "private-reviews" / session_id
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        for folder in (path.parent, path):
            folder.chmod(0o700)
        return path

    @contextmanager
    def lock(self, session_id: str, name: str) -> Iterator[None]:
        """Serialize writers of one session record family, across threads and processes."""
        locks = self.session(session_id) / ".locks"
        locks.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(locks / (name + ".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


def write_json(path: Path, value: Any) -> None:
    """Atomic replace; a reader sees the old record or the new one, never a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + ".tmp")
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_bytes())


def records(folder: Path) -> list[dict[str, Any]]:
    if not folder.is_dir():
        return []
    return [read_json(path) for path in sorted(folder.glob("*.json"))]
