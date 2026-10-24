"""Hidden comparison, change claims and E1-E5 rule conclusions on real CLI reviews."""

import json
from pathlib import Path
from typing import Any

from test_w13_pack import Session
from test_w13_pack import session as session
from test_w13_review import review
from test_w13_submission import prepare, submit

from career_lab.contracts.v2.engineer import EngineerPublicReport, EngineerRegressionReport
from career_lab.engineer.files import encode, file_ref


def target_session(session: Session) -> Session:
    """The W13 regression example: a policy-limit target that freshness_guard=warn repairs."""
    from career_lab.scenarios.v2.module import ref_for

    app, client, sid, headers, send, _, cli, root, credentials = session
    query = (
        "住宿报销上限是多少？"
        if app.state.scenario_v2.work_language == "zh"
        else "What is the hotel reimbursement limit per night?"
    )
    send(
        "configuration",
        "apply",
        "configuration.apply",
        {
            "base": ref_for("config", app.state.scenario_v2.package.baseline(sid)).model_dump(
                mode="json"
            ),
            "settings": {"work_items": ["scope_filter", "human_fallback"], "fallback": "human"},
        },
    )
    trial = send("tests", "target", "tests.create", {"query": query, "config_version": 1})[
        "result"
    ]["test"]
    return app, client, sid, headers, send, trial, cli, root, credentials


def reviewed(
    session: Session, pack: Path, source: Path
) -> tuple[EngineerRegressionReport, EngineerPublicReport, str, Path]:
    submitted = submit(session, pack, source)
    assert submitted.returncode == 0, submitted.stdout + submitted.stderr
    folder = session[7] / "submissions" / json.loads(submitted.stdout)["directory"]
    result = review(session, pack, folder)
    assert result.returncode in {0, 1}, result.stdout + result.stderr
    identity = json.loads(result.stdout)["review_id"]
    private = session[7] / "private-reviews" / "reports" / identity / "report.json"
    public_raw = (session[7] / "public-reviews" / identity / "report.json").read_text()
    return (
        EngineerRegressionReport.model_validate_json(private.read_bytes()),
        EngineerPublicReport.model_validate_json(public_raw),
        public_raw,
        folder,
    )


def rewrite(source: Path, update: dict[str, Any]) -> None:
    record = json.loads(source.read_bytes())
    record.update(update)
    source.write_bytes(encode(record))


def test_review_reports_hidden_comparison_counts_only(session: Session) -> None:
    target = target_session(session)
    pack, source = prepare(target, {"freshness_guard": "warn"})
    report, public, public_raw, folder = reviewed(target, pack, source)
    # A submission without change claims is still accepted and stored byte for byte.
    assert "changes" not in json.loads(source.read_bytes())
    assert (folder / "submission.json").read_bytes() == source.read_bytes()
    rows = {row.probe_id: row for row in report.results}
    assert rows["F09"].visibility == "hidden" and rows["F09"].result == "fail"
    comparison = report.hidden_comparison
    assert comparison is not None and comparison.new_failures == 1
    assert comparison.unverified == 0
    hidden = [row for row in report.results if row.visibility == "hidden"]
    assert comparison.new_failures + comparison.fixed + comparison.still_failing <= len(hidden)
    assert public.hidden_comparison == comparison
    assert json.loads(public_raw)["hidden_comparison"]["new_failures"] == 1
    for row in hidden:
        assert row.probe_id not in public_raw
        assert row.query not in public_raw


def evaluate(report: EngineerRegressionReport, folder: Path) -> Any:
    """Evaluate from the stored submission repository, as a trusted caller would."""
    from career_lab.contracts.v2 import AssistantConfig
    from career_lab.contracts.v2.engineer import EngineerClaimedReport, EngineerSubmissionRecord
    from career_lab.engineer.evaluation import evaluate_review

    record = EngineerSubmissionRecord.model_validate_json((folder / "submission.json").read_bytes())
    claimed = (
        EngineerClaimedReport.model_validate_json(
            (folder / record.regression_report.path).read_bytes()
        )
        if record.regression_report is not None
        else None
    )
    return evaluate_review(
        report,
        record,
        AssistantConfig.model_validate_json((folder / "baseline.json").read_bytes()),
        AssistantConfig.model_validate_json((folder / record.config.path).read_bytes()),
        claimed=claimed,
    )


