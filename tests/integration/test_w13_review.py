"""Configuration verification at the CLI and immutable report boundaries."""

import json
import subprocess
from pathlib import Path

import pytest
from test_w13_pack import Session
from test_w13_pack import session as session
from test_w13_submission import prepare, submit

from career_lab.contracts.v2.engineer import EngineerPublicReport, EngineerRegressionReport


def review(session: Session, pack: Path, folder: Path) -> subprocess.CompletedProcess[str]:
    return session[6](
        "review",
        "--pack",
        str(pack),
        "--submission",
        str(folder),
        "--private-output",
        str(session[7] / "private-reviews"),
        "--output",
        str(session[7] / "public-reviews"),
    )


def prepared_submission(session: Session) -> tuple[Path, Path]:
    pack, source = prepare(session, {"freshness_guard": "warn"})
    result = submit(session, pack, source)
    assert result.returncode == 0, result.stdout + result.stderr
    return pack, session[7] / "submissions" / json.loads(result.stdout)["directory"]


def test_review_executes_candidate(session: Session) -> None:
    app, client, sid, headers, _, _, _, root, _ = session
    pack, folder = prepared_submission(session)
    before = client.get("/sessions/" + sid + "/timeline", headers=headers).json()
    result = review(session, pack, folder)
    assert result.returncode == 0, result.stdout + result.stderr
    identity = json.loads(result.stdout)["review_id"]
    report = EngineerRegressionReport.model_validate_json(
        (root / "private-reviews" / "reports" / identity / "report.json").read_bytes()
    )
    public = EngineerPublicReport.model_validate_json(
        (root / "public-reviews" / identity / "report.json").read_bytes()
    )
    assert report.status == "verified" and report.claim_check == "not_provided"
    assert len(report.results) == 13
    assert {r.probe_id for r in public.public_results} == {"F01", "F04", "F05", "F12"}
    assert public.hidden.passed + public.hidden.failed + public.hidden.errors == 9
    assert report.input.work_language == app.state.scenario_v2.work_language
    assert all(
        r.actual and r.actual.config.requested.freshness_guard == "warn" for r in report.results
    )
    assert all(r.actual and r.actual.execution.attempts == () for r in report.results)
    assert report.advice.status == "waiting_model" and report.advice.text is None
    assert public.affects_score is False
    assert client.get("/sessions/" + sid + "/timeline", headers=headers).json() == before


def test_review_claim_mismatch(session: Session) -> None:
    from career_lab.contracts.v2.engineer import EngineerClaimedReport
    from career_lab.engineer.files import encode, file_ref

    pack, source = prepare(session)
    record = json.loads(source.read_bytes())
    claim = EngineerClaimedReport(
        contract_version="engineer-review-v1",
        id="claimed-all-pass",
        pack=record["pack"],
        config=record["config"],
        created_at=record["created_at"],
        results=tuple(
            {"probe_id": ident, "result": "pass"} for ident in ("F01", "F04", "F05", "F12")
        ),
    )
    claim_raw = encode(claim)
    (source.parent / "claim.json").write_bytes(claim_raw)
    record["regression_report"] = file_ref("claim.json", claim_raw).model_dump(mode="json")
    source.write_bytes(encode(record))
    submitted = submit(session, pack, source)
    assert submitted.returncode == 0, submitted.stdout
    folder = session[7] / "submissions" / json.loads(submitted.stdout)["directory"]
    result = review(session, pack, folder)
    assert result.returncode == 1, result.stdout
    data = json.loads(result.stdout)
    assert data["status"] == "report_mismatch"
    report_dir = session[7] / "private-reviews" / "reports" / data["review_id"]
    report = EngineerRegressionReport.model_validate_json((report_dir / "report.json").read_bytes())
    assert report.claim_check == "mismatch"
    assert (folder / "claim.json").read_bytes() == claim_raw
    assert any(r.result == "fail" for r in report.results)
    assert any(f.kind == "claim_consistency" and f.status == "fail" for f in report.findings)


