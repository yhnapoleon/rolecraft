"""Materialize fixed historical inputs for the regression gate."""

import gzip
import hashlib
from pathlib import Path

HISTORICAL_RULES_ARCHIVE = (
    Path(__file__).resolve().parents[2] / "tests/regression/fixtures/w05-r10-owned-source.tar.gz"
)

HISTORICAL_RULES_BYTES = 542720
HISTORICAL_RULES_SHA256 = "99297d18c80e69248624b7ad2177729c5ac2f3ccb19afeedb138f3d799030bf3"


def materialize_historical_rules(target: Path, *, source: Path = HISTORICAL_RULES_ARCHIVE) -> Path:
    with gzip.open(source, "rb") as stream:
        raw = stream.read(HISTORICAL_RULES_BYTES + 1)
    if (
        len(raw) != HISTORICAL_RULES_BYTES
        or hashlib.sha256(raw).hexdigest() != HISTORICAL_RULES_SHA256
    ):
        raise ValueError("historical rules archive identity mismatch")
    with target.open("xb") as stream:
        stream.write(raw)
    return target
