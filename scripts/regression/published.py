"""Resolve the shipped scenario catalog without generating or rebinding packages."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "tests/regression/published-catalog.json"


def reviewed_identity(root: Path, language: str, installed_hash: str) -> str | None:
    """Follow the existing release continuity proof; do not issue new content approval.

    Historical installation changed revision/evaluation metadata. Its full bytes
    are protected separately; the original review is never relabeled as a code review.
    """
    reviews = ROOT / "scenarios/pm_pilot/v2/variants/reviews"
    continuity = json.loads((reviews / "content-continuity-2.9.6.json").read_text())
    approval_bytes = (reviews / "content-approval-2.9.0.json").read_bytes()
    if hashlib.sha256(approval_bytes).hexdigest() != continuity["independent_review"]["sha256"]:
        raise ValueError("Original content approval identity changed")
    approval = json.loads(approval_bytes)
    if approval["scope"] != "authored_content_only" or approval["verdict"] != "accepted":
        raise ValueError("Original content approval unavailable")
    scenario_id = json.loads((root / "manifest.json").read_text())["id"]
    matching = [
        row
        for row in continuity["bindings"]
        if row["scenario_id"] == scenario_id and row["work_language"] == language
    ]
    if not matching:
        if scenario_id != "pm_pilot":
            raise ValueError("Missing published content lineage")
        return None
    binding = matching[0]
    if binding["installed_scenario_hash"] != installed_hash:
        raise ValueError("Installed package does not match the published lineage")
    identity = binding["reviewed_source_hash"]
    approved = {
        (row["scenario_id"], row["work_language"], row["scenario_hash"])
        for row in approval["bundles"]
    }
    if (scenario_id, language, identity) not in approved:
        raise ValueError("Original content identity is not independently approved")
    return identity


def write_catalog(target: Path) -> Path:
    """Check release identity, then make only catalog paths absolute."""
    catalog = json.loads(CATALOG.read_text())
    for entry in catalog["scenarios"]:
        root = (ROOT / entry["root"]).resolve()
        if not root.is_relative_to(ROOT / "scenarios"):
            raise ValueError("Scenario root must belong to this checkout")
        actual = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
        if actual != entry["scenario_hash"]:
            raise ValueError("Published scenario identity changed: " + entry["root"])
        entry["authored_manifest"] = actual
        reviewed = reviewed_identity(root, entry["work_language"], actual)
        if reviewed is not None:
            entry["reviewed_authored_manifest"] = reviewed
        entry["root"] = str(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(catalog, indent=2) + "\n")
    return target
