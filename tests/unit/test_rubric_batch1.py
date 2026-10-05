import pytest

from career_lab.contracts.evaluation import EvidencePackage, RuleContext
from career_lab.rubrics.checks import CriterionResult, RULES_REVISION, run_rule_checks


def evidence(criterion, *, plan=None, tests=(), **context):
    return EvidencePackage(
        item_id="rule-check", task_type="criterion", criterion=criterion,
        claim="check", as_of_seq=8, candidate_evidence=(), completeness="complete",
        context=RuleContext(**{
            "capacity": 30, "dev_days": 3, "deadline_day": 7,
            "plan": {"participants": 20, "knowledge_domains": ["stable_faq", "policy"],
                     "launch_day": 7, "update_strategy": "daily", "fallback": "human",
                     "work_items": ["scope_filter", "human_fallback"], **(plan or {})},
            "deliverable": {}, "tests": tests,
            "work_costs": {"scope_filter": 1, "human_fallback": 1, "realtime_sync": 4},
            "approvals": (), "policy_updated": True, "policy_update_seq": 4,
            "logs_complete": True, "config_version": 2, **context,
        }),
    )


def observation(version=2, seq=5, id="test-one"):
    return {"id": id, "query": "报销政策是什么？", "fallback": False,
            "stale": False, "config_version": version, "as_of_seq": seq}


def test_resource_reason_affirms_only_a_feasible_plan():
    result = run_rule_checks(evidence("R3.resources"))[0]
    assert result.label == "MET"
    assert result.reason == "工作项成本2/3人日；上线日7/7；必要依赖已核验。"
    assert not result.review_required


@pytest.mark.parametrize(("plan", "context", "reason"), [
    ({"work_items": ["human_fallback"]}, {}, "缺少必要工作项：scope_filter"),
    ({"work_items": ["scope_filter"]}, {}, "缺少必要工作项：human_fallback"),
    ({"update_strategy": "realtime"}, {}, "缺少必要工作项：realtime_sync"),
    ({}, {"dev_days": 1}, "工作项成本超出可用人日"),
    ({"launch_day": 8}, {}, "上线日超出期限"),
    ({"fallback": "none"}, {}, "兜底不是人工"),
    ({"work_items": ["scope_filter", "human_fallback", "unknown"]}, {}, "未知工作项：unknown"),
])
def test_resource_reason_names_failed_constraint(plan, context, reason):
    result = run_rule_checks(evidence("R3.resources", plan=plan, **context))[0]
    assert result.label == "NOT_MET"
    assert reason in result.reason
    assert "必要依赖已核验" not in result.reason


def test_resource_reason_includes_all_failures_without_changing_verdict():
    result = run_rule_checks(evidence("R3.resources", dev_days=0,
        plan={"work_items": ["scope_filter"], "launch_day": 9, "fallback": "none"}))[0]
    assert result.label == "NOT_MET"
    assert all(fragment in result.reason for fragment in (
        "缺少必要工作项：human_fallback", "成本超出可用人日", "上线日超出期限", "兜底不是人工",
    ))


@pytest.mark.parametrize(("tests", "label", "reason"), [
    ((), "NOT_MET", "完整日志中没有实际测试。"),
    ((observation(1), observation(1, id="test-two")), "NOT_MET",
     "有 2 次测试，都不在提交时的配置版本 v2 下。"),
    ((observation(),), "PARTIAL", "存在实际测试；问题覆盖与验收标准仍需语义核验。"),
])
def test_functional_reason_distinguishes_absence_from_other_versions(tests, label, reason):
    result = run_rule_checks(evidence("R4.functional_tests", tests=tests))[0]
    assert (result.label, result.reason) == (label, reason)


@pytest.mark.parametrize(("tests", "reason"), [
    ((), "开放动态政策但完整日志中没有实际测试。"),
    ((observation(seq=2), observation(1, seq=3, id="test-two")),
     "政策更新后没有新的测试（更新前有 2 次）。"),
    ((observation(1),), "政策更新后的 1 次测试都不在提交时的配置版本 v2 下。"),
])
def test_staleness_reason_distinguishes_test_time_and_version(tests, reason):
    result = run_rule_checks(evidence("R4.staleness_test", tests=tests))[0]
    assert (result.label, result.reason, result.review_required) == ("NOT_MET", reason, False)


def test_staleness_current_version_after_update_still_requires_review():
    result = run_rule_checks(evidence("R4.staleness_test", tests=(observation(seq=4),)))[0]
    assert result.label == "INSUFFICIENT"
    assert result.review_required
    assert result.reason == "已有测试，仍需核验是否在政策更新后覆盖风险并用于决策。"


@pytest.mark.parametrize("plan", [
    {"knowledge_domains": ["stable_faq"]}, {"update_strategy": "manual_policy"},
])
def test_staleness_not_automatically_answering_policy_remains_not_applicable(plan):
    assert run_rule_checks(evidence("R4.staleness_test", plan=plan))[0].label == "NOT_APPLICABLE"


@pytest.mark.parametrize(("completeness", "reason"), [
    ("overflow", "证据超过长度上限，本项未评。"),
    ("missing", "材料或日志不完整，暂不扣分。"),
])
def test_completeness_preserves_abstention_and_explains_overflow(completeness, reason):
    item = evidence("R3.resources").model_copy(update={"completeness": completeness, "context": None})
    result = run_rule_checks(item)[0]
    assert (result.label, result.reason, result.completeness) == ("INSUFFICIENT", reason, completeness)
    assert result.review_required
    assert result.model_dump(mode="json")["completeness"] == completeness


def test_rules_revision_and_old_criterion_default():
    assert RULES_REVISION == "rules-v3"
    assert CriterionResult(criterion_id="R3.resources", label="MET").completeness == "complete"
