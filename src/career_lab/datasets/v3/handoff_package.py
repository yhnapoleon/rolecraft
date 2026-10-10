"""Read hash-bound training handoffs without executing any supplied code."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, JsonValue

from career_lab.contracts.v2.core import FileRef, ProtocolError, digest, read_file

from .common import sha


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


def load_package(root: Path) -> HandoffPackage:
    if root.is_symlink() or any(path.is_symlink() for path in root.rglob("*")):
        raise ProtocolError("handoff_symlink_forbidden")
    raw = (root / "dataset-manifest.json").read_bytes()
    manifest = HandoffManifest.model_validate(decode_json(raw))
    if manifest.schema_version != 1 or not manifest.splits:
        raise ProtocolError("handoff_manifest_version_invalid")
    files = {"dataset-manifest.json": raw}
    for name, identity in manifest.files.items():
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
    for name in ("audit/metadata.jsonl", "data_card.md", manifest.split_manifest):
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
        if declared != package.manifest.splits:
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
