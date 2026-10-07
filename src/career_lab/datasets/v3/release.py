"""Audited, immutable directory publication. Fixture releases are explicitly separate."""
from pathlib import Path

from career_lab.contracts.v2.core import FileRef, ProtocolError, digest, read_file
from career_lab.contracts.v2.data import DatasetRecordV2, AnnotationV2, SplitEntry, SplitManifest, DatasetSnapshotMetadata, DatasetMetadataV2, metadata_projection, validate_record_annotation
from .common import json_bytes, sha, write_new, read_json, immutable_directory
from .quality import audit_records, fixture_record, source_policy_error
from .export import ExportResult,aggregate_exports,validate_source_membership
from .attestation import verify_annotation_artifacts
from . import EXPORTER_REVISION
from .origin import binding,verify_sources
from .readiness import input_problem,readiness


def save_export(target, result):
    validate_source_membership(result)
    with immutable_directory(target) as root:
        data = {"records": [r.model_dump(mode="json") for r in result.records],
            "annotations": [a.model_dump(mode="json") for a in result.annotations],
            "source_maps": result.source_maps, "quarantined": result.quarantined,
            "snapshot_digest": result.snapshot_digest, "origin": result.origin,"source_snapshots":result.source_snapshots,"source_set_digest":result.source_set_digest}
        write_new(root / "export.json", data)
        write_new(root / "manifest.json", {"exporter": EXPORTER_REVISION,
            "export": FileRef(path="export.json", sha256=sha(json_bytes(data))).model_dump(mode="json")})


def load_export(root):
    import json
    root = Path(root)
    envelope = read_json(root / "manifest.json")
    data = json.loads(read_file(root, FileRef.model_validate(envelope["export"])))
    result=ExportResult(tuple(DatasetRecordV2.model_validate(x) for x in data["records"]),
        tuple(AnnotationV2.model_validate(x) for x in data["annotations"]), data["source_maps"],
        tuple(data["quarantined"]), data["snapshot_digest"], data["origin"],tuple(data.get("source_snapshots",())))
    validate_source_membership(result)
    if result.source_set_digest!=data.get("source_set_digest"):raise ProtocolError("export_source_set_mismatch")
    return result


