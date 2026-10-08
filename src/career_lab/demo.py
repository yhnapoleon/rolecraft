from pathlib import Path

from career_lab.api.feedback import generate_feedback
from career_lab.api.timeline import timeline
from career_lab.assistant.service import TrainingService
from career_lab.runtime.loop import AgentRuntime
from career_lab.runtime.model_adapter import LocalModel
from career_lab.scenarios.loader import load_scenario
from career_lab.storage.sessions import SessionStore


def run_demo(database_url: str, scenario_path: Path, model=None):
    store = SessionStore(database_url)
    spec = load_scenario(scenario_path)
    sid = store.create_session(spec).session_id
    service = TrainingService(store)
    plan = {
        "participants": min(20, spec.constraints.capacity),
        "knowledge_domains": ["stable_faq", "policy"],
        "launch_day": min(7, spec.constraints.deadline_day),
        "update_strategy": "daily",
        "fallback": "human",
        "work_items": ["scope_filter", "human_fallback"],
    }
    service.action(sid, "update_pilot", {"plan": plan}, "config", 0)
    service.action(sid, "read_material", {"material_id": "technical"}, "read", 1)
    turn = AgentRuntime(store, model or LocalModel()).run_turn(
        sid, "tech_lead", "请说明容量、资源与索引风险。", "turn"
    )
    stale = service.run_assistant_test(sid, "住宿报销上限是多少？", 1, "stale-test")
    state = store.get_state(sid)
    plan["knowledge_domains"] = ["stable_faq"]
    service.action(sid, "update_pilot", {"plan": plan}, "safer-config", state.version)
    service.run_assistant_test(sid, "如何申请会议室？", 2, "faq-test")
    service.run_assistant_test(sid, "火星天气如何？", 2, "ood-test")
    artifact = service.save_artifact(
        sid,
        {
            "goal": "帮助内部员工处理稳定办公咨询",
            "owner": "试点PM",
            "metrics": "人工核验有效解答率达到80%",
            "observation_window": "上线后7天",
            "exit_condition": "出现严重错误即暂停并人工处理",
            "rationale": "政策测试出现过期答案，因此首期限制稳定FAQ，动态政策转人工。",
        },
        "artifact",
    )
    submission = service.submit_plan(sid, artifact["id"], 2, "submit")
    feedback = generate_feedback(store, sid, submission["id"])
    before = timeline(store, sid)
    store.close()
    reopened = SessionStore(database_url)
    stable = before == timeline(reopened, sid)
    result = {
        "session_id": sid,
        "scenario": spec.id,
        "state_status": reopened.get_state(sid).status,
        "source_versions": stale["source_versions"],
        "indexed_versions": stale["indexed_versions"],
        "stale_answer_detected": stale["stale"],
        "model_revision": turn["model_revision"],
        "replay_stable": stable,
        "feedback": feedback,
    }
    reopened.close()
    return result
