"""Reviews, trials and task packages run the engineer regression suite, never authored probes.

Authored scenario probes carry per-probe preconditions; under one candidate configuration they
produce false regressions. A scenario without an engineer suite has no engineer path.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_engineer_session import Eng, draft, sign, trial
from test_engineer_session import eng as eng

from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts.v2.engineer import EngineerRegressionReport
from career_lab.engineer import suite as engineer_suites
from career_lab.engineer.suite import engineer_suite


def suite_bytes(eng: Eng) -> bytes:
    raw = engineer_suite(eng.app.state.scenario_v2.package)
    assert raw is not None
    return raw


def test_review_binds_the_engineer_suite(eng: Eng) -> None:
    ticket = eng.seeded()
    made = eng.ok(draft(eng, ticket, "d"))["draft"]
    review_id = eng.ok(sign(eng, ticket, made["id"], "s"))["review"]["review_id"]
    folder = eng.root / "private-reviews" / eng.sid
    raw = suite_bytes(eng)
    assert (folder / "inputs" / review_id / "probe-suite.json").read_bytes() == raw
    report = EngineerRegressionReport.model_validate_json(
        (folder / "reports" / review_id / "report.json").read_bytes()
    )
    assert report.input.probe_suite.sha256 == hashlib.sha256(raw).hexdigest()
    assert report.input.probe_ids == tuple(row["id"] for row in json.loads(raw))


def test_trial_reads_the_engineer_suite(
    eng: Eng, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A suite whose public F01 expects the stale answer makes the baseline trial pass F01."""
    copy = tmp_path / "suites"
    shutil.copytree(engineer_suites.SUITES, copy)
    path = copy / "pm_pilot" / (eng.language + ".json")
    rows = json.loads(path.read_bytes())
    rows[0]["expected"] = {"status": "answered", "contains": ["500"], "citation_versions": {}}
    path.write_text(json.dumps(rows, ensure_ascii=False))
    monkeypatch.setattr(engineer_suites, "SUITES", copy)
    ticket = eng.seeded()
    rows = eng.ok(trial(eng, ticket, {}, "baseline"))["trial"]["rows"]
    f01 = next(row for row in rows if row["id"] == "F01")
    assert (f01["expected_status"], f01["result"]) == ("answered", "pass")


@pytest.mark.parametrize("language", ["zh", "en"])
def test_scenarios_without_an_engineer_suite_have_no_engineer_tickets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    from scripts.regression.published import write_catalog

    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    monkeypatch.setenv("CAREER_LAB_ENGINEER_ROOT", str(tmp_path / "engineer"))
    monkeypatch.setenv("CAREER_LAB_SCENARIO_CATALOG", str(write_catalog(tmp_path / "catalog.json")))
    monkeypatch.delenv("CAREER_LAB_RECOGNIZERS", raising=False)
    app = create_runtime_app("sqlite:///" + str(tmp_path / "source.db"))
    try:
        with TestClient(app) as client:
            response = client.post(
                "/sessions",
                json={
                    "schema_version": 2,
                    "scenario": "pm_pilot_urgent_v2",
                    "work_language": language,
                },
            )
            assert response.status_code == 200, response.text
            created = response.json()
            variant = Eng(
                app, client, created["session_id"], created["token"], language, tmp_path / "e"
            )
            query = "火星天气如何？" if language == "zh" else "What is the weather on Mars?"
            made = variant.ok(
                variant.call("/tests", "tests.create", {"query": query, "config_version": 0}, "t")
            )
            state = variant.state()
            for key, payload in (
                ("seed", {"from": "seeded"}),
                ("tests", {"from": "tests", "test_ids": [made["test"]["id"]]}),
            ):
                refused = variant.call("/engineer/tickets", "engineer.tickets.create", payload, key)
                assert refused.status_code == 409, refused.text
                assert refused.json()["code"] == "engineer_suite_unavailable"
            # No go-live either: the world is left as the learner had it.
            assert variant.state() == state
            assert variant.ok(variant.read("/engineer/tickets"))["tickets"] == []
    finally:
        app.state.store.close()


def test_ticket_pack_exports_the_suite_public_rows(eng: Eng) -> None:
    ticket = eng.seeded()
    detail = eng.ok(eng.read("/engineer/tickets/" + ticket["id"]))["ticket"]
    rows = json.loads(suite_bytes(eng))
    public = [{"id": row["id"], "query": row["query"]} for row in rows if row["public"]]
    assert detail["public_probes"] == public


def test_the_cli_refuses_a_scenario_without_an_engineer_suite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The command line has no authored-probe fallback either: no pack, so no review."""
    import subprocess
    import sys

    from scripts.regression.published import write_catalog

    catalog = json.loads(write_catalog(tmp_path / "catalog.json").read_text())
    root = next(
        Path(row["root"])
        for row in catalog["scenarios"]
        if row["work_language"] == "zh" and Path(row["root"]).name == "pm_pilot_urgent"
    )
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    monkeypatch.delenv("CAREER_LAB_SCENARIO_CATALOG", raising=False)
    database = tmp_path / "source.db"
    app = create_runtime_app("sqlite:///" + str(database), scenario_root=root)
    try:
        with TestClient(app) as client:
            created = client.post(
                "/sessions",
                json={"schema_version": 2, "scenario": "pm_pilot_urgent_v2", "work_language": "zh"},
            ).json()
            variant = Eng(app, client, created["session_id"], created["token"], "zh", tmp_path)
            made = variant.ok(
                variant.call(
                    "/tests", "tests.create", {"query": "火星天气如何？", "config_version": 0}, "t"
                )
            )
    finally:
        app.state.store.close()
    credentials = tmp_path / "credentials.json"
    credentials.write_text(
        json.dumps(
            {
                "api_url": "http://127.0.0.1:9",
                "session_id": created["session_id"],
                "token": created["token"],
            }
        )
    )
    credentials.chmod(0o600)
    repo = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "career_lab.engineer",
            "pack",
            "--database",
            str(database),
            "--credentials",
            str(credentials),
            "--scenario",
            str(root),
            "--test",
            made["test"]["id"],
            "--output",
            str(tmp_path / "pack"),
        ],
        capture_output=True,
        text=True,
        cwd=repo,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(repo / "src"), "PYTHONSAFEPATH": "1"},
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"status": "failed", "code": "engineer_suite_unavailable"}
    assert not (tmp_path / "pack").exists()
