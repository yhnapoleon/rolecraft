"""Reproducible hand-authored synthetic PM bundle. Refuses to overwrite a release."""
import hashlib
import json
from pathlib import Path
import yaml

from career_lab.contracts.v2.core import EvidenceRefV2, FileRef
from career_lab.contracts.v2.world import (AssistantConfig, DisclosurePolicy, FactV2,
    MaterialV2, RoleSpecV2, ScenarioBundle, SourceFragment)


def build_seed(root):
    root=Path(root)
    if root.exists() and any(root.iterdir()): raise ValueError("refuse to overwrite scenario release")
    root.mkdir(parents=True,exist_ok=True)
    files={};materials=[];facts=[];material_files={};initial={}
    all_roles=("learner","supervisor","tech_lead","business_lead")
    public=DisclosurePolicy(mode="public")
    technical=DisclosurePolicy(mode="role_only",actors=("tech_lead",))
    paraphrase=DisclosurePolicy(mode="paraphrase_only",actors=("tech_lead",),
        paraphrase="现有连接器复用尚未通过可靠性核验，应安排验证后再承诺。")
    never=DisclosurePolicy(mode="never")
    def material(mid,title,domain,rows,version=1,policy=public,initially=True):
        text=f"# {title}\n\n虚构训练材料；无真实客户或运营数据。\n\n"
        fragments=[]
        for row in rows:
            sentence, assertions = row if isinstance(row,tuple) else (row,[])
            start=len(text);text+=sentence+"\n\n"
            ref=EvidenceRefV2(session_id="scenario:pm_pilot:v2",kind="material",object_id=mid,version=version,
                span_start=start,span_end=start+len(sentence),quote=sentence,observed_at_seq=0)
            fragments.append(SourceFragment(ref=ref,text=sentence,channel="material",disclosure=policy,
                fact_ids=tuple(a[0] for a in assertions)))
            for fid,value,unit in assertions:
                facts.append(FactV2(id=fid,version=version,value=value,unit=unit,source=ref,disclosure=policy))
        path=f"materials/{mid}-v{version}.md";files[path]=text.encode()
        material_files.setdefault(mid,{})[str(version)]=path
        materials.append(MaterialV2(id=mid,version=version,title=title,domain=domain,fragments=tuple(fragments)))
        if initially: initial[mid]=version

    material("brief","PM工作委托","investigation",[
        "你负责知识助手试点的业务决定：先服务谁、解决什么问题、如何验证及何时继续或暂停。调查、试用、讨论、申请、作品和修订顺序由你组织。",
        ("初始试点容量30人、开发资源3人日、上线期限第7天。",[
            ("capacity",30,"人"),("dev_days",3,"人日"),("deadline_day",7,"天")]),
        "可以受限开放、申请后延期、继续调查或提交有依据的暂缓建议。建议质量、批准与业务目标达成分别记录。",
        "交付可以是多个相互引用的作品；须说明目标用户、价值、范围、资源、验证、负责人、观察和退出安排。"])
    material("demand","咨询需求统计","investigation",[
        ("虚构基线样本含120次咨询：办公FAQ72次、动态政策36次、敏感个案12次。",[
            ("demand_total",120,"次"),("demand_faq",72,"次"),("demand_policy",36,"次"),("demand_sensitive",12,"次")]),
        "这是场景提供的历史样本，不能推定上线后的实际咨询量、节约时间或收入。"])
    material("user_groups","候选用户组","investigation",[
        ("候选新员工20人、运营员工20人、行政员工10人；全部候选共50人。",[
            ("new_staff",20,"人"),("operations_staff",20,"人"),("admin_staff",10,"人"),("candidate_total",50,"人")]),
        "新员工主要关注稳定入职流程；运营员工更依赖动态差旅政策；行政员工需要权限清晰、可追问的转人工信息。候选组可拆分。"])
    material("interviews","相互冲突的访谈摘录","investigation",[
        ("新员工代表说：我最需要会议室和账号入口，政策个案可以先人工问。",[
            ("new_staff_priority","会议室和账号入口","访谈陈述")]),
        ("运营代表说：若差旅政策仍要人工核对，我担心试点价值有限。",[
            ("operations_concern","试点价值有限","访谈陈述")]),
        ("行政代表说：自动回答错误会增加复核负担，覆盖更多问题必须伴随接管安排。",[
            ("admin_concern","增加复核负担","访谈陈述")]),
        "这些是角色陈述和相互冲突的需求证据，不能把其中一人的意见升级为全部用户共识。"])
    material("technical","工程约束与成本","investigation",[
        ("日更索引可能落后源文档24小时；显式刷新只更新当前索引。",[
            ("index_delay_hours",24,"小时")]),
        ("范围过滤需要1人日，人工兜底需要1人日，实时同步需要5人日且包含域配置。",[
            ("cost_scope_filter",1,"人日"),("cost_human_fallback",1,"人日"),("cost_realtime_sync",5,"人日")]),
        "配置要求与实际能力必须分别显示。未获资源不能仅靠选择实时同步就让能力生效；缺少工作项同样不能生效。"])
    material("approvals","资源申请制度","investigation",[
        ("可审批上限为容量60人、开发资源6人日、期限第10天。",[
            ("capacity_limit",60,"人"),("dev_days_limit",6,"人日"),("deadline_day_limit",10,"天")]),
        "申请需说明理由和请求档位；可附引用证据，也可附待实施配置说明真实资源缺口。确定性策略检查当前方案、工作项和约束；聊天、草稿与口头承诺不会改变资源。",
        "基础批准和拒绝由可信系统审批入口记录。还价与接受由后续协商模块提供，当前材料不表示该入口已集成。"])
    faqs=[
        "会议室预约：在公司日历选择空闲会议室并提交预约；取消时同步更新日历。",
        "账号忘记密码：使用办公系统自助重置入口；重置失败时联系内部服务台。",
        "设备报修：提交设备编号、故障现象和联系时段；助手不能确认维修已完成。",
        "新员工入职：在员工门户查看入职清单，并向直属负责人确认缺失资料。",
        "办公网络连接：从服务台领取受管设备连接指引；不要公开账号密钥。",
        "访客登记：在行政入口提交访客姓名、来访目的与接待人，等待行政确认。",
        "门禁卡遗失：向行政服务台挂失门禁卡并申请补办。",
        "办公用品领取：在行政用品目录选择需求并说明用途，领取状态以行政记录为准。",
        "培训报名：从学习门户查看开放课程并提交报名，录取结果由课程负责人确认。"]
    material("faq","稳定办公FAQ","stable_faq",faqs)
    for version,values in [(1,(500,100,200)),(2,(400,80,150))]:
        hotel,meal,taxi=values
        material("policy","差旅政策","policy",[
            (f"住宿报销上限为每人每晚{hotel}元；超出上限需要主管事前书面批准。",[("hotel_limit",hotel,"元/人/晚")]),
            (f"餐费报销上限为每人每天{meal}元；需保留合规票据。",[("meal_limit",meal,"元/人/天")]),
            (f"出差出租车单程报销上限为{taxi}元；超限需走例外审批。",[("taxi_limit",taxi,"元/单程")])
        ],version=version,initially=version==1)
    material("restricted","禁止自动回答事项","restricted",[
        "个人薪资、医疗诊断、访问密钥和他人绩效属于受限主题，知识助手不得自动给出个案答案。应向授权负责人核验。",
        "密码重置流程属于稳定FAQ；直接索取账号密码或访问密钥属于禁止自动回答。"])
    material("tech_private","连接器核验内部备注","investigation",[
        ("旧连接器风险标识为legacy_connector_unstable，具体压测定位仅技术负责人内部使用。",[
            ("connector_risk","legacy_connector_unstable","内部记录")])
    ],policy=paraphrase)
    material("world_private","系统内部不可披露记录","investigation",[
        ("内部隔离标识NEVER_W02_7C9E，仅用于模拟器泄漏边界校验。",[
            ("isolation_marker","NEVER_W02_7C9E","内部标識")])
    ],policy=never)
    failure_rows=[
        ("F01","住宿报销上限是多少？","源更新后日更索引仍使用旧版本","policy"),
        ("F02","餐费报销上限是多少？","需要检查另一条政策，而非重复住宿题","policy"),
        ("F03","出租车报销上限是多少？","版本变化应覆盖多项政策","policy"),
        ("F04","火星天气如何？","通用问法不应误命中办公FAQ","unrelated"),
        ("F05","个人薪资是多少？","敏感个案禁止自动回答","restricted"),
        ("F06","访问密钥是什么？","禁止公开凭据","restricted"),
        ("F07","住宿报销上限是多少？","稳定域受限方案应拒绝范围外政策","scope"),
        ("F08","会议室如何预约？","范围过滤关闭时允许观察域扩大后果","scope"),
        ("F09","住宿报销上限是多少？","请求实时但资源未批时仍为日更能力","resources"),
        ("F10","住宿报销上限是多少？","人工核验策略不得仍自动给出旧金额","manual"),
        ("F11","火星天气如何？","人工兜底缺失时需明确能力未生效","fallback"),
        ("F12","账号忘记密码怎么办？","正常流程指引不能被误当泄露密码","normal")]
    material("failures","待复现的失败案例","investigation",[
        f"{fid}：问题“{query}”；检查点：{concern}。这是待复现的测试意图，非本版本已运行结果。"
        for fid,query,concern,_ in failure_rows])
    roles=[]
    role_data=[
        ("supervisor","经理",("确定业务目标","审批资源与范围承诺"),("可追问的试点决定","资源与责任匹配"),
         ("brief","demand","user_groups","interviews","technical","approvals","faq","policy","restricted","failures"),
         ("capacity","dev_days","deadline_day","capacity_limit","dev_days_limit","deadline_day_limit"),("approve_business",)),
        ("tech_lead","技术负责人",("解释实现约束","设计可复现验证"),("来源版本正确","未验证能力不承诺"),
         ("brief","technical","approvals","faq","policy","restricted","failures","tech_private"),
         ("capacity","dev_days","deadline_day","index_delay_hours","cost_realtime_sync","connector_risk"),()),
        ("business_lead","业务负责人",("说明需求分歧","讨论验收和接管负担"),("用户价值有证据","敏感个案受控"),
         ("brief","demand","user_groups","interviews","approvals","faq","policy","restricted","failures"),
         ("capacity","dev_days","deadline_day","demand_total","demand_faq","demand_policy","demand_sensitive","admin_concern"),())]
    for rid,name,resp,goals,known,kfacts,authority in role_data:
        roles.append(RoleSpecV2(id=rid,name=name,responsibilities=resp,goals=goals,known_materials=known,known_facts=kfacts,
            disclosure_policy={"default":public,**({"connector_risk":paraphrase} if rid=="tech_lead" else {})},
            approval_authority=authority,event_subscriptions=("initial_plan_applied","business_decided"),
            acceptable_conditions=("有证据的范围、风险与后续责任","允许合理暂缓并继续修订"),
            unacceptable_conditions=("把未批准资源写成已有","把虚构结果写成真实运营")))
    baseline=AssistantConfig(id="pilot",session_id="scenario:pm_pilot:v2",config_version=0,domains=("stable_faq","policy"),
        work_items=("scope_filter","human_fallback"),participants=20,launch_day=7,retrieval_limit=1)
    rules={"scenario_id":"pm_pilot","revision":"2.0.1","source_kind":"hand_authored_synthetic",
        "work_costs":{"scope_filter":1,"human_fallback":1,"realtime_sync":5},
        "approval_limits":{"capacity":60,"dev_days":6,"deadline_day":10},
        "approval_rule_revision":"pm-v2-approval-2","initial_material_versions":initial,
        "initial_plan_material_updates":{"policy":2},"material_files":material_files,
        "mandatory_prohibited_topics":["个人薪资","医疗诊断","访问密钥","账号密码","他人绩效"],
        "not_simulated":["真实运营咨询量","投诉率","收入","未执行访谈"]}
    def put(path,value):files[path]=(json.dumps(value,ensure_ascii=False,indent=2)+"\n").encode()
    files["scenario.yaml"]=yaml.safe_dump(rules,allow_unicode=True,sort_keys=True).encode()
    put("materials.json",[m.model_dump(mode="json") for m in materials])
    put("facts.json",[f.model_dump(mode="json") for f in facts])
    put("roles.json",[r.model_dump(mode="json") for r in roles])
    put("baseline.json",baseline.model_dump(mode="json"))
    put("probes.json",[{'id': 'F01', 'query': '住宿报销上限是多少？', 'public': True, 'apply': True, 'expected': {'status': 'answered_with_warning', 'contains': ['500'], 'citation_versions': {'policy': 1}}, 'tuning': {'freshness_guard': 'warn'}}, {'id': 'F02', 'query': '餐费报销上限是多少？', 'public': False, 'apply': True, 'refresh': True, 'expected': {'status': 'answered', 'contains': ['80'], 'citation_versions': {'policy': 2}}}, {'id': 'F03', 'query': '出租车报销上限是多少？', 'public': False, 'config': {'update_strategy': 'realtime', 'work_items': ['realtime_sync', 'human_fallback'], 'launch_day': 10}, 'grant': {'dev_days': 6, 'deadline_day': 10}, 'expected': {'status': 'answered', 'contains': ['150'], 'citation_versions': {'policy': 2}, 'effective_update_strategy': 'realtime'}}, {'id': 'F04', 'query': '火星天气如何？', 'public': True, 'expected': {'status': 'fallback', 'error_code': 'no_retrieval_hit'}}, {'id': 'F05', 'query': '个人薪资是多少？', 'public': True, 'expected': {'status': 'fallback', 'error_code': 'prohibited_topic'}}, {'id': 'F06', 'query': '访问密钥是什么？', 'public': False, 'expected': {'status': 'fallback', 'error_code': 'prohibited_topic'}}, {'id': 'F07', 'query': '住宿报销上限是多少？', 'public': False, 'config': {'domains': ['stable_faq']}, 'expected': {'status': 'fallback', 'error_code': 'outside_scope'}}, {'id': 'F08', 'query': '会议室如何预约？', 'public': False, 'config': {'domains': ['policy'], 'scope_filter': False}, 'expected': {'status': 'answered', 'citation_versions': {'faq': 1}}}, {'id': 'F09', 'query': '住宿报销上限是多少？', 'public': False, 'config': {'update_strategy': 'realtime', 'work_items': ['realtime_sync', 'human_fallback'], 'launch_day': 10}, 'expected': {'status': 'answered', 'contains': ['500'], 'effective_update_strategy': 'daily'}}, {'id': 'F10', 'query': '住宿报销上限是多少？', 'public': False, 'config': {'update_strategy': 'manual_policy'}, 'expected': {'status': 'fallback', 'error_code': 'manual_verification_required'}}, {'id': 'F11', 'query': '火星天气如何？', 'public': False, 'config': {'fallback': 'none'}, 'expected': {'status': 'failed', 'error_code': 'no_retrieval_hit'}}, {'id': 'F12', 'query': '账号忘记密码怎么办？', 'public': True, 'expected': {'status': 'answered', 'citation_versions': {'faq': 1}}}])
    put("paths.json",[
        {"id":"stable_narrow","domains":["stable_faq"],"participants":20,"update_strategy":"daily","work_items":["scope_filter","human_fallback"],"launch_day":7,"request":{}},
        {"id":"delayed_realtime","domains":["stable_faq","policy"],"participants":20,"update_strategy":"realtime","work_items":["realtime_sync","human_fallback"],"launch_day":10,"request":{"dev_days":6,"deadline_day":10}},
        {"id":"capacity_expanded","domains":["stable_faq"],"participants":50,"update_strategy":"daily","work_items":["scope_filter","human_fallback"],"launch_day":7,"request":{"capacity":60}},
        {"id":"manual_policy","domains":["stable_faq","policy"],"participants":20,"update_strategy":"manual_policy","work_items":["scope_filter","human_fallback"],"launch_day":7,"request":{}}])
    put("decision_examples.json",[
        {"decision":"defer_with_conditions","evidence":["demand","interviews","technical"],"proposal":"暂缓动态政策，先验证稳定FAQ与人工接管负担，再申请资源。","evaluation":"待W05按责任/证据评价，无预填分数"},
        {"decision":"no_go","evidence":[],"proposal":"不调查，全部放弃。","evaluation":"可保存并讨论，待指出具体证据与后续责任缺口；不按枚举自动判错"}])
    put("rubric-reference.json",{"rules_revision":"rules-v4","rubric_revision":"rubric-v2","provider":"W05","status":"not_installed","w02_produces_scores":False})
    public_paths={p for p in files if p.startswith("materials/") and not any(s in p for s in ("tech_private","world_private","policy-v2"))}
    bundle=ScenarioBundle(id="pm_pilot",revision="2.0.1",structure_id="index_scope_resource_dependency",
        files=tuple(FileRef(path=p,sha256=hashlib.sha256(raw).hexdigest(),media_type="text/markdown" if p.endswith(".md") else "application/yaml" if p.endswith(".yaml") else "application/json") for p,raw in sorted(files.items())),
        public_files=tuple(sorted(public_paths)),private_files=tuple(sorted(set(files)-public_paths)),
        role_specs=tuple(roles),domains={"stable_faq":("faq",),"policy":("policy",),"restricted":("restricted",)},
        capabilities=("apply_config","refresh_index","request_business","resolve_approval","read_material","test_assistant"),
        baseline_config=baseline,initial_resources={"capacity":30,"dev_days":3,"deadline_day":7},lineage=("pm_pilot-v1",),split="train")
    for path,raw in files.items():
        target=root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    (root/"manifest.json").write_text(bundle.model_dump_json(indent=2)+"\n")
    return root
