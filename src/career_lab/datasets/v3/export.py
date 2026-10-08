"""Pure conversion from a fixed, permission-projected upstream snapshot.

FrozenSnapshot and ExportUnit are internal adapter ports, not replacement public
schemas. The live storage adapter is supplied by integration, never by an LLM.
"""

from dataclasses import dataclass
from typing import Protocol

from pydantic import TypeAdapter
from career_lab.contracts.v2.core import (
    EvidenceRefV2,
    ObjectRef,
    VersionPoint,
    FileRef,
    ProtocolError,
    digest,
)
from career_lab.contracts.v2.data import (
    ModelInput,
    DatasetRecordV2,
    AnnotationV2,
    Lineage,
    Provenance,
    FAMILY_TASK,
)
from .common import json_bytes, sha, check_payload
from . import EXPORTER_REVISION
from .temporal import POLICY_VERSION, CONTEXT_KEY

INPUT = TypeAdapter(ModelInput)


def object_key(ref):
    return digest(
        ObjectRef.model_validate(
            {k: ref.model_dump(mode="json")[k] for k in ObjectRef.model_fields}
        )
    )


@dataclass(frozen=True)
class SourceObject:
    ref: ObjectRef
    text: str
    available_at: VersionPoint
    readers: tuple[str, ...]
    usage: str = "visible"  # visible, private, gold, probe, solution
    validity_known: bool = False
    valid_from_seq: int = 0
    valid_until_seq: int | None = None

    def __post_init__(self):
        if (
            type(self.validity_known) is not bool
            or type(self.valid_from_seq) is not int
            or self.valid_from_seq < 0
        ):
            raise ProtocolError("source_validity_metadata_invalid")
        if self.valid_until_seq is not None and (
            type(self.valid_until_seq) is not int or self.valid_until_seq < self.valid_from_seq
        ):
            raise ProtocolError("source_validity_metadata_invalid")


@dataclass(frozen=True)
class FrozenSnapshot:
    session_id: str
    actor_id: str
    point: VersionPoint
    objects: tuple[SourceObject, ...]
    source_digest: str
    origin: str  # fixture or an actual DatasetRecordV2 bucket


class SnapshotPort(Protocol):
    def read_snapshot(self, session_id: str, point: VersionPoint) -> FrozenSnapshot: ...


@dataclass(frozen=True)
class ExportUnit:
    family: str
    model_input: object
    lineage: Lineage
    provenance: Provenance
    split: str = "train"
    language: str = "zh"
    label_tier: str = "G2"
    evaluation_time_known: bool = False

    def __post_init__(self):
        if type(self.evaluation_time_known) is not bool:
            raise ProtocolError("evaluation_time_status_invalid")


@dataclass(frozen=True)
class ExportResult:
    records: tuple[DatasetRecordV2, ...]
    annotations: tuple[AnnotationV2, ...]
    source_maps: dict
    quarantined: tuple[dict, ...]
    snapshot_digest: str | None
    origin: str
    source_snapshots: tuple[dict, ...] = ()

    @property
    def source_set_digest(self):
        return digest(
            {
                "protocol": "w07-snapshot-set-v1",
                "members": sorted(self.source_snapshots, key=lambda x: x["snapshot_digest"]),
            }
        )


def _not_after(a, b):
    return all(
        getattr(a, k) <= getattr(b, k)
        for k in ("business_seq", "workspace_revision", "storage_revision")
    )