def labels(evaluation: Any) -> dict[str, str | None]:
    return {item.criterion.split(".")[0]: item.label for item in evaluation.criteria}


def claim_file(source: Path, results: dict[str, str]) -> dict[str, Any]:
    record = json.loads(source.read_bytes())
    raw = encode(
        {
            "contract_version": "engineer-review-v1",
            "id": "self-report",
            "pack": record["pack"],
            "config": record["config"],
            "created_at": record["created_at"],
            "results": [{"probe_id": k, "result": v} for k, v in results.items()],
        }
    )
    (source.parent / "claim.json").write_bytes(raw)
    return file_ref("claim.json", raw).model_dump(mode="json")


FRESHNESS = {"field": "freshness_guard", "before": "none", "after": "warn"}


def test_freshness_guard_repair_rule_conclusions(session: Session) -> None:
    target = target_session(session)
    pack, source = prepare(target, {"freshness_guard": "warn"})
    rewrite(source, {"id": "repair-unclaimed", "changes": [FRESHNESS]})
    first, public, _, folder = reviewed(target, pack, source)
    stored = json.loads((folder / "submission.json").read_bytes())
    assert stored["changes"] == [{"schema_version": 2, **FRESHNESS, "reason": None}]
    unclaimed = evaluate(first, folder)
    assert labels(unclaimed)["E4"] == "INSUFFICIENT"
    actual = {row.probe_id: row.result for row in public.public_results}
    assert actual["F01"] == "pass"

    rewrite(source, {"id": "repair-claimed", "regression_report": claim_file(source, actual)})
    report, public, public_raw, folder = reviewed(target, pack, source)
    assert report.status == "verified" and report.claim_check == "matched"
    assert report.hidden_comparison is not None and report.hidden_comparison.new_failures == 1
    evaluation = evaluate(report, folder)
    assert labels(evaluation) == {
        "E1": "MET",
        "E2": "NOT_MET",
        "E3": "MET",
        "E4": "MET",
        "E5": None,
    }
    e1, e2 = evaluation.conclusion("E1.target_fixed"), evaluation.conclusion("E2.no_regressions")
    assert e1.probe_ids == ("F01",)
    assert e2.probe_ids == () and e2.hidden_probes == 1
    e5 = evaluation.conclusion("E5.remaining_explanation")
    assert e5.status == "waiting_model" and e5.precheck is not None
    assert set(e5.precheck.unexplained_probe_ids) == {k for k, v in actual.items() if v == "fail"}
    raw = evaluation.model_dump_json()
    for row in report.results:
        if row.visibility == "hidden":
            assert row.probe_id not in raw and row.query not in raw
            assert row.probe_id not in public_raw

    rewrite(
        source,
        {
            "id": "repair-wrong-before",
            "changes": [FRESHNESS | {"before": "fallback"}],
            "regression_report": claim_file(source, actual),
        },
    )
    wrong, _, _, folder = reviewed(target, pack, source)
    e3 = evaluate(wrong, folder).conclusion("E3.change_consistency")
    assert e3.label == "NOT_MET"
    assert [(c.field, c.status) for c in e3.field_checks] == [
        ("freshness_guard", "before_mismatch")
    ]

    rewrite(
        source,
        {
            "id": "repair-false-claim",
            "changes": [FRESHNESS],
            "regression_report": claim_file(source, actual | {"F01": "fail"}),
        },
    )
    false_claim, _, _, folder = reviewed(target, pack, source)
    assert false_claim.claim_check == "mismatch"
    e4 = evaluate(false_claim, folder).conclusion("E4.reproducibility")
    assert e4.label == "NOT_MET" and e4.probe_ids == ("F01",)


def test_omitted_change_claim_is_partial(session: Session) -> None:
    target = target_session(session)
    pack, source = prepare(target, {"freshness_guard": "warn", "retrieval_limit": 4})
    rewrite(source, {"id": "repair-omitted", "changes": [FRESHNESS]})
    report, _, _, folder = reviewed(target, pack, source)
    e3 = evaluate(report, folder).conclusion("E3.change_consistency")
    assert e3.label == "PARTIAL" and "changes_omitted" in e3.reason_codes
    assert [(c.field, c.status) for c in e3.field_checks] == [
        ("retrieval_limit", "omitted"),
        ("freshness_guard", "matched"),
    ]
