"""Read the frozen portable return dataset without generating labels or training data."""

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from career_lab.contracts import v2 as C

from .core import LABELS, Example


@dataclass(frozen=True)
class ReturnDataset:
    examples: tuple[Example, ...]
    dataset_id: str
    manifest_hash: str
    fixture: bool


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


def load_return_dataset(root: Path, checksum: str, partition: str) -> ReturnDataset:
    if partition != "dev":
        raise C.ProtocolError("return_selection_partition_forbidden", status=403)
    try:
        manifest = DatasetManifest.model_validate(
            strict_json(C.read_file(root, C.FileRef(path="dataset-manifest.json", sha256=checksum)))
        )
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
    if (
        not inputs
        or inputs.keys() != labels.keys()
        or len(inputs) != manifest.splits[partition].records
    ):
        raise C.ProtocolError("return_dataset_record_set_mismatch")
    fixture = manifest.status == "FIXTURE_ONLY_NOT_FINAL_TRAINING_DATA"
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
    declared = manifest.splits[partition].language
    if any(counts[language] != declared.get(language, 0) for language in {"zh", "en", *declared}):
        raise C.ProtocolError("return_language_count_mismatch")
    return ReturnDataset(tuple(examples), manifest.dataset_id, checksum, fixture)
