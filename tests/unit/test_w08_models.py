"""Explicit synthetic pipeline data. No W07 release, W11 structure or model quality claim."""
from dataclasses import replace
from pathlib import Path
import json
import numpy as np
import pytest

from career_lab.contracts.v2.core import FileRef,SourceIdentity,EvidenceRefV2,VersionPoint,Executor,digest,ProtocolError
from career_lab.contracts.v2.evaluation import EvidencePackageV2,CandidateEvidenceV2
from career_lab.contracts.v2.data import RelationInput,CriterionInput,AnnotationDecision,AnnotationV2,SplitEntry,SplitManifest,Lineage,Provenance,DatasetRecordV2,DatasetSnapshotMetadata,metadata_projection
from career_lab.models.v3.core import Example,LABELS,Prediction
from career_lab.models.v3.linear import LinearCandidate,ConstantCandidate
from career_lab.models.v3.encoder import AttentionEncoder,array_digest
from career_lab.models.v3.bundle import save_bundle,load_bundle,json_bytes,sha
from career_lab.models.v3.ensemble import select_alpha,FusionCandidate,blend,reconcile_advice
from career_lab.experiments.v3.training.metrics import grade,summarize,paired_cluster_delta
from career_lab.experiments.v3.training.data import ReleaseReader
from career_lab.experiments.v3.training.reward import reward,completion_mask,masked_cross_entropy,reference_policy


def examples(split="train",n=2,task="relation"):
    result=[]
    for repetition in range(n):
        for index,label in enumerate(LABELS[task]):
            rid=f"{split}-{task}-{repetition}-{index}"
            seq=VersionPoint(business_seq=2,workspace_revision=1,storage_revision=3)
            refs=[EvidenceRefV2(session_id="synthetic-session-"+rid,kind="document",object_id=f"doc-{i}",version=1,observed_at_seq=1) for i in (1,2)]
            field="capacity" if split=="train" else "version"
            value=(12 if index==0 else 3) if split=="train" else (2 if index==0 else 1)
            claim="capacity >= 8" if split=="train" else "version == 2"
            body={"schema_version":2,"item_id":rid,"task_type":task,"criterion":"fixture-criterion" if task=="criterion" else None,
                "claim":claim,"subjects":[refs[0].model_dump(mode="json")],"purpose":"synthetic pipeline check",
                "as_of":seq.model_dump(mode="json"),"applicability":"not_applicable" if label=="NOT_APPLICABLE" else "applicable",
                "candidate_evidence":[CandidateEvidenceV2(id="e1",ref=refs[0],text=json.dumps({"budget" if label=="INSUFFICIENT" else field:value})).model_dump(mode="json"),
                    CandidateEvidenceV2(id="e2",ref=refs[1],text=f"{split} discussion note {repetition} unrelated").model_dump(mode="json")],
                "rule_context":{"evidence_time_context":{"policy":"historical-evidence-time-v1","status":"known","reference_seq":2,"validity_known_ids":["e1","e2"]}},"rule_bound":None,"completeness":"complete","dropped_refs":[],"missing_refs":[]}
            package=EvidencePackageV2(**body,input_hash=digest(body));item=RelationInput(evidence=package) if task=="relation" else CriterionInput(evidence=package)
            empty=label in {"INSUFFICIENT","NOT_APPLICABLE"}
            final=AnnotationDecision(task_type=task,label=label,applicability=package.applicability,evidence_ids=() if empty else ("e1",),
                acceptable_evidence_sets=((),) if empty else (("e1",),),evidence_evaluable=True,missing_reason="fixture missing capacity" if empty else None)
            annotation=AnnotationV2(record_id=rid,annotation_version="synthetic-unit-v1",input_hash=digest(item),label_tier="G0",status="accepted",
                passes=(),final=final,verifier_id="synthetic-fixture-labels-no-workplace-truth")
            result.append(Example(rid,item,annotation,split,f"synthetic-{split}",f"synthetic-{split}-root-{repetition}","en","fixture",True))
    return result


