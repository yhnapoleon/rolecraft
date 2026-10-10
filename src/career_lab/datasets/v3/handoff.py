"""Mechanical review of responsible-party records; never a training/quality approval."""

from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, JsonValue

from career_lab.contracts.v2.core import FileRef, ProtocolError, digest
from career_lab.contracts.v2.data import (
    FAMILY_TASK,
    AnnotationDecision,
    AnnotationV2,
    DatasetRecordV2,
    SplitManifest,
)

from .attestation import validate_decision
from .common import check_payload, immutable_directory, json_bytes, sha, write_new
from .handoff_annotations import (
    minimal_decision,
    require_acceptable_selection,
    verify_handoff_annotation,
)
from .handoff_model import validate_model_return
from .handoff_package import HandoffPackage, check_card, load_package
from .handoff_records import LABEL_ORDERS, InputRow, LabelRow, Metadata, RowIndex
from .origin import verify_source_bodies
from .quality import QualityError, audit_records


class RecordReview(BaseModel):
    record_id: str
    input_hash: str
    annotation_version: str | None = None
    status: Literal["accept", "quarantine", "pending"] = "quarantine"
    reasons: list[str] = []
    accepted_label_tier: str | None = None
    normalized_decision: AnnotationDecision | None = None


def index_rows(rows: list[dict[str, JsonValue]]) -> dict[str, dict[str, JsonValue]]:
    result = {}
    for row in rows:
        rid = row.get("record_id")
        if not isinstance(rid, str) or not rid or rid in result:
            raise ProtocolError("handoff_record_identity_invalid")
        result[rid] = row
    return result


def build_record(row: InputRow, meta: Metadata, label: LabelRow) -> DatasetRecordV2:
    if (row.record_id, row.input_hash) != (meta.record_id, meta.input_hash):
        raise ProtocolError("handoff_metadata_identity_mismatch")
    if (row.record_id, row.input_hash) != (label.record_id, label.input_hash):
        raise ProtocolError("handoff_label_identity_mismatch")
    check_payload(row.model_input.model_dump(mode="json"))
    task = row.model_input.task_type
    return DatasetRecordV2(
        record_id=row.record_id,
        input_hash=row.input_hash,
        family=next(family for family, name in FAMILY_TASK.items() if name == task),
        language=meta.language,
        label_tier=label.label_tier,
        bucket=meta.bucket,
        split=meta.split,
        lineage=meta.lineage,
        provenance=meta.provenance,
        model_input=row.model_input,
        label_ref=FileRef(path=f"labels/{digest(row.record_id)}.json", sha256=digest(label)),
    )


def source_reasons(
    package: HandoffPackage,
    metadata: Metadata,
    record: DatasetRecordV2,
    decision: AnnotationDecision,
) -> list[str]:
    originals, packaged = metadata.provenance.actual_sources, metadata.packaged_sources
    if (
        not originals
        or len(originals) != len(packaged)
        or len({r.path for r in packaged}) != len(packaged)
    ):
        raise ProtocolError("handoff_source_mapping_invalid")
    bodies = []
    for original, mapped in zip(originals, packaged, strict=True):
        body = package.read(mapped.path)
        if original.sha256 != mapped.sha256 or sha(body) != mapped.sha256:
            raise ProtocolError("handoff_source_mapping_invalid")
        bodies.append(body)
    verify_source_bodies(record, bodies)
    reasons = []
    if record.bucket != "fixture":
        reasons.append("authoritative_source_reader_required")
        if not decision.evidence_evaluable and record.label_tier != "G0":
            reasons.append("label_only_semantic_review_required")
    return reasons


