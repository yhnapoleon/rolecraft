"""Read a frozen return dataset without generating labels or training data.

Two layouts. The fixture-v2 portable layout shares one annotation file and therefore only
ever holds train/dev. The v3 split-sealed layout (``rolecraft-dataset-split-sealed-v1``)
binds every split's own files under ``splits.<split>.files``; reading one split opens only
that split's four files, and the held-out test split opens only with a recorded opening.
"""

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from career_lab.contracts import v2 as C
from career_lab.datasets.v3.handoff_package import (
    SEALED_LAYOUT,
    check_sealed_structure,
    require_regular,
    split_file_names,
)

from .core import LABELS, Example

PORTABLE_LAYOUT = "portable-v2"
FIXTURE_STATUS = "FIXTURE_ONLY_NOT_FINAL_TRAINING_DATA"
# A constructed mechanism sample: may exercise the held-out opening, is reported as synthetic.
SYNTHETIC_STATUS = "SYNTHETIC_MECHANISM_SAMPLE_NOT_TRAINING_DATA"


@dataclass(frozen=True)
class ReturnDataset:
    examples: tuple[Example, ...]
    dataset_id: str
    manifest_hash: str
    fixture: bool
    layout: str = PORTABLE_LAYOUT
    split: str = "dev"
    status: str = ""

    @property
    def synthetic(self) -> bool:
        return self.fixture or self.status == SYNTHETIC_STATUS


class HeldOutOpening(Protocol):
    """The recorded one-time test opening (see ``held_out``); re-checked before each read."""

    def require_open(self, dataset_hash: str) -> None: ...