def release_fixture(root):
    root=Path(root);root.mkdir(parents=True)
    rows=examples("train")+examples("dev",1)+examples("test",1)
    files={};entries=[];metadata={}
    for row in rows:
        input_path=f"inputs/{row.record_id}.json";label_path=f"labels/{row.record_id}.json"
        for name,value in [(input_path,row.item),(label_path,row.annotation)]:
            p=root/name;p.parent.mkdir(exist_ok=True);p.write_bytes(json_bytes(value));files[name]=sha(p.read_bytes())
        lineage=Lineage(structure_id=row.structure_id,component_id=row.component_id,session_id="synthetic-session-"+row.record_id)
        provenance=Provenance(command="W08 schema fixture only",source=SourceIdentity(base_commit="a"*40,source_digest=digest("schema-fixture-runtime")),
            executor=Executor(id="unit-fixture",kind="system"),actual_sources=(FileRef(path="fixture-source.json",sha256=digest(row.record_id)),),
            transformations=("fixture:not-business-run",),captured_at="2026-10-07T00:00:00Z")
        record=DatasetRecordV2(record_id=row.record_id,input_hash=row.annotation.input_hash,family=row.item.task_type,
            label_tier=row.annotation.label_tier,bucket="fixture",language=row.language,lineage=lineage,split=row.split,provenance=provenance,
            model_input=row.item,label_ref=FileRef(path=label_path,sha256=files[label_path]))
        snapshot=DatasetSnapshotMetadata(snapshot_digest=digest(row.record_id),source_digest=provenance.source.source_digest,
            session_id=lineage.session_id,capture_point=row.item.evidence.as_of,origin="fixture")
        meta=metadata_projection(record,row.annotation,capture_point=snapshot.capture_point,source_snapshots=(snapshot,)).model_dump(mode="json")
        meta_path=f"metadata/{row.record_id}.json";(root/meta_path).parent.mkdir(exist_ok=True);(root/meta_path).write_bytes(json_bytes(meta));files[meta_path]=sha((root/meta_path).read_bytes())
        metadata[row.record_id]=FileRef(path=meta_path,sha256=files[meta_path]).model_dump(mode="json")
        entries.append(SplitEntry(record_id=row.record_id,structure_id=row.structure_id,component_id=row.component_id,split=row.split,file=FileRef(path=input_path,sha256=files[input_path])))
    split=SplitManifest(id="synthetic-split",entries=tuple(entries),independent_structure_count=3)
    (root/"split-manifest.json").write_bytes(json_bytes(split));files["split-manifest.json"]=sha((root/"split-manifest.json").read_bytes())
    (root/"records.json").write_text('DO NOT READ: global sidecar includes held-out content')
    files["records.json"]=sha((root/"records.json").read_bytes())
    (root/"record-metadata.json").write_bytes(json_bytes({"protocol":"w07-record-metadata-index-v1","records":metadata}));files["record-metadata.json"]=sha((root/"record-metadata.json").read_bytes())
    manifest={"protocol":"expansion-v3-w07-release-v3","metadata":FileRef(path="record-metadata.json",sha256=files["record-metadata.json"]).model_dump(mode="json"),"files":files,"records":len(rows),"fixture":True,"splits":{"train":6,"dev":3,"test":3}}
    manifest["id"]=digest(manifest);(root/"manifest.json").write_bytes(json_bytes(manifest))
    return FileRef(path="manifest.json",sha256=sha((root/"manifest.json").read_bytes())),FileRef(path="split-manifest.json",sha256=files["split-manifest.json"])


