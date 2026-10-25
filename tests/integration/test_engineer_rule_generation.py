"""Engineering keeps LLM provenance while running its fixed rule evaluation."""

import pytest
from test_engineer_session import Eng, draft, private_report, sign, ticket_path, trial
from test_engineer_session import eng as eng


class NoGeneration:
    revision = "configured-llm"
    retries = 0

    def complete(self, *args):
        pytest.fail("Rule engineering must never invoke the generation provider")


@pytest.mark.parametrize("generator", ["llm", "extractive"])
def test_rule_engineering_with_configured_provider(eng: Eng, generator: str) -> None:
    from career_lab.scenarios.v2.module import ref_for

    module = eng.app.state.scenario_v2
    module.assistant.model = NoGeneration()
    base = module.package.baseline(eng.sid)
    eng.ok(
        eng.call(
            "/configuration",
            "configuration.apply",
            {
                "base": ref_for("config", base).model_dump(mode="json"),
                "settings": {"generator": generator},
            },
            "configure",
        )
    )
    module.assistant.model = NoGeneration()
    before = eng.state()
    ticket = eng.seeded()
    detail = eng.ok(eng.read("/engineer/tickets/" + ticket["id"]))["ticket"]
    assert "rule" in detail["retrieval"]["mode"]
    reproduced = eng.ok(
        eng.call(
            ticket_path(ticket, "reproductions"),
            "engineer.reproduce",
            {"ticket_id": ticket["id"]},
            "reproduce",
        )
    )["reproduction"]
    assert reproduced["counts"]["matched"] == 1
    tried = eng.ok(trial(eng, ticket, {"freshness_guard": "warn"}, "trial"))["trial"]
    assert tried["counts"]["passed"] == 4 and tried["counts"]["errors"] == 0
    made = eng.ok(draft(eng, ticket, "draft"))["draft"]
    review = eng.ok(sign(eng, ticket, made["id"], "sign"))["review"]
    assert review["status"] == "verified"
    full = private_report(eng, review["review_id"])
    assert {row.result for row in full.results} == {"pass"}
    assert all(row.actual.config.requested.generator == generator for row in full.results)
    assert all(row.actual.execution.attempts == () for row in full.results)
    # A too-broad repair must still expose regressions in the hidden suite.
    broad = eng.ok(
        draft(
            eng,
            ticket,
            "broad",
            changes={"freshness_guard": "warn", "min_score": 0.2},
            change_statements=[
                {"field": "freshness_guard", "before": "none", "after": "warn", "reason": "warn"},
                {"field": "min_score", "before": 0.3, "after": 0.2, "reason": "broaden"},
            ],
        )
    )["draft"]
    broad_review = eng.ok(sign(eng, ticket, broad["id"], "broad-sign"))["review"]
    broad_full = private_report(eng, broad_review["review_id"])
    assert any(row.result == "fail" for row in broad_full.results)
    assert eng.state() == before
