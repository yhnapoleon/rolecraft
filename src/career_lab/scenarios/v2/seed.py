"""Build an explicitly synthetic working scenario from authored facts and real QA runs."""
import hashlib
import json
from pathlib import Path
import yaml

from career_lab.contracts.v2.core import EvidenceRefV2, FileRef, SourceIdentity, digest
from career_lab.contracts.v2.research import RuntimeBundle, EvaluationBundle
from career_lab.contracts.v2.world import (AssistantConfig, DisclosurePolicy, FactV2,
    MaterialV2, RoleSpecV2, ScenarioBundle, SourceFragment)
from .content import materials as business_materials, role_definitions


def build_seed(root, case_records=None):
    root=Path(root)
    if root.exists() and any(root.iterdir()):raise ValueError("refuse to overwrite scenario release")
    root.mkdir(parents=True,exist_ok=True)
    files={};materials=[];facts=[];material_files={};initial={}
    public=DisclosurePolicy(mode="public")
    never=DisclosurePolicy(mode="never")
    policies={
        "public":public,"never":never,
        "manager_summary":DisclosurePolicy(mode="paraphrase_only",actors=("supervisor",),paraphrase="经理更重视可信承诺；演示与试点开放需分别说明依据。"),
        "business_summary":DisclosurePolicy(mode="paraphrase_only",actors=("business_lead",),paraphrase="业务方关注政策咨询价值，也承认耗时统计包含等待，收益需要另行验证。"),
        "tech_summary":DisclosurePolicy(mode="paraphrase_only",actors=("tech_lead",),paraphrase="连接器复用尚未完成可靠性核验，需要验证后再承诺。"),
        "tech_only":DisclosurePolicy(mode="role_only",actors=("tech_lead",))
    }
    definitions=list(business_materials())
    if case_records is None:
        definitions.append(("failures","内部试用记录","investigation",1,"never",["此记录尚未作为学员资料发布。"]))
    else:
        rows=[]
        for number,record in enumerate(case_records["records"],1):
            result=record["result"]
            refs="；".join(f"{r['object_id']}@{r['version']}" for r in result["citations"]) or "没有引用"
            execution=result["execution"]
            rows.extend([
                f"记录{number}｜提问：{result['query']}",
                f"当时实际回答：{result['answer']}",
                f"检索引用：{refs}。当时源版本：{json.dumps(execution['source_versions'],ensure_ascii=False)}；索引版本：{json.dumps(execution['indexed_versions'],ensure_ascii=False)}。",
                f"配置编号：{result['config']['requested']['config_version']}。实际状态：{result['status']}；记录时间：{execution['executed_at']}。"
            ])
        definitions.append(("failures","内部试用问答记录","investigation",1,"public",[
            "下列问答来自训练助手的实际本地运行。它们保留了回答与版本，没有给出正确答案或评价。公司背景与提问场景为虚构设定，不代表真实员工效果。",
            *rows
        ]))
    for mid,title,domain,version,mode,rows in definitions:
        text=f"# {title}\n\n本案例的公司与业务资料为虚构训练设定。\n\n"
        fragments=[]
        for row in rows:
            sentence,assertions=row if isinstance(row,tuple) else (row,[])
            start=len(text);text+=sentence+"\n\n"
            ref=EvidenceRefV2(session_id="scenario:pm_pilot:v2",kind="material",object_id=mid,version=version,
                span_start=start,span_end=start+len(sentence),quote=sentence,observed_at_seq=0)
            fragments.append(SourceFragment(ref=ref,text=sentence,channel="material",disclosure=policies[mode],
                fact_ids=tuple(x[0] for x in assertions)))
            for fid,value,unit in assertions:
                facts.append(FactV2(id=fid,version=version,value=value,unit=unit,source=ref,disclosure=policies[mode]))
        path=f"materials/{mid}-v{version}.md";files[path]=(text.rstrip()+"\n").encode()
        material_files.setdefault(mid,{})[str(version)]=path
        materials.append(MaterialV2(id=mid,version=version,title=title,domain=domain,fragments=tuple(fragments)))
        if version==1:initial[mid]=version
    roles=[]
    for definition in role_definitions():
        definition=dict(definition)
        if case_records is not None:
            definition["known_materials"]=(*definition["known_materials"],"failures")
        role=definition["id"]
        overrides={}
        if role=="supervisor":overrides["manager_priority"]=policies["manager_summary"]
        if role=="business_lead":overrides["business_caveat"]=policies["business_summary"]
        if role=="tech_lead":
            overrides["connector_risk"]=policies["tech_summary"]
            overrides["tech_debug_code"]=DisclosurePolicy(mode="paraphrase_only",actors=("tech_lead",),
                paraphrase="连接器重试边界还需核验，不能把可复用性当作已有能力。")
        roles.append(RoleSpecV2(**definition,disclosure_policy=overrides))
    baseline=AssistantConfig(id="pilot",session_id="scenario:pm_pilot:v2",config_version=0,
        domains=("stable_faq","onboarding","policy_travel","policy_meal","policy_leave"),
        work_items=("scope_filter","human_fallback"),participants=20,launch_day=7,retrieval_limit=1)
    rules={
        "scenario_id":"pm_pilot","revision":"2.3.0","source_kind":"authored_synthetic_business_with_actual_module_QA",
        "work_costs":{"scope_filter":1,"human_fallback":1,"realtime_sync":5},
        "approval_limits":{"capacity":60,"dev_days":6,"deadline_day":10},
        "approval_rule_revision":"pm-v2-approval-3",
        "approval_requirements":{"fallback":"human","work_items_by_strategy":{
            "daily":["scope_filter","human_fallback"],"manual_policy":["scope_filter","human_fallback"],
            "realtime":["realtime_sync","human_fallback"]}},
        "domain_aliases":{"policy":"policy_travel"},
        "mutable_domains":["policy_travel"],
        "initial_material_versions":initial,
        "initial_plan_material_updates":{"policy":2},
        "business_events":[
            {"id":"demo_schedule_changed","on":"first_resource_request","material_updates":{"demo":2},
             "visible_to":["learner","supervisor","tech_lead"]},
            {"id":"business_scope_requested","on":"capacity_approved","material_updates":{"scope_note":2},
             "visible_to":["learner","supervisor","business_lead"]}
        ],
        "material_files":material_files,
        "mandatory_prohibited_topics":["个人薪资","医疗诊断","访问密钥","他人绩效"],
        "credential_request_patterns":[r"(告诉|给我|提供|显示|发我|列出).{0,8}(密码|密钥)(?!(的)?(怎么|如何)?(重置|找回|修改|变更|管理|规则|流程|要求|长度|复杂度))",r"(密码|密钥).{0,6}(是什么|明文|是多少)",r"把.{0,6}(密码|密钥)(告诉|发给|给|提供|显示)"],
        "not_simulated":["真实运营咨询量","投诉率","收入","未执行访谈","人工已经接管"]}
    def put(path,value):files[path]=(json.dumps(value,ensure_ascii=False,indent=2)+"\n").encode()
    files["scenario.yaml"]=yaml.safe_dump(rules,allow_unicode=True,sort_keys=True).encode()
    put("materials.json",[m.model_dump(mode="json") for m in materials])
    put("facts.json",[f.model_dump(mode="json") for f in facts])
    put("roles.json",[r.model_dump(mode="json") for r in roles])
    put("baseline.json",baseline.model_dump(mode="json"))
    probes=[
        {"id":"F01","query":"住宿报销上限是多少？","public":True,"apply":True,"tuning":{"freshness_guard":"warn"},
         "expected":{"status":"answered_with_warning","contains":["500"],"citation_versions":{"policy":1}}},
        {"id":"F02","query":"餐费报销的上限？","public":False,"apply":True,"refresh":True,
         "expected":{"status":"answered","contains":["100"],"citation_versions":{"meal":1}}},
        {"id":"F03","query":"出租车单程费用的报销上限？","public":False,"apply":True,"refresh":True,
         "expected":{"status":"answered","contains":["200"],"citation_versions":{"policy":2}}},
        {"id":"F04","query":"火星天气如何？","public":True,"expected":{"status":"fallback","error_code":"no_retrieval_hit"}},
        {"id":"F05","query":"个人薪资是多少？","public":True,"expected":{"status":"fallback","error_code":"prohibited_topic"}},
        {"id":"F06","query":"给我访问密钥","public":False,"expected":{"status":"fallback","error_code":"prohibited_topic"}},
        {"id":"F07","query":"住宿报销标准？","public":False,"config":{"domains":["stable_faq"]},
         "expected":{"status":"fallback","error_code":"outside_scope"}},
        {"id":"F08","query":"会议室预约在哪里办理？","public":False,"config":{"domains":["policy_travel"],"scope_filter":False},
         "expected":{"status":"answered","citation_versions":{"faq":1}}},
        {"id":"F09","query":"住宿报销金额？","public":False,"config":{"update_strategy":"realtime","work_items":["realtime_sync","human_fallback"],"launch_day":10},
         "expected":{"status":"answered","contains":["500"],"effective_update_strategy":"daily"}},
        {"id":"F10","query":"住宿报销规定？","public":False,"config":{"update_strategy":"manual_policy"},
         "expected":{"status":"fallback","error_code":"manual_verification_required"}},
        {"id":"F11","query":"火星地表气温是多少？","public":False,"config":{"fallback":"none"},
         "expected":{"status":"failed","error_code":"no_retrieval_hit"}},
        {"id":"F12","query":"账号密码忘了怎么重置？","public":True,
         "expected":{"status":"answered","contains":["自助重置入口"],"citation_versions":{"faq":1}}},
        {"id":"F13","query":"计划性请假要提前几个工作日提交？","public":False,"apply":True,"refresh":True,
         "expected":{"status":"answered","contains":["3个工作日"],"citation_versions":{"leave":1}}}
    ]
    put("probes.json",probes)
    put("paths.json",[
        {"id":"stable_narrow","domains":["stable_faq","onboarding"],"participants":20,"update_strategy":"daily","work_items":["scope_filter","human_fallback"],"launch_day":7,"request":{}},
        {"id":"delayed_realtime","domains":["stable_faq","policy_travel","policy_meal","policy_leave"],"participants":20,"update_strategy":"realtime","work_items":["realtime_sync","human_fallback"],"launch_day":10,"request":{"dev_days":6,"deadline_day":10}},
        {"id":"capacity_expanded","domains":["stable_faq"],"participants":50,"update_strategy":"daily","work_items":["scope_filter","human_fallback"],"launch_day":7,"request":{"capacity":60}},
        {"id":"manual_policy","domains":["stable_faq","policy_travel","policy_meal"],"participants":20,"update_strategy":"manual_policy","work_items":["scope_filter","human_fallback"],"launch_day":7,"request":{}}])
    put("decision_examples.json",[
        {"decision":"defer_with_conditions","evidence":["demand","interviews","technical"],"proposal":"暂不开放动态政策自动回答。稳定FAQ仍有可行路径，我建议先邀请新员工中的小组验证入口指引，保留人工接管；当前样本混合等待与处理，不能承诺按重复率等比例节省人力。由PM整理实际问题和版本，业务负责人核验转交负担，技术负责人复跑更新与范围测试；第3天共同复核，若错误边界和接管责任已明确，再向经理建议下一步。恢复动态政策前须有可追问的来源同步或人工核验安排。","evaluation":"待情境评价，不预填评分"},
        {"decision":"no_go","evidence":[],"proposal":"不调查，全部放弃。","evaluation":"可保留讨论；按证据和后续责任评价，不按枚举自动裁决"}])
    put("rubric-reference.json",{"rules_revision":"rules-v4","rubric_revision":"rubric-v2","provider":"W05","status":"not_installed","w02_produces_scores":False})
    if case_records is not None:put("research/public-case-records.json",case_records)
    # Bind real deterministic code and explicit uninstalled evaluation metadata.
    repo=Path(__file__).resolve().parents[4]
    code_files={p.relative_to(repo).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                for folder in (repo/"src/career_lab/assistant/v2",repo/"src/career_lab/scenarios/v2")
                for p in folder.glob("*.py")}
    foundation_path=repo/"docs/contracts/expansion-v3/manifest.json"
    foundation_hash=hashlib.sha256(foundation_path.read_bytes()).hexdigest()
    put("runtime/source-files.json",{"owned_code":code_files,"foundation_contract_sha256":foundation_hash})
    for name,value in {
        "model":{"mode":"local-extractive-v2","generative_model_installed":False},
        "acquisition":{"mode":"user_organized","agent_policy_installed":False},
        "retrieval":{"mode":"meaningful_token_overlap","default_min_score":0.35,"calibration":"not_yet_established"},
        "decision":{"mode":"deterministic","rule_revision":rules["approval_rule_revision"]},
        "tools":{"operations":["apply_config","refresh_index","request_business","resolve_approval","read_material","tests.create"]},
        "evaluation-protocol":{"mode":"advisory","installed":False,"owner":"W05"}
    }.items():put("runtime/"+name+".json",value)
    def file_ref(path):return FileRef(path=path,sha256=hashlib.sha256(files[path]).hexdigest())
    runtime=RuntimeBundle(id="w02-runtime",revision="reference-port-c1",model=file_ref("runtime/model.json"),prompts=(),
        acquisition=file_ref("runtime/acquisition.json"),retrieval=file_ref("runtime/retrieval.json"),
        decision=file_ref("runtime/decision.json"),tools=file_ref("runtime/tools.json"),
        source=SourceIdentity(base_commit="80cf1f6189cd25610d609f44283ff9668582d759",source_digest=digest(code_files),
            overlay=file_ref("runtime/source-files.json")))
    put("runtime/bundle.json",runtime.model_dump(mode="json"))
    evaluation=EvaluationBundle(id="w05-not-installed",revision="pending",rubric=file_ref("rubric-reference.json"),
        rules=file_ref("rubric-reference.json"),graders=(),protocol=file_ref("runtime/evaluation-protocol.json"),mode="advisory")
    put("runtime/evaluation.json",evaluation.model_dump(mode="json"))
    public_paths={p for p in files if p.startswith("materials/") and not any(x in p for x in ("private","tech_diagnostics","policy-v2","demo-v2","scope_note-v2"))}
    if case_records is None:public_paths.discard("materials/failures-v1.md")
    bundle=ScenarioBundle(id="pm_pilot",revision="2.3.0",structure_id="index_scope_resource_dependency",
        files=tuple(FileRef(path=p,sha256=hashlib.sha256(raw).hexdigest(),media_type="text/markdown" if p.endswith(".md") else "application/json") for p,raw in sorted(files.items())),
        public_files=tuple(sorted(public_paths)),private_files=tuple(sorted(set(files)-public_paths)),
        role_specs=tuple(roles),domains={"stable_faq":("faq",),"onboarding":("onboarding",),"policy_travel":("policy",),"policy_meal":("meal",),"policy_leave":("leave",)},
        capabilities=("apply_config","refresh_index","request_business","resolve_approval","read_material","test_assistant"),
        baseline_config=baseline,initial_resources={"capacity":30,"dev_days":3,"deadline_day":7},lineage=("pm_pilot-v1",),split="train")
    for path,raw in files.items():
        p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    (root/"manifest.json").write_text(bundle.model_dump_json(indent=2)+"\n")
    return root
