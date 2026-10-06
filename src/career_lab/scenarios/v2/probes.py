"""Authoring-only probe runner. This module is never called by assistant.run."""
import json
from career_lab.contracts.v2.world import TestRequestV2
from career_lab.assistant.v2 import Assistant, RetrievalTuning
from .engine import ScenarioEngine


def run_probes(package):
    from .__main__ import auth,plan
    engine=ScenarioEngine(package);assistant=Assistant(package);runs=[]
    for probe in json.loads((package.root/"probes.json").read_text()):
        sid="probe-"+probe["id"];s=engine.initial(sid);trace=[]
        if probe.get("config") or probe.get("apply") or probe.get("tuning"):
            cfg=s.config.model_dump(mode="json")
            cfg.update(probe.get("config",{}));cfg.update(probe.get("tuning",{}));cfg.update(version=2,config_version=1)
            t=plan(engine,s,"apply_config","config",config=cfg);s=t.snapshot;trace.extend(t.events)
        if probe.get("grant"):
            t=plan(engine,s,"request_business","ask",terms=probe["grant"],reason="按探针配置验证合法资源路径")
            s=t.snapshot;trace.extend(t.events)
            ref={"session_id":sid,"kind":"business_request","object_id":t.result.id,"version":1}
            t=plan(engine,s,"resolve_approval","grant",approval=True,request=ref,expected_request_revision=1)
            s=t.snapshot;trace.extend(t.events)
            if t.result.status!="approved":raise ValueError("probe approval rejected")
        if probe.get("refresh"):
            t=plan(engine,s,"refresh_index","refresh");s=t.snapshot;trace.extend(t.events)
        output=assistant.run(s,TestRequestV2(query=probe["query"],config_version=s.config.config_version),
            auth(sid),"query")
        expected=probe["expected"];actual=output.result
        checks={"status":actual.status==expected["status"],"error_code":actual.error_code==expected.get("error_code"),
            "contains":all(text in actual.answer for text in expected.get("contains",[])),
            "citations":all(any(ref.object_id==mid and ref.version==version for ref in actual.citations)
                            for mid,version in expected.get("citation_versions",{}).items())}
        if "effective_update_strategy" in expected:
            checks["effective_update_strategy"]=actual.config.effective.update_strategy==expected["effective_update_strategy"]
        runs.append({"probe_id":probe["id"],"public":probe["public"],"expected":expected,
            "actual":actual.model_dump(mode="json"),"provenance":output.provenance,"checks":checks,
            "result":"pass" if all(checks.values()) else "fail",
            "events":[engine.public_event(e,s,auth(sid)) for e in trace]})
    return {"mode":"authoring_probe_execution","scenario_hash":package.content_hash,
        "executor":"local_deterministic_module","api_integrated":False,
        "attempts":len(runs),"passed":sum(x["result"]=="pass" for x in runs),"runs":runs}


def export_public_probes(package):
    """Only explicitly public authored probes can enter an engineering handoff.

    This never returns hidden queries/expectations or the full probe file. The
    learner material API does not use authoring probe files at all.
    """
    rows=json.loads((package.root/"probes.json").read_text())
    return tuple(dict(row) for row in rows if row.get("public") is True)