def export_snapshot(snapshot: FrozenSnapshot, units, *, annotation_version="w07-pending-v1"):
    """No writes or runtime actions. Invalid units are quarantined independently."""
    if snapshot.origin not in {
        "fixture",
        "env_run",
        "human_session",
        "public_aux",
        "business_synth",
    }:
        raise ProtocolError("unknown_snapshot_origin")
    # Copy nested contract values: frozen dataclasses alone do not freeze a
    # mutable Pydantic model supplied by an upstream adapter.
    snapshot = FrozenSnapshot(
        snapshot.session_id,
        snapshot.actor_id,
        VersionPoint.model_validate(snapshot.point.model_dump(mode="json")),
        tuple(
            SourceObject(
                ObjectRef.model_validate(x.ref.model_dump(mode="json")),
                x.text,
                VersionPoint.model_validate(x.available_at.model_dump(mode="json")),
                tuple(x.readers),
                x.usage,
                x.validity_known,
                x.valid_from_seq,
                x.valid_until_seq,
            )
            for x in snapshot.objects
        ),
        snapshot.source_digest,
        snapshot.origin,
    )
    if snapshot.origin == "fixture":
        try:
            TypeAdapter(DatasetRecordV2.model_fields["bucket"].annotation).validate_python(
                "fixture"
            )
        except ValueError:
            raise ProtocolError("fixture_bucket_contract_unavailable", status=503) from None
    sources = {object_key(x.ref): x for x in snapshot.objects}
    if len(sources) != len(snapshot.objects):
        raise ProtocolError("duplicate_source_object")
    snapshot_before = digest(
        {
            "session": snapshot.session_id,
            "point": snapshot.point.model_dump(mode="json"),
            "objects": [
                {
                    "ref": x.ref.model_dump(mode="json"),
                    "text": x.text,
                    "available_at": x.available_at.model_dump(mode="json"),
                    "readers": x.readers,
                    "usage": x.usage,
                    "validity_known": x.validity_known,
                    "valid_from_seq": x.valid_from_seq,
                    "valid_until_seq": x.valid_until_seq,
                }
                for x in snapshot.objects
            ],
            "source_digest": snapshot.source_digest,
            "origin": snapshot.origin,
        }
    )
    records, annotations, source_maps, excluded = [], [], {}, []
    seen = set()
    for index, unit in enumerate(units):
        try:
            if unit.label_tier != "G2":
                raise ProtocolError("export_tier_must_be_pending_model")
            lineage = Lineage.model_validate(unit.lineage.model_dump(mode="json"))
            provenance = Provenance.model_validate(unit.provenance.model_dump(mode="json"))
            if lineage.session_id != snapshot.session_id:
                raise ProtocolError("lineage_session_mismatch")
            if provenance.source.source_digest != snapshot.source_digest:
                raise ProtocolError("source_snapshot_mismatch")
            if not provenance.actual_sources:
                raise ProtocolError("source_files_required")
            raw = (
                unit.model_input.model_dump(mode="json")
                if hasattr(unit.model_input, "model_dump")
                else unit.model_input
            )
            data = INPUT.validate_python(raw).model_dump(mode="json")
            if FAMILY_TASK.get(unit.family) != data["task_type"]:
                raise ProtocolError("family_task_mismatch")
            check_payload(data)

            def strings(value):
                if isinstance(value, str):
                    yield value
                elif isinstance(value, dict):
                    for child in value.values():
                        yield from strings(child)
                elif isinstance(value, list):
                    for child in value:
                        yield from strings(child)

            input_strings = tuple(strings(data))
            for source in snapshot.objects:
                if (
                    (source.usage != "visible" or snapshot.actor_id not in source.readers)
                    and source.text
                    and any(source.text in text for text in input_strings)
                ):
                    raise ProtocolError("private_content_in_input")

            def visible_identity(value):
                if isinstance(value, dict):
                    return {
                        k: visible_identity(v)
                        for k, v in value.items()
                        if k not in {"id", "item_id", "object_id", "session_id", "input_hash"}
                    }
                if isinstance(value, list):
                    return [visible_identity(v) for v in value]
                return value

            public_seed_input = visible_identity(data)
            if "evidence" in public_seed_input:
                public_seed_input["evidence"]["candidate_evidence"] = sorted(
                    public_seed_input["evidence"]["candidate_evidence"], key=digest
                )
            public_seed = digest(public_seed_input)
            refs = {}
            observation_bindings = {}

            def resolve(ref, *, optional_missing=False, at=None):
                at = snapshot.point if at is None else at
                if ref.session_id != snapshot.session_id:
                    raise ProtocolError("cross_session_reference")
                key = object_key(ref)
                source = sources.get(key)
                if source is None:
                    if not optional_missing:
                        raise ProtocolError("unresolved_source_reference")
                else:
                    if source.usage != "visible" or snapshot.actor_id not in source.readers:
                        raise ProtocolError("unauthorized_source_reference", status=403)
                    if not _not_after(source.available_at, at):
                        raise ProtocolError("future_source_reference")
                if isinstance(ref, EvidenceRefV2):
                    if ref.observed_at_seq > at.business_seq:
                        raise ProtocolError("future_evidence_reference")
                    if (
                        source is not None
                        and ref.observed_at_seq < source.available_at.business_seq
                    ):
                        raise ProtocolError("observation_before_source_available")
                    if (
                        source is not None
                        and source.validity_known
                        and (
                            ref.valid_from_seq != source.valid_from_seq
                            or ref.valid_until_seq != source.valid_until_seq
                        )
                    ):
                        raise ProtocolError("source_validity_mismatch")
                    if source is not None and ref.span_start is not None:
                        if source.text[ref.span_start : ref.span_end] != ref.quote:
                            raise ProtocolError("source_quote_mismatch")
                    if source is not None and ref.quote and ref.quote not in source.text:
                        raise ProtocolError("source_quote_mismatch")
                alias = "o-" + digest([public_seed, key])[:24]
                exact = ref.model_dump(mode="json")
                if exact not in refs.setdefault(alias, []):
                    refs[alias].append(exact)
                projected = ref.model_dump(mode="json") | {
                    "object_id": alias,
                    "session_id": "input-session",
                }
                return projected, source

            def evidence_ref(raw_ref, **kwargs):
                return resolve(EvidenceRefV2.model_validate(raw_ref), **kwargs)

            def steps(items):
                previous = -1
                ids = set()
                for step in items:
                    point = VersionPoint.model_validate(step["as_of"])
                    if not _not_after(point, snapshot.point) or point.business_seq < previous:
                        raise ProtocolError("trajectory_time_order")
                    if step["id"] in ids:
                        raise ProtocolError("duplicate_step_id")
                    ids.add(step["id"])
                    previous = point.business_seq
                    for ref in step["evidence_refs"]:
                        if ref["observed_at_seq"] > point.business_seq:
                            raise ProtocolError("future_step_evidence")
                    original_id = step["id"]
                    projected = [evidence_ref(r, at=point) for r in step["evidence_refs"]]
                    # Each observation is an exact source-backed span or full
                    # source text visible at this step, never an uncited summary.
                    for index, observation in enumerate(step["observations"]):
                        matches = []
                        for raw_ref, (ref, source) in zip(
                            step["evidence_refs"], projected, strict=True
                        ):
                            supported_text = raw_ref.get("quote") or source.text
                            if observation and observation == supported_text:
                                matches.append(raw_ref)
                        if not matches:
                            raise ProtocolError("observation_source_required")
                        observation_bindings[f"{original_id}:{index}"] = {
                            "text_hash": digest(observation),
                            "as_of": point.model_dump(mode="json"),
                            "sources": matches,
                        }
                    step["evidence_refs"] = [ref for ref, source in projected]
                    step["id"] = "step-" + digest(original_id)[:24]

            candidate_map = {}
            if unit.family in {"relation", "criterion"}:
                package = data["evidence"]
                reference = VersionPoint.model_validate(package["as_of"])
                if not _not_after(reference, snapshot.point):
                    raise ProtocolError("future_evaluation_frame")
                package["subjects"] = [
                    evidence_ref(r, at=reference)[0] for r in package["subjects"]
                ]
                # A deterministic hash permutation depends on source identity, not
                # producer order or gold. Keep the source map for exact recovery.
                candidates = sorted(
                    package["candidate_evidence"],
                    key=lambda c: digest([public_seed, visible_identity(c)]),
                )
                known = []
                for number, candidate in enumerate(candidates, 1):
                    ref, source = evidence_ref(candidate["ref"], at=reference)
                    expected = candidate["ref"].get("quote") or source.text
                    if candidate["text"] != expected:
                        raise ProtocolError("candidate_text_source_mismatch")
                    neutral = f"e{number}"
                    candidate_map[neutral] = candidate["id"]
                    candidate["id"], candidate["ref"] = neutral, ref
                    if source.validity_known:
                        known.append(neutral)
                package["candidate_evidence"] = candidates
                package["rule_context"][CONTEXT_KEY] = {
                    "policy": POLICY_VERSION,
                    "status": "known" if unit.evaluation_time_known else "undetermined",
                    "reference_seq": reference.business_seq,
                    "validity_known_ids": sorted(known),
                }
                package["dropped_refs"] = [
                    resolve(ObjectRef.model_validate(r))[0] for r in package["dropped_refs"]
                ]
                package["missing_refs"] = [
                    resolve(ObjectRef.model_validate(r), optional_missing=True)[0]
                    for r in package["missing_refs"]
                ]
                package["item_id"] = "item-" + public_seed[:24]
                package["input_hash"] = digest(
                    {k: v for k, v in package.items() if k != "input_hash"}
                )
            elif unit.family == "trajectory":
                steps(data["steps"])
            else:
                if VersionPoint.model_validate(data["as_of"]) != snapshot.point:
                    raise ProtocolError("mixed_snapshot_point")
                steps(data["observed_steps"])
                ids = [c["id"] for c in data["candidates"]]
                if len(ids) != len(set(ids)):
                    raise ProtocolError("duplicate_candidate_action")
            model = INPUT.validate_python(data)
            ih = digest(model)
            rid = (
                "w07-"
                + digest(
                    {
                        "input": ih,
                        "lineage": lineage.model_dump(mode="json"),
                        "source": provenance.source.model_dump(mode="json"),
                        "exporter": EXPORTER_REVISION,
                    }
                )[:32]
            )
            if rid in seen:
                raise ProtocolError("duplicate_export_record")
            pending = AnnotationV2(
                record_id=rid,
                annotation_version=annotation_version,
                input_hash=ih,
                label_tier=unit.label_tier,
                status="pending",
                passes=(),
            )
            transformations = (
                *provenance.transformations,
                EXPORTER_REVISION,
                "neutral-reference-ids",
            )
            if snapshot.origin == "fixture":
                transformations += ("fixture:not-business-run",)
            provenance = Provenance.model_validate(
                provenance.model_dump(mode="json") | {"transformations": transformations}
            )
            record = DatasetRecordV2(
                record_id=rid,
                family=unit.family,
                label_tier=unit.label_tier,
                bucket=snapshot.origin,
                language=unit.language,
                lineage=lineage,
                split=unit.split,
                provenance=provenance,
                model_input=model,
                label_ref=FileRef(path=f"labels/{rid}.json", sha256=sha(json_bytes(pending))),
                input_hash=ih,
            )
            seen.add(rid)
            records.append(record)
            annotations.append(pending)
            source_maps[rid] = {
                "objects": refs,
                "candidate_ids": candidate_map,
                "observation_bindings": observation_bindings,
                "snapshot_digest": snapshot_before,
            }
        except (ValueError, KeyError, TypeError) as exc:
            excluded.append(
                {
                    "unit_index": index,
                    "family": unit.family,
                    "reason": getattr(exc, "code", "invalid_source_or_schema"),
                    "error_type": type(exc).__name__,
                }
            )
    descriptor = {
        "snapshot_digest": snapshot_before,
        "session_id": snapshot.session_id,
        "actor_id": snapshot.actor_id,
        "capture_point": snapshot.point.model_dump(mode="json"),
        "source_digest": snapshot.source_digest,
        "origin": snapshot.origin,
        "record_ids": sorted(r.record_id for r in records),
    }
    return ExportResult(
        tuple(records),
        tuple(annotations),
        source_maps,
        tuple(excluded),
        snapshot_before,
        snapshot.origin,
        (descriptor,),
    )


