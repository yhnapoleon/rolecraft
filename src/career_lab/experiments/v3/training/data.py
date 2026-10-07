"""Partition-scoped W07 release reads, with metadata and errors bound to record IDs."""
from collections import Counter
from pathlib import Path
import json

from career_lab.contracts.v2.core import FileRef,ProtocolError,digest,read_file
from career_lab.contracts.v2.data import SplitManifest,AnnotationV2,Lineage,FAMILY_TASK,DatasetRecordV2,DatasetMetadataV2,metadata_projection,validate_record_annotation,require_training_split
from career_lab.models.v3.core import INPUT,Example,LABELS


class RecordReadError(ProtocolError):
    def __init__(self,record_id,partition,cause):
        self.record_id,self.partition,self.cause_code=record_id,partition,getattr(cause,"code",type(cause).__name__)
        self.report={"record_id":record_id,"partition":partition,"reason":self.cause_code,"action":"reject frozen release; repair upstream, do not silently relabel"}
        super().__init__("release_record_invalid",f"record {record_id}: {self.cause_code}")


class ReleaseReader:
    def __init__(self,root,release_ref:FileRef,split_ref:FileRef,*,metadata_approval=None,allow_fixture=False,source_authority=None,label_only_authority=None):
        self.source_authority=source_authority;self.label_only_authority=label_only_authority
        self._label_only_records={}
        self.root=Path(root);self.release_ref=release_ref;self.split_ref=split_ref;self.access_log=[];self.excluded=[]
        self.manifest=json.loads(self._read(release_ref,"metadata-index"))
        if self.manifest.get("id")!=digest({k:v for k,v in self.manifest.items() if k!="id"}):raise ProtocolError("release_manifest_drift")
        if self.manifest.get("protocol")!="expansion-v3-w07-release-v4":raise ProtocolError("unsupported_release_protocol")
        if self.manifest.get("files",{}).get(split_ref.path)!=split_ref.sha256:raise ProtocolError("release_split_identity_mismatch")
        self.split=SplitManifest.model_validate_json(self._read(split_ref,"metadata-index"))
        self.fixture=bool(self.manifest.get("fixture"))
        if self.fixture:
            if not allow_fixture:raise ProtocolError("fixture_release_not_research")
        elif metadata_approval is None:raise ProtocolError("independent_release_approval_required")
        else:
            groups={s:{e.structure_id for e in self.split.entries if e.split==s} for s in ("train","dev","test")}
            if self.split.independent_structure_count<6 or any(len(groups[s])<2 for s in groups):raise ProtocolError("research_structure_release_not_ready")
            metadata_approval(self.release_ref,self.split_ref)
        if dict(Counter(e.split for e in self.split.entries))!=self.manifest.get("splits"):raise ProtocolError("release_partition_counts_mismatch")
        meta_ref=FileRef.model_validate(self.manifest["metadata"])
        if self.manifest["files"].get(meta_ref.path)!=meta_ref.sha256:raise ProtocolError("metadata_index_hash_mismatch")
        metadata=json.loads(self._read(meta_ref,"metadata-index"))
        if metadata.get("protocol")!="w07-record-metadata-index-v1" or set(metadata.get("records",{}))!={e.record_id for e in self.split.entries}:
            raise ProtocolError("metadata_index_identity_mismatch")
        self.metadata=metadata["records"]

    def _read(self,ref,purpose):
        raw=read_file(self.root,ref);self.access_log.append({"path":ref.path,"sha256":ref.sha256,"purpose":purpose});return raw

    def load(self,partition,task_type="relation"):
        if task_type not in LABELS:raise ProtocolError("unsupported_model_task")
        require_training_split(partition)
        requested=[e for e in self.split.entries if e.split==partition]
        ready=self.manifest.get('readiness',{})
        if (not self.fixture and self.manifest.get('training_ready') is not True) or ready.get('policy')!='complete-accepted-training-v1' or ready.get('status')!='ready' or ready.get('scope')!=('fixture' if self.fixture else 'development'):
            ids={e.record_id for e in requested}
            blocked=next((b for b in ready.get('blockers',[]) if b.get('record_id') in ids),None)
            if blocked is None:blocked=next((b for b in ready.get('blockers',[]) if b.get('record_id') in {e.record_id for e in self.split.entries}),None)
            rid=blocked['record_id'] if blocked else requested[0].record_id if requested else '<partition:'+partition+'>'
            error=RecordReadError(rid,partition,ProtocolError(blocked['reason'] if blocked else 'release_not_training_ready'))
            self.excluded.append(error.report);raise error
        rows=[]
        for entry in self.split.entries:
            if entry.split!=partition:continue
            try:
                meta_ref=FileRef.model_validate(self.metadata[entry.record_id])
                if self.manifest["files"].get(meta_ref.path)!=meta_ref.sha256:raise ProtocolError("metadata_file_hash_mismatch")
                metadata=DatasetMetadataV2.model_validate_json(self._read(meta_ref,partition+":metadata"))
                if metadata.record_id!=entry.record_id or metadata.split!=partition:raise ProtocolError("metadata_record_identity_mismatch")
                lineage=metadata.lineage
                if lineage.structure_id!=entry.structure_id:raise ProtocolError("metadata_structure_mismatch")
                if self.fixture and metadata.bucket!="fixture":raise ProtocolError("fixture_bucket_identity_mismatch")
                if not self.fixture and metadata.bucket=="fixture":raise ProtocolError("fixture_research_mix_forbidden")
                if len(metadata.source_snapshots)!=1 or metadata.capture_point!=metadata.source_snapshots[0].capture_point:
                    raise ProtocolError("record_snapshot_binding_required")
                if self.manifest["files"].get(entry.file.path)!=entry.file.sha256:raise ProtocolError("release_input_hash_mismatch")
                item=INPUT.validate_json(self._read(entry.file,partition+":input"))
                family=next((name for name,task in FAMILY_TASK.items() if task==item.task_type),None)
                if family is None:raise ProtocolError("input_family_unknown")
                if metadata.input_hash!=digest(item):raise ProtocolError("metadata_input_hash_mismatch")
                if item.task_type in LABELS and item.evidence.completeness!="complete":raise ProtocolError("input_"+item.evidence.completeness)
                if item.task_type!=task_type:
                    self.excluded.append({"record_id":entry.record_id,"task_type":item.task_type,"reason":"different_task"});continue
                name=f"labels/{entry.record_id}.json"
                if name not in self.manifest["files"]:raise ProtocolError("release_label_missing")
                label_ref=FileRef(path=name,sha256=self.manifest["files"][name])
                annotation=AnnotationV2.model_validate_json(self._read(label_ref,partition+":label"))
                record=DatasetRecordV2(record_id=metadata.record_id,input_hash=metadata.input_hash,family=family,
                    label_tier=metadata.requested_label_tier,bucket=metadata.bucket,language=metadata.language,lineage=metadata.lineage,
                    split=metadata.split,provenance=metadata.provenance,model_input=item,label_ref=label_ref)
                snapshot=metadata.source_snapshots[0]
                if snapshot.origin!=record.bucket:raise ProtocolError("source_origin_bucket_mismatch")
                expected_origin={'protocol':'w07-source-origin-v1','record_id':record.record_id,'origin':record.bucket,
                    'session_id':record.lineage.session_id,'lineage_hash':digest(record.lineage),
                    'snapshot_digest':snapshot.snapshot_digest,'source_digest':record.provenance.source.source_digest,
                    'source_files':[x.model_dump(mode='json') for x in record.provenance.actual_sources]}
                origin_path=f"origins/{record.record_id}.json"
                if origin_path not in self.manifest['files']:raise ProtocolError('source_origin_binding_missing')
                origin=json.loads(self._read(FileRef(path=origin_path,sha256=self.manifest['files'][origin_path]),partition+':origin'))
                if origin!=expected_origin:raise ProtocolError('source_origin_binding_mismatch')
                if not self.fixture:
                    if self.source_authority is None or self.source_authority(metadata,tuple(record.provenance.actual_sources))!=expected_origin:
                        raise ProtocolError('independent_source_authority_required')
                validate_record_annotation(record,annotation,require_accepted=True)
                label_only=None
                if not annotation.final.evidence_evaluable:
                    if not self.fixture and annotation.label_tier!='G0' and (self.label_only_authority is None or self.label_only_authority(record,annotation) is not True):
                        raise ProtocolError('label_only_semantic_review_required')
                    label_only={'release_sha256':self.release_ref.sha256,'partition':partition,'record_id':record.record_id,'evidence_training':False,'evidence_metrics':False,
                        'label_basis':'fixture only; no semantic truth claim' if self.fixture else 'upstream numeric verifier' if annotation.label_tier=='G0' else 'independent semantic review'}
                projected=metadata_projection(record,annotation,capture_point=metadata.capture_point,source_snapshots=metadata.source_snapshots)
                if projected!=metadata:raise ProtocolError("metadata_annotation_status_mismatch")
                row=Example(entry.record_id,item,annotation,partition,entry.structure_id,entry.component_id,
                            language=metadata.language,bucket=metadata.bucket,fixture=self.fixture)
                row.validate()
                if label_only is not None:
                    self._label_only_records[(self.release_ref.sha256,partition,record.record_id)]=label_only
                rows.append(row)
            except (ValueError,KeyError,TypeError,OSError) as exc:
                error=RecordReadError(entry.record_id,partition,exc);self.excluded.append(error.report);raise error from exc
        if not rows:raise ProtocolError("empty_requested_partition")
        return rows

    @property
    def label_only_records(self):
        return [dict(row) for row in self._label_only_records.values()]

    def scope_report(self):
        return {"release":self.release_ref.model_dump(mode="json"),"split_manifest":self.split_ref.model_dump(mode="json"),
                "fixture":self.fixture,"declared_structure_count":self.split.independent_structure_count,
                "independence_claim":"none for synthetic fixture" if self.fixture else "requires upstream W11 approval",
                "label_only_records":list(self.label_only_records),"accesses":list(self.access_log),"excluded_or_invalid_records":list(self.excluded),"test_content_opened":False,
                "metadata_scope":"only requested train/dev per-record sidecars; no mixed records.json or test metadata body"}