def test_review_detects_regression(session: Session) -> None:
    app, client, sid, headers, send, _, cli, root, credentials = session
    query = (
        "住宿报销上限是多少？"
        if app.state.scenario_v2.work_language == "zh"
        else ("What is the hotel reimbursement limit per night?")
    )
    from career_lab.scenarios.v2.module import ref_for

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
    assert trial["execution"]["source_versions"]["policy"] == 2
    assert "500" in trial["answer"]
    target: Session = app, client, sid, headers, send, trial, cli, root, credentials
    pack, folder = prepared_submission(target)
    result = review(target, pack, folder)
    assert result.returncode == 0, result.stdout
    identity = json.loads(result.stdout)["review_id"]
    report = EngineerRegressionReport.model_validate_json(
        (root / "private-reviews" / "reports" / identity / "report.json").read_bytes()
    )
    rows = {r.probe_id: r for r in report.results}
    assert rows["F01"].result == "pass"
    assert rows["F01"].actual.status == "answered_with_warning"
    assert rows["F09"].result == "fail"
    assert any(
        f.kind == "target_fix" and f.status == "pass" and "F01" in f.probe_ids
        for f in report.findings
    )
    assert any(
        f.kind == "new_regression" and f.status == "fail" and "F09" in f.probe_ids
        for f in report.findings
    )
    baseline = json.loads(
        (root / "private-reviews" / "reports" / identity / "baseline-results.json").read_bytes()
    )
    assert next(r for r in baseline if r["probe_id"] == "F01")["result"] == "fail"
    assert next(r for r in baseline if r["probe_id"] == "F09")["result"] == "pass"


def test_review_immutable(session: Session) -> None:
    pack, folder = prepared_submission(session)
    first = review(session, pack, folder)
    assert first.returncode == 0, first.stdout
    identity = json.loads(first.stdout)["review_id"]
    private = session[7] / "private-reviews" / "reports" / identity
    original = {p.name: p.read_bytes() for p in private.iterdir()}
    session[4]("actions", "refresh-later", "refresh_index", {"tool": "refresh_index"})
    again = review(session, pack, folder)
    assert again.returncode == 0, again.stdout
    assert json.loads(again.stdout)["review_id"] == identity
    assert {p.name: p.read_bytes() for p in private.iterdir()} == original
    report_file = private / "report.json"
    report_file.write_bytes(report_file.read_bytes() + b" ")
    rejected = review(session, pack, folder)
    assert rejected.returncode == 1
    assert "engineer_review_changed" in rejected.stdout


def test_review_interrupted(session: Session) -> None:
    import shutil

    pack, folder = prepared_submission(session)
    first = review(session, pack, folder)
    assert first.returncode == 0
    identity = json.loads(first.stdout)["review_id"]
    root = session[7]
    interrupted = root / "interrupted-store"
    interrupted.mkdir(mode=0o700)
    # Recreate the externally visible durable boundary after reservation but
    # before report publication. No assistant implementation is mocked.
    shutil.copytree(root / "private-reviews" / "inputs", interrupted / "inputs")

    def resume() -> subprocess.CompletedProcess[str]:
        return session[6](
            "review",
            "--pack",
            str(pack),
            "--submission",
            str(folder),
            "--private-output",
            str(interrupted),
            "--output",
            str(root / "recovered-public"),
        )

    recovered = resume()
    assert recovered.returncode == 1, recovered.stdout
    assert json.loads(recovered.stdout)["status"] == "incomplete"
    report_path = interrupted / "reports" / identity / "report.json"
    saved = report_path.read_bytes()
    report = EngineerRegressionReport.model_validate_json(saved)
    assert len(report.results) == 13
    assert all(r.result == "error" and r.actual is None for r in report.results)
    assert all(r.error_code == "engineer_review_interrupted" for r in report.results)
    assert resume().returncode == 1
    assert report_path.read_bytes() == saved