def review_record(
    package: HandoffPackage,
    raw: dict[str, JsonValue],
    meta: dict[str, JsonValue],
    target: dict[str, JsonValue],
    declared: dict[str, JsonValue] | None,
) -> tuple[RecordReview, DatasetRecordV2 | None]:
    review = RecordReview(record_id=raw["record_id"], input_hash=raw["input_hash"])
    record = None
    try:
        row, metadata, label = (
            InputRow.from_wire(raw),
            Metadata.model_validate(meta),
            LabelRow.model_validate(target),
        )
        record = build_record(row, metadata, label)
        order = LABEL_ORDERS[label.task_type]
        frozen = package.manifest.label_orders.get(label.task_type, package.manifest.label_order)
        if frozen != order or label.label_index != order.index(label.label):
            raise ProtocolError("handoff_label_order_mismatch")
        decision = label.decision()
        if decision.applicability == "not_applicable" and decision.label != "NOT_APPLICABLE":
            raise ProtocolError("annotation_applicability_mismatch")
        decision = validate_decision(
            decision.model_dump_json(), row.model_input.model_dump(mode="json")
        )
        require_acceptable_selection(decision)
        decision = minimal_decision(decision)
        reasons = source_reasons(package, metadata, record, decision)
        if reasons:
            review.status, review.reasons = "pending", reasons
            return review, record
        if declared is None:
            review.status, review.reasons = "pending", ["annotation_proof_required"]
            return review, record
        try:
            annotation = AnnotationV2.model_validate(declared)
            review.annotation_version = annotation.annotation_version
            versions = [label.annotation_version, package.manifest.annotation_version]
            if any(version and version != annotation.annotation_version for version in versions):
                raise ProtocolError("annotation_version_mismatch")
            artifacts = {
                name.removeprefix("audit/"): data
                for name, data in package.files.items()
                if name.startswith("audit/labels/passes/")
            }
            verified = verify_handoff_annotation(record, annotation, artifacts, label.label_tier)
        except (ValueError, KeyError, TypeError) as error:
            review.status = "pending"
            review.reasons = [getattr(error, "code", "annotation_proof_invalid")]
            return review, record
        if verified.status != "accepted":
            review.status, review.reasons = "pending", ["annotation_not_accepted"]
        elif (
            minimal_decision(verified.final) != decision or verified.label_tier != label.label_tier
        ):
            raise ProtocolError("handoff_declared_label_mismatch")
        else:
            review.status = "accept"
            review.accepted_label_tier = verified.label_tier
            review.normalized_decision = decision
    except (ValueError, KeyError, TypeError) as error:
        review.status = "quarantine"
        review.reasons = [getattr(error, "code", "handoff_record_invalid")]
    return review, record


def package_rows(package: HandoffPackage) -> tuple[RowIndex, RowIndex, RowIndex, RowIndex]:
    metadata = index_rows(package.rows("audit/metadata.jsonl"))
    inputs, labels = {}, {}
    for split in package.manifest.splits:
        if split not in {"train", "dev", "test", "regression"}:
            raise ProtocolError("handoff_split_invalid")
        incoming = index_rows(package.rows(f"data/{split}.inputs.jsonl"))
        targets = index_rows(package.rows(f"data/{split}.labels.jsonl"))
        if incoming.keys() != targets.keys() or inputs.keys() & incoming.keys():
            raise ProtocolError("handoff_record_set_mismatch")
        if any(metadata.get(rid, {}).get("split") != split for rid in incoming):
            raise ProtocolError("handoff_split_mismatch")
        inputs.update(incoming)
        labels.update(targets)
    if not inputs or metadata.keys() != inputs.keys():
        raise ProtocolError("handoff_record_set_mismatch")
    annotations = (
        index_rows(package.rows("audit/original-annotations.jsonl"))
        if "audit/original-annotations.jsonl" in package.files
        else {}
    )
    if annotations.keys() - inputs.keys():
        raise ProtocolError("handoff_annotation_set_mismatch")
    verify_counts(package, inputs, labels, metadata)
    return inputs, labels, metadata, annotations


