"""Targeted review regressions. Simulated env inputs are unit doubles, not data releases for research.
The actual fixture-origin path is tested separately and cannot downgrade its bucket.
"""
from dataclasses import replace
from types import SimpleNamespace
import json
import time
import pytest

from test_w07_pipeline import make_case,FakeModel,decision,label_result
from career_lab.contracts.v2.core import FileRef,Executor,digest,ProtocolError
from career_lab.contracts.v2.data import AnnotationV2,DatasetRecordV2
from career_lab.datasets.v3.common import json_bytes,sha
from career_lab.datasets.v3.export import export_snapshot,aggregate_exports
from career_lab.datasets.v3.release import publish_exports,publish_release,audit_release
from career_lab.datasets.v3.labeling import AnnotationBatch,LabelResult
from career_lab.datasets.v3.attestation import validate_decision
from career_lab.datasets.v3.quality import duplicate_pairs,QualityError
from career_lab.datasets.v3.g0 import verify_numeric
from career_lab.datasets.v3.origin import binding

def simulated_source_authority(record,snapshot,refs):
    """Explicit unit double; never a production source authority."""
    return binding(record,snapshot)



def simulated_export(root,sid="unit-a",split="train",field="capacity"):
    root.mkdir(parents=True)
    snapshot,units,policies=make_case(root,origin="env_run")
    objects=[]
    for source in snapshot.objects:
        ref=source.ref.model_copy(update={"session_id":sid})
        text='{"'+field+'": 30}' if 'capacity' in source.text else source.text
        objects.append(replace(source,ref=ref,text=text,validity_known=True))
    snapshot=replace(snapshot,session_id=sid,objects=tuple(objects))
    unit=units[0];data=unit.model_input.model_dump(mode="json")
    p=data["evidence"];p["claim"]=field+" <= 30";p["item_id"]=sid
    for raw in [*p["subjects"],*(x["ref"] for x in p["candidate_evidence"])]:raw["session_id"]=sid
    p["candidate_evidence"][0]["text"]='{"'+field+'": 30}'
    p["input_hash"]=digest({k:v for k,v in p.items() if k!="input_hash"})
    lineage=unit.lineage.model_copy(update={"session_id":sid,"run_id":sid,"structure_id":field+"-fixture-structure","component_id":sid,"fact_root_ids":(sid,)})
    raw=json_bytes({"kind":"simulated_env_input_for_unit_test_only","session_id":sid,"objects":[{"ref":x.ref.model_dump(mode="json"),"text":x.text} for x in objects]})
    (root/"source.json").write_bytes(raw);source_ref=FileRef(path="source.json",sha256=sha(raw))
    provenance=unit.provenance.model_copy(update={"actual_sources":(source_ref,),"command":"unit test double; not actual environment data"})
    unit=replace(unit,model_input=data,lineage=lineage,provenance=provenance,split=split,evaluation_time_known=True)
    return snapshot,unit,{"source.json":{"sha256":source_ref.sha256,"review_status":"approved"}},export_snapshot(snapshot,[unit])


def test_set_order_consensus_uses_two_calls_and_preserves_raw(tmp_path):
    s,u,pol,result=simulated_export(tmp_path/"source")
    batch=AnnotationBatch.create(tmp_path/"batch",result.records,annotation_version="set-v1",executor=Executor(id="test-double",kind="external_agent"),source_root=tmp_path/"source",policies=pol)
    calls=[]
    def model(request):
        calls.append(request)
        d=decision(request).model_dump(mode="json")
        ids=[x["id"] for x in request["model_input"]["evidence"]["candidate_evidence"]]
        d["evidence_ids"]=ids;d["acceptable_evidence_sets"]=[ids,list(reversed(ids))]
        return label_result(request,json.dumps(d),"test-double","unit-test",{})
    out=batch.run(model);a=out["annotations"][0]
    assert len(calls)==2 and a.status=="accepted" and a.label_tier=="G2v" and a.adjudication_ref is None
    assert a.passes[0].raw_output!=a.passes[1].raw_output
    assert a.passes[0].decision==a.passes[1].decision


