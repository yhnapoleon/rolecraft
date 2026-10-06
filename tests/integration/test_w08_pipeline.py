"""Subprocess and artifact integration on explicitly synthetic, known fixtures."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import numpy as np
import pytest

# Permit isolated integration invocation, independent of pytest collection order.
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'unit'))
from test_w08_models import examples,release_fixture
from career_lab.contracts.v2.core import FileRef,SourceIdentity,Budget,ProtocolError,digest
from career_lab.contracts.v2.data import TestCampaign as Campaign,CampaignCandidate
from career_lab.models.v3.bundle import sha,json_bytes,save_bundle,load_bundle
from career_lab.models.v3.linear import LinearCandidate
from career_lab.models.v3.legacy import LegacyMLP
from career_lab.experiments.v3.training.freeze import freeze_selection,verify_freeze,validate_campaign
from career_lab.experiments.v3.training.reward import reference_policy

WORKSPACE=Path(__file__).resolve().parents[2]


def command(*args):
    return subprocess.run([sys.executable,"-m","career_lab.experiments.v3.training",*map(str,args)],capture_output=True,text=True)


def test_pipeline_cli_trains_reloads_predicts_freezes_and_moves(tmp_path):
    release,split=release_fixture(tmp_path/"data")
    output=tmp_path/"experiment"
    result=command("train-v3","--release-root",tmp_path/"data","--release-hash",release.sha256,"--split-hash",split.sha256,
                   "--output",output,"--workspace",WORKSPACE,"--fixture","--epochs",2,"--dimension",4)
    assert result.returncode==0,result.stdout+result.stderr
    summary=json.loads(result.stdout);assert summary["mode"]=="synthetic_pipeline" and not summary["formal_E1_E2_complete"]
    report=json.loads((output/"reports/development.json").read_text())
    assert report["test_evaluation"]=="not_run" and report["external_model_calls"]==0
    assert report["training"]["attention_pack"]["weight_delta_l2"]>0
    assert report["training"]["attention_pair"]["weight_delta_l2"]>0
    assert report["training"]["legacy_character_mlp"]["contextual_encoder"] is False
    assert not any("test-" in x["path"] or x["path"]=="records.json" for x in report["data_scope"]["accesses"])
    bundle_root=output/"models/attention_pack";ref=FileRef.model_validate(report["bundles"]["attention_pack"]["manifest"])
    input_path=tmp_path/"input.json";input_path.write_bytes(json_bytes(examples("dev",1)[0].item))
    infer=command("predict-v3","--root",bundle_root,"--bundle-hash",ref.sha256,"--input",input_path)
    assert infer.returncode==0,infer.stdout+infer.stderr
    assert json.loads(infer.stdout)["mode"]=="advisory" and not json.loads(infer.stdout)["affects_score"]
    assert json.loads(infer.stdout)["training_scope"]=="synthetic_pipeline" and json.loads(infer.stdout)["training_release"]["sha256"]
    frozen_ref=FileRef(path="freeze.json",sha256=sha((output/"freeze.json").read_bytes()))
    moved=tmp_path/"moved";shutil.copytree(output,moved)
    assert verify_freeze(moved,frozen_ref)["id"]==summary["freeze_id"]
    a,_=load_bundle(bundle_root,ref);b,_=load_bundle(moved/"models/attention_pack",ref)
    assert a.predict(examples()[0].item)==b.predict(examples()[0].item)
    (moved/"models/attention_pack/weights/model.npz").write_bytes(b"tampered")
    checked=command("check-freeze-v3","--root",moved,"--freeze-hash",frozen_ref.sha256)
    assert checked.returncode!=0 and json.loads(checked.stdout)["error"]=="file_hash_mismatch"
    assert command("train-v3","--release-root",tmp_path/"data","--release-hash",release.sha256,"--split-hash",split.sha256,
                   "--output",output,"--workspace",WORKSPACE,"--fixture").returncode!=0


def freeze_fixture(root):
    root.mkdir();refs=[]
    for name in ["source.json","lock.txt","split.json","runtime.json","evaluation.json"]:
        (root/name).write_bytes(json_bytes({"fixture":True,"name":name}));refs.append(FileRef(path=name,sha256=sha((root/name).read_bytes())))
    source=SourceIdentity(base_commit="a"*40,source_digest=digest("synthetic source"),overlay=refs[0],dependency_locks=(refs[1],))
    candidate=CampaignCandidate(id="synthetic-candidate",runtime=refs[3],evaluation=refs[4],source=source,budget=Budget(model_calls=0,actions=0,wall_seconds=30))
    return refs,source,candidate


def test_freeze_campaign_requires_exact_budget_identity_and_no_raw_gold(tmp_path):
    root=tmp_path/"freeze";refs,source,candidate=freeze_fixture(root)
    frozen=freeze_selection(root,"freeze.json",files=refs,source=source,selection={"selection_split":"dev"},split_manifest=refs[2],candidates=(candidate,))
    fr=FileRef(path="freeze.json",sha256=sha((root/"freeze.json").read_bytes()))
    campaign=Campaign(id="synthetic-campaign",candidates=(candidate,),split_manifest=refs[2],frozen_at="2026-10-06T12:00:00Z",opened_at="2026-10-06T12:01:00Z",output_audience=("fixture-evaluator",))
    (root/"campaign.json").write_bytes(json_bytes(campaign));cr=FileRef(path="campaign.json",sha256=sha((root/"campaign.json").read_bytes()))
    check=validate_campaign(root,freeze_ref=fr,campaign_ref=cr,candidate=candidate,split_manifest=refs[2])
    assert check["test_content_opened"] is False
    changed=candidate.model_copy(update={"budget":Budget(model_calls=1,actions=0,wall_seconds=30)})
    changed_campaign=campaign.model_copy(update={"candidates":(changed,)})
    (root/"changed.json").write_bytes(json_bytes(changed_campaign));changed_ref=FileRef(path="changed.json",sha256=sha((root/"changed.json").read_bytes()))
    with pytest.raises(ProtocolError,match="budget"):
        validate_campaign(root,freeze_ref=fr,campaign_ref=changed_ref,candidate=changed,split_manifest=refs[2])
    with pytest.raises(FileExistsError):freeze_selection(root,"freeze.json",files=refs,source=source,selection={"selection_split":"dev"},split_manifest=refs[2])
    with pytest.raises(ProtocolError,match="dev"):
        freeze_selection(root,"bad.json",files=refs,source=source,selection={"selection_split":"test"},split_manifest=refs[2])
    secret=FileRef(path="gold/test.json",sha256="0"*64)
    with pytest.raises(ProtocolError,match="raw dataset"):
        freeze_selection(root,"bad2.json",files=[*refs,secret],source=source,selection={"selection_split":"dev"},split_manifest=refs[2])


def test_reference_includes_active_adapter_and_rejects_drift(tmp_path):
    for name,value in [("base",np.arange(4.)),("adapter",np.arange(3.)+.1)]:np.savez(tmp_path/f"{name}.npz",weights=value)
    base=FileRef(path="base.npz",sha256=sha((tmp_path/"base.npz").read_bytes()));adapter=FileRef(path="adapter.npz",sha256=sha((tmp_path/"adapter.npz").read_bytes()))
    out=reference_policy(tmp_path,(base,),(adapter,),sft_identity=None)
    assert out["adapter_enabled"] and not out["training_executed"]
    with pytest.raises(ProtocolError,match="adapter"):reference_policy(tmp_path,(base,),(),sft_identity=None)
    (tmp_path/"adapter.npz").write_bytes(b"changed")
    with pytest.raises(ProtocolError,match="hash"):reference_policy(tmp_path,(base,),(adapter,),sft_identity=None)


def test_huggingface_missing_dependency_is_explicit_without_network(tmp_path,monkeypatch):
    import builtins
    from career_lab.models.v3.huggingface import HuggingFaceCandidate
    original=builtins.__import__
    def missing(name,*args,**kwargs):
        if name in {"torch","transformers"}:raise ImportError("intentional dependency-negative test")
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,"__import__",missing)
    with pytest.raises(ProtocolError,match="dependencies"):
        HuggingFaceCandidate(tmp_path,revision="a"*40)
    with pytest.raises(ProtocolError,match="revision"):
        HuggingFaceCandidate(tmp_path,revision="main")


def test_legacy_baseline_remains_distinct_and_roundtrips(tmp_path):
    model=LegacyMLP();report=model.fit(examples())
    assert report["contextual_encoder"] is False and report["fit_seconds"]>0
    ref,split=release_fixture(tmp_path/"data");source=SourceIdentity(base_commit="a"*40,source_digest=digest("fixture"))
    bundle_ref=save_bundle(model,tmp_path/"model",source_root=tmp_path/"data",training_release=ref,split_manifest=split,source=source)
    loaded,_=load_bundle(tmp_path/"model",bundle_ref)
    assert model.predict(examples()[0].item)==loaded.predict(examples()[0].item)
    assert len(loaded.predict(examples()[0].item).evidence_ids)==2


def test_fusion_bundle_persists_selected_threshold_and_components(tmp_path):
    from career_lab.models.v3.encoder import AttentionEncoder
    from career_lab.models.v3.ensemble import FusionCandidate
    from career_lab.models.v3.fusion_bundle import save_fusion_bundle
    rows=examples();left=LinearCandidate();left.fit(rows)
    right=AttentionEncoder(dimension=4);right.fit(rows,epochs=1)
    release,split=release_fixture(tmp_path/"data");source=SourceIdentity(base_commit="a"*40,source_digest=digest("unit-source"))
    lref=save_bundle(left,tmp_path/"left",source_root=tmp_path/"data",training_release=release,split_manifest=split,source=source)
    rref=save_bundle(right,tmp_path/"right",source_root=tmp_path/"data",training_release=release,split_manifest=split,source=source)
    ref=save_fusion_bundle(tmp_path/"fusion",left_root=tmp_path/"left",left_ref=lref,right_root=tmp_path/"right",right_ref=rref,alpha=.25,threshold=.75)
    loaded,bundle=load_bundle(tmp_path/"fusion",ref);expected=FusionCandidate(left,right,.25,.75);expected.revision=bundle.model_revision
    assert loaded.predict(rows[0].item)==expected.predict(rows[0].item)
    assert loaded.threshold==.75 and loaded.alpha==.25
    copied=tmp_path/"moved-fusion";shutil.copytree(tmp_path/"fusion",copied)
    moved,_=load_bundle(copied,ref);assert moved.predict(rows[0].item)==loaded.predict(rows[0].item)
    (copied/"components/right/weights/model.npz").write_bytes(b'changed')
    with pytest.raises(ProtocolError,match="hash"):load_bundle(copied,ref)
