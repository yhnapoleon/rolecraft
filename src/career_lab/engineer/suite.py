"""Engineer regression suites: one candidate configuration, consistent across probes.

Authored scenario probes carry per-probe preconditions (config, tuning, grant,
refresh, apply). Engineer review runs every probe under one candidate
configuration, so it uses these suites instead. Each file is indexed by scenario
ID and work language; published scenario bytes stay untouched.
"""

import json
import re
from pathlib import Path

from career_lab.contracts import v2 as C
from career_lab.scenarios.v2.probes import export_public_probes

from .execution import Probe, suite_probes

SUITES = Path(__file__).resolve().parent / "suites"
FIELDS = frozenset({"id", "query", "public", "expected", "canonical_probe_id", "locale"})


def validate_suite(raw: bytes, package) -> tuple[Probe, ...]:
    """Parse a suite the reviewer can run under one configuration, or reject it.

    Rows carry no preconditions, IDs are unique, every row matches the package
    language, and the public rows keep the scenario's public IDs and questions.
    """
    try:
        rows = json.loads(raw)
        if not isinstance(rows, list) or not all(
            isinstance(row, dict)
            and row.keys() == FIELDS
            and isinstance(row["public"], bool)
            and row["locale"] == package.locale
            and isinstance(row["canonical_probe_id"], str)
            and row["canonical_probe_id"].strip()
            for row in rows
        ):
            raise ValueError("engineer suite row")
        probes = suite_probes(raw)
    except (ValueError, KeyError, TypeError):
        raise C.ProtocolError("engineer_suite_invalid") from None
    canonical = [row["canonical_probe_id"] for row in rows]
    public = {p.id: p.query for p in probes if p.public}
    authored = {row["id"]: row["query"] for row in export_public_probes(package)}
    if len(set(canonical)) != len(canonical) or public != authored:
        raise C.ProtocolError("engineer_suite_invalid")
    return probes


def engineer_suite(package) -> bytes | None:
    """Validated suite bytes for this scenario and work language; None when none exists."""
    scenario, language = package.bundle.id, package.locale
    if not re.fullmatch(r"[a-z0-9_]+", scenario) or not re.fullmatch(r"[a-z]+", language):
        return None
    path = SUITES / scenario / (language + ".json")
    if not path.is_file():
        return None
    raw = path.read_bytes()
    validate_suite(raw, package)
    return raw