def export_from_port(port: SnapshotPort, session_id, point, build_units):
    """One fixed read; integration must implement atomic business/workspace capture."""
    captured = port.read_snapshot(session_id, point)
    if captured.session_id != session_id or captured.point != point:
        raise ProtocolError("snapshot_port_identity_mismatch")
    return export_snapshot(captured, build_units(captured))


def validate_source_membership(result):
    """Reject hand-concatenated records that omit their snapshot identity."""
    if not result.source_snapshots:
        raise ProtocolError("source_snapshot_manifest_required")
    descriptors = {d["snapshot_digest"]: d for d in result.source_snapshots}
    if len(descriptors) != len(result.source_snapshots):
        raise ProtocolError("duplicate_source_snapshot")
    rows = {r.record_id: r for r in result.records}
    if len(rows) != len(result.records) or set(result.source_maps) != set(rows):
        raise ProtocolError("source_record_identity_mismatch")
    membership = {}
    for digest_id, desc in descriptors.items():
        VersionPoint.model_validate(desc["capture_point"])
        if len(desc["record_ids"]) != len(set(desc["record_ids"])):
            raise ProtocolError("duplicate_snapshot_member")
        for rid in desc["record_ids"]:
            if rid in membership:
                raise ProtocolError("ambiguous_snapshot_member")
            membership[rid] = digest_id
    if set(membership) != set(rows):
        raise ProtocolError("snapshot_manifest_record_set_mismatch")
    for rid, record in rows.items():
        desc = descriptors[membership[rid]]
        mapping = result.source_maps[rid]
        if (
            mapping.get("snapshot_digest") != membership[rid]
            or record.lineage.session_id != desc["session_id"]
        ):
            raise ProtocolError("snapshot_record_source_mismatch")
        if desc["origin"] != record.bucket:
            raise ProtocolError("source_origin_bucket_mismatch")
        if record.provenance.source.source_digest != desc["source_digest"]:
            raise ProtocolError("snapshot_code_identity_mismatch")
    if len(descriptors) == 1:
        if result.snapshot_digest != next(iter(descriptors)):
            raise ProtocolError("single_snapshot_digest_mismatch")
    elif result.snapshot_digest is not None:
        raise ProtocolError("aggregate_cannot_claim_single_snapshot")
    return membership


