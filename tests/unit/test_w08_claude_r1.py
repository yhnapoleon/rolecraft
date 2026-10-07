"""Selection, time, metadata and failure regressions; no formal-model claims."""
from dataclasses import replace
import json
import numpy as np
import pytest
from test_w08_models import examples,release_fixture
from career_lab.contracts.v2.core import ProtocolError,digest,FileRef
from career_lab.contracts.v2.evaluation import EvidencePackageV2
from career_lab.contracts.v2.data import RelationInput
from career_lab.models.v3.core import Prediction,LABELS
from career_lab.models.v3.encoder import AttentionEncoder
from career_lab.models.v3.ensemble import select_alpha
from career_lab.models.v3.huggingface import verify_local_checkpoint
from career_lab.models.v3.bundle import json_bytes,sha
from career_lab.experiments.v3.training.selection import choose_dev,SelectionPolicy
from career_lab.experiments.v3.training.data import ReleaseReader,RecordReadError
from career_lab.experiments.v3.training.metrics import grade,summarize
from career_lab.experiments.v3.training.pipeline import evaluate,EvaluationProgrammingError
from career_lab.experiments.v3.training.reward import reference_policy


def test_joint_primary_rejects_high_macro_all_reference_baseline():
    candidates=[{"id":"all-reference","metrics":{"joint_correctness":0.,"joint_denominator":3,"coverage":1.,"macro_f1":1.}},
                {"id":"evidence-aware","metrics":{"joint_correctness":1/3,"joint_denominator":3,"coverage":1.,"macro_f1":.5}}]
    assert choose_dev(candidates)["selected"]=="evidence-aware"
    assert choose_dev(candidates[:1])["selected"] is None
    assert choose_dev([{"id":"not-evaluable","metrics":{"joint_correctness":None,"joint_denominator":0,"coverage":1.,"macro_f1":1.}}])["selected"] is None


def test_fusion_has_positive_joint_gain_case():
    rows=examples("dev",1)[:2]
    class Stub:
        def __init__(self,name,values):self.revision=name;self.values=values
        def predict(self,item):
            probs=self.values[item.evidence.item_id]
            return Prediction("relation",digest(item),self.revision,"ok",LABELS["relation"][int(np.argmax(probs))],probs,("e1",),(("e1",1.),("e2",0.)))
    a=Stub("left",{rows[0].item.evidence.item_id:(.8,.19,.01),rows[1].item.evidence.item_id:(.51,.48,.01)})
    b=Stub("right",{rows[0].item.evidence.item_id:(.48,.51,.01),rows[1].item.evidence.item_id:(.19,.8,.01)})
    choice=select_alpha(rows,a,b)
    assert 0<choice["alpha"]<1 and choice["fusion_gain_observed"]
    assert choice["policy"]["priority"][0]=="joint_correctness"
    assert choice["evidence_threshold"] in choice["policy"]["evidence_thresholds"]


def test_historical_gold_is_legal_current_stale_gold_is_rejected():
    row=examples()[0];data=row.item.evidence.model_dump(mode="json",exclude={"input_hash"})
    data["candidate_evidence"][0]["ref"]["valid_until_seq"]=3
    data["input_hash"]=digest(data);past=RelationInput(evidence=EvidencePackageV2(**data))
    history=replace(row,item=past,annotation=row.annotation.model_copy(update={"input_hash":digest(past)}))
    output=Prediction("relation",digest(past),"unit","ok","SUPPORTED",(1.,0.,0.),("e1",))
    assert grade(history,output)["joint_correct"]
    data.pop("input_hash");data["as_of"]["business_seq"]=4;data["rule_context"]["evidence_time_context"]["reference_seq"]=4;data["input_hash"]=digest(data)
    current=RelationInput(evidence=EvidencePackageV2(**data));bad=replace(row,item=current,annotation=row.annotation.model_copy(update={"input_hash":digest(current)}))
    with pytest.raises(ProtocolError,match="inapplicable") as exc:bad.validate()
    assert exc.value.record_id==row.record_id
    data.pop("input_hash");data["rule_context"]["evidence_time_context"]["status"]="undetermined";data["input_hash"]=digest(data)
    unknown=RelationInput(evidence=EvidencePackageV2(**data))
    with pytest.raises(ProtocolError,match="undetermined"):
        replace(row,item=unknown,annotation=row.annotation.model_copy(update={"input_hash":digest(unknown)})).validate()