def test_review_public_boundary(session: Session) -> None:
    from career_lab.engineer.files import encode

    pack, source = prepare(session)
    record = json.loads(source.read_bytes())
    marker = "PRIVATE-UNVERIFIED-EXPLANATION"
    record["explanation"] = marker
    record["unresolved"] = [{"id": "u1", "description": marker, "visibility": "public"}]
    source.write_bytes(encode(record))
    submitted = submit(session, pack, source)
    assert submitted.returncode == 0
    folder = session[7] / "submissions" / json.loads(submitted.stdout)["directory"]
    result = review(session, pack, folder)
    assert result.returncode == 0, result.stdout
    identity = json.loads(result.stdout)["review_id"]
    public_raw = (session[7] / "public-reviews" / identity / "report.json").read_text()
    assert marker not in public_raw
    full = EngineerRegressionReport.model_validate_json(
        (session[7] / "private-reviews" / "reports" / identity / "report.json").read_bytes()
    )
    assert full.unresolved[0].description == marker
    for row in full.results:
        if row.visibility == "hidden":
            assert row.probe_id not in public_raw
            assert row.query not in public_raw
    assert "resources" not in json.loads(public_raw)
    assert "score" not in json.loads(public_raw)


def test_review_effective_resources(session: Session) -> None:
    pack, source = prepare(
        session, {"update_strategy": "realtime", "work_items": ["realtime_sync", "human_fallback"]}
    )
    submitted = submit(session, pack, source)
    assert submitted.returncode == 0
    folder = session[7] / "submissions" / json.loads(submitted.stdout)["directory"]
    result = review(session, pack, folder)
    assert result.returncode == 0, result.stdout
    identity = json.loads(result.stdout)["review_id"]
    report = EngineerRegressionReport.model_validate_json(
        (session[7] / "private-reviews" / "reports" / identity / "report.json").read_bytes()
    )
    assert report.input.resolved_config.requested.update_strategy == "realtime"
    assert report.input.resolved_config.effective.update_strategy == "daily"
    assert (
        report.input.resolved_config.differences["update_strategy"]
        == "realtime_sync_not_provisioned"
    )
    assert all(
        r.actual and r.actual.config.effective.update_strategy == "daily" for r in report.results
    )


@pytest.mark.parametrize("damage", ["pack", "candidate", "suite", "source_db", "revoked"])
def test_review_rechecks_sources_and_permission(session: Session, damage: str) -> None:
    from datetime import UTC, datetime, timedelta

    app, _, _, _, send, _, _, root, credentials = session
    pack, folder = prepared_submission(session)
    first = review(session, pack, folder)
    assert first.returncode == 0
    if damage == "pack":
        (pack / "public-probes.json").write_text("[]")
    elif damage == "candidate":
        (folder / "candidate.json").write_text("{}")
    elif damage == "suite":
        # A learner-supplied replacement suite is an unexpected submission file.
        (folder / "probe-suite.json").write_text("[]")
    elif damage == "source_db":
        # Keep the actual app database intact: target a missing source file via argv.
        rejected = session[6](
            "review",
            "--database",
            str(root / "absent.db"),
            "--pack",
            str(pack),
            "--submission",
            str(folder),
            "--output",
            str(root / "public-reviews"),
            "--private-output",
            str(root / "private-reviews"),
        )
        assert rejected.returncode == 1 and "engineer_database_unavailable" in rejected.stdout
        return
    else:
        grant = send(
            "delegations",
            "grant-review",
            "delegations.create",
            {
                "agent_label": "review-reader",
                "capabilities": ["read", "act"],
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            },
        )["result"]["result"]
        value = json.loads(credentials.read_bytes())
        value["token"] = grant["token"]
        credentials.write_text(json.dumps(value))
        did = grant["delegation"]["id"]
        send(
            "delegations/" + did,
            "revoke-review",
            "delegations.revoke",
            {"delegation_id": did},
            method="DELETE",
        )
    rejected = review(session, pack, folder)
    assert rejected.returncode == 1 and not rejected.stderr
    assert json.loads(rejected.stdout)["status"] == "failed"