def test_linear_trains_real_heads_and_reload_is_identical(tmp_path):
    model=LinearCandidate();report=model.fit(examples())
    assert report["fit_seconds"]>0 and report["evidence_pairs"]==12
    release,split=release_fixture(tmp_path/"data")
    source=SourceIdentity(base_commit="a"*40,source_digest=digest("fixture-source"))
    ref=save_bundle(model,tmp_path/"model",source_root=tmp_path/"data",training_release=release,split_manifest=split,source=source)
    loaded,bundle=load_bundle(tmp_path/"model",ref)
    assert bundle.mode=="advisory" and tuple(bundle.labels)==LABELS["relation"]
    for row in examples("dev",1):
        a,b=model.predict(row.item),loaded.predict(row.item)
        np.testing.assert_allclose(a.probabilities,b.probabilities,atol=1e-12)
        assert a.evidence_ids==b.evidence_ids and b.as_dict()["affects_score"] is False


@pytest.mark.parametrize("variant",["pack","pair"])
def test_contextual_encoder_gradients_match_finite_difference(variant):
    rows=examples();model=AttentionEncoder(variant=variant,dimension=4);model.initialize(rows)
    row=rows[0];loss,grads=model.loss_and_grad(row)
    token=model.vocabulary["capacity"]
    coordinates={"embedding":(token,0),"query":(0,1),"key":(1,0),"value":(0,0),"relation":(0,1),"relation_bias":(0,),"evidence":(0,),"evidence_bias":(0,)}
    for name,index in coordinates.items():
        original=model.params[name][index];eps=1e-5
        model.params[name][index]=original+eps;plus=model.loss_and_grad(row)[0]
        model.params[name][index]=original-eps;minus=model.loss_and_grad(row)[0]
        model.params[name][index]=original
        assert grads[name][index]==pytest.approx((plus-minus)/(2*eps),rel=2e-3,abs=2e-6),(name,grads[name][index],(plus-minus)/(2*eps))


@pytest.mark.parametrize("variant",["pack","pair"])
def test_attention_real_update_mask_and_reload(tmp_path,variant):
    rows=examples();model=AttentionEncoder(variant=variant,dimension=6)
    report=model.fit(rows,epochs=3)
    assert report["before_weights"]!=report["after_weights"] and report["weight_delta_l2"]>0 and report["max_abs_gradient"]>0
    assert report["pretrained"] is False and report["post_training"] is False
    ids,groups=model.encode_inputs(rows[0].item)[0]
    z,ev,_=model._forward(ids,groups);zp,evp,_=model._forward(np.pad(ids,(0,3)),groups)
    np.testing.assert_allclose(z,zp,atol=1e-12);np.testing.assert_allclose(ev,evp,atol=1e-12)
    assert np.all(model.params["embedding"][0]==0)
    release,split=release_fixture(tmp_path/"data");source=SourceIdentity(base_commit="a"*40,source_digest=digest("synthetic"))
    ref=save_bundle(model,tmp_path/"model",source_root=tmp_path/"data",training_release=release,split_manifest=split,source=source)
    loaded,bundle=load_bundle(tmp_path/"model",ref)
    assert array_digest(loaded.params)==array_digest(model.params)
    a,b=model.predict(rows[0].item),loaded.predict(rows[0].item)
    np.testing.assert_allclose(a.probabilities,b.probabilities,atol=1e-12)
    assert a.evidence_ids==b.evidence_ids


def test_training_dev_forbidden_and_vocab_train_only():
    with pytest.raises(ProtocolError,match="partition"):
        AttentionEncoder().fit(examples("dev"))
    with pytest.raises(ProtocolError,match="partition"):
        LinearCandidate().fit(examples("dev"))
    model=AttentionEncoder(dimension=4);model.fit(examples(),epochs=1)
    assert "onlydevxyz" not in model.vocabulary
    item=examples("dev",1)[0].item
    body=item.evidence.model_dump(mode="json",exclude={"input_hash"});body["claim"]="ONLYDEVXYZ capacity >= 8";body["input_hash"]=digest(body)
    changed=RelationInput(evidence=EvidencePackageV2(**body));model.predict(changed)
    assert "onlydevxyz" not in model.vocabulary