def publish_release(target, result, *, source_root, policies, annotations=None,
                    annotation_artifacts=None, fixture=False, allow_pending=False,source_contexts=None,source_authority=None,label_only_authority=None):
    membership=validate_source_membership(result)
    snapshot_by_digest={d["snapshot_digest"]:d for d in result.source_snapshots}
    contexts=source_contexts or {r.record_id:{"root":source_root,"policies":policies} for r in result.records}
    if set(contexts)!={r.record_id for r in result.records}:raise ProtocolError("source_context_identity_mismatch")
    if result.origin == "fixture" and not fixture:
        raise ProtocolError("fixture_cannot_publish_as_real")
    if fixture and any(r.bucket!="fixture" for r in result.records):
        raise ProtocolError("fixture_release_requires_fixture_bucket")
    if any(r.split == "test" for r in result.records):
        raise ProtocolError("sealed_release_requires_integrator", status=403)
    if not result.records:
        raise ProtocolError("empty_release")
    # Check connected leakage before exclusions can accidentally hide it.
    audit_records(result.records)
    labels = list(result.annotations if annotations is None else annotations)
    by_id = {a.record_id: a for a in labels}
    if len(by_id) != len(labels) or by_id.keys() - {r.record_id for r in result.records}:
        raise ProtocolError("annotation_identity_set_mismatch")
    artifacts = annotation_artifacts or {}
    accepted, selected_labels, excluded = [], [], list(result.quarantined)
    origins={}
    for record in result.records:
        context=contexts[record.record_id]
        reason = source_policy_error(record, context["policies"])
        if fixture_record(record) and not fixture:
            reason = "fixture_cannot_publish_as_real"
        if reason:
            excluded.append({"record_id": record.record_id, "reason": reason})
            continue
        if record.record_id not in by_id:
            raise ProtocolError("annotation_identity_set_mismatch")
        incomplete=input_problem(record)
        if incomplete and not allow_pending:
            excluded.append({"record_id":record.record_id,"reason":incomplete})
            continue
        annotation = AnnotationV2.model_validate(by_id[record.record_id].model_dump(mode="json"))
        if annotation.input_hash != record.input_hash:
            raise ProtocolError("annotation_input_mismatch")
        if annotation.final and annotation.final.task_type != record.model_input.task_type:
            raise ProtocolError("annotation_task_mismatch")
        if annotation.status != "accepted" and not allow_pending:
            reason = reason or "annotation_not_accepted"
        if reason:
            excluded.append({"record_id": record.record_id, "reason": reason})
            continue
        origins[record.record_id]=verify_sources(record,snapshot_by_digest[membership[record.record_id]],Path(context["root"]),source_authority)
        if record.record_id not in result.source_maps:
            raise ProtocolError("missing_source_map")
        verify_annotation_artifacts(record, annotation, artifacts)
        if annotation.final and not annotation.final.evidence_evaluable and record.bucket!="fixture" and annotation.label_tier!="G0":
            if label_only_authority is None or label_only_authority(record,annotation) is not True:
                raise ProtocolError("label_only_semantic_review_required")
        if annotation.adjudication_ref:
            ref = annotation.adjudication_ref
            if ref.path not in artifacts or sha(artifacts[ref.path]) != ref.sha256:
                raise ProtocolError("missing_adjudication_evidence")
        from .temporal import validate_time_citations
        if annotation.final:validate_time_citations(record.model_input,annotation.final)
        record = DatasetRecordV2.model_validate(record.model_dump(mode="json") | {
            "label_tier": annotation.label_tier,
            "label_ref": FileRef(path=f"labels/{record.record_id}.json", sha256=sha(json_bytes(annotation))).model_dump(mode="json")})
        validate_record_annotation(record,annotation,require_accepted=annotation.status=="accepted" or not allow_pending)
        accepted.append(record)
        selected_labels.append(annotation)
    if not accepted:
        error=ProtocolError("no_publishable_records")
        error.record_id=excluded[0]["record_id"] if excluded else None
        error.report={"excluded":excluded}
        raise error
    ready=readiness(accepted,selected_labels,fixture=fixture)
    quality = audit_records(accepted, annotations=selected_labels)
    quality["readiness"]=ready
    quality.update(excluded=excluded, input_records=len(result.records),
                   origin=result.origin, fixture_release=fixture, pending_allowed=allow_pending)
    required_labels = {"relation": {"SUPPORTED", "CONTRADICTED", "INSUFFICIENT"},
                       "criterion": {"MET", "PARTIAL", "NOT_MET", "INSUFFICIENT", "NOT_APPLICABLE"}}
    missing_train_labels = {}
    for family in required_labels:
        subset = [(r, a) for r, a in zip(accepted, selected_labels, strict=True) if r.family == family and r.split == "train"]
        if subset:
            observed = {a.final.label for r, a in subset if a.final}
            missing_train_labels[family] = sorted(required_labels[family] - observed)
    quality["missing_train_labels"] = missing_train_labels
    source_maps = {r.record_id: result.source_maps[r.record_id] for r in accepted}
    records_file = [r.model_dump(mode="json") for r in accepted]
    components = {rid: "component-" + digest(members)[:24] for members in quality["component_members"] for rid in members}
    entries = [SplitEntry(record_id=r.record_id, structure_id=r.lineage.structure_id,
        component_id=components[r.record_id], ancestors=r.lineage.source_record_ids, split=r.split,
        seen_test="seen-test" in r.provenance.transformations,
        file=FileRef(path=f"inputs/{r.record_id}.json", sha256=sha(json_bytes(r.model_input)))) for r in accepted]
    split = SplitManifest(id="split-" + digest([e.model_dump(mode="json") for e in entries])[:24], entries=tuple(entries),
                          independent_structure_count=quality["structures"], test_opened=False)
    with immutable_directory(target) as root:
        for record, annotation in zip(accepted, selected_labels, strict=True):
            write_new(root / f"inputs/{record.record_id}.json", record.model_input)
            write_new(root / record.label_ref.path, annotation)
            write_new(root / f"origins/{record.record_id}.json",origins[record.record_id])
        needed_passes = {f"labels/passes/{p.id}.json" for a in selected_labels for p in a.passes}
        if needed_passes - artifacts.keys():
            raise ProtocolError("missing_annotation_attempt_evidence")
        for path in sorted(needed_passes):
            raw = artifacts[path]
            ref = FileRef(path=path, sha256=sha(raw))
            if not ref.path.startswith("labels/passes/"):
                raise ProtocolError("annotation_artifact_path_forbidden")
            dest = root / ref.path
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("xb") as handle:
                handle.write(raw)
        write_new(root / "records.json", records_file)
        # Safe metadata-only projection. No model_input, raw label, reason or
        # acceptable sets are included. Consumers never need records.json.
        metadata={}
        for r,a in zip(accepted,selected_labels,strict=True):
            descriptor=snapshot_by_digest[membership[r.record_id]]
            snap=DatasetSnapshotMetadata(**{k:descriptor[k] for k in DatasetSnapshotMetadata.model_fields if k!="schema_version"})
            metadata[r.record_id]=metadata_projection(r,a,capture_point=snap.capture_point,source_snapshots=(snap,)).model_dump(mode="json")
        metadata_refs={}
        for rid,value in metadata.items():
            path=f"metadata/{rid}.json";write_new(root/path,value)
            metadata_refs[rid]=FileRef(path=path,sha256=sha(json_bytes(value))).model_dump(mode="json")
        write_new(root/"record-metadata.json",{"protocol":"w07-record-metadata-index-v1","records":metadata_refs})
        write_new(root / "source-map.json", source_maps)
        write_new(root / "source-reviews.json", {r.record_id:contexts[r.record_id]["policies"] for r in accepted})
        accepted_ids={r.record_id for r in accepted}
        snapshots=[dict(d,record_ids=sorted(set(d["record_ids"])&accepted_ids)) for d in result.source_snapshots]
        write_new(root / "source-snapshots.json",snapshots)
        write_new(root / "split-manifest.json", split)
        write_new(root / "quality-report.json", quality)
        (root / "data_card.md").write_text(
            "# expansion-v3 W07 data release\n\n"
            + ("TEST FIXTURE ONLY. No actual environment, model or human experiment.\n\n" if fixture else "Source-backed development release; not a confirmatory test release.\n\n")
            + f"Records: {len(accepted)}; source sessions: {quality['sessions']}; structures: {quality['structures']}.\n"
            + f"Families: {quality['families']}; label tiers: {quality['label_tiers']}; statuses: {quality['annotation_status']}.\n"
            + f"Excluded/quarantined: {len(excluded)}. See quality-report.json for reasons.\n\n"
            + "Only inputs/ may be given to label workers. Labels, records, source-map and reviews are evaluator-only.\n"
            + "G2v means model-reviewed labels. It does not establish independent human validity or workplace learning.\n"
            + "Lexical duplicate screening cannot prove causal structure independence. W11 review remains required.\n"
            + "No new sealed test is included. No scoring adoption is granted.\n", encoding="utf-8")
        files = {p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file()}
        manifest = {"protocol": "expansion-v3-w07-release-v4", "exporter": EXPORTER_REVISION,
            "files": files, "records": len(accepted), "fixture": fixture, "splits": quality["splits"],
            "source_set_digest":digest({"protocol":"w07-snapshot-set-v1","members":snapshots}),"source_snapshot_count":len(snapshots),"training_ready": not fixture and ready["status"]=="ready", "readiness":ready,
            "confirmatory": False,"metadata":FileRef(path="record-metadata.json",sha256=files["record-metadata.json"]).model_dump(mode="json")}
        manifest["id"] = digest(manifest)
        write_new(root / "manifest.json", manifest)
        audit_release(root,source_authority=source_authority,label_only_authority=label_only_authority)
    return manifest


