"""Partition-scoped W07 release reads, with metadata and errors bound to record IDs."""
from collections import Counter
from pathlib import Path
import json

from career_lab.contracts.v2.core import FileRef,ProtocolError,digest,read_file
from career_lab.contracts.v2.data import SplitManifest,AnnotationV2,Lineage,FAMILY_TASK,require_training_split
from career_lab.models.v3.core import INPUT,Example,LABELS


class RecordReadError(ProtocolError):
    def __init__(self,record_id,partition,cause):
        self.record_id,self.partition,self.cause_code=record_id,partition,getattr(cause,"code",type(cause).__name__)
        self.report={"record_id":record_id,"partition":partition,"reason":self.cause_code,"action":"reject frozen release; repair upstream, do not silently relabel"}
        super().__init__("release_record_invalid",f"record {record_id}: {self.cause_code}")


class ReleaseReader:
    def __init__(self,root,release_ref:FileRef,split_ref:FileRef,*,metadata_approval=None,allow_fixture=False):
        self.root=Path(root);self.release_ref=release_ref;self.split_ref=split_ref;self.access_log=[];self.excluded=[]
        self.manifest=json.loads(self._read(release_ref,"metadata-index"))
        if self.manifest.get("id")!=digest({k:v for k,v in self.manifest.items() if k!="id"}):raise ProtocolError("release_manifest_drift")
        if self.manifest.get("protocol")!="expansion-v3-w07-release-v3":raise ProtocolError("unsupported_release_protocol")
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
        rows=[]
        for entry in self.split.entries:
            if entry.split!=partition:continue
            try:
                meta_ref=FileRef.model_validate(self.metadata[entry.record_id])
                if self.manifest["files"].get(meta_ref.path)!=meta_ref.sha256:raise ProtocolError("metadata_file_hash_mismatch")
                metadata=json.loads(self._read(meta_ref,partition+":metadata"))
                if metadata["record_id"]!=entry.record_id:raise ProtocolError("metadata_record_identity_mismatch")
                if not isinstance(metadata.get("language"),str) or not metadata["language"].strip():raise ProtocolError("metadata_language_invalid")
                if metadata.get("bucket") not in {"fixture","env_run","human_session","public_aux","business_synth"}:raise ProtocolError("metadata_bucket_invalid")
                lineage=Lineage.model_validate(metadata["lineage"])
                if lineage.structure_id!=entry.structure_id:raise ProtocolError("metadata_structure_mismatch")
                if self.fixture and metadata["bucket"]!="fixture":raise ProtocolError("fixture_bucket_identity_mismatch")
                if not self.fixture and metadata["bucket"]=="fixture":raise ProtocolError("fixture_research_mix_forbidden")
                if self.manifest["files"].get(entry.file.path)!=entry.file.sha256:raise ProtocolError("release_input_hash_mismatch")
                item=INPUT.validate_json(self._read(entry.file,partition+":input"))
                if FAMILY_TASK.get(metadata.get("family"))!=item.task_type:raise ProtocolError("metadata_family_mismatch")
                if metadata["input_hash"]!=digest(item):raise ProtocolError("metadata_input_hash_mismatch")
                if item.task_type!=task_type:
                    self.excluded.append({"record_id":entry.record_id,"task_type":item.task_type,"reason":"different_task"});continue
                name=f"labels/{entry.record_id}.json"
                if name not in self.manifest["files"]:raise ProtocolError("release_label_missing")
                annotation=AnnotationV2.model_validate_json(self._read(FileRef(path=name,sha256=self.manifest["files"][name]),partition+":label"))
                if metadata["annotation_status"]!=annotation.status or metadata["accepted_label_tier"]!=(annotation.label_tier if annotation.status=="accepted" else None):
                    raise ProtocolError("metadata_annotation_status_mismatch")
                row=Example(entry.record_id,item,annotation,partition,entry.structure_id,entry.component_id,
                            language=metadata["language"],bucket=metadata["bucket"],fixture=self.fixture)
                row.validate();rows.append(row)
            except (ValueError,KeyError,TypeError,OSError) as exc:
                error=RecordReadError(entry.record_id,partition,exc);self.excluded.append(error.report);raise error from exc
        if not rows:raise ProtocolError("empty_requested_partition")
        return rows

    def scope_report(self):
        return {"release":self.release_ref.model_dump(mode="json"),"split_manifest":self.split_ref.model_dump(mode="json"),
                "fixture":self.fixture,"declared_structure_count":self.split.independent_structure_count,
                "independence_claim":"none for synthetic fixture" if self.fixture else "requires upstream W11 approval",
                "accesses":list(self.access_log),"excluded_or_invalid_records":list(self.excluded),"test_content_opened":False,
                "metadata_scope":"only requested train/dev per-record sidecars; no mixed records.json or test metadata body"}