def test_overflow_and_incomplete_input_abstain_without_silent_truncation():
    model=AttentionEncoder(dimension=4);model.fit(examples(),epochs=1)
    model.max_tokens=4;out=model.predict(examples()[0].item)
    assert out.status=="abstained" and out.reason_code=="encoder_input_truncated" and out.label is None
    item=examples()[0].item;body=item.evidence.model_dump(mode="json",exclude={"input_hash"});body["completeness"]="missing";body["input_hash"]=digest(body)
    out=model.predict(RelationInput(evidence=EvidencePackageV2(**body)))
    assert out.reason_code=="input_missing"


def test_release_loader_only_opens_requested_partition(tmp_path,monkeypatch):
    root=tmp_path/"data";release,split=release_fixture(root)
    original=Path.read_bytes
    def guarded(path,*args,**kwargs):
        assert not path.name.startswith("test-") and path.name!="records.json",f"forbidden open: {path}"
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,"read_bytes",guarded)
    reader=ReleaseReader(root,release,split,allow_fixture=True)
    train=reader.load("train")
    assert len(train)==6 and all(r.split=="train" for r in train)
    assert not any("dev-" in x["path"] or "test-" in x["path"] for x in reader.access_log)
    assert len(reader.load("dev"))==3
    with pytest.raises(ProtocolError,match="forbidden"):reader.load("test")
    with pytest.raises(ProtocolError,match="fixture"):ReleaseReader(root,release,split)


def test_task_labels_do_not_mix_and_criterion_is_not_ordinal():
    model=LinearCandidate("criterion");model.fit(examples(task="criterion"))
    out=model.predict(examples("dev",1,"criterion")[0].item)
    assert len(out.probabilities)==5 and out.task_type=="criterion"
    with pytest.raises(ProtocolError,match="task"):model.predict(examples()[0].item)
    with pytest.raises(ProtocolError,match="fusion"):blend(out,out,.5,examples("dev",1,"criterion")[0].item)


def test_evidence_alternatives_extra_refs_and_null_denominators():
    row=examples()[0]
    final=row.annotation.final.model_copy(update={"acceptable_evidence_sets":(("e1",),("e2",))})
    row=replace(row,annotation=row.annotation.model_copy(update={"final":final}))
    out=Prediction("relation",row.annotation.input_hash,"fixture","ok","SUPPORTED",(1.,0.,0.),("e2",))
    assert grade(row,out)["joint_correct"]
    extra=replace(out,evidence_ids=("e1","e2"));assert not grade(row,extra)["joint_correct"]
    wrong=replace(out,evidence_ids=("missing",));assert grade(row,wrong)["error_code"]=="prediction_invalid_reference"
    metric=summarize([grade(row,out)],"relation")
    assert metric["macro_f1"]==pytest.approx(1/3) and metric["false_pass"]["rate"] is None
    assert len(metric["per_class"])==3
    noev=replace(row,annotation=row.annotation.model_copy(update={"final":final.model_copy(update={"evidence_evaluable":False})}))
    assert grade(noev,out)["joint_correct"] is None


def test_fusion_endpoint_no_gain_and_pairing_identity():
    rows=examples();model=LinearCandidate();model.fit(rows)
    dev=[replace(r,split="dev") for r in rows]  # Selector tie-mechanism fixture, not an independent validation claim.
    report=select_alpha(dev,model,model)
    assert report["alpha"]==0 and report["endpoint_selected"] and not report["fusion_gain_observed"]
    graded=[grade(r,model.predict(r.item)) for r in rows]
    assert paired_cluster_delta(graded,graded)["delta"]==0
    altered=[dict(graded[0],input_hash="changed"),*graded[1:]]
    with pytest.raises(ProtocolError,match="paired"):paired_cluster_delta(graded,altered)


