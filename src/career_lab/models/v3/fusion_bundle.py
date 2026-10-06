"""Portable composite ModelBundle; only referenced component artifacts are copied."""
from pathlib import Path
import json,os,shutil,tempfile
from career_lab.contracts.v2.core import FileRef,SourceIdentity,ProtocolError,digest,read_file
from career_lab.contracts.v2.research import ModelBundle
from .ensemble import FusionCandidate

ENTRYPOINT="career_lab.models.v3.ensemble:FusionCandidate"


def load_fusion(root,bundle,config,depth):
    from .bundle import load_bundle
    if depth>1:raise ProtocolError("nested_fusion_not_supported")
    if bundle.task_type!="relation":raise ProtocolError("relation_fusion_only")
    components=[]
    for name in ("left","right"):
        descriptor=config[name];safe=FileRef(path=descriptor["root"],sha256="0"*64)
        child_root=(Path(root)/safe.path).resolve()
        if not child_root.is_relative_to(Path(root).resolve()):raise ProtocolError("component_outside_bundle")
        model,child=load_bundle(child_root,FileRef.model_validate(descriptor["manifest"]),_depth=depth+1)
        if child.inference_entrypoint==ENTRYPOINT:raise ProtocolError("nested_fusion_not_supported")
        components.append((model,child))
    left,right=components
    if left[1].training_release.sha256!=right[1].training_release.sha256 or left[1].split_manifest.sha256!=right[1].split_manifest.sha256:
        raise ProtocolError("fusion_component_data_mismatch")
    model=FusionCandidate(left[0],right[0],config["alpha"],config["evidence_threshold"])
    expected="probability_fusion:"+digest({"config":bundle.preprocessing.sha256,"weights":[w.sha256 for w in bundle.weights],"source":bundle.source.model_dump(mode="json")})
    if bundle.model_revision!=expected:raise ProtocolError("fusion_revision_mismatch")
    model.revision=bundle.model_revision
    return model,bundle


def save_fusion_bundle(target,*,left_root,left_ref,right_root,right_ref,alpha,threshold):
    from .bundle import load_bundle,write_json,json_bytes,sha
    left,lb=load_bundle(left_root,left_ref);right,rb=load_bundle(right_root,right_ref)
    if lb.task_type!="relation" or rb.task_type!="relation" or lb.training_release.sha256!=rb.training_release.sha256 or lb.split_manifest.sha256!=rb.split_manifest.sha256 or lb.source!=rb.source:
        raise ProtocolError("fusion_component_identity_mismatch")
    FusionCandidate(left,right,alpha,threshold)
    target=Path(target).absolute();target.parent.mkdir(parents=True,exist_ok=True)
    lock=target.with_name(target.name+".lock")
    try:lock.mkdir()
    except FileExistsError:raise ProtocolError("bundle_publish_busy") from None
    stage=None
    try:
        if target.exists():raise ProtocolError("immutable_bundle_exists")
        stage=Path(tempfile.mkdtemp(prefix=".fusion-",dir=target.parent));weights=[];config={"kind":"probability_fusion","preprocessing_revision":"historical-time-v1","task_type":"relation","alpha":alpha,"evidence_threshold":threshold}
        def prefixed(prefix,ref):return FileRef(path=prefix+"/"+ref.path,sha256=ref.sha256,media_type=ref.media_type)
        for name,source,ref,b in (("left",Path(left_root),left_ref,lb),("right",Path(right_root),right_ref,rb)):
            prefix="components/"+name
            refs=[ref,b.preprocessing,b.training_release,b.split_manifest,*b.weights,*b.source.dependency_locks]
            if b.source.overlay:refs.append(b.source.overlay)
            if b.inference_entrypoint==ENTRYPOINT:raise ProtocolError("nested_fusion_not_supported")
            for value in refs:
                raw=read_file(source,value);dest=stage/prefixed(prefix,value).path;dest.parent.mkdir(parents=True,exist_ok=True)
                if dest.exists() and dest.read_bytes()!=raw:raise ProtocolError("component_artifact_collision")
                if not dest.exists():dest.write_bytes(raw)
            weights.extend(prefixed(prefix,w) for w in b.weights)
            config[name]={"root":prefix,"manifest":ref.model_dump(mode="json")}
        source=SourceIdentity(base_commit=lb.source.base_commit,source_digest=lb.source.source_digest,
            overlay=prefixed("components/left",lb.source.overlay) if lb.source.overlay else None,
            dependency_locks=tuple(prefixed("components/left",r) for r in lb.source.dependency_locks))
        write_json(stage/"preprocessing.json",config);pre=FileRef(path="preprocessing.json",sha256=sha(json_bytes(config)))
        revision="probability_fusion:"+digest({"config":pre.sha256,"weights":[w.sha256 for w in weights],"source":source.model_dump(mode="json")})
        bundle=ModelBundle(id="fusion-"+digest(revision)[:24],task_type="relation",labels=lb.labels,model_revision=revision,
            tokenizer_revision="component-tokenizers-pinned",weights=tuple(weights),preprocessing=pre,inference_entrypoint=ENTRYPOINT,
            training_release=prefixed("components/left",lb.training_release),split_manifest=prefixed("components/left",lb.split_manifest),source=source)
        write_json(stage/"model-bundle.json",bundle);ref=FileRef(path="model-bundle.json",sha256=sha(json_bytes(bundle)))
        load_bundle(stage,ref);os.rename(stage,target);stage=None
        return ref
    finally:
        if stage is not None:shutil.rmtree(stage)
        lock.rmdir()
