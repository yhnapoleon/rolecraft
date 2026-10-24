"""Signed engineer reviews carry the E1-E5 rule evaluation and the learner's change claims."""

import json
from typing import Any

from test_engineer_session import PUBLIC_PROBES, Eng, draft, private_report, sign
from test_engineer_session import eng as eng

from career_lab.contracts.v2.engineer import EngineerSubmissionRecord


def criteria(evaluation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["criterion"].split(".")[0]: item for item in evaluation["criteria"]}


def checks(conclusion: dict[str, Any]) -> list[tuple[str, str]]:
    return [(check["field"], check["status"]) for check in conclusion["field_checks"]]


def hidden_ids(eng: Eng, review_id: str) -> set[str]:
    return {row.probe_id for row in private_report(eng, review_id).results} - PUBLIC_PROBES


def test_signed_review_carries_the_rule_evaluation(eng: Eng) -> None:
    eng.advance_world()
    ticket = eng.seeded()
    made = eng.ok(draft(eng, ticket, "d"))["draft"]
    signed = eng.ok(sign(eng, ticket, made["id"], "s"))["review"]
    review_id = signed["review_id"]
    assert signed["report"]["hidden_comparison"]["new_failures"] == 1
    evaluation = signed["evaluation"]
    assert evaluation["review_id"] == review_id and evaluation["affects_score"] is False
    assert evaluation["rubric_revision"] == "engineer-rubric-v1-final-20261009"
    found = criteria(evaluation)
    assert [found[key]["label"] for key in ("E1", "E2", "E3", "E4")] == [
        "MET",
        "NOT_MET",
        "MET",
        "MET",
    ]
    assert found["E1"]["probe_ids"] == ["F01"]
    # The hidden regression (F09) is a count, never an ID.
    assert found["E2"]["probe_ids"] == [] and found["E2"]["hidden_probes"] == 1
    assert checks(found["E3"]) == [("freshness_guard", "matched")]
    assert found["E5"]["status"] == "waiting_model" and found["E5"]["label"] is None
    read = eng.ok(eng.read("/engineer/reviews/" + review_id))["review"]
    assert read["evaluation"] == evaluation and read["report"] == signed["report"]
    text = json.dumps(evaluation)
    assert not any(f'"{probe}"' in text for probe in hidden_ids(eng, review_id))


def submitted_record(eng: Eng, review_id: str) -> EngineerSubmissionRecord:
    folder = eng.root / "private-reviews" / eng.sid / "inputs" / review_id
    return EngineerSubmissionRecord.model_validate_json((folder / "submission.json").read_bytes())


def test_a_wrong_original_value_is_signed_and_judged_by_e3(eng: Eng) -> None:
    eng.advance_world()
    ticket = eng.seeded()
    wrong = [
        {
            "field": "freshness_guard",
            "before": "fallback",
            "after": "warn",
            "reason": "The Agent misread the original setting.",
        }
    ]
    made = eng.ok(draft(eng, ticket, "d", change_statements=wrong, claimed_results={}))["draft"]
    assert made["change_statements"] == wrong
    signed = eng.ok(sign(eng, ticket, made["id"], "s"))["review"]
    found = criteria(signed["evaluation"])
    assert found["E3"]["label"] == "NOT_MET"
    assert found["E3"]["reason_codes"] == ["change_claims_contradicted"]
    assert checks(found["E3"]) == [("freshness_guard", "before_mismatch")]
    # Without a self-report there is nothing to reproduce.
    assert found["E4"]["label"] == "INSUFFICIENT"
    assert found["E4"]["reason_codes"] == ["claim_not_provided"]
    assert [found[key]["label"] for key in ("E1", "E2")] == ["MET", "NOT_MET"]
    record = submitted_record(eng, signed["review_id"])
    assert [
        claim.model_dump(mode="json", exclude={"schema_version"}) for claim in record.changes
    ] == [
        {
            "field": "freshness_guard",
            "before": "fallback",
            "after": "warn",
            "reason": "The Agent misread the original setting.",
        }
    ]