def test_reward_table_and_completion_mask():
    row=examples()[0];out=Prediction("relation",row.annotation.input_hash,"fixture","ok","SUPPORTED",(1.,0.,0.),("e1",))
    assert reward(row,out)["total"]==1
    assert reward(row,replace(out,evidence_ids=("e1","e2")))["total"]==pytest.approx(.9)
    assert reward(row,replace(out,label="CONTRADICTED",probabilities=(0.,1.,0.)))["total"]==-.5
    assert reward(row,replace(out,evidence_ids=("missing",)))["total"]==-1
    noev=replace(row,annotation=row.annotation.model_copy(update={"final":row.annotation.final.model_copy(update={"evidence_evaluable":False})}))
    assert reward(noev,out)["total"]==.7
    with pytest.raises(ProtocolError,match="train"):reward(replace(row,split="dev"),out)
    mask=completion_mask([2,1],[4,3],5)
    assert mask.tolist()==[[False,False,True,True,False],[False,True,True,False,False]]
    logits=np.zeros((2,5,3));targets=np.zeros((2,5),dtype=int)
    before=masked_cross_entropy(logits,targets,mask);logits[~mask]=100
    assert masked_cross_entropy(logits,targets,mask)==before


@pytest.mark.parametrize("values",[(.1,.1,.1),(float('nan'),0.,1.),(-.1,.1,1.),(1.,0.)])
def test_probabilities_reject_unscaled_confidence_and_wrong_shape(values):
    from career_lab.models.v3.core import probabilities
    with pytest.raises(ProtocolError):probabilities(values,"relation")


def test_probability_label_order_and_mixed_task_predictions_rejected():
    row=examples()[0]
    p=Prediction("relation",row.annotation.input_hash,"x","ok","SUPPORTED",(0.,1.,0.),("e1",))
    assert grade(row,p)["error_code"]=="prediction_probability_order_mismatch"
    p=replace(p,task_type="criterion",label="MET",probabilities=(1.,0.,0.,0.,0.))
    assert grade(row,p)["error_code"]=="prediction_input_identity_mismatch"


def test_non_evaluable_evidence_excluded_even_when_prediction_fails():
    row=examples()[0];row=replace(row,annotation=row.annotation.model_copy(update={"final":row.annotation.final.model_copy(update={"evidence_evaluable":False})}))
    output=Prediction("relation",row.annotation.input_hash,"x","failed",None,None,reason_code="timeout")
    r=grade(row,output);m=summarize([r],"relation")
    assert r["joint_correct"] is None and r["evidence_f1"] is None
    assert m["joint_denominator"]==0 and m["joint_correctness"] is None and m["accuracy"]==0
    assert m["infrastructure_failures"]==1 and m["coverage"]==0
    assert reward(row,output)["total"]==-1


def test_temporally_invalid_reference_cannot_be_joint_correct():
    row=examples()[0];body=row.item.evidence.model_dump(mode="json",exclude={"input_hash"})
    body["candidate_evidence"][0]["ref"]["valid_until_seq"]=2;body["input_hash"]=digest(body)
    item=RelationInput(evidence=EvidencePackageV2(**body))
    final=row.annotation.final.model_copy(update={"evidence_ids":("e2",),"acceptable_evidence_sets":(("e2",),)})
    row=replace(row,item=item,annotation=row.annotation.model_copy(update={"input_hash":digest(item),"final":final}))
    out=Prediction("relation",digest(item),"x","ok","SUPPORTED",(1.,0.,0.),("e1",))
    graded=grade(row,out)
    assert graded["label_correct"] and not graded["joint_correct"] and graded["error_code"]=="invalid_evidence_time"
    assert summarize([graded],"relation")["invalid_references"]==1 and reward(row,out)["total"]==-1


