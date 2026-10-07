"""Module-only commands. No API/worker/product-QA claim is made."""
import argparse,json
from dataclasses import asdict
from pathlib import Path
from pydantic import ValidationError
from career_lab.contracts.v2.core import AuthContext,Command,Executor,ProtocolError
from career_lab.contracts.v2.world import TestRequestV2
from career_lab.scenarios.v2 import load_package,ScenarioEngine
from career_lab.assistant.v2 import Assistant
from .localization import text, locale_root


def auth(sid,approval=False):
    actor="supervisor" if approval else "learner"
    return AuthContext(session_id=sid,actor_id=actor,
        executor=Executor(id=actor,kind="system" if approval else "human"),
        capabilities=("approve",) if approval else ("read","act"),credential_id="module-demo-fixture")


def plan(engine,s,operation,key,approval=False,**payload):
    return engine.plan(s,Command(schema_version=2,request_id=key,expected_version=s.world.business_seq,
        expected_workspace_revision=s.world.workspace_revision,operation=operation,
        payload=payload if approval else {"tool":operation,**payload}),auth(s.world.session_id,approval))


def paths_report(package):
    engine=ScenarioEngine(package);assistant=Assistant(package)
    paths=json.loads((package.root/"paths.json").read_text())
    paths.append({"id":"unlisted-combination","domains":["stable_faq","policy"],"participants":35,
        "update_strategy":"manual_policy","work_items":["scope_filter","human_fallback"],"launch_day":7,"request":{"capacity":45}})
    report=[]
    for path in paths:
        s=engine.initial("module-"+path["id"]);sid=s.world.session_id
        before=assistant.run(s,TestRequestV2(query=text(package,"path_question"),config_version=0),auth(sid),"baseline")
        config=s.config.model_dump(mode="json")
        config.update({k:v for k,v in path.items() if k not in {"id","request"}});config["config_version"]=1;config["version"]=2
        transition=plan(engine,s,"apply_config","apply",config=config);s=transition.snapshot
        trace=list(transition.events);decision=None
        if path["request"]:
            refs=engine.read(s,__import__("career_lab.contracts.v2.core",fromlist=["ObjectRef"]).ObjectRef(session_id=sid,kind="material",object_id="user_groups",version=1),auth(sid))
            t=plan(engine,s,"request_business","ask",terms=path["request"],reason=text(package,"path_reason"),evidence_refs=[refs[0].ref.model_dump(mode="json")]);s=t.snapshot;trace.extend(t.events)
            ref={"session_id":sid,"kind":"business_request","object_id":t.result.id,"version":1}
            t=plan(engine,s,"resolve_approval","approve",approval=True,request=ref,expected_request_revision=1)
            s=t.snapshot;trace.extend(t.events);decision=t.result.model_dump(mode="json")
        after=assistant.run(s,TestRequestV2(query=text(package,"path_question"),config_version=1),auth(sid),"after")
        report.append({"path":path["id"],"before":before.result.model_dump(mode="json"),
            "after":after.result.model_dump(mode="json"),"provenance":after.provenance,
            "resources":dict(s.world.resources),"decision":decision,
            "events":[engine.public_event(e,s,auth(sid)) for e in trace]})
    return {"mode":"w02_module_execution","authority":"constructed_AuthContext_for_local_policy_verification",
        "api_integrated":False,"persistent_storage":False,"online_model":False,
        "scenario_hash":package.content_hash,"paths":report}


def main(argv=None):
    parser=argparse.ArgumentParser(description="W02 module validation and local deterministic execution (not public API).")
    parser.add_argument("command",choices=["validate","paths","probes","public-probes","serve"])
    parser.add_argument("root",type=Path)
    parser.add_argument("--work-language",choices=("zh","en"))
    parser.add_argument("--database-url")
    parser.add_argument("--port",type=int,default=19832)
    args=parser.parse_args(argv)
    try:
        if args.command=="serve":
            if not args.database_url:raise ProtocolError("database_url_required")
            from career_lab.api.app import create_app
            from career_lab.api.modules import ExtensionRegistry
            from .module import ScenarioModule
            import uvicorn
            module=ScenarioModule(args.root,work_language=args.work_language)
            uvicorn.run(create_app(args.database_url,extensions=module.install(ExtensionRegistry())),host="127.0.0.1",port=args.port)
            return 0
        package=load_package(locale_root(args.root,args.work_language))
        from .probes import run_probes, export_public_probes
        if args.command=="public-probes":
            print(json.dumps({"audience":"public","probes":list(export_public_probes(package)),"hidden_included":False},ensure_ascii=False,indent=2));return 0
        result={"valid":True,"scenario":package.bundle.id,"revision":package.bundle.revision,"hash":package.content_hash,
                "materials":len(package.materials),"facts":len(package.facts),"work_language":package.locale} if args.command=="validate" else paths_report(package) if args.command=="paths" else run_probes(package)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result.get("passed",0)==result.get("attempts",0) else 1
    except (ProtocolError,ValidationError,OSError,ValueError) as exc:
        print(json.dumps({"valid":False,"code":getattr(exc,"code","invalid_module_input"),
            "message":"Scenario/module validation failed; inspect authorized local diagnostics."}));return 1


if __name__=="__main__":
    raise SystemExit(main())
