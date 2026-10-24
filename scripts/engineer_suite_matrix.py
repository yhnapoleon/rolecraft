"""Print candidate configurations x engineer regression probes, for review.

Run from the repository root with the project environment:

    .venv/bin/python -m scripts.engineer_suite_matrix [--language zh|en|both]

The world is the installed pm_pilot release after the first configuration.apply:
policy v2 is published while the index still holds v1. Every probe of the
engineer suite runs under one candidate configuration through the reviewer's own
execute_suite (rule retrieval, no recognition layer, no model). Each candidate
is the session's current configuration plus the listed changes. Read-only:
nothing is written and no provider is called.
"""

import argparse
from typing import Any

from career_lab.api.vertical_runtime import default_installed_scenario
from career_lab.contracts import v2 as C
from career_lab.contracts.v2.engineer import EngineerProbeResult
from career_lab.engineer.execution import execute_suite
from career_lab.engineer.suite import engineer_suite, validate_suite
from career_lab.scenarios.v2.__main__ import auth, plan
from career_lab.scenarios.v2.engine import ScenarioSnapshot
from career_lab.scenarios.v2.module import ScenarioModule

SESSION = "engineer-suite-matrix"
KNOWLEDGE_DOMAINS_WITHOUT_ONBOARDING = [
    "stable_faq",
    "policy_travel",
    "policy_meal",
    "policy_leave",
]

# Changes applied to the session's current configuration. The first nine are
# pinned by tests/integration/test_engineer_suite.py; the rest are shown for review.
CANDIDATES: dict[str, dict[str, Any]] = {
    "baseline": {},
    "root_cause": {"freshness_guard": "warn"},
    "demo_overreach": {"freshness_guard": "warn", "min_score": 0.2},
    "raise_threshold": {"freshness_guard": "warn", "min_score": 0.5},
    "more_passages": {"freshness_guard": "warn", "retrieval_limit": 2},
    "drop_onboarding": {"freshness_guard": "warn", "domains": KNOWLEDGE_DOMAINS_WITHOUT_ONBOARDING},
    "stale_to_human": {"freshness_guard": "fallback"},
    "manual_policy": {"update_strategy": "manual_policy"},
    "no_human_fallback": {"freshness_guard": "warn", "fallback": "none"},
    "lower_threshold_only": {"min_score": 0.2},
    "manual_travel": {"freshness_guard": "warn", "manual_domains": ["policy_travel"]},
    "scope_filter_off": {"freshness_guard": "warn", "scope_filter": False},
    "realtime_unprovisioned": {
        "update_strategy": "realtime",
        "work_items": ["realtime_sync", "human_fallback"],
    },
}

NOTES = {
    "baseline": "原配置（会话当前配置）",
    "root_cause": "根因修法：索引落后时回答带过期提醒",
    "demo_overreach": "演示过宽改法：加提醒，同时把门槛调到 0.2 想“找回新政策”",
    "raise_threshold": "加提醒，同时把门槛调到 0.5 想“只答有把握的”",
    "more_passages": "加提醒，同时多取一段资料想“看到新通知”",
    "drop_onboarding": "加提醒，同时删掉入职知识域",
    "stale_to_human": "资料落后就一律转人工",
    "manual_policy": "差旅政策一律人工核验（更新策略）",
    "no_human_fallback": "加提醒，同时关掉人工兜底",
    "lower_threshold_only": "只调低门槛，不加提醒",
    "manual_travel": "加提醒，同时差旅域一律人工核验",
    "scope_filter_off": "加提醒，同时关掉范围过滤（五个域都已配置，无实际影响）",
    "realtime_unprovisioned": "改实时同步（资源未批，生效时退回每日）",
}

CLASSES = {
    "F01": "目标",
    "F14": "目标同类",
    "F15": "目标同类",
    "F04": "护栏·知识库外",
    "F05": "护栏·禁区",
    "F06": "护栏·禁区",
    "F12": "护栏·新鲜FAQ",
    "F02": "护栏·新鲜餐费",
    "F13": "护栏·新鲜请假",
    "F16": "护栏·知识库外｜哨兵:门槛调低",
    "F17": "护栏·新鲜FAQ｜哨兵:门槛调高",
    "F18": "护栏·新鲜餐费｜哨兵:多取段落",
    "F19": "护栏·新鲜入职｜哨兵:删入职域",
}


def lagging_world(module: ScenarioModule) -> ScenarioSnapshot:
    """Policy v2 published, index still v1: the state after the first configuration.apply."""
    initial = module.engine.initial(SESSION)
    settings = initial.config.model_dump(mode="json") | {
        "work_items": ["scope_filter", "human_fallback"],
        "fallback": "human",
        "version": 2,
        "config_version": 1,
    }
    return plan(module.engine, initial, "apply_config", "config", config=settings).snapshot


def run_suite(
    module: ScenarioModule, world: ScenarioSnapshot, changes: dict[str, Any]
) -> tuple[EngineerProbeResult, ...]:
    raw = engineer_suite(module.package)
    if raw is None:
        raise C.ProtocolError("engineer_suite_missing")
    probes = validate_suite(raw, module.package)
    candidate = C.AssistantConfig.model_validate(world.config.model_dump(mode="json") | changes)
    return execute_suite(module, world, auth(SESSION), candidate, probes, "matrix")


def cell(row: EngineerProbeResult) -> str:
    if row.result == "pass":
        return "ok"
    if row.actual is None:
        return "ER"
    status = {
        "answered": "AN",
        "answered_with_warning": "AW",
        "fallback": "FB",
        "failed": "FA",
    }[row.actual.status]
    return status + ("" if row.actual.error_code is None else ":" + row.actual.error_code[:6])


def matrix(language: str) -> None:
    module = ScenarioModule(default_installed_scenario(), work_language=language)
    world = lagging_world(module)
    probes = validate_suite(engineer_suite(module.package) or b"", module.package)
    rows = {name: run_suite(module, world, changes) for name, changes in CANDIDATES.items()}
    before = {r.probe_id: r.result for r in rows["baseline"]}
    source, indexed = world.source_versions["policy"], world.indexed_versions["policy"]
    print(f"\n[{language}] source policy v{source}, index policy v{indexed}")
    print("* = public; ok = expected met; otherwise actual status:error_code")
    header = "".join(f"{p.id + ('*' if p.public else ''):>10s}" for p in probes)
    print(f"{'candidate':24s}{header}   pass  new-regressions")
    for name, results in rows.items():
        new = [r.probe_id for r in results if before[r.probe_id] == "pass" and r.result == "fail"]
        passed = sum(r.result == "pass" for r in results)
        cells = "".join(f"{cell(r):>10s}" for r in results)
        print(f"{name:24s}{cells}   {passed:2d}/{len(results)}  {','.join(new) or '-'}")
    print("\nprobe classes:")
    for probe in probes:
        visibility = "public" if probe.public else "hidden"
        print(f"  {probe.id} {visibility}  {CLASSES.get(probe.id, '')}  {probe.query}")
    print("\ncandidates:")
    for name, changes in CANDIDATES.items():
        print(f"  {name:24s} {NOTES[name]}  {changes}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--language", choices=("zh", "en", "both"), default="both")
    language = parser.parse_args().language
    for item in ("zh", "en") if language == "both" else (language,):
        matrix(item)


if __name__ == "__main__":
    main()