def test_review_lock_prevents_concurrent_execution(session: Session) -> None:
    import fcntl

    pack, folder = prepared_submission(session)
    first = review(session, pack, folder)
    assert first.returncode == 0
    identity = json.loads(first.stdout)["review_id"]
    lock = session[7] / "private-reviews" / ".locks" / (identity + ".lock")
    with lock.open("r+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        blocked = review(session, pack, folder)
        assert blocked.returncode == 1 and "engineer_review_busy" in blocked.stdout
    assert review(session, pack, folder).returncode == 0


def test_review_claim_matches_actual_public_results(session: Session) -> None:
    from career_lab.engineer.files import encode, file_ref

    pack, source = prepare(session)
    submitted = submit(session, pack, source)
    folder = session[7] / "submissions" / json.loads(submitted.stdout)["directory"]
    first = review(session, pack, folder)
    assert first.returncode == 0
    original = json.loads(
        (
            session[7] / "public-reviews" / json.loads(first.stdout)["review_id"] / "report.json"
        ).read_bytes()
    )
    record = json.loads(source.read_bytes())
    record["id"] = "with-verified-self-report"
    claim_raw = encode(
        {
            "contract_version": "engineer-review-v1",
            "id": "accurate",
            "pack": record["pack"],
            "config": record["config"],
            "created_at": record["created_at"],
            "results": [
                {"probe_id": r["probe_id"], "result": r["result"]}
                for r in original["public_results"]
            ],
        }
    )
    (source.parent / "claim.json").write_bytes(claim_raw)
    record["regression_report"] = file_ref("claim.json", claim_raw).model_dump(mode="json")
    source.write_bytes(encode(record))
    second = submit(session, pack, source)
    assert second.returncode == 0
    folder = session[7] / "submissions" / json.loads(second.stdout)["directory"]
    checked = review(session, pack, folder)
    assert checked.returncode == 0
    actual = json.loads(
        (
            session[7] / "public-reviews" / json.loads(checked.stdout)["review_id"] / "report.json"
        ).read_bytes()
    )
    assert actual["claim_check"] == "matched"
    assert actual["id"] != original["id"]


@pytest.mark.parametrize("member", ["candidate", "claim"])
def test_review_reserved_input_filename(session: Session, member: str) -> None:
    from career_lab.engineer.files import encode, file_ref

    pack, source = prepare(session)
    record = json.loads(source.read_bytes())
    if member == "candidate":
        raw = (source.parent / "candidate.json").read_bytes()
        record["config"] = file_ref("input.json", raw).model_dump(mode="json")
    else:
        raw = encode(
            {
                "contract_version": "engineer-review-v1",
                "id": "claim",
                "pack": record["pack"],
                "config": record["config"],
                "created_at": record["created_at"],
                "results": [{"probe_id": "F01", "result": "pass"}],
            }
        )
        record["regression_report"] = file_ref("input.json", raw).model_dump(mode="json")
    (source.parent / "input.json").write_bytes(raw)
    source.write_bytes(encode(record))
    rejected = submit(session, pack, source)
    assert rejected.returncode == 1, rejected.stdout
    assert "engineer_submission_filename_invalid" in rejected.stdout
    assert not (session[7] / "submissions").exists()


def test_review_execution_error_is_incomplete(session: Session) -> None:
    made = session[4](
        "work-products",
        "draft-close",
        "work_products.create",
        {"kind": "text", "title": "Decision", "content": "Defer pending verification."},
    )
    product = next(ref for ref in made["objects"] if ref["kind"] == "product")
    session[4](
        "submissions",
        "close",
        "submissions.create",
        {"decision": "defer_with_conditions", "products": [product]},
    )
    pack, folder = prepared_submission(session)
    result = review(session, pack, folder)
    assert result.returncode == 1, result.stdout
    data = json.loads(result.stdout)
    assert data["status"] == "incomplete"
    report = EngineerRegressionReport.model_validate_json(
        (
            session[7] / "private-reviews" / "reports" / data["review_id"] / "report.json"
        ).read_bytes()
    )
    assert all(r.result == "error" and r.actual is None for r in report.results)
    assert all(r.error_code == "engineer_probe_execution_failed" for r in report.results)
    assert all(f.status == "unverified" for f in report.findings if f.kind == "new_regression")


CLOCK_FAILURE = """
import sys
from datetime import datetime, tzinfo
from unittest.mock import patch
from career_lab.engineer.cli import main

class Clock:
    failed = False

    @staticmethod
    def now(tz: tzinfo | None = None) -> datetime:
        if not Clock.failed:
            Clock.failed = True
            raise OSError("clock unavailable")
        return datetime.now(tz)

# Only the external clock boundary fails; the CLI, assistant and policy run
# their real source. The first baseline execution faults, then time recovers.
with patch("career_lab.assistant.v2.service.datetime", Clock):
    sys.exit(main(sys.argv[1:]))
"""


def test_review_baseline_clock_failure_is_incomplete(session: Session) -> None:
    import sys

    from test_w13_pack import ROOT, source_environment

    pack, folder = prepared_submission(session)
    root = session[7]
    failed = subprocess.run(
        [
            sys.executable,
            "-c",
            CLOCK_FAILURE,
            "review",
            "--database",
            str(root / "source.db"),
            "--credentials",
            str(session[8]),
            "--scenario",
            str(session[0].state.scenario_v2.package.root),
            "--pack",
            str(pack),
            "--submission",
            str(folder),
            "--output",
            str(root / "public-reviews"),
            "--private-output",
            str(root / "private-reviews"),
        ],
        cwd=ROOT,
        env=source_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert failed.returncode == 1, failed.stdout + failed.stderr
    data = json.loads(failed.stdout)
    assert data["status"] == "incomplete"
    report = EngineerRegressionReport.model_validate_json(
        (root / "private-reviews" / "reports" / data["review_id"] / "report.json").read_bytes()
    )
    assert report.results[0].result == "error"
    assert report.results[0].error_code == "engineer_baseline_execution_failed"
    assert report.results[0].actual is not None
    assert any(r.result != "error" for r in report.results[1:])


SOURCE_CHANGE = """
import json
import sys
from pathlib import Path
from unittest.mock import patch
from career_lab.engineer.cli import main

probe_path, trigger = Path(sys.argv[1]), Path(sys.argv[2])
original_read = Path.read_bytes
changed = False

def read_bytes(path: Path) -> bytes:
    global changed
    if path == trigger and not changed:
        changed = True
        rows = json.loads(original_read(probe_path))
        rows[1]["expected"]["status"] = "failed"
        probe_path.write_text(json.dumps(rows))
    return original_read(path)

# The only fault is a change to an isolated installed file after its first
# verified load. Actual CLI, manifest checks and simulator remain unchanged.
with patch.object(Path, "read_bytes", read_bytes):
    sys.exit(main(sys.argv[3:]))
"""


def test_review_rechecks_suite_bytes_after_initial_load(session: Session) -> None:
    import shutil
    import sys

    from test_w13_pack import ROOT, source_environment

    pack, folder = prepared_submission(session)
    root = session[7]
    original = session[0].state.scenario_v2.package.root
    before = (original / "probes.json").read_bytes()
    scenario = root / "isolated-installed-scenario"
    shutil.copytree(original, scenario)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            SOURCE_CHANGE,
            str(scenario / "probes.json"),
            str(folder / "submission.json"),
            "review",
            "--database",
            str(root / "source.db"),
            "--credentials",
            str(session[8]),
            "--scenario",
            str(scenario),
            "--pack",
            str(pack),
            "--submission",
            str(folder),
            "--output",
            str(root / "public-reviews"),
            "--private-output",
            str(root / "private-reviews"),
        ],
        cwd=ROOT,
        env=source_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "file_hash_mismatch" in result.stdout
    assert not (root / "private-reviews").exists()
    assert (original / "probes.json").read_bytes() == before


@pytest.mark.parametrize(
    "shape",
    [None, ["report.json", "baseline-results.json", "candidate-results.json", "config-diff.json"]],
    ids=["null", "member-list"],
)
def test_review_malformed_cache_index_is_json_error(session: Session, shape: object) -> None:
    pack, folder = prepared_submission(session)
    first = review(session, pack, folder)
    assert first.returncode == 0
    identity = json.loads(first.stdout)["review_id"]
    path = session[7] / "private-reviews" / "reports" / identity / "index.json"
    path.write_text(json.dumps(shape))
    malformed = path.read_bytes()
    rejected = review(session, pack, folder)
    assert rejected.returncode == 1
    assert not rejected.stderr
    assert json.loads(rejected.stdout) == {"status": "failed", "code": "engineer_review_changed"}
    assert path.read_bytes() == malformed
