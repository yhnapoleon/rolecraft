"""The AI colleagues' rule tables (engineer/colleague.py): what Daniel tries, why, and how
Grace decides on a signed report. No model is involved."""

from types import SimpleNamespace

from career_lab.engineer.candidate import EDITABLE_FIELDS
from career_lab.engineer.colleague import (
    CANDIDATE_RULES,
    MAX_TRIALS,
    NO_HIT,
    STALE_UNWARNED,
    facts_of,
    failure_of,
    grace_reply,
    grace_rule,
    pick,
    rules_for,
    target_check,
)


def test_every_rule_changes_only_editable_settings_and_says_why_in_both_languages() -> None:
    assert len({r.id for r in CANDIDATE_RULES}) == len(CANDIDATE_RULES)
    for rule in CANDIDATE_RULES:
        assert rule.changes and set(rule.changes) <= set(EDITABLE_FIELDS)
        assert rule.why["zh"].strip() and rule.why["en"].strip()
        assert len(rule.why["zh"]) <= 500 and len(rule.why["en"]) <= 500


def _test(source: dict, indexed: dict, error: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        execution=SimpleNamespace(source_versions=source, indexed_versions=indexed),
        error_code=error,
    )


def test_facts_come_from_the_target_tests_own_versions() -> None:
    assert facts_of([_test({"policy": 2}, {"policy": 1})]) == {"index_lag"}
    assert facts_of([_test({"policy": 1}, {"policy": 1})]) == set()
    assert facts_of([_test({}, {}, "no_retrieval_hit")]) == {"no_hit"}


def test_narrow_changes_are_tried_before_broad_ones_and_capped() -> None:
    lag = rules_for({"index_lag"})
    assert [r.id for r in lag] == ["freshness_warn", "realtime_index", "freshness_fallback"]
    assert len(rules_for({"index_lag", "no_hit"})) == MAX_TRIALS
    assert rules_for(set()) == []


def test_pick_takes_the_first_clean_trial_else_the_fewest_failures() -> None:
    a, b, c = CANDIDATE_RULES[:3]
    trial = lambda failed, errors=0: {"counts": {"failed": failed, "errors": errors}}  # noqa: E731
    assert pick([(a, trial(1)), (b, trial(0)), (c, trial(0))])[0] is b
    assert pick([(a, trial(2)), (b, trial(1, 1)), (c, trial(1))])[0] is c


def test_pick_prefers_a_trial_that_clears_the_targets_failure() -> None:
    a, b, c = CANDIDATE_RULES[:3]

    def trial(failed: int, cleared: int) -> dict:
        target = {"failures": [STALE_UNWARNED], "questions": 1, "cleared": cleared}
        return {"counts": {"failed": failed, "errors": 0}, "target": target}

    # A clean public run that leaves the stale answer as it was does not win.
    assert pick([(a, trial(0, 0)), (b, trial(1, 1)), (c, trial(0, 1))])[0] is c
    assert pick([(a, trial(0, 0)), (b, trial(1, 1))])[0] is b
    assert pick([(a, trial(0, 0)), (b, trial(1, 0))])[0] is a


def test_the_failure_a_rule_can_check_is_a_stale_unwarned_answer_or_no_hit() -> None:
    sources = {"policy": 2, "faq": 1}
    assert failure_of("answered", None, [("policy", 1)], sources) == STALE_UNWARNED
    assert failure_of("answered_with_warning", None, [("policy", 1)], sources) is None
    assert failure_of("answered", None, [("policy", 2), ("faq", 1)], sources) is None
    assert failure_of("fallback", "stale_source_guard", [], sources) is None
    assert failure_of("fallback", "no_retrieval_hit", [], sources) == NO_HIT


def _row(status: str | None, cited: list, result: str = "unchecked", query: str = "q") -> dict:
    return {
        "is_target": True,
        "query": query,
        "actual_status": status,
        "error_code": None,
        "citations": [{"object_id": o, "version": v} for o, v in cited],
        "result": result,
    }


def test_a_trial_clears_the_target_only_when_its_failure_is_gone() -> None:
    sources = {"policy": 2}
    failing = {"q": STALE_UNWARNED}
    warned = target_check(failing, [_row("answered_with_warning", [("policy", 1)])], sources)
    assert warned == {"failures": [STALE_UNWARNED], "questions": 1, "cleared": 1}
    current = target_check(failing, [_row("answered", [("policy", 2)])], sources)
    assert current is not None and current["cleared"] == 1
    stale = target_check(failing, [_row("answered", [("policy", 1)])], sources)
    assert stale is not None and stale["cleared"] == 0
    # A row that could not run clears nothing; questions that showed no failure are not counted.
    broken = target_check(failing, [_row(None, [], "error")], sources)
    assert broken is not None and broken["cleared"] == 0
    assert target_check(failing, [_row("answered", [("policy", 1)], query="other")], sources) is None
    assert target_check({}, [_row("answered", [("policy", 1)])], sources) is None


def _eval(e1: str, e2: str, probes: tuple = (), hidden: int = 0) -> dict:
    return {
        "criteria": [
            {"criterion": "E1.target_fixed", "label": e1, "probe_ids": list(probes)},
            {"criterion": "E2.no_regressions", "label": e2, "hidden_probes": hidden},
        ]
    }


def test_grace_applies_only_a_verified_fix_without_new_failures() -> None:
    assert grace_rule(_eval("MET", "MET"), "verified")["result"] == "applied"
    back = grace_rule(_eval("NOT_MET", "NOT_MET", ("F01",), 2), "verified")
    assert back["result"] == "returned"
    assert back["reasons"] == ["target_not_fixed", "new_failures"]
    assert back["probe_ids"] == ["F01"] and back["hidden_probes"] == 2
    assert grace_rule(_eval("MET", "MET"), "report_mismatch")["reasons"] == ["claims_not_verified"]


def test_grace_says_who_applied_and_which_versions_or_which_checks_failed() -> None:
    applied = {"result": "applied", "from_version": 2, "to_version": 3}
    assert "已由 Grace 应用，配置从 v2 变为 v3" in grace_reply("zh", applied)
    assert "Applied by Grace: configuration v2 → v3" in grace_reply("en", applied)
    back = {
        "result": "returned",
        "reasons": ["new_failures"],
        "probe_ids": ["F04"],
        "hidden_probes": 1,
    }
    assert "F04" in grace_reply("zh", back) and "1 项隐藏检查" in grace_reply("zh", back)
    assert "F04" in grace_reply("en", back) and "1 hidden checks" in grace_reply("en", back)
