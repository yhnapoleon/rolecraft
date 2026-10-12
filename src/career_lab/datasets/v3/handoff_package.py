"""Read hash-bound training handoffs without executing any supplied code."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, JsonValue

from career_lab.contracts.v2.core import FileRef, ProtocolError, digest, read_file

from .common import sha

# v3 split-sealed layout: every split owns its files under ``splits.<split>.files``.
SEALED_LAYOUT = "rolecraft-dataset-split-sealed-v1"
SPLITS = ("train", "dev", "test")


def split_file_names(split: str) -> dict[str, str]:
    """The four files every split of the sealed layout owns."""
    return {
        "inputs": f"data/{split}.inputs.jsonl",
        "labels": f"data/{split}.labels.jsonl",
        "annotations": f"audit/{split}/annotations.jsonl",
        "metadata": f"audit/{split}/metadata.jsonl",
    }


def split_owner(name: str) -> str | None:
    """The split whose prefix a package path is under; ``unknown`` for other data files."""
    for split in SPLITS:
        if name.startswith(f"data/{split}.") or name.startswith(f"audit/{split}/"):
            return split
    return "unknown" if name.startswith("data/") else None


def require_regular(root: Path, name: str) -> None:
    """Refuse a package path that passes through a symbolic link (``load_package`` refuses
    links anywhere; readers of one split check the files they open)."""
    current = Path(root)
    for part in Path(name).parts:
        current = current / part
        if current.is_symlink():
            raise ProtocolError("dataset_symlink_forbidden", status=403)


def check_sealed_structure(splits, shared, test_sealed: bool) -> None:
    """Structural isolation of the sealed layout; run before any split file is read.

    ``splits`` maps each split to its bound file names; ``shared`` lists top-level files.
    """
    if not splits or set(splits) - set(SPLITS):
        raise ProtocolError("dataset_split_unknown")
    if any(split_owner(name) is not None for name in shared):
        raise ProtocolError("dataset_split_file_not_isolated", status=403)
    for split, names in splits.items():
        if not set(split_file_names(split).values()) <= set(names):
            raise ProtocolError("dataset_split_files_incomplete")
        if any(split_owner(name) != split for name in names):
            raise ProtocolError("dataset_split_file_outside_partition", status=403)
    # Two splits whose own files carry the same bytes are one partition under two names.
    owned = [
        getattr(names[name], "sha256", None)
        for split, names in splits.items()
        for name in split_file_names(split).values()
        if isinstance(names, dict)
    ]
    if len(set(owned)) != len(owned):
        raise ProtocolError("dataset_split_file_not_isolated", status=403)
    if "test" in splits and not test_sealed:
        raise ProtocolError("dataset_test_split_must_be_sealed", status=403)
    if test_sealed and "test" not in splits:
        raise ProtocolError("dataset_test_sealed_without_test")


class FileIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sha256: str
    size: int


class SplitCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    records: int
    labels: dict[str, int]
    language: dict[str, int]
    evidence_evaluable: int
    label_only: int
    label_tiers: dict[str, int] | None = None
    # v3 split-sealed layout only: the files this split owns.
    files: dict[str, FileIdentity] | None = None


class HandoffManifest(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    schema_version: int
    dataset_id: str
    status: str
    splits: dict[str, SplitCounts]
    files: dict[str, FileIdentity]
    annotation_version: str | None = None
    label_orders: dict[str, list[str]] = {}
    task_type: str | None = None
    label_order: list[str] | None = None
    split_manifest: str = "audit/original-release/split-manifest.json"
    layout: str | None = None
    test_sealed: bool | None = None

    @property
    def sealed_layout(self) -> bool:
        return self.layout is not None


@dataclass(frozen=True)
class HandoffPackage:
    manifest: HandoffManifest
    manifest_hash: str
    package_hash: str
    files: dict[str, bytes]

    def read(self, name: str) -> bytes:
        if name not in self.files:
            raise ProtocolError("handoff_required_file_missing")
        return self.files[name]

    def json(self, name: str) -> JsonValue:
        return decode_json(self.read(name))

    def rows(self, name: str) -> list[dict[str, JsonValue]]:
        rows = [decode_json(line) for line in self.read(name).splitlines() if line.strip()]
        if any(not isinstance(row, dict) for row in rows):
            raise ProtocolError("handoff_object_row_required")
        return rows

    def line_count(self, name: str) -> int:
        """Non-empty lines, without parsing them (sealed files are never decoded)."""
        return sum(1 for line in self.read(name).splitlines() if line.strip())


def load_package(root: Path) -> HandoffPackage:
    if root.is_symlink() or any(path.is_symlink() for path in root.rglob("*")):
        raise ProtocolError("handoff_symlink_forbidden")
    raw = (root / "dataset-manifest.json").read_bytes()
    manifest = HandoffManifest.model_validate(decode_json(raw))
    if manifest.schema_version != 1 or not manifest.splits:
        raise ProtocolError("handoff_manifest_version_invalid")
    identities = dict(manifest.files)
    if manifest.sealed_layout:
        if manifest.layout != SEALED_LAYOUT or not isinstance(manifest.test_sealed, bool):
            raise ProtocolError("handoff_manifest_version_invalid")
        owned = {split: count.files or {} for split, count in manifest.splits.items()}
        check_sealed_structure(owned, manifest.files, manifest.test_sealed)
        for names in owned.values():
            identities.update(names)
    files = {"dataset-manifest.json": raw}
    # Sealed test files are read here only to check their bytes against the manifest.
    for name, identity in identities.items():
        data = read_file(root, FileRef(path=name, sha256=identity.sha256))
        if len(data) != identity.size:
            raise ProtocolError("handoff_file_size_mismatch")
        files[name] = data
    sums = root / "SHA256SUMS"
    if sums.exists():
        files["SHA256SUMS"] = sums.read_bytes()
        seen = set()
        for line in files["SHA256SUMS"].decode().splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            if match is None or match[2] in seen or match[2] == "SHA256SUMS":
                raise ProtocolError("handoff_checksum_list_invalid")
            seen.add(match[2])
            files[match[2]] = read_file(root, FileRef(path=match[2], sha256=match[1]))
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if actual != files.keys():
        raise ProtocolError("handoff_file_set_mismatch")
    package_hash = digest({name: sha(data) for name, data in sorted(files.items())})
    package = HandoffPackage(manifest, sha(raw), package_hash, files)
    required = (
        ("data_card.md",)
        if manifest.sealed_layout
        else ("audit/metadata.jsonl", "data_card.md", manifest.split_manifest)
    )
    for name in required:
        package.read(name)
    return package


def check_card(package: HandoffPackage) -> str:
    """Check structured summaries or the original fixture's numeric Markdown table.

    Free-form narrative and real-world authority always require independent review.
    """
    card = package.read("data_card.md").decode()
    blocks = re.findall(r"```json\s*\n(.*?)\n```", card, re.DOTALL)
    if blocks:
        if len(blocks) != 1:
            raise ProtocolError("handoff_data_card_ambiguous")
        summary = decode_json(blocks[0])
        if not isinstance(summary, dict) or not isinstance(summary.get("splits"), dict):
            raise ProtocolError("handoff_data_card_invalid")
        declared = {
            split: SplitCounts.model_validate(count) for split, count in summary["splits"].items()
        }
        counted = {
            split: count.model_copy(update={"files": None})
            for split, count in package.manifest.splits.items()
        }
        if declared != counted:
            raise ProtocolError("handoff_data_card_mismatch")
        return "structured_counts; narrative_requires_review"
    # Legacy v2 card: split, count, each frozen label count, evaluable, label-only.
    table = {}
    for line in card.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0] in package.manifest.splits:
            if cells[0] in table:
                raise ProtocolError("handoff_data_card_ambiguous")
            table[cells[0]] = [int(cell) for cell in cells[1:]]
    expected = {
        split: [
            count.records,
            *[count.labels.get(label, 0) for label in package.manifest.label_order or []],
            count.evidence_evaluable,
            count.label_only,
        ]
        for split, count in package.manifest.splits.items()
    }
    if not package.manifest.label_order or table != expected:
        raise ProtocolError("handoff_data_card_summary_required")
    return "legacy_table_counts; language_and_narrative_require_review"


def _unique_pairs(items: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result = {}
    for key, value in items:
        if key in result:
            raise ProtocolError("handoff_duplicate_json_key")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise ProtocolError("handoff_nonfinite_json_number")


def decode_json(raw: bytes | str) -> JsonValue:
    return json.loads(raw, object_pairs_hook=_unique_pairs, parse_constant=_nonfinite)