def test_rule_bound_does_not_mutate_input_or_rank_na():
    row=examples(task="criterion")[0];body=row.item.evidence.model_dump(mode="json",exclude={"input_hash"})
    body["rule_bound"]={"schema_version":2,"lower":"NOT_MET","upper":"NOT_MET"};body["input_hash"]=digest(body)
    item=CriterionInput(evidence=EvidencePackageV2(**body));before=item.model_dump(mode="json")
    out=Prediction("criterion",digest(item),"x","ok","MET",(1.,0.,0.,0.,0.),("e1",))
    reconciled=reconcile_advice(item,out)
    assert reconciled["rule_conflict"] and reconciled["label"] is None and not reconciled["affects_score"]
    assert item.model_dump(mode="json")==before
    out=replace(out,label="NOT_APPLICABLE",probabilities=(0.,0.,0.,0.,1.))
    assert reconcile_advice(item,out)["source"]=="pending"


def test_bundle_integrity_entrypoint_and_probability_order(tmp_path):
    model=LinearCandidate();model.fit(examples())
    release,split=release_fixture(tmp_path/"data");source=SourceIdentity(base_commit="a"*40,source_digest=digest("fixture"))
    ref=save_bundle(model,tmp_path/"model",source_root=tmp_path/"data",training_release=release,split_manifest=split,source=source)
    path=tmp_path/"model/model-bundle.json";raw=json.loads(path.read_text())
    raw["inference_entrypoint"]="os:system";path.write_bytes(json_bytes(raw))
    with pytest.raises(ProtocolError,match="entrypoint"):
        load_bundle(tmp_path/"model",FileRef(path="model-bundle.json",sha256=sha(path.read_bytes())))
    raw["inference_entrypoint"]="career_lab.models.v3.linear:LinearCandidate";raw["labels"].reverse();path.write_bytes(json_bytes(raw))
    with pytest.raises(ProtocolError,match="label"):
        load_bundle(tmp_path/"model",FileRef(path="model-bundle.json",sha256=sha(path.read_bytes())))


def test_source_label_drift_and_unaccepted_labels_stop_reader(tmp_path):
    root=tmp_path/"data";release,split=release_fixture(root)
    target=next((root/"labels").glob("train-*.json"));target.write_text('{}')
    reader=ReleaseReader(root,release,split,allow_fixture=True)
    with pytest.raises(ProtocolError,match="hash"):reader.load("train")
    row=examples()[0];pending=row.annotation.model_copy(update={"status":"pending","final":None})
    with pytest.raises(ProtocolError,match="unaccepted"):
        replace(row,annotation=pending).validate()


def test_formal_reader_requires_approved_six_structure_release(tmp_path):
    root=tmp_path/"data";release,split=release_fixture(root)
    data=json.loads((root/"manifest.json").read_text());data["fixture"]=False;data["id"]=digest({k:v for k,v in data.items() if k!="id"});(root/"manifest.json").write_bytes(json_bytes(data))
    actual=FileRef(path="manifest.json",sha256=sha((root/"manifest.json").read_bytes()))
    with pytest.raises(ProtocolError,match="approval"):ReleaseReader(root,actual,split)
    with pytest.raises(ProtocolError,match="structure"):ReleaseReader(root,actual,split,metadata_approval=lambda *args:None)


def test_missing_or_wrong_model_identity_is_not_a_successful_result():
    from career_lab.experiments.v3.training.pipeline import evaluate
    row=examples()[0]
    bad=Prediction("relation",row.annotation.input_hash,"","ok","SUPPORTED",(1.,0.,0.),("e1",))
    assert grade(row,bad)["error_code"]=="prediction_model_identity_required"
    class WrongRevision:
        revision="expected-model"
        def predict(self,item):return replace(bad,model_revision="returned-stale-model")
    report=evaluate(WrongRevision(),[row])
    assert report["rows"][0]["error_code"]=="candidate_model_revision_mismatch"
    assert report["metrics"]["coverage"]==0
    assert "returned-stale-model" in report["predictions"][0]["raw_adapter_prediction_json"]