def test_multiple_snapshots_keep_all_provenance_and_roots(tmp_path):
    a=simulated_export(tmp_path/"a","a","train","capacity")
    b=simulated_export(tmp_path/"b","b","dev","dev_days")
    combined=aggregate_exports([a[3],b[3]])
    assert combined.snapshot_digest is None and len(combined.source_snapshots)==2
    contributions=[]
    for name,entry in [("a",a),("b",b)]:
        r=entry[3];contributions.append({"export":r,"source_root":tmp_path/name,"policies":entry[2],"annotations":[verify_numeric(x) for x in r.records]})
    manifest=publish_exports(tmp_path/"release",contributions,source_authority=simulated_source_authority)
    assert manifest["source_snapshot_count"]==2 and audit_release(tmp_path/"release",source_authority=simulated_source_authority)["records"]==2
    snapshots=json.loads((tmp_path/"release/source-snapshots.json").read_text())
    assert {x["snapshot_digest"] for x in snapshots}=={a[3].snapshot_digest,b[3].snapshot_digest}
    reviews=json.loads((tmp_path/"release/source-reviews.json").read_text())
    assert len({next(iter(x.values()))["sha256"] for x in reviews.values()})==2
    false=replace(a[3],records=combined.records,annotations=combined.annotations,source_maps=combined.source_maps)
    with pytest.raises(ProtocolError,match="record set"):
        aggregate_exports([false])


def test_pending_cannot_impersonate_g1_and_counts_are_separate(tmp_path):
    s,u,pol,result=simulated_export(tmp_path/"source")
    rejected=export_snapshot(s,[replace(u,label_tier="G1")])
    assert not rejected.records and rejected.quarantined[0]["reason"]=="export_tier_must_be_pending_model"
    fake=result.annotations[0].model_copy(update={"label_tier":"G1"})
    with pytest.raises(ProtocolError,match="pending"):
        publish_release(tmp_path/"bad",result,source_root=tmp_path/"source",policies=pol,annotations=[fake],allow_pending=True,source_authority=simulated_source_authority)
    publish_release(tmp_path/"pending",result,source_root=tmp_path/"source",policies=pol,allow_pending=True,source_authority=simulated_source_authority)
    q=json.loads((tmp_path/"pending/quality-report.json").read_text())
    assert q["label_tiers"]=={} and q["annotation_status"]=={"pending":1}


def test_fixture_origin_never_silently_becomes_env_run(tmp_path):
    snapshot,units,_=make_case(tmp_path)
    try:result=export_snapshot(snapshot,units)
    except ProtocolError as exc:
        assert exc.code=="fixture_bucket_contract_unavailable"
    else:
        assert result.records and all(x.bucket=="fixture" for x in result.records)


def test_history_current_and_unknown_frame_have_consistent_gold_targets(tmp_path):
    s,u,pol,result=simulated_export(tmp_path/"source")
    data=json.loads(json.dumps(u.model_input));p=data["evidence"]
    p["candidate_evidence"][0]["ref"]["valid_until_seq"]=3
    p["subjects"][0]["valid_until_seq"]=3
    sources=(replace(s.objects[0],valid_until_seq=3),*s.objects[1:]);s=replace(s,objects=sources)
    p["as_of"]["business_seq"]=2;p["input_hash"]=digest({k:v for k,v in p.items() if k!="input_hash"})
    past=export_snapshot(s,[replace(u,model_input=data)])
    assert verify_numeric(past.records[0]).final.label=="SUPPORTED"
    p["as_of"]["business_seq"]=4;p["input_hash"]=digest({k:v for k,v in p.items() if k!="input_hash"})
    present=export_snapshot(s,[replace(u,model_input=data)])
    assert verify_numeric(present.records[0]).final.label=="INSUFFICIENT"
    stale=next(c.id for c in present.records[0].model_input.evidence.candidate_evidence if 'capacity' in c.text)
    bad={"task_type":"relation","label":"SUPPORTED","applicability":"undetermined","evidence_ids":[stale],"acceptable_evidence_sets":[[stale]],"evidence_evaluable":True}
    with pytest.raises(ProtocolError,match="reference time"):
        validate_decision(json.dumps(bad),present.records[0].model_input.model_dump(mode="json"))
    unknown=export_snapshot(s,[replace(u,model_input=data,evaluation_time_known=False)])
    with pytest.raises(ProtocolError,match="undetermined"):verify_numeric(unknown.records[0])


