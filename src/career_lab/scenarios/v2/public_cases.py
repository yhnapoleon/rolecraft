"""Capture public QA evidence from actual module runs, separate from probes."""
from copy import deepcopy
from datetime import datetime,timezone
import re
from career_lab.contracts.v2.core import AuthContext,Command,Executor
from career_lab.contracts.v2.world import TestRequestV2
from career_lab.scenarios.v2.engine import ScenarioEngine
from career_lab.assistant.v2 import Assistant


def record_public_cases(package):
    engine=ScenarioEngine(package);assistant=Assistant(package);records=[]
    auth=AuthContext(session_id="public-qa-run",actor_id="learner",
        executor=Executor(id="w02-public-case-recorder",kind="system"),capabilities=("read","act"),credential_id="module-run-only")
    state=engine.initial(auth.session_id)
    def test(label,query):
        run=assistant.run(state,TestRequestV2(query=query,config_version=state.config.config_version),auth,label)
        records.append({"label":label,"result":run.result.model_dump(mode="json"),"provenance":run.provenance})
    def configure(**changes):
        nonlocal state
        config=state.config.model_copy(update={**changes,"version":state.config.version+1,"config_version":state.config.config_version+1})
        state=engine.plan(state,Command(schema_version=2,request_id="config-"+str(config.version),
            expected_version=state.world.business_seq,expected_workspace_revision=state.world.workspace_revision,
            operation="apply_config",payload={"tool":"apply_config","config":config.model_dump(mode="json")}),auth).snapshot
    test("Q01","会议室预约入口在什么地方")
    test("Q02","我的账号密码忘记了，需要重置")
    test("Q03","入职账号没有开通通知该怎么办")
    test("Q04","设备坏了想报修应该提供哪些信息")
    test("Q05","出差住宿报销一晚能报多少")
    configure()
    test("Q06","出差住宿报销一晚能报多少")
    test("Q07","今天餐费报销每天按什么额度")
    test("Q08","计划性请假提交申请需要提前多久")
    configure(domains=("stable_faq","onboarding"))
    test("Q09","出差住店报销金额按什么规则")
    configure(domains=("policy_travel","policy_meal"),update_strategy="realtime",
              work_items=("realtime_sync","human_fallback"),launch_day=10)
    test("Q10","出差住宿的报销额度")
    configure(update_strategy="manual_policy",work_items=("scope_filter","human_fallback"),launch_day=7)
    test("Q11","住宿费用要按哪个报销标准")
    test("Q12","餐费每日可以报销多少钱")
    return {"schema_version":1,"source_kind":"actual_deterministic_module_run_on_synthetic_scenario",
            "captured_at":datetime.now(timezone.utc).isoformat(),"input_bundle_hash":package.content_hash,
            "executor":"system:w02-public-case-recorder","http_or_human_trial":False,
            "expected_answers_included":False,"records":records}