def audit_release(root,*,source_authority=None,label_only_authority=None):
    root = Path(root)
    manifest = read_json(root / "manifest.json")
    if manifest.get("protocol") != "expansion-v3-w07-release-v4":
        raise ProtocolError("release_raw_evidence_revalidation_required")
    if manifest["id"] != digest({k: v for k, v in manifest.items() if k != "id"}):
        raise ProtocolError("release_manifest_drift")
    if manifest.get("splits", {}).get("test", 0):
        raise ProtocolError("sealed_release_requires_integrator", status=403)
    files = manifest["files"]
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p.name != "manifest.json"}
    if actual != set(files):
        raise ProtocolError("release_member_set_mismatch")
    for name, expected in files.items():
        read_file(root, FileRef(path=name, sha256=expected))
    rows = [DatasetRecordV2.model_validate(x) for x in read_json(root / "records.json")]
    if manifest["fixture"] and any(r.bucket!="fixture" for r in rows):raise ProtocolError("fixture_release_requires_fixture_bucket")
    if not manifest["fixture"] and any(r.bucket=="fixture" for r in rows):raise ProtocolError("fixture_cannot_publish_as_real")
    if any(r.split == "test" for r in rows):
        raise ProtocolError("sealed_release_requires_integrator", status=403)
    labels = [AnnotationV2.model_validate_json(read_file(root, r.label_ref)) for r in rows]
    split = SplitManifest.model_validate(read_json(root / "split-manifest.json"))
    entries = {e.record_id: e for e in split.entries}
    if entries.keys() != {r.record_id for r in rows}:
        raise ProtocolError("split_record_mismatch")
    for record in rows:
        entry = entries[record.record_id]
        if entry.split != record.split or entry.structure_id != record.lineage.structure_id:
            raise ProtocolError("split_identity_mismatch")
        if read_file(root, entry.file) != json_bytes(record.model_input):
            raise ProtocolError("model_input_file_mismatch")
    metadata=read_json(root/"record-metadata.json")
    if metadata.get("protocol")!="w07-record-metadata-index-v1" or set(metadata.get("records",{}))!={r.record_id for r in rows}:raise ProtocolError("metadata_identity_mismatch")
    policies = read_json(root / "source-reviews.json")
    snapshots=read_json(root/"source-snapshots.json")
    if manifest["source_set_digest"]!=digest({"protocol":"w07-snapshot-set-v1","members":snapshots}):raise ProtocolError("release_source_set_mismatch")
    if manifest["source_snapshot_count"]!=len(snapshots):raise ProtocolError("release_source_count_mismatch")
    source_maps=read_json(root/"source-map.json")
    capture=ExportResult(tuple(rows),tuple(labels),source_maps,(),snapshots[0]["snapshot_digest"] if len(snapshots)==1 else None,
                         "fixture" if manifest["fixture"] else "mixed",tuple(snapshots))
    validate_source_membership(capture)
    membership=validate_source_membership(capture);snapshot_by_digest={x["snapshot_digest"]:x for x in snapshots}
    for record,annotation in zip(rows,labels,strict=True):
        validate_record_annotation(record,annotation,require_accepted=annotation.status=="accepted")
        descriptor=snapshot_by_digest[membership[record.record_id]]
        snap=DatasetSnapshotMetadata(**{k:descriptor[k] for k in DatasetSnapshotMetadata.model_fields if k!="schema_version"})
        expected=metadata_projection(record,annotation,capture_point=snap.capture_point,source_snapshots=(snap,))
        meta_ref=FileRef.model_validate(metadata["records"][record.record_id])
        if files.get(meta_ref.path)!=meta_ref.sha256:raise ProtocolError("metadata_hash_mismatch")
        origin_name=f"origins/{record.record_id}.json"
        if origin_name not in files:raise ProtocolError("source_origin_binding_missing")
        if read_json(root/origin_name)!=binding(record,descriptor):raise ProtocolError("source_origin_binding_mismatch")
        if not manifest['fixture']:
            if source_authority is None or source_authority(record,descriptor,tuple(record.provenance.actual_sources))!=binding(record,descriptor):
                raise ProtocolError('authoritative_source_reader_required')
            if annotation.final and not annotation.final.evidence_evaluable and annotation.label_tier!='G0' and (label_only_authority is None or label_only_authority(record,annotation) is not True):
                raise ProtocolError('label_only_semantic_review_required')
        actual=DatasetMetadataV2.model_validate_json(read_file(root,meta_ref))
        if actual!=expected:raise ProtocolError("metadata_record_mismatch")
    pass_paths = {f"labels/passes/{p.id}.json" for a in labels for p in a.passes}
    if pass_paths != {name for name in files if name.startswith("labels/passes/")}:
        raise ProtocolError("annotation_artifact_set_mismatch")
    artifacts = {name: read_file(root, FileRef(path=name, sha256=files[name])) for name in pass_paths}
    for record, annotation in zip(rows, labels, strict=True):
        reason = source_policy_error(record, policies.get(record.record_id,{}))
        if reason:
            raise ProtocolError(reason, status=403)
        verify_annotation_artifacts(record, annotation, artifacts)
        from .temporal import validate_time_citations
        if annotation.final:validate_time_citations(record.model_input,annotation.final)
        if annotation.adjudication_ref:
            read_file(root, annotation.adjudication_ref)
    report = audit_records(rows, annotations=labels)
    ready=readiness(rows,labels,fixture=manifest['fixture'])
    if manifest.get('readiness')!=ready or manifest.get('training_ready')!=(not manifest['fixture'] and ready['status']=='ready'):
        raise ProtocolError('training_readiness_mismatch')
    report['readiness']=ready
    if report["records"] != manifest["records"]:
        raise ProtocolError("release_count_mismatch")
    return report


