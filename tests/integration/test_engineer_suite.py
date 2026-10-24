"""Engineer regression suite: one candidate configuration, one consistent world.

The world is the installed pm_pilot release after the first configuration.apply
(policy v2 published, index still v1). Every probe runs under one candidate
configuration through the reviewer's execute_suite, as engineer review does.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from career_lab.api.vertical_runtime import default_installed_scenario
from career_lab.contracts import v2 as C
from career_lab.contracts.v2.engineer import EngineerProbeResult
from career_lab.engineer.execution import suite_probes
from career_lab.engineer.suite import engineer_suite, validate_suite
from career_lab.scenarios.v2.loader import load_package
from career_lab.scenarios.v2.module import ScenarioModule
from scripts.engineer_suite_matrix import CANDIDATES, lagging_world, run_suite

ROOT = Path(__file__).resolve().parents[2]
LANGUAGES = ("zh", "en")
PUBLIC = {"F01", "F04", "F05", "F12"}
TARGET_CLASS = {"F01", "F14", "F15"}
WITHOUT_ONBOARDING = ["stable_faq", "policy_travel", "policy_meal", "policy_leave"]

# Changes to the session's current configuration that these tests pin.
PINNED: dict[str, dict[str, Any]] = {
    "baseline": {},
    "root_cause": {"freshness_guard": "warn"},
    "demo_overreach": {"freshness_guard": "warn", "min_score": 0.2},
    "raise_threshold": {"freshness_guard": "warn", "min_score": 0.5},
    "more_passages": {"freshness_guard": "warn", "retrieval_limit": 2},
    "drop_onboarding": {"freshness_guard": "warn", "domains": WITHOUT_ONBOARDING},
    "stale_to_human": {"freshness_guard": "fallback"},
    "manual_policy": {"update_strategy": "manual_policy"},
    "no_human_fallback": {"freshness_guard": "warn", "fallback": "none"},
}


@pytest.fixture(scope="module", params=LANGUAGES)
def module(request: pytest.FixtureRequest) -> ScenarioModule:
    """The installed release the normal entry and the reviewer actually use."""
    return ScenarioModule(default_installed_scenario(), work_language=request.param)


def results(module: ScenarioModule, name: str) -> dict[str, EngineerProbeResult]:
    world = lagging_world(module)
    return {row.probe_id: row for row in run_suite(module, world, PINNED[name])}


def outcomes(module: ScenarioModule, name: str) -> dict[str, str]:
    return {probe: row.result for probe, row in results(module, name).items()}


def regressions(module: ScenarioModule, name: str) -> set[str]:
    before, after = outcomes(module, "baseline"), outcomes(module, name)
    return {i for i in after if before[i] == "pass" and after[i] == "fail"}


def test_suite_keeps_public_probes(module: ScenarioModule) -> None:
    raw = engineer_suite(module.package)
    assert raw is not None
    probes = suite_probes(raw)
    public = {p.id: (p.query, p.expected) for p in probes if p.public}
    authored = (module.package.root / "probes.json").read_bytes()
    original = {p.id: (p.query, p.expected) for p in suite_probes(authored) if p.public}
    assert public == original
    assert set(public) == PUBLIC and len(probes) == 13


def test_suite_absent_elsewhere() -> None:
    other = load_package(ROOT / "scenarios/it_ticket_pilot/v2/candidates/it-1/it_ticket_pilot")
    assert engineer_suite(other) is None


def test_matrix_shows_pinned_candidates() -> None:
    assert {name: CANDIDATES[name] for name in PINNED} == PINNED


def test_world_index_lags(module: ScenarioModule) -> None:
    world = lagging_world(module)
    assert world.source_versions["policy"] == 2 and world.indexed_versions["policy"] == 1
    assert world.config.config_version == 1


def test_baseline_misses_target_class(module: ScenarioModule) -> None:
    observed = outcomes(module, "baseline")
    assert "error" not in observed.values()
    assert {i for i, r in observed.items() if r == "fail"} == TARGET_CLASS


def test_root_cause_fix_passes_all(module: ScenarioModule) -> None:
    observed = outcomes(module, "root_cause")
    assert len(observed) == 13 and set(observed.values()) == {"pass"}


def test_demo_overreach_caught_hidden(module: ScenarioModule) -> None:
    """Agent adds the warning and also lowers the threshold to 'find the new policy'."""
    observed = outcomes(module, "demo_overreach")
    assert {i: observed[i] for i in PUBLIC} == dict.fromkeys(PUBLIC, "pass")
    assert all(observed[i] == "pass" for i in TARGET_CLASS)
    assert regressions(module, "demo_overreach") == {"F16"}
    before = results(module, "baseline")["F16"].actual
    after = results(module, "demo_overreach")["F16"].actual
    assert before is not None and after is not None
    assert (before.status, before.error_code) == ("fallback", "no_retrieval_hit")
    assert after.status == "answered" and after.error_code is None and after.citations


@pytest.mark.parametrize(
    ("name", "caught"),
    [
        pytest.param("raise_threshold", {"F17"}, id="raise_threshold"),
        pytest.param("more_passages", {"F18"}, id="more_passages"),
        pytest.param("drop_onboarding", {"F19"}, id="drop_onboarding"),
    ],
)
def test_other_overreach_caught_hidden(module: ScenarioModule, name: str, caught: set[str]) -> None:
    observed = outcomes(module, name)
    assert {i: observed[i] for i in PUBLIC} == dict.fromkeys(PUBLIC, "pass")
    assert all(observed[i] == "pass" for i in TARGET_CLASS)
    assert regressions(module, name) == caught


@pytest.mark.parametrize(
    ("name", "failing", "new"),
    [
        pytest.param("stale_to_human", TARGET_CLASS, set(), id="stale_to_human"),
        pytest.param("manual_policy", TARGET_CLASS, set(), id="manual_policy"),
        pytest.param(
            "no_human_fallback",
            {"F04", "F05", "F06", "F16"},
            {"F04", "F05", "F06", "F16"},
            id="no_human_fallback",
        ),
    ],
)
def test_public_probes_catch(
    module: ScenarioModule, name: str, failing: set[str], new: set[str]
) -> None:
    """Over-cautious or safeguard-removing changes already fail a public probe."""
    observed = outcomes(module, name)
    assert {i for i, r in observed.items() if r == "fail"} == failing
    assert failing & PUBLIC
    assert regressions(module, name) == new


def test_languages_agree() -> None:
    seen = {}
    for language in LANGUAGES:
        item = ScenarioModule(default_installed_scenario(), work_language=language)
        world = lagging_world(item)
        rows = json.loads(engineer_suite(item.package) or b"[]")
        canonical = {row["id"]: row["canonical_probe_id"] for row in rows}
        seen[language] = {
            name: {
                canonical[r.probe_id]: (
                    r.result,
                    r.actual.status if r.actual else None,
                    r.actual.error_code if r.actual else None,
                )
                for r in run_suite(item, world, changes)
            }
            for name, changes in CANDIDATES.items()
        }
    assert seen["zh"] == seen["en"]


def _with_precondition(rows: list[dict[str, Any]], key: str) -> None:
    rows[1][key] = {"freshness_guard": "warn"} if key in {"config", "tuning"} else True


MUTATIONS: dict[str, Callable[[list[dict[str, Any]]], None]] = {
    "duplicate_id": lambda rows: rows[-1].update(id=rows[0]["id"]),
    "duplicate_canonical": lambda rows: rows[-1].update(canonical_probe_id="F02"),
    "public_missing": lambda rows: rows[0].update(public=False),
    "public_question_changed": lambda rows: rows[0].update(query=rows[0]["query"] + "?"),
    "extra_public": lambda rows: rows[-1].update(public=True),
    "locale_mismatch": lambda rows: rows[2].update(locale="xx"),
    "canonical_missing": lambda rows: rows[2].pop("canonical_probe_id"),
    "unknown_expectation": lambda rows: rows[2]["expected"].update(score=1),
    **{
        "precondition_" + key: (lambda rows, key=key: _with_precondition(rows, key))
        for key in ("config", "tuning", "grant", "refresh", "apply")
    },
}


@pytest.mark.parametrize("mutation", sorted(MUTATIONS))
def test_suite_validation_rejects(module: ScenarioModule, mutation: str) -> None:
    raw = engineer_suite(module.package)
    assert raw is not None
    assert len(validate_suite(raw, module.package)) == 13
    rows = json.loads(raw)
    MUTATIONS[mutation](rows)
    with pytest.raises(C.ProtocolError) as rejected:
        validate_suite(json.dumps(rows).encode(), module.package)
    assert rejected.value.code == "engineer_suite_invalid"
