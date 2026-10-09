"""The gate restores the exact historical rule input, independent of live rules."""

import gzip
import hashlib
from pathlib import Path

import pytest

from scripts.regression.fixtures import materialize_historical_rules


def test_restore_keeps_the_original_historical_tar(tmp_path: Path) -> None:
    target = tmp_path / "historical-rules.tar"
    assert materialize_historical_rules(target) == target
    assert hashlib.sha256(target.read_bytes()).hexdigest() == (
        "99297d18c80e69248624b7ad2177729c5ac2f3ccb19afeedb138f3d799030bf3"
    )


def test_changed_contents_are_rejected_before_writing(tmp_path: Path) -> None:
    changed = tmp_path / "changed.tar.gz"
    changed.write_bytes(gzip.compress(b"substituted current implementation", mtime=0))
    target = tmp_path / "historical-rules.tar"
    with pytest.raises(ValueError, match="historical rules archive identity mismatch"):
        materialize_historical_rules(target, source=changed)
    assert not target.exists()
