"""Approval decisions record the terms, the plan's need and the published rule sentences.

Every installed package (main scenario and both variants, Chinese and English) is
exercised. Status, reason code and reason text stay exactly what the policy decided.
"""

from dataclasses import replace

import pytest

from career_lab.scenarios.v2 import ScenarioEngine, load_package
from career_lab.scenarios.v2.policy import evaluate_request
from tests.support.scenario_packages import installed_locale_root

from .conftest import apply, auth, command
from .test_engine import approve

PACKAGES = [
    (sid, lang)
    for sid in ("pm_pilot", "pm_pilot_urgent", "pm_pilot_capacity15")
    for lang in ("zh", "en")
]
CEILINGS = {
    "zh": "可审批上限：容量60人，开发资源6人日，期限第10天。",
    "en": "Approval ceilings: capacity 60 people, 6 developer-days, and deadline day 10.",
}


@pytest.fixture(params=PACKAGES, ids=["-".join(p) for p in PACKAGES])
def installed(request):
    sid, language = request.param
    return ScenarioEngine(load_package(installed_locale_root(sid, language))), language


def rows(assessment):
    return [term.model_dump(mode="json", exclude={"schema_version"}) for term in assessment.terms]


def test_over_ceiling_request_records_each_number_and_the_ceiling_sentence(installed):
    engine, language = installed
    realtime = ("scope_filter", "human_fallback", "realtime_sync")
    s = apply(engine, engine.initial("session"), update_strategy="realtime", work_items=realtime)
    result = approve(engine, s.snapshot, {"dev_days": 7})
    decision = result.result
    assert (decision.status, decision.reason_code) == ("rejected", "request_over_limit")
    assessment = decision.assessment
    assert rows(assessment) == [
        {
            "resource": "dev_days",
            "current": 3,
            "requested": 7,
            "limit": 6,
            "needed": 7,
            "issues": ["over_limit", "need_over_limit"],
        }
    ]
    assert assessment.missing_work_items == () and assessment.fallback_required is False
    ceiling = assessment.clauses[0]
    assert (ceiling.session_id, ceiling.kind, ceiling.object_id, ceiling.version) == (
        "session",
        "material",
        "approvals",
        1,
    )
    assert ceiling.quote == CEILINGS[language]
    assert engine.material_evidence_valid(result.snapshot, ceiling)


def test_mixed_request_names_every_problem_not_only_the_first(installed):
    # 164 walkthrough: real-time strategy without the real-time work item, asking for
    # 7 developer-days and repeating the unchanged deadline.
    engine, language = installed
    start = engine.initial("session")
    deadline = start.world.resources["deadline_day"]
    s = apply(
        engine,
        start,
        update_strategy="realtime",
        work_items=("scope_filter", "human_fallback"),
        launch_day=deadline,
    )
    result = approve(engine, s.snapshot, {"dev_days": 7, "deadline_day": deadline})
    decision = result.result
    assert (decision.status, decision.reason_code) == ("rejected", "request_over_limit")
    assessment = decision.assessment
    assert rows(assessment) == [
        {
            "resource": "deadline_day",
            "current": deadline,
            "requested": deadline,
            "limit": 10,
            "needed": deadline,
            "issues": ["no_increase", "no_shortfall"],
        },
        {
            "resource": "dev_days",
            "current": 3,
            "requested": 7,
            "limit": 6,
            "needed": 2,
            "issues": ["over_limit", "no_shortfall"],
        },
    ]
    assert assessment.missing_work_items == ("realtime_sync",)
    ceiling, shortfall, safeguards = assessment.clauses
    assert ceiling.quote == CEILINGS[language]
    assert ("整单退回" if language == "zh" else "returned as a whole") in shortfall.quote
    assert "realtime_sync" in safeguards.quote and "human_fallback" in safeguards.quote
    assert all(engine.material_evidence_valid(result.snapshot, c) for c in assessment.clauses)


def test_lowering_a_term_is_told_apart_from_exceeding_the_ceiling(installed):
    engine, language = installed
    start = engine.initial("session")
    deadline = start.world.resources["deadline_day"]
    s = apply(engine, start, launch_day=9)
    result = approve(engine, s.snapshot, {"deadline_day": deadline - 1})
    decision = result.result
    assert (decision.status, decision.reason_code) == ("rejected", "request_over_limit")
    assert rows(decision.assessment) == [
        {
            "resource": "deadline_day",
            "current": deadline,
            "requested": deadline - 1,
            "limit": 10,
            "needed": 9,
            "issues": ["below_current", "insufficient"],
        }
    ]
    (shortfall,) = decision.assessment.clauses
    assert ("真实配置缺口" if language == "zh" else "real configuration shortfall") in (
        shortfall.quote
    )


