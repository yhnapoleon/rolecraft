"""Reproductions for independent M3 review findings; do not grade the whole package."""

import json
from tests.support.scenario_packages import installed_root
import pytest
from career_lab.scenarios.v2.module import ScenarioModule
from .test_evaluation_facts import history, question, facts

PACK = installed_root()
VARIANTS = [
    (sid, lang) for sid in ["pm_pilot_capacity15", "pm_pilot_urgent"] for lang in ["zh", "en"]
]


@pytest.mark.parametrize("history", VARIANTS, indirect=True)
@pytest.mark.parametrize("decision", ["launch", "defer_with_conditions", "no_go"])
def test_policy_fix_remains_verified_when_capacity_or_date_is_pending(history, decision):
    h = history
    h.apply(freshness_guard="warn")
    urgent = h.module.package.bundle.id.endswith("urgent")
    request = h.post(
        "actions",
        "request_business",
        {
            "tool": "request_business",
            "terms": {"deadline_day": 7} if urgent else {"capacity": 20},
            "reason": "The working draft exceeds this assignment allocation; request approval before launch.",
        },
    )
    assert request["result"]["request_data"]["status"] == "pending"
    h.post("actions", "refresh_index", {"tool": "refresh_index"})
    h.run(question(h))
    product = h.product(
        "Policy is retested. Capacity/date approval remains unresolved; do not treat this as an approval."
    )
    sub = h.submit((product,), decision)
    snap = h.adapter.submission_rule_provider(h.auth, sub)
    f = facts(snap)
    assert f["adjustment_appropriate_verified"] is True
    assert f["unapproved_resource_excess"] is True
    assert f["current_obligation_verified"] is (decision == "launch")
    assert f["passing_dynamic_test_ids"]


@pytest.mark.parametrize("sid,lang", VARIANTS)
def test_trial_cards_explain_unchanged_excess_and_draft_numbers_have_facts(sid, lang):
    p = ScenarioModule(installed_root(sid), work_language=lang).package
    text = (p.root / "materials/trial_details-v1.md").read_text()
    assert (
        "超出当前额度（未自动修改）"
        if lang == "zh"
        else "Over current allocation (not changed automatically)"
    ) in text
    assert (
        "未生效项（已按实际配置执行）"
        if lang == "zh"
        else "Not effective (using the effective settings)"
    ) in text
    assert "requested_participants_exceed_approved_capacity" not in text
    assert "requested_launch_exceeds_approved_deadline" not in text
    values = {f.id: f.value for f in p.facts}
    assert values["draft_participants"] == 20 and values["draft_launch_day"] == 7
    for role in p.bundle.role_specs:
        if role.id in ["supervisor", "tech_lead"]:
            assert {"draft_participants", "draft_launch_day"} <= set(role.known_facts)


@pytest.mark.parametrize("sid", ["pm_pilot", "pm_pilot_urgent", "pm_pilot_capacity15"])
def test_english_technical_diagnostic_matches_frozen_actual_results(sid):
    root = installed_root(sid)
    p = ScenarioModule(root, work_language="en").package
    records = json.loads((p.root / "research/private-diagnostic.json").read_text())
    trials = {
        r["result"]["config"]["requested"]["min_score"]: r
        for r in records["records"]
        if "control" not in r["trial_id"]
    }
    assert set(trials) == {0.35, 0.3, 0.2}
    assert trials[0.35]["result"]["status"] == trials[0.3]["result"]["status"] == "fallback"
    assert trials[0.2]["result"]["answer"].startswith("Device repair:")
    role = next(r for r in p.bundle.role_specs if r.id == "tech_lead")
    summary = role.disclosure_policy["retrieval_probe_query"].paraphrase
    assert "Device repair" in summary and "did not solve" in summary and "default 0.3" in summary
    assert "research/private-diagnostic.json" in p.bundle.private_files