def verify_counts(
    package: HandoffPackage, inputs: RowIndex, labels: RowIndex, metadata: RowIndex
) -> None:
    splits = package.json(package.manifest.split_manifest)
    if "entries" in splits:
        split_rows = SplitManifest.model_validate(splits)
        split_map = {entry.record_id: entry.split for entry in split_rows.entries}
        for entry in split_rows.entries:
            meta = metadata.get(entry.record_id)
            if meta is None or (entry.component_id, entry.structure_id) != (
                meta["connected_component_id"],
                meta["lineage"]["structure_id"],
            ):
                raise ProtocolError("handoff_split_identity_mismatch")
    else:
        split_map = splits
    if split_map != {rid: meta["split"] for rid, meta in metadata.items()}:
        raise ProtocolError("handoff_split_mismatch")
    component_splits: dict[str, str] = {}
    for meta in metadata.values():
        component = meta["connected_component_id"]
        previous = component_splits.setdefault(component, meta["split"])
        if previous != meta["split"]:
            raise ProtocolError("handoff_component_cross_split")
    for split, count in package.manifest.splits.items():
        ids = [rid for rid in inputs if metadata[rid]["split"] == split]
        actual = {
            "records": len(ids),
            "labels": dict(Counter(labels[rid]["label"] for rid in ids)),
            "language": dict(Counter(metadata[rid]["language"] for rid in ids)),
            "evidence_evaluable": sum(labels[rid].get("evidence_evaluable") is True for rid in ids),
            "label_only": sum(labels[rid].get("evidence_evaluable") is False for rid in ids),
        }
        if count.label_tiers is not None:
            actual["label_tiers"] = dict(Counter(labels[rid]["label_tier"] for rid in ids))
        expected = count.model_dump(exclude_none=True)
        for key in ("labels", "language", "label_tiers"):
            if key in expected:
                expected[key] = {k: v for k, v in expected[key].items() if v != 0}
        if actual != expected:
            raise ProtocolError("handoff_count_mismatch")


def save_review(output: Path, report: dict[str, JsonValue]) -> None:
    try:
        with immutable_directory(output) as stage:
            write_new(stage / "report.json", report)
    except ProtocolError as error:
        if error.code != "immutable_output_exists":
            raise
        if output.is_symlink() or not output.is_dir():
            raise ProtocolError("handoff_review_conflict") from None
        paths = list(output.iterdir())
        if (
            len(paths) != 1
            or paths[0].name != "report.json"
            or paths[0].is_symlink()
            or not paths[0].is_file()
            or paths[0].read_bytes() != json_bytes(report)
        ):
            raise ProtocolError("handoff_review_conflict") from None


def validate_handoff(
    root: Path, output: Path, *, checkpoint: Path | None = None, split: str = "dev"
) -> dict[str, JsonValue]:
    if output.resolve().is_relative_to(root.resolve()) or root.resolve().is_relative_to(
        output.resolve()
    ):
        raise ProtocolError("handoff_output_overlaps_package")
    package = load_package(root)
    card_check = check_card(package)
    inputs, labels, metadata, annotations = package_rows(package)
    reviews, records = [], []
    for rid, row in inputs.items():
        review, record = review_record(
            package, row, metadata[rid], labels[rid], annotations.get(rid)
        )
        reviews.append(review)
        if record:
            records.append(record)
    try:
        audit = audit_records(records)
    except QualityError as error:
        audit = error.report
    for error in audit["errors"]:
        for review in reviews:
            affected = error.get("record_ids", [error.get("record_id")])
            if affected == [None] or review.record_id in affected:
                review.status = "quarantine"
                review.reasons.append(error["code"])
                review.accepted_label_tier = None
                review.normalized_decision = None
    report = {
        "protocol": "data-handoff-review-v1",
        "dataset_id": package.manifest.dataset_id,
        "manifest_sha256": package.manifest_hash,
        "package_sha256": package.package_hash,
        "data_card_check": card_check,
        "records": [review.model_dump(mode="json") for review in reviews],
        "counts": dict(Counter(review.status for review in reviews)),
        "training_ready": False,
        "scope": "mechanical_validation",
        "quality_verified": False,
        "call_authenticity_verified": False,
        "blockers": ["responsible_party_data_and_model_review_required"],
    }
    if checkpoint is not None:
        if output.resolve().is_relative_to(
            checkpoint.parent.resolve()
        ) or checkpoint.parent.resolve().is_relative_to(output.resolve()):
            raise ProtocolError("handoff_output_overlaps_package")
        report["model_return"] = validate_model_return(
            package,
            checkpoint,
            split,
            {rid: InputRow.from_wire(row) for rid, row in inputs.items()},
            {rid: LabelRow.model_validate(row) for rid, row in labels.items()},
            {rid: Metadata.model_validate(row) for rid, row in metadata.items()},
        )
    save_review(output, report)
    return report
