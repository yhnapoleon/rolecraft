"""Identify the actual engineering source, including uncommitted source changes."""

import hashlib
from pathlib import Path

from career_lab.contracts import v2 as C


def source_version() -> str:
    """A content snapshot works without Git history or installed distribution metadata."""
    try:
        paths = sorted(Path(__file__).parent.glob("*.py"))
        if not paths:
            raise OSError("engineering source unavailable")
        members = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    except OSError:
        raise C.ProtocolError("engineer_tool_source_unavailable", status=503) from None
    return "source-sha256:" + C.digest(members)
