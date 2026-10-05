from typing import Literal

from career_lab.contracts.base import Contract
from career_lab.contracts.evaluation import CriterionLabel, EvidencePackage

RULES_REVISION = "rules-v3"


class CriterionResult(Contract):
    criterion_id: str
    label: CriterionLabel
    reason: str = ""
    evidence_ids: tuple[str, ...] = ()
    review_required: bool = False
    completeness: Literal["complete", "missing", "overflow"] = "complete"


def run_rule_checks(item: EvidencePackage) -> list[CriterionResult]:
    key, ctx = item.criterion, item.context
    label, reason, review = "INSUFFICIENT", "该项需要进一步语义核验。", True
    if item.completeness == "overflow":
        reason = "证据超过长度上限，本项未评。"
    elif item.completeness != "complete" or ctx is None or not ctx.logs_complete:
        reason = "材料或日志不完整，暂不扣分。"
    elif key == "R3.capacity":
        label = "MET" if 0 < ctx.plan.participants <= ctx.capacity else "NOT_MET"
        reason, review = f"提交人数{ctx.plan.participants}，当前有效上限{ctx.capacity}。", False
    elif key == "R3.resources":
        work = set(ctx.plan.work_items)
        required = {"realtime_sync" if ctx.plan.update_strategy == "realtime" else "scope_filter", "human_fallback"}
        total = sum(ctx.work_costs.get(w, 0) for w in work)
        failures = []
        if required - work:
            failures.append("缺少必要工作项：" + "、".join(sorted(required - work)))
        if work - ctx.work_costs.keys():
            failures.append("未知工作项：" + "、".join(sorted(work - ctx.work_costs.keys())))
        if total > ctx.dev_days:
            failures.append("工作项成本超出可用人日")
        if ctx.plan.launch_day > ctx.deadline_day:
            failures.append("上线日超出期限")
        if ctx.plan.fallback != "human":
            failures.append("兜底不是人工")
        label, review = ("NOT_MET" if failures else "MET"), False
        reason = f"工作项成本{total}/{ctx.dev_days}人日；上线日{ctx.plan.launch_day}/{ctx.deadline_day}；" + ("；".join(failures) if failures else "必要依赖已核验") + "。"
    elif key == "R4.functional_tests":
        tests = [t for t in ctx.tests if t.config_version == ctx.config_version]
        if not tests:
            label, review = "NOT_MET", False
            reason = f"有 {len(ctx.tests)} 次测试，都不在提交时的配置版本 v{ctx.config_version} 下。" if ctx.tests else "完整日志中没有实际测试。"
        else:
            label, reason = "PARTIAL", "存在实际测试；问题覆盖与验收标准仍需语义核验。"
    elif key == "R4.staleness_test":
        if not ctx.policy_updated:
            label, reason, review = "NOT_APPLICABLE", "提交前没有政策变化事件，尚无更新后测试窗口。", False
        elif "policy" not in ctx.plan.knowledge_domains or ctx.plan.update_strategy == "manual_policy":
            label, reason, review = "NOT_APPLICABLE", "未向用户自动回答动态政策。", False
        elif not any(t.config_version == ctx.config_version and ctx.policy_update_seq is not None and t.as_of_seq >= ctx.policy_update_seq for t in ctx.tests):
            label, review = "NOT_MET", False
            before = sum(ctx.policy_update_seq is not None and t.as_of_seq < ctx.policy_update_seq for t in ctx.tests)
            after = len(ctx.tests) - before if ctx.policy_update_seq is not None else 0
            if after:
                reason = f"政策更新后的 {after} 次测试都不在提交时的配置版本 v{ctx.config_version} 下。"
            elif before:
                reason = f"政策更新后没有新的测试（更新前有 {before} 次）。"
            else:
                reason = "开放动态政策但完整日志中没有实际测试。"
        else:
            reason = "已有测试，仍需核验是否在政策更新后覆盖风险并用于决策。"
    elif key in {"R5.impact", "R5.adjustment"} and not ctx.policy_updated:
        label, reason, review = "NOT_APPLICABLE", "提交时尚无政策变化事件。", False
    elif key == "R6.operations":
        fields = (ctx.deliverable.owner, ctx.deliverable.observation_window, ctx.deliverable.exit_condition)
        if not any(x.strip() for x in fields):
            label, reason, review = "NOT_MET", "完整成果中没有负责人、观察窗口和退出条件。", False
        elif not all(x.strip() for x in fields):
            label, reason = "PARTIAL", "运行安排缺少部分必要字段；内容可执行性仍需核验。"
    elif key == "R1.target" and not ctx.deliverable.goal.strip():
        label, reason, review = "NOT_MET", "完整成果中未定义业务目标。", False
    elif key == "R1.metrics" and not ctx.deliverable.metrics.strip():
        label, reason, review = "NOT_MET", "完整成果中未定义成功指标。", False
    ids = tuple(e.id for e in item.candidate_evidence if e.id in item.source_map and item.source_map[e.id].kind in {"config", "event", "artifact", "test_result"})
    return [CriterionResult(criterion_id=key, label=label, reason=reason, evidence_ids=ids, review_required=review, completeness=item.completeness)]