def test_hidden_content_does_not_change_model_input_permutation(tmp_path):
    from career_lab.datasets.v3.export import SourceObject
    from career_lab.contracts.v2.core import ObjectRef
    s,u,pol,result=simulated_export(tmp_path/"source")
    hidden=SourceObject(ObjectRef(session_id=s.session_id,kind="document",object_id="hidden",version=1),"hidden outcome alpha",s.point,(),"gold")
    one=export_snapshot(replace(s,objects=(*s.objects,hidden)),[u])
    two=export_snapshot(replace(s,objects=(*s.objects,replace(hidden,text="hidden outcome beta"))),[u])
    assert one.records[0].input_hash==two.records[0].input_hash
    assert one.records[0].model_input==two.records[0].model_input
    assert one.snapshot_digest!=two.snapshot_digest


def test_semantic_shingles_do_not_match_json_boilerplate():
    rows=[SimpleNamespace(record_id="a",split="train",family="relation"),SimpleNamespace(record_id="b",split="dev",family="relation")]
    assert not list(duplicate_pairs(rows,{"a":"客户访问权限需经过部门主管明确授权","b":"预算不足导致人工审核工作量无法按时完成"},.94))
    assert list(duplicate_pairs(rows,{"a":"相同的内容","b":"相同的内容"},.94))[0]["code"]=="duplicate_input_cross_split"


def test_batch_schema_snapshot_survives_annotation_schema_description_change(tmp_path,monkeypatch):
    from career_lab.contracts.v2.data import AnnotationDecision
    s,u,pol,result=simulated_export(tmp_path/"source")
    batch=AnnotationBatch.create(tmp_path/"batch",result.records,annotation_version="schema-freeze",executor=Executor(id="unit",kind="external_agent"),source_root=tmp_path/"source",policies=pol)
    frozen=batch.manifest["output_schema"]
    changed=dict(frozen,title="changed documentation only")
    monkeypatch.setattr(AnnotationDecision,"model_json_schema",classmethod(lambda cls,*a,**kw:changed))
    model=FakeModel();out=batch.run(model)
    assert len(model.calls)==2 and out["annotations"][0].status=="accepted"
    assert all(c["output_schema"]==frozen for c in model.calls)
    assert all(c["output_schema_hash"]==digest(frozen) for c in model.calls)


def test_http_failure_keeps_safe_status_body_and_usage(tmp_path):
    import httpx
    from career_lab.datasets.v3.labeling import OpenAICompatibleExecutor
    s,u,pol,result=simulated_export(tmp_path/"source")
    batch=AnnotationBatch.create(tmp_path/"batch",result.records,annotation_version="http-failure",executor=Executor(id="unit",kind="external_agent"),source_root=tmp_path/"source",policies=pol)
    def transport(request):
        return httpx.Response(429,headers={"x-request-id":"req-test"},json={"error":{"message":"quota exhausted fixture-secret","api_key":"fixture-secret"},"usage":{"cost":.125,"prompt_tokens":7,"completion_tokens":0}})
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        out=batch.run(OpenAICompatibleExecutor(client,"https://unit.invalid/v1/chat/completions","requested-model","fixture-secret"))
    assert out["usage"]["known_cost"]==.25 and out["usage"]["failed"]==2
    for raw in batch.artifacts().values():
        record=json.loads(raw);receipt=record["receipt"]
        assert receipt["error_code"]=="provider_http_429" and receipt["error_details"]["http_status"]==429
        assert receipt["usage"]["prompt_tokens"]==7 and "quota exhausted" in receipt["raw_output"]
        assert "fixture-secret" not in raw.decode()