def test_metadata_slices_and_record_identity_errors(tmp_path):
    root=tmp_path/"data";release,split=release_fixture(root)
    reader=ReleaseReader(root,release,split,allow_fixture=True);rows=reader.load("train")
    assert all(r.bucket=="fixture" and r.language=="en" for r in rows)
    assert not any(x["path"].startswith("metadata/test-") for x in reader.access_log)
    label_path=root/f"labels/{rows[0].record_id}.json";label_path.write_text('{}')
    with pytest.raises(RecordReadError) as exc:reader.load("train")
    assert exc.value.record_id==rows[0].record_id and exc.value.report["reason"]=="file_hash_mismatch"


def test_programming_bug_not_swallowed_as_infrastructure():
    class Broken:
        revision="broken-test-double"
        def predict(self,item):raise KeyError("program bug")
    row=examples()[0]
    with pytest.raises(EvaluationProgrammingError) as exc:evaluate(Broken(),[row])
    assert exc.value.record_id==row.record_id and exc.value.report["kind"]=="programming_error"


def test_overlong_training_record_is_counted_and_excluded():
    rows=examples();r=rows[0];data=r.item.evidence.model_dump(mode="json",exclude={"input_hash"})
    data["candidate_evidence"][1]["text"]="longonlytoken "*1000;data["input_hash"]=digest(data)
    item=RelationInput(evidence=EvidencePackageV2(**data));rid=r.record_id+"-long"
    oversized=replace(r,record_id=rid,item=item,annotation=r.annotation.model_copy(update={"record_id":rid,"input_hash":digest(item)}))
    model=AttentionEncoder(dimension=4,max_tokens=128);report=model.fit([*rows,oversized],epochs=1)
    assert report["input_train_records"]==7 and report["train_records"]==6
    assert report["excluded_records"][0]["record_id"]==rid
    assert "longonlytoken" not in model.vocabulary
    assert model.predict(item).status=="abstained"


def test_mean_logit_pair_gradient_and_configuration():
    rows=examples();model=AttentionEncoder(variant="pair",aggregation="mean_logits",dimension=4);model.initialize(rows)
    loss,grads=model.loss_and_grad(rows[0]);eps=1e-5;key="relation";index=(0,1);original=model.params[key][index]
    model.params[key][index]=original+eps;plus=model.loss_and_grad(rows[0])[0]
    model.params[key][index]=original-eps;minus=model.loss_and_grad(rows[0])[0];model.params[key][index]=original
    assert grads[key][index]==pytest.approx((plus-minus)/(2*eps),rel=2e-3,abs=2e-6)
    assert model.fit(rows,epochs=1)["aggregation"]=="mean_logits"


def test_supported_to_insufficient_is_visible_false_rejection():
    row=examples()[0];p=Prediction("relation",row.annotation.input_hash,"unit","ok","INSUFFICIENT",(0.,0.,1.),())
    metrics=summarize([grade(row,p)],"relation")
    assert metrics["false_deduction"]["rate"]==1
    assert metrics["supported_contradicted"]["rate"]==0 and metrics["supported_insufficient"]["rate"]==1


def test_local_checkpoint_manifest_binds_actual_files_not_directory_name(tmp_path):
    (tmp_path/"config.json").write_text('{}');(tmp_path/"model.safetensors").write_bytes(b'unit file hash fixture, not real weights')
    revision="a"*40
    data={"protocol":"w08-hf-local-files-v1","source_revision":revision,"files":{name:sha((tmp_path/name).read_bytes()) for name in ["config.json","model.safetensors"]}}
    (tmp_path/"local.json").write_bytes(json_bytes(data));ref=FileRef(path="local.json",sha256=sha((tmp_path/"local.json").read_bytes()))
    assert verify_local_checkpoint(tmp_path,revision,ref)["verified_files_digest"]
    with pytest.raises(ProtocolError,match="revision"):verify_local_checkpoint(tmp_path,"b"*40,ref)
    (tmp_path/"model.safetensors").write_bytes(b'other bytes')
    with pytest.raises(ProtocolError,match="hash"):verify_local_checkpoint(tmp_path,revision,ref)


def test_reference_identity_is_weight_bound(tmp_path):
    for name in ["base","adapter"]:(tmp_path/name).write_text(name)
    a=FileRef(path="base",sha256=sha((tmp_path/"base").read_bytes()));b=FileRef(path="adapter",sha256=sha((tmp_path/"adapter").read_bytes()))
    reference=reference_policy(tmp_path,(a,),(b,))
    assert reference["sft_identity"]==digest({"base":[a.model_dump(mode="json")],"active_adapter":[b.model_dump(mode="json")]})
    with pytest.raises(ProtocolError,match="identity"):reference_policy(tmp_path,(a,),(b,),sft_identity="arbitrary-name")