def publish_exports(target,contributions,*,fixture=False,allow_pending=False,source_authority=None,label_only_authority=None):
    """Public multi-export publishing API. Each source retains its own root/reviews.

    contributions: {export: ExportResult, source_root: Path, policies: mapping,
    annotations?: iterable, annotation_artifacts?: path->bytes}. Nothing is
    inferred from the first source and colliding artifact bytes are rejected.
    """
    contributions=list(contributions)
    result=aggregate_exports(c["export"] for c in contributions)
    contexts={};annotations=[];artifacts={}
    for contribution in contributions:
        exported=contribution["export"]
        ids={r.record_id for r in exported.records}
        labels=list(contribution.get("annotations",exported.annotations))
        if {a.record_id for a in labels}-ids:raise ProtocolError("foreign_annotation_contribution")
        annotations.extend(labels)
        for rid in ids:contexts[rid]={"root":contribution["source_root"],"policies":contribution["policies"]}
        for name,raw in contribution.get("annotation_artifacts",{}).items():
            if name in artifacts and artifacts[name]!=raw:raise ProtocolError("annotation_artifact_collision")
            artifacts[name]=raw
    return publish_release(target,result,source_root=None,policies=None,source_contexts=contexts,
                           annotations=annotations,annotation_artifacts=artifacts,fixture=fixture,allow_pending=allow_pending,source_authority=source_authority,label_only_authority=label_only_authority)