def aggregate_exports(results):
    """Combine immutable exports without changing record IDs, lineage or source roots."""
    results = list(results)
    if not results:
        raise ProtocolError("aggregate_requires_exports")
    records = []
    annotations = []
    maps = {}
    snapshots = []
    excluded = []
    origins = set()
    for result in results:
        validate_source_membership(result)
        if set(maps) & set(result.source_maps):
            raise ProtocolError("duplicate_aggregate_record")
        records.extend(result.records)
        annotations.extend(result.annotations)
        maps.update(result.source_maps)
        snapshots.extend(result.source_snapshots)
        origins.add(result.origin)
        excluded.extend(
            dict(row, export_source_set=result.source_set_digest) for row in result.quarantined
        )
    if "fixture" in origins and origins != {"fixture"}:
        raise ProtocolError("fixture_research_mix_forbidden")
    snapshots = tuple(sorted(snapshots, key=lambda x: x["snapshot_digest"]))
    origin = next(iter(origins)) if len(origins) == 1 else "mixed"
    combined = ExportResult(
        tuple(sorted(records, key=lambda r: r.record_id)),
        tuple(sorted(annotations, key=lambda a: a.record_id)),
        maps,
        tuple(excluded),
        snapshots[0]["snapshot_digest"] if len(snapshots) == 1 else None,
        origin,
        snapshots,
    )
    validate_source_membership(combined)
    return combined