class FileIdentity(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    sha256: C.Hash


class SplitSummary(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    records: int = Field(ge=1)
    language: dict[str, int]


class DatasetManifest(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    schema_version: Literal[1]
    dataset_id: str = Field(min_length=1)
    status: str
    test_included: bool = False
    task_type: Literal["relation"]
    label_order: list[str]
    files: dict[str, FileIdentity]
    splits: dict[str, SplitSummary]


class SealedFileIdentity(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    sha256: C.Hash
    size: int = Field(ge=0)


class SealedSplit(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    records: int = Field(ge=1)
    language: dict[str, int]
    files: dict[str, SealedFileIdentity]


class SealedManifest(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    schema_version: Literal[1]
    layout: Literal["rolecraft-dataset-split-sealed-v1"]
    dataset_id: str = Field(min_length=1)
    status: str
    task_type: Literal["relation"]
    label_order: list[str]
    test_sealed: bool
    splits: dict[str, SealedSplit]
    files: dict[str, SealedFileIdentity]


def strict_json(raw: bytes | str) -> Any:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in values:
            if key in result:
                raise C.ProtocolError("return_duplicate_json_key")
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=pairs)


def json_lines(raw: bytes) -> list[dict[str, Any]]:
    rows = [strict_json(line) for line in raw.decode().splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise C.ProtocolError("return_row_must_be_object")
    return rows


def unique_records(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for row in rows:
        identifier = row.get("record_id")
        if not isinstance(identifier, str) or not identifier or identifier in result:
            raise C.ProtocolError("return_record_identity_invalid")
        result[identifier] = row
    return result


def load_return_dataset(
    root: Path, checksum: str, partition: str, *, opening: HeldOutOpening | None = None
) -> ReturnDataset:
    """Records of one partition, aligned with their labels, annotations and metadata.

    ``partition="test"`` requires the sealed layout and a recorded ``opening``.
    """
    raw = strict_json(C.read_file(root, C.FileRef(path="dataset-manifest.json", sha256=checksum)))
    if isinstance(raw, dict) and "layout" in raw:
        return load_sealed_dataset(root, checksum, raw, partition, opening)
    if partition != "dev":
        raise C.ProtocolError("return_selection_partition_forbidden", status=403)
    try:
        manifest = DatasetManifest.model_validate(raw)
    except ValidationError as error:
        raise C.ProtocolError("return_dataset_protocol_invalid") from error
    if manifest.label_order != list(LABELS["relation"]):
        raise C.ProtocolError("return_dataset_protocol_invalid")
    if manifest.test_included or not set(manifest.splits) <= {"train", "dev"}:
        raise C.ProtocolError("return_held_out_bundle_forbidden", status=403)

    def records(name: str) -> dict[str, dict[str, Any]]:
        ref = C.FileRef(path=name, sha256=manifest.files[name].sha256)
        return unique_records(json_lines(C.read_file(root, ref)))

    # The portable format has one shared annotation file. Check its entire
    # declared partition inventory before opening any labels, not after filtering.
    metadata = records("audit/metadata.jsonl")
    if any(row.get("split") not in {"train", "dev"} for row in metadata.values()):
        raise C.ProtocolError("return_shared_annotation_partition_forbidden", status=403)
    inputs = records(f"data/{partition}.inputs.jsonl")
    labels = records(f"data/{partition}.labels.jsonl")
    annotations = records("audit/original-annotations.jsonl")
    fixture = manifest.status == FIXTURE_STATUS
    examples = aligned_examples(
        partition, inputs, labels, annotations, metadata, manifest.splits[partition], fixture
    )
    return ReturnDataset(examples, manifest.dataset_id, checksum, fixture, status=manifest.status)


def load_sealed_dataset(
    root: Path,
    checksum: str,
    raw: Any,
    partition: str,
    opening: HeldOutOpening | None,
) -> ReturnDataset:
    try:
        manifest = SealedManifest.model_validate(raw)
    except ValidationError as error:
        raise C.ProtocolError("return_dataset_protocol_invalid") from error
    if manifest.label_order != list(LABELS["relation"]):
        raise C.ProtocolError("return_dataset_protocol_invalid")
    check_sealed_structure(
        {split: entry.files for split, entry in manifest.splits.items()},
        manifest.files,
        manifest.test_sealed,
    )
    if partition == "test":
        if opening is None:
            raise C.ProtocolError("held_out_test_not_opened", status=403)
        opening.require_open(checksum)
    elif partition != "dev":
        raise C.ProtocolError("return_selection_partition_forbidden", status=403)
    if partition not in manifest.splits:
        raise C.ProtocolError("return_partition_missing")
    split = manifest.splits[partition]

    names = split_file_names(partition)
    for name in names.values():
        require_regular(root, name)

    def records(kind: str) -> dict[str, dict[str, Any]]:
        ref = C.FileRef(path=names[kind], sha256=split.files[names[kind]].sha256)
        return unique_records(json_lines(C.read_file(root, ref)))

    inputs, labels = records("inputs"), records("labels")
    annotations, metadata = records("annotations"), records("metadata")
    if annotations.keys() != inputs.keys() or metadata.keys() != inputs.keys():
        raise C.ProtocolError("return_dataset_record_set_mismatch")
    fixture = manifest.status == FIXTURE_STATUS
    examples = aligned_examples(partition, inputs, labels, annotations, metadata, split, fixture)
    return ReturnDataset(
        examples, manifest.dataset_id, checksum, fixture, SEALED_LAYOUT, partition, manifest.status
    )


def aligned_examples(
    partition: str,
    inputs: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    annotations: dict[str, dict[str, Any]],
    metadata: dict[str, dict[str, Any]],
    declared: SplitSummary | SealedSplit,
    fixture: bool,
) -> tuple[Example, ...]:
    if not inputs or inputs.keys() != labels.keys() or len(inputs) != declared.records:
        raise C.ProtocolError("return_dataset_record_set_mismatch")
    examples = []
    for identifier, raw in inputs.items():
        item = C.RelationInput.model_validate(raw["model_input"])
        label = labels[identifier]
        annotation = C.AnnotationV2.model_validate(annotations[identifier])
        meta = metadata[identifier]
        if (
            C.digest(item) != raw["input_hash"]
            or annotation.input_hash != raw["input_hash"]
            or label["input_hash"] != raw["input_hash"]
            or meta["input_hash"] != raw["input_hash"]
            or meta["split"] != partition
        ):
            raise C.ProtocolError("return_input_identity_mismatch")
        if annotation.final is None or annotation.status != "accepted":
            raise C.ProtocolError("return_labels_not_accepted")
        decision = annotation.final.model_dump(mode="json", exclude={"schema_version"})
        if any(label.get(key) != value for key, value in decision.items()) or (
            label.get("label_index") != LABELS["relation"].index(annotation.final.label)
            or label.get("label_tier") != annotation.label_tier
        ):
            raise C.ProtocolError("return_label_projection_mismatch")
        if meta.get("language") not in {"zh", "en"}:
            raise C.ProtocolError("return_record_language_required")
        example = Example(
            identifier,
            item,
            annotation,
            partition,
            meta["lineage"]["structure_id"],
            meta["lineage"]["component_id"],
            meta["language"],
            meta.get("bucket", "unspecified"),
            fixture,
        )
        examples.append(example.validate())
    counts = Counter(row.language for row in examples)
    language = declared.language
    if any(counts[name] != language.get(name, 0) for name in {"zh", "en", *language}):
        raise C.ProtocolError("return_language_count_mismatch")
    return tuple(examples)
