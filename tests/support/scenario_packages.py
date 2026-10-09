"""Scenario package roots for tests: the formally installed packages, not legacy sources.

Business tests exercise what ``installed/current.json`` and its published catalog
actually install: released packages that are validated by content identity,
review and evaluation signature. Legacy packages (the authoring root, its
``variants/`` and the historical ``installed/rubric-v2-a577-*`` directories)
pin one historical foundation-contract digest, so they can only be constructed
while that digest is still the current contract. They remain inputs for
migration, rejection and identity tests, never for business behaviour tests.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from career_lab.scenarios.v2.rebind import rebind
from career_lab.scenarios.v2.release import PROTOCOL, RELEASE_PATH

ROOT = Path(__file__).resolve().parents[2]
LEGACY_ROOT = ROOT / "scenarios/pm_pilot/v2"
CURRENT_POINTER = LEGACY_ROOT / "installed/current.json"
FOUNDATION = ROOT / "docs/contracts/expansion-v3/manifest.json"


def current_foundation_sha256() -> str:
    return hashlib.sha256(FOUNDATION.read_bytes()).hexdigest()


def current_contract_revision() -> str:
    return "expansion-v3-" + current_foundation_sha256()


def installed_catalog() -> dict[str, Path]:
    """Scenario id -> Chinese root of every package the current installation publishes."""
    pointer = json.loads(CURRENT_POINTER.read_bytes())
    rows = json.loads((ROOT / pointer["catalog"]).read_bytes())["scenarios"]
    roots: dict[str, Path] = {}
    for row in rows:
        if row["work_language"] == "zh":
            root = ROOT / row["root"]
            roots[root.name] = root
    main = ROOT / pointer["main"]["zh"]["root"]
    roots.setdefault(main.name, main)
    return roots


def is_released(root: Path) -> bool:
    return (Path(root) / RELEASE_PATH).is_file()


def installed_root(scenario_id: str = "pm_pilot") -> Path:
    """The installed, released package root for one scenario (Chinese root)."""
    root = installed_catalog()[scenario_id]
    if not is_released(root):
        raise FileNotFoundError(f"{root} is installed but carries no {RELEASE_PATH}")
    return root


def installed_locale_root(scenario_id: str, language: str) -> Path:
    root = installed_root(scenario_id)
    return root if language == "zh" else root / "locales/en"


def pinned_foundation_sha256(root: Path) -> str | None:
    source = json.loads((Path(root) / "runtime/source-files.json").read_bytes())
    value = source.get("foundation_contract_sha256")
    return value if isinstance(value, str) else None


def legacy_matches_current_contract(root: Path) -> bool:
    return pinned_foundation_sha256(root) == current_foundation_sha256()


def runtime_root(root: Path, scratch: Path, *, revision: str = "protocol-v1-test") -> Path:
    """Return a root that ``ScenarioModule`` can construct under the current contract.

    Released packages are returned unchanged, as is a legacy package whose pinned
    foundation digest still equals the current contract. Any other legacy package
    is migrated with the formal rebind tool into a fresh directory under
    ``scratch``: business content and review identity are preserved and the
    original directory is never written.
    """
    root = Path(root)
    if is_released(root) or legacy_matches_current_contract(root):
        return root
    parts = root.resolve().relative_to(LEGACY_ROOT.resolve()).parts
    destination = Path(scratch) / ("-".join(parts) or "root")
    rebind(
        root,
        destination,
        protocol=PROTOCOL,
        contract_revision=current_contract_revision(),
        scenario_revision=revision,
        runtime_revision=revision,
    )
    return destination
