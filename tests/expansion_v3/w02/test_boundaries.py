from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timezone,timedelta
import json,subprocess,sys
from pathlib import Path
import pytest
from career_lab.contracts.v2.core import ProtocolError
from career_lab.contracts.v2.world import TestRequestV2 as AssistantTestRequest
from career_lab.assistant.v2 import Assistant
from .conftest import auth,command,apply
from .test_engine import approve


def test_repeated_test_has_deterministic_identity_without_mutating_world(package,engine):
    s=engine.initial("session");before=deepcopy(s)
    req=AssistantTestRequest(query="会议室预约",config_version=0)
    a=Assistant(package).run(s,req,auth(),"same")
    b=Assistant(package).run(s,req,auth(),"same")
    assert a.result==b.result and a.provenance["chunk_ids"]==b.provenance["chunk_ids"]
    assert s==before and not s.world.applied_milestones
    # Persistence, cross-process request replay and duplicate-ID conflict are W01 gates.


def test_expired_and_object_limited_auth(package,engine):
    s=engine.initial("session")
    expired=auth().model_copy(update={"expires_at":datetime.now(timezone.utc)-timedelta(seconds=1)})
    with pytest.raises(ProtocolError,match="credential expired"):
        Assistant(package).run(s,AssistantTestRequest(query="住宿",config_version=0),expired,"expired")
    with pytest.raises(ProtocolError,match="object forbidden"):
        engine.plan(s,command(s,"read_material","limited",material={"session_id":"session","kind":"material","object_id":"policy","version":1}),auth(objects=("faq",)))


def test_config_alone_never_grants_resources_or_claims_rollout(engine):
    s=engine.initial("session")
    t=apply(engine,s,participants=70,launch_day=12,update_strategy="realtime",work_items=("realtime_sync","human_fallback"))
    assert t.snapshot.world.resources==s.world.resources
    assert t.result.requested.participants==t.result.effective.participants==70
    assert t.result.effective.update_strategy=="daily"
    assert set(t.result.differences)>={"participants","launch_day","work_items","update_strategy"}
    assert not any("launched" in e["event_type"] for e in t.events)


def test_request_with_cross_session_or_future_evidence_is_not_planned(engine):
    s=engine.initial("session")
    for ref,code in [
        ({"session_id":"other","kind":"material","object_id":"faq","version":1,"observed_at_seq":0},"evidence session mismatch"),
        ({"session_id":"session","kind":"material","object_id":"faq","version":1,"observed_at_seq":1},"future evidence")]:
        with pytest.raises(ProtocolError,match=code):
            engine.plan(s,command(s,"request_business","bad",terms={"capacity":60},reason="reason",evidence_refs=[ref]),auth())
    assert not s.requests and s.world.business_seq==0


def test_unsupported_operation_counteroffer_remains_unavailable(engine):
    s=engine.initial("session")
    with pytest.raises(ProtocolError,match="capability not installed"):
        engine.plan(s,command(s,"accept_counteroffer","counter",terms={"capacity":45}),auth())
    assert s.world.resources["capacity"]==30


def test_approval_stale_revision_and_reused_request_are_rejected(engine):
    s=apply(engine,engine.initial("session"),participants=50).snapshot
    req=engine.plan(s,command(s,"request_business","r",terms={"capacity":60},reason="scope"),auth())
    with pytest.raises(ProtocolError,match="request id reused"):
        engine.plan(req.snapshot,command(req.snapshot,"request_business","r",terms={"capacity":60},reason="scope"),auth())
    ref={"session_id":"session","kind":"business_request","object_id":req.result.id,"version":1}
    with pytest.raises(ProtocolError,match="request revision conflict"):
        engine.plan(req.snapshot,command(req.snapshot,"resolve_approval","stale",request=ref,expected_request_revision=2),auth(actor="supervisor",capabilities=("approve",)))


def test_no_retrieval_to_private_or_investigation_content(package,engine):
    s=engine.initial("session")
    for question in ("legacy_connector_unstable", "NEVER_W02_7C9E", "咨询样本120次"):
        result=Assistant(package).run(s,AssistantTestRequest(query=question,config_version=0),auth(),"private")
        assert result.result.status=="fallback" and not result.result.citations
        assert question not in result.result.answer


def test_pause_resume_does_not_trigger_policy_or_rerecord_milestone(engine):
    s=engine.initial("session")
    paused=engine.plan(s,command(s,"pause","p"),auth()).snapshot
    assert paused.world.status=="paused"
    with pytest.raises(ProtocolError,match="session paused"):
        apply(engine,paused)
    resumed=engine.plan(paused,command(paused,"resume","r"),auth()).snapshot
    assert resumed.world.status=="active" and resumed.source_versions["policy"]==1


def test_module_cli_real_entry_and_failures(package):
    ok=subprocess.run([sys.executable,"-m","career_lab.scenarios.v2","validate",str(package.root)],capture_output=True,text=True)
    assert ok.returncode==0 and json.loads(ok.stdout)["valid"]
    bad=subprocess.run([sys.executable,"-m","career_lab.scenarios.v2","validate","/definitely-missing-w02-bundle"],capture_output=True,text=True)
    assert bad.returncode==1 and json.loads(bad.stdout)["code"]=="scenario_bundle_invalid"
    assert "Traceback" not in bad.stdout


def test_readonly_material_access_and_catalog_are_version_scoped(engine):
    from career_lab.contracts.v2.core import ObjectRef
    s=engine.initial("session");original=deepcopy(s)
    catalog=engine.catalog(s,auth())
    assert "tech_private" not in {m.id for m in catalog}
    ref=ObjectRef(session_id="session",kind="material",object_id="policy",version=1)
    assert "500" in str(engine.read(s,ref,auth()))
    with pytest.raises(ProtocolError,match="material unavailable"):
        engine.read(s,ref.model_copy(update={"version":2}),auth())
    assert s==original


def test_config_object_revision_and_effective_work_are_explicit(package,engine):
    s=engine.initial("session")
    t=apply(engine,s,update_strategy="realtime",work_items=("realtime_sync","human_fallback"))
    assert t.snapshot.config.version==2 and t.snapshot.config.config_version==1
    assert t.result.requested.work_items==("realtime_sync","human_fallback")
    assert t.result.effective.work_items==("human_fallback",)
    bad=t.snapshot.config.model_copy(update={"config_version":2})
    with pytest.raises(ProtocolError,match="config revision conflict"):
        engine.plan(t.snapshot,command(t.snapshot,"apply_config","bad-revision",config=bad.model_dump(mode="json")),auth())


def test_authored_probes_execute_against_real_module_and_no_gold_in_results(package):
    from career_lab.scenarios.v2.probes import run_probes
    report=run_probes(package)
    assert report["attempts"]==report["passed"]==12
    assert all("expected" not in x["actual"] for x in report["runs"])