def test_different_change_statements_are_different_reviews(eng: Eng) -> None:
    eng.advance_world()
    ticket = eng.seeded()
    right = eng.ok(draft(eng, ticket, "right"))["draft"]
    stated = right["change_statements"][0]
    other = [{**stated, "before": "warn"}]
    wrong = eng.ok(draft(eng, ticket, "wrong", change_statements=other))["draft"]
    first = eng.ok(sign(eng, ticket, right["id"], "s1"))
    second = eng.ok(sign(eng, ticket, wrong["id"], "s2"))
    assert second["signoff"]["already_signed"] is False
    assert second["review"]["review_id"] != first["review"]["review_id"]
    assert second["review_budget"] == {"used": 2, "limit": 3}
    assert criteria(first["review"]["evaluation"])["E3"]["label"] == "MET"
    assert criteria(second["review"]["evaluation"])["E3"]["label"] == "NOT_MET"
    # The same statements signed again are the same review and cost nothing.
    again = eng.ok(draft(eng, ticket, "again", change_statements=other))["draft"]
    repeated = eng.ok(sign(eng, ticket, again["id"], "s3"))
    assert repeated["signoff"]["already_signed"] is True
    assert repeated["review"]["review_id"] == second["review"]["review_id"]
    assert repeated["review_budget"] == {"used": 2, "limit": 3}


def test_statements_must_name_editable_settings_once(eng: Eng) -> None:
    eng.advance_world()
    ticket = eng.seeded()
    for number, statements in enumerate(
        (
            [{"field": "session_id", "before": "a", "after": "b", "reason": "r"}],
            [{"field": "generator", "before": None, "after": None, "reason": "r"}],
        )
    ):
        refused = draft(eng, ticket, f"bad-{number}", change_statements=statements)
        assert refused.status_code == 422, refused.text
        assert refused.json()["code"] == "engineer_change_statement_invalid"
    too_long = [
        {"field": "freshness_guard", "before": "none", "after": "warn", "reason": "x" * 501}
    ]
    refused = draft(eng, ticket, "long", change_statements=too_long)
    assert refused.status_code == 422, refused.text
    # An unchanged setting may be declared unchanged (before == after).
    kept = [
        {"field": "freshness_guard", "before": "none", "after": "warn", "reason": "Warn on lag."},
        {"field": "fallback", "before": "human", "after": "human", "reason": "Kept on purpose."},
    ]
    made = eng.ok(draft(eng, ticket, "kept", change_statements=kept))["draft"]
    signed = eng.ok(sign(eng, ticket, made["id"], "s"))["review"]
    assert checks(criteria(signed["evaluation"])["E3"]) == [
        ("fallback", "matched"),
        ("freshness_guard", "matched"),
    ]
    assert (
        eng.ok(eng.read("/engineer/tickets/" + ticket["id"]))["ticket"]["drafts"][0][
            "change_statements"
        ]
        == kept
    )


def test_a_review_stored_before_hidden_comparison_still_reads(eng: Eng) -> None:
    """Reviews written before hidden_comparison existed keep their bytes and still evaluate."""
    from career_lab.engineer.files import encode, file_ref

    eng.advance_world()
    ticket = eng.seeded()
    made = eng.ok(draft(eng, ticket, "d"))["draft"]
    review_id = eng.ok(sign(eng, ticket, made["id"], "s"))["review"]["review_id"]
    private = eng.root / "private-reviews" / eng.sid / "reports" / review_id
    public = eng.root / "public-reviews" / eng.sid / review_id / "report.json"
    for path in (private / "report.json", public):
        value = json.loads(path.read_bytes())
        del value["hidden_comparison"]
        path.write_bytes(encode(value))
    members = {
        name: file_ref(name, (private / name).read_bytes())
        for name in json.loads((private / "index.json").read_bytes())
    }
    (private / "index.json").write_bytes(encode(members))
    read = eng.ok(eng.read("/engineer/reviews/" + review_id))["review"]
    assert "hidden_comparison" not in read["report"]
    found = criteria(read["evaluation"])
    assert [found[key]["label"] for key in ("E1", "E2", "E3", "E4")] == [
        "MET",
        "NOT_MET",
        "MET",
        "MET",
    ]


def test_altered_private_records_are_refused(eng: Eng) -> None:
    eng.advance_world()
    ticket = eng.seeded()
    made = eng.ok(draft(eng, ticket, "d"))["draft"]
    review_id = eng.ok(sign(eng, ticket, made["id"], "s"))["review"]["review_id"]
    stored = eng.root / "private-reviews" / eng.sid / "inputs" / review_id / "baseline.json"
    stored.write_bytes(stored.read_bytes().replace(b'"none"', b'"warn"', 1))
    refused = eng.read("/engineer/reviews/" + review_id)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "engineer_review_changed"
    assert str(eng.root) not in refused.text
