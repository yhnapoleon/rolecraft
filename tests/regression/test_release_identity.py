"""The release identity entry point refreshes only protected hashes and checks like the gate."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts.regression.release_identity import check, refresh


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def write_identity(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/a.json").write_text("a")
    (tmp_path / "docs/b.json").write_text("b")
    identity = tmp_path / "release-identity.json"
    data = {
        "commit": "73e14e9",
        "protected": {"docs/a.json": sha("a"), "docs/b.json": sha("b")},
        "scenarios": [{"root": "scenarios/x", "scenario_hash": "h"}],
        "scope": "Business content.",
    }
    identity.write_text(json.dumps(data, indent=2) + "\n")
    return identity


def test_refresh_updates_changed_hashes_adds_paths_and_then_checks_clean(tmp_path: Path) -> None:
    identity = write_identity(tmp_path)
    before = json.loads(identity.read_text())
    (tmp_path / "docs/b.json").write_text("b2")
    (tmp_path / "docs/new.json").write_text("new")
    assert check(identity, tmp_path) == ["protected release file changed: docs/b.json"]

    result = refresh(identity, tmp_path, ["docs/new.json"])

    assert result == {"changed": ["docs/b.json"], "added": ["docs/new.json"]}
    after = json.loads(identity.read_text())
    assert list(after) == list(before)
    assert {k: after[k] for k in ("commit", "scenarios", "scope")} == {
        k: before[k] for k in ("commit", "scenarios", "scope")
    }
    assert after["protected"] == {
        "docs/a.json": sha("a"),
        "docs/b.json": sha("b2"),
        "docs/new.json": sha("new"),
    }
    assert identity.read_text() == json.dumps(after, indent=2) + "\n"
    assert check(identity, tmp_path) == []


def test_refresh_fails_without_writing_when_a_listed_or_protected_file_is_missing(
    tmp_path: Path,
) -> None:
    identity = write_identity(tmp_path)
    original = identity.read_bytes()
    with pytest.raises(SystemExit, match="docs/absent.json"):
        refresh(identity, tmp_path, ["docs/absent.json"])
    (tmp_path / "docs/a.json").unlink()
    with pytest.raises(SystemExit, match="docs/a.json"):
        refresh(identity, tmp_path, [])
    assert identity.read_bytes() == original
    assert check(identity, tmp_path) == ["protected release file changed: docs/a.json"]