def test_approval_records_covered_terms_and_when_resources_take_effect(installed):
    engine, language = installed
    s = apply(
        engine,
        engine.initial("session"),
        update_strategy="realtime",
        work_items=("human_fallback", "realtime_sync"),
    )
    result = approve(engine, s.snapshot, {"dev_days": 6})
    decision = result.result
    assert (decision.status, decision.granted) == ("approved", {"dev_days": 6})
    assert rows(decision.assessment) == [
        {
            "resource": "dev_days",
            "current": 3,
            "requested": 6,
            "limit": 6,
            "needed": 6,
            "issues": [],
        }
    ]
    shortfall, effect = decision.assessment.clauses
    assert ("真实配置缺口" if language == "zh" else "real configuration shortfall") in (
        shortfall.quote
    )
    assert ("决定记录生效后才调整资源额度" if language == "zh" else "change only after") in (
        effect.quote
    )


def test_incomplete_plan_lists_missing_safeguards_and_cites_them(installed):
    engine, language = installed
    s = apply(
        engine,
        engine.initial("session"),
        work_items=("human_fallback",),
        fallback="none",
        participants=50,
    )
    result = approve(engine, s.snapshot, {"capacity": 60})
    decision = result.result
    assert (decision.status, decision.reason_code) == ("rejected", "approval_plan_incomplete")
    assert decision.assessment.missing_work_items == ("scope_filter",)
    assert decision.assessment.fallback_required is True
    assert "human_fallback" in decision.assessment.clauses[0].quote


REASONS = {
    "zh": {
        "request_over_limit": "请求超过当前可审批上限，或试图降低既有资源；"
        "请对照审批规则调整条款。",
        "request_not_needed": "所请求条款未显示新增缺口；"
        "请按实际目标人数、工作成本与日期重新说明需要。"
        " 开发人日：现有3，方案需要6，请求6；正式试点期限：现有7，方案需要7，请求7",
        "requested_resources_insufficient": "所请求资源仍不足以支持该条款对应的拟实施方案。",
        "within_scenario_limits": "申请条款存在真实缺口且在可审批范围内；"
        "决定提交成功后资源才生效。",
    },
    "en": {
        "request_over_limit": "The request exceeds an approval ceiling or would reduce an existing "
        "allocation. Check the published approval rules.",
        "request_not_needed": "The requested terms do not demonstrate an additional shortfall. "
        "Recheck the target participants, work-item costs and date. Developer-days: allocated 3, "
        "proposed need 6, requested 6; Pilot deadline day: allocated 7, proposed need 7, "
        "requested 7",
        "requested_resources_insufficient": "The requested amount is still insufficient for the "
        "corresponding proposed configuration.",
        "within_scenario_limits": "The request has a genuine shortfall and is within the approval "
        "ceilings. Resources change only after the decision commits successfully.",
    },
}


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize(
    "work_items,terms,code",
    [
        (
            ("human_fallback", "realtime_sync", "scope_filter"),
            {"dev_days": 7},
            "request_over_limit",
        ),
        (
            ("human_fallback", "realtime_sync"),
            {"dev_days": 6, "deadline_day": 7},
            "request_not_needed",
        ),
        (
            ("human_fallback", "realtime_sync", "scope_filter"),
            {"dev_days": 6},
            "requested_resources_insufficient",
        ),
        (("human_fallback", "realtime_sync"), {"dev_days": 6}, "within_scenario_limits"),
    ],
)
def test_assessment_leaves_the_decision_and_its_reason_unchanged(language, work_items, terms, code):
    engine = ScenarioEngine(load_package(installed_locale_root("pm_pilot", language)))
    s = apply(engine, engine.initial("session"), update_strategy="realtime", work_items=work_items)
    request = engine.plan(
        s.snapshot,
        command(s.snapshot, "request_business", "r", terms=terms, reason="按方案申请"),
        auth(),
    )

    def decide():
        return evaluate_request(engine.package, request.result, request.snapshot, lambda _: True)

    decision = decide()
    assert (decision.reason_code, decision.reason) == (code, REASONS[language][code])
    assert decide() == decision


def test_unrecognised_rules_layout_records_no_clause_rather_than_a_wrong_one(installed):
    engine, _ = installed
    package = engine.package
    shortened = replace(
        package,
        materials=tuple(
            m.model_copy(update={"fragments": m.fragments[:5]}) if m.id == "approvals" else m
            for m in package.materials
        ),
    )
    engine = ScenarioEngine(shortened)
    s = apply(engine, engine.initial("session"), update_strategy="realtime")
    decision = approve(engine, s.snapshot, {"dev_days": 7}).result
    assert decision.assessment.terms and decision.assessment.clauses == ()
