"""Research export through the real HTTP runtime and module CLI (no model provider)."""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import JsonValue

from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts.v2 import VersionPoint
from career_lab.datasets.v3.common import json_bytes
from career_lab.jobs.worker import Worker


def command(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "career_lab.datasets.v3", *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )


class LiveSession:
    def __init__(self, root: Path, language: str) -> None:
        self.root = root
        self.language = language
        self.database = "sqlite:///" + str(root / "live.db")
        index = json.loads(Path("scenarios/pm_pilot/v2/installed/current.json").read_text())
        self.scenario = Path(index["main"][language]["root"]).resolve()
        self.app = create_runtime_app(self.database, scenario_root=self.scenario)
        self.client = TestClient(self.app)
        response = self.client.post(
            "/sessions",
            json={
                "schema_version": 2,
                "scenario": "pm_pilot_v2",
                "work_language": language,
            },
        )
        assert response.status_code == 200, response.text
        session = response.json()
        self.session_id = session["session_id"]
        self.headers = {"Authorization": "Bearer " + session["token"]}
        self.token_file = root / "owner-token"
        self.token_file.write_text(session["token"])
        self.token_file.chmod(0o600)
        self.key_file = root / "research-key"
        self.key_file.write_bytes(os.urandom(32))
        self.key_file.chmod(0o600)
        self.point_file = root / "point.json"
        self.grant_file = root / "authorization.json"

    def state(self) -> dict[str, JsonValue]:
        response = self.client.get("/sessions/" + self.session_id, headers=self.headers)
        assert response.status_code == 200, response.text
        return response.json()["state"]

    def send(
        self, path: str, request: str, operation: str, payload: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        state = self.state()
        response = self.client.post(
            "/sessions/" + self.session_id + "/" + path,
            headers=self.headers,
            json={
                "schema_version": 2,
                "request_id": request,
                "operation": operation,
                "payload": payload,
                "expected_version": state["business_seq"],
                "expected_workspace_revision": state["workspace_revision"],
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    def work(self) -> None:
        read = self.send(
            "actions",
            "read",
            "read_material",
            {
                "tool": "read_material",
                "material": {
                    "schema_version": 2,
                    "session_id": self.session_id,
                    "kind": "material",
                    "object_id": "brief",
                    "version": 1,
                },
            },
        )
        self.quote = read["result"]["fragments"][1]["ref"]
        self.content = (
            "Defer until scope and ownership are verified."
            if self.language == "en"
            else "在范围和负责人核实前暂缓试点。"
        )
        made = self.send(
            "work-products",
            "draft",
            "work_products.create",
            {
                "kind": "text",
                "purpose": "commitment",
                "title": "Decision",
                "content": self.content,
                "evidence_refs": [self.quote],
            },
        )
        self.product = next(ref for ref in made["objects"] if ref["kind"] == "product")
        trial = self.send(
            "tests",
            "trial",
            "tests.create",
            {
                "query": "What is the hotel reimbursement limit?"
                if self.language == "en"
                else "住宿报销上限是多少？",
                "config_version": 0,
            },
        )
        self.answer = trial["result"]["test"]["answer"]
        self.send(
            "work-products/" + self.product["object_id"] + "/shares",
            "share",
            "work_products.shares.create",
            {
                "product_id": self.product["object_id"],
                "product_version": self.product["version"],
                "recipient_role": "tech_lead",
            },
        )
        self.send(
            "submissions",
            "submit",
            "submissions.create",
            {"decision": "defer_with_conditions", "products": [self.product]},
        )
        assert Worker(self.app.state.jobs, self.app.state.handlers).run_once()
        restored = self.client.get(
            "/sessions/" + self.session_id + "/requests/submit", headers=self.headers
        ).json()
        assert restored["jobs"][0]["status"] == "completed", restored

    def connection(self) -> list[object]:
        return [
            "--database-url",
            self.database,
            "--session",
            self.session_id,
            "--token-file",
            self.token_file,
            "--scenario-root",
            self.scenario,
            "--point",
            self.point_file,
        ]

    def authorize(self) -> dict[str, JsonValue]:
        self.point_file.write_bytes(
            json_bytes({key: self.state()[key] for key in VersionPoint.model_fields})
        )
        response = command(
            "authorize",
            *self.connection(),
            "--key-file",
            self.key_file,
            "--purpose",
            "dataset_export",
            "--consent",
            "--expires-at",
            (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "--output",
            self.grant_file,
        )
        assert response.returncode == 0, response.stdout + response.stderr
        return json.loads(response.stdout)

    def export(self, output: Path, *, authorized: bool = True) -> subprocess.CompletedProcess[str]:
        args = ["export", "--live", *self.connection(), "--output", output]
        if authorized:
            args += ["--key-file", self.key_file, "--authorization", self.grant_file]
        return command(*args)

    def close(self) -> None:
        self.client.close()
        self.app.state.store.close()


@pytest.fixture(params=["zh", "en"])
def live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[LiveSession]:
    monkeypatch.delenv("CAREER_LAB_SCENARIO_CATALOG", raising=False)
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    session = LiveSession(tmp_path, request.param)
    try:
        yield session
    finally:
        session.close()


def test_exp_02_research_consent_is_separate_from_session_ownership(live: LiveSession) -> None:
    """EXP-02: an owner without an explicit grant cannot export private work."""
    live.work()
    identity = live.authorize()
    assert identity["purpose"] == "dataset_export"
    assert identity["issuer"]["kind"] == "human"
    assert live.token_file.read_text() not in live.grant_file.read_text()
    response = live.export(live.root / "denied", authorized=False)
    assert response.returncode != 0
    assert json.loads(response.stdout)["error"] == "research_authorization_required"
    assert live.content not in response.stdout + response.stderr
    assert not (live.root / "denied").exists()


def test_exp_01_live_export_requires_trusted_runtime(live: LiveSession) -> None:
    """EXP-01: self-declared JSON is rejected; a real saved session is exportable."""
    from career_lab.datasets.v3.release import load_export

    offline = live.root / "self-declared.json"
    offline.write_bytes(json_bytes({"origin": "env_run"}))
    units = live.root / "units.json"
    units.write_text("[]")
    forged = command(
        "export", "--snapshot", offline, "--units", units, "--output", live.root / "forged"
    )
    assert forged.returncode != 0
    assert json.loads(forged.stdout)["error"] == "live_snapshot_adapter_required"
    live.work()
    live.authorize()
    response = live.export(live.root / "export")
    assert response.returncode == 0, response.stdout + response.stderr
    result = load_export(live.root / "export/audit/export")
    assert result.origin == "env_run"
    assert len([r for r in result.records if r.family == "relation"]) == 1
    assert len([r for r in result.records if r.family == "criterion"]) == 14
    assert all(r.language == live.language for r in result.records)
    assert all(a.status == "pending" for a in result.annotations)
    assert not json.loads(response.stdout)["training_ready"]


def test_exp_03_export_replays_without_changing_the_session(live: LiveSession) -> None:
    """EXP-03: identical window/output is idempotent; later work cannot enter it."""
    live.work()
    live.authorize()
    original = live.state()
    first = live.export(live.root / "export")
    assert first.returncode == 0, first.stdout + first.stderr
    repeated = live.export(live.root / "export")
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert json.loads(first.stdout) == json.loads(repeated.stdout)
    assert live.state() == original
    second = live.export(live.root / "copy")
    assert second.returncode == 0, second.stdout + second.stderr
    first_files = {
        str(p.relative_to(live.root / "export")): p.read_bytes()
        for p in (live.root / "export").rglob("*")
        if p.is_file()
    }
    second_files = {
        str(p.relative_to(live.root / "copy")): p.read_bytes()
        for p in (live.root / "copy").rglob("*")
        if p.is_file()
    }
    assert first_files == second_files
    assert live.state() == original


def test_exp_04_absent_research_facets_have_reasons(live: LiveSession) -> None:
    """EXP-04: no branch/decision records means zero rows, never fabricated rows."""
    live.work()
    live.authorize()
    response = live.export(live.root / "export")
    assert response.returncode == 0, response.stdout + response.stderr
    families = json.loads(response.stdout)["families"]
    assert families["trajectory"] == {"records": 0, "empty_reason": "no_branch_records"}
    assert families["acquisition"] == {"records": 0, "empty_reason": "no_acquisition_records"}
    assert families["relation"]["records"] == 1
    assert families["criterion"]["records"] == 14


def test_exp_05_inputs_are_separate_and_reaudited_by_allowlist(live: LiveSession) -> None:
    """EXP-05: exported inputs exclude hidden state; altered files fail the public audit."""
    import hashlib

    live.work()
    live.authorize()
    output = live.root / "export"
    response = live.export(output)
    assert response.returncode == 0, response.stdout + response.stderr
    audit = command("validate-data", "--export", output)
    assert audit.returncode == 0, audit.stdout + audit.stderr
    inputs_path = output / "data/train.inputs.jsonl"
    rows = [json.loads(line) for line in inputs_path.read_text().splitlines()]
    assert all(set(row) == {"record_id", "input_hash", "model_input"} for row in rows)
    assert all(
        set(row["model_input"]["evidence"]["rule_context"]) == {"evidence_time_context"}
        for row in rows
    )
    assert (output / "data/train.labels.jsonl").is_file()
    assert (output / "audit/source-index.json").is_file()
    sources = json.loads((output / "audit/source-index.json").read_text())
    assert any(value["ref"]["kind"] == "test" for value in sources.values())
    assert any(value["ref"]["object_id"] == live.product["object_id"] for value in sources.values())
    rows[0]["model_input"]["evidence"]["rule_context"]["hidden_probes"] = ["secret-probe"]
    inputs_path.write_bytes(b"".join(json_bytes(row) for row in rows))
    manifest_path = output / "dataset-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["data/train.inputs.jsonl"] = {
        "sha256": hashlib.sha256(inputs_path.read_bytes()).hexdigest(),
        "size": inputs_path.stat().st_size,
    }
    manifest_path.write_bytes(json_bytes(manifest))
    rejected = command("validate-data", "--export", output)
    assert rejected.returncode != 0
    assert json.loads(rejected.stdout)["error"] == "model_input_metadata_leak"
    assert "secret-probe" not in rejected.stdout + rejected.stderr


def test_exp_06_language_anchors_and_shared_lineage_cannot_cross_split(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EXP-06: real bilingual sources retain spans; a supplied split cannot divide them."""
    from dataclasses import replace

    from career_lab.datasets.v3.release import load_export, save_export

    monkeypatch.delenv("CAREER_LAB_SCENARIO_CATALOG", raising=False)
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    outputs = []
    records = []
    for language in ("zh", "en"):
        root = tmp_path / language
        root.mkdir()
        session = LiveSession(root, language)
        try:
            session.work()
            session.authorize()
            output = root / "export"
            response = session.export(output)
            assert response.returncode == 0, response.stdout + response.stderr
            outputs.append(output)
            records.append(load_export(output / "audit/export"))
        finally:
            session.close()
    result = command("validate-data", "--export", outputs[0], "--export", outputs[1])
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["languages"] == {"en": 15, "zh": 15}
    assert report["source_anchors"]["zh"] > 0 and report["source_anchors"]["en"] > 0
    assert {row.split for result in records for row in result.records} == {"train"}
    assert {row.provenance.executor.kind for result in records for row in result.records} == {
        "human"
    }
    bad = replace(
        records[1],
        records=tuple(row.model_copy(update={"split": "dev"}) for row in records[1].records),
    )
    save_export(tmp_path / "bad-split", bad)
    rejected = command("validate-data", "--export", outputs[0], "--export", tmp_path / "bad-split")
    assert rejected.returncode != 0
    assert any(
        row["code"] == "connected_lineage_cross_split"
        for row in json.loads(rejected.stdout)["report"]["errors"]
    )


def test_exp_02_signed_scope_tampering_and_expiry_are_rejected(live: LiveSession) -> None:
    """An authentic owner cannot widen an issued grant or bypass its expiry."""
    from career_lab.contracts.v2 import ProtocolError
    from career_lab.research.authorization import SignedAuthorization, validate

    live.authorize()
    original = live.grant_file.read_bytes()
    signed = SignedAuthorization.model_validate_json(original)
    with pytest.raises(ProtocolError, match="expired"):
        validate(
            signed,
            key=live.key_file.read_bytes(),
            session_id=live.session_id,
            purpose="dataset_export",
            point=signed.authorization.through_point,
            now=signed.authorization.expires_at,
        )
    forged = json.loads(original)
    forged["authorization"]["purpose"] = "branch_restore"
    live.grant_file.write_bytes(json_bytes(forged))
    rejected = live.export(live.root / "tampered")
    assert rejected.returncode != 0
    assert json.loads(rejected.stdout)["error"] == "research_authorization_invalid"
    live.grant_file.write_bytes(original)
    live.work()
    live.point_file.write_bytes(
        json_bytes({key: live.state()[key] for key in VersionPoint.model_fields})
    )
    rejected = live.export(live.root / "outside-window")
    assert rejected.returncode != 0
    assert json.loads(rejected.stdout)["error"] == "research_authorization_window"
    assert not (live.root / "outside-window").exists()


def test_catalog_session_resolves_its_frozen_english_scenario(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CAREER_LAB_SCENARIO_CATALOG",
        str(Path("tests/regression/published-catalog.json").resolve()),
    )
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    session = LiveSession(tmp_path, "en")
    try:
        session.work()
        session.authorize()
        response = session.export(tmp_path / "export")
        assert response.returncode == 0, response.stdout + response.stderr
        assert json.loads(response.stdout)["languages"] == {"en": 15}
    finally:
        session.close()


def test_overflow_retains_authorized_dropped_source_identity(live: LiveSession) -> None:
    from career_lab.datasets.v3.release import load_export

    long = live.send(
        "work-products",
        "long",
        "work_products.create",
        {"kind": "text", "content": "Long supporting record. " * 1500},
    )
    reference = next(ref for ref in long["objects"] if ref["kind"] == "product")
    short = live.send(
        "work-products",
        "short",
        "work_products.create",
        {
            "kind": "text",
            "content": "Verify scope before a decision.",
            "evidence_refs": [{**reference, "observed_at_seq": long["state"]["business_seq"]}],
        },
    )
    product = next(ref for ref in short["objects"] if ref["kind"] == "product")
    live.send(
        "submissions",
        "submit",
        "submissions.create",
        {"decision": "defer_with_conditions", "products": [product]},
    )
    live.authorize()
    response = live.export(live.root / "export")
    assert response.returncode == 0, response.stdout + response.stderr
    result = load_export(live.root / "export/audit/export")
    assert len(result.records) == 14
    assert any(row.model_input.evidence.completeness == "text_overflow" for row in result.records)
    assert not result.quarantined


def test_failed_execution_is_counted_without_a_semantic_label(live: LiveSession) -> None:
    from career_lab.contracts.v2 import ObjectRef

    response = live.client.get("/sessions/" + live.session_id + "/workbench", headers=live.headers)
    config = response.json()["result"]["result"]["timeline"]["workspace"]["config"]
    base = ObjectRef(
        session_id=live.session_id,
        kind="config",
        object_id=config["id"],
        version=config["version"],
        config_version=config["config_version"],
    )
    live.send(
        "configuration",
        "configuration",
        "configuration.apply",
        {"base": base.model_dump(mode="json"), "settings": {"fallback": "none"}},
    )
    trial = live.send(
        "tests",
        "failed-test",
        "tests.create",
        {
            "query": "火星天气如何？" if live.language == "zh" else "What is the weather on Mars?",
            "config_version": 1,
        },
    )
    assert trial["result"]["test"]["status"] == "failed"
    live.authorize()
    response = live.export(live.root / "export")
    assert response.returncode == 0, response.stdout + response.stderr
    manifest = json.loads(response.stdout)
    assert len(manifest["execution_failures"]) == 1
    assert manifest["execution_failures"][0]["ref"]["object_id"] == trial["result"]["test"]["id"]
    assert manifest["families"]["relation"]["records"] == 0
    assert manifest["training_ready"] is False


@pytest.mark.parametrize("attack", ["unmanifested_symlink", "unbound_index", "replay_symlink"])
def test_export_audit_keeps_file_reads_inside_the_package(live: LiveSession, attack: str) -> None:
    import hashlib

    live.authorize()
    output = live.root / "export"
    response = live.export(output)
    assert response.returncode == 0, response.stdout + response.stderr
    clean = command("validate-data", "--export", output)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    outside = live.root / "outside.json"
    outside.write_text(json.dumps({"outside": {"language": "private-canary"}}))
    index = output / "audit/source-index.json"
    manifest_path = output / "dataset-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if attack in {"unmanifested_symlink", "replay_symlink"}:
        index.unlink()
        index.symlink_to(outside)
        del manifest["files"]["audit/source-index.json"]
    else:
        index.write_bytes(outside.read_bytes())
        manifest["files"]["audit/source-index.json"] = {
            "sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
            "size": index.stat().st_size,
        }
    manifest_path.write_bytes(json_bytes(manifest))
    rejected = (
        live.export(output)
        if attack == "replay_symlink"
        else command("validate-data", "--export", output)
    )
    assert rejected.returncode != 0
    assert "private-canary" not in rejected.stdout + rejected.stderr
    if attack == "replay_symlink":
        assert json.loads(rejected.stdout)["error"] == "export_output_symlink"


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("excluded", ["source", "parent"])
def test_export_window_rejections_keep_safe_parent_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str, excluded: str
) -> None:
    from career_lab.research.authorization import issue

    monkeypatch.delenv("CAREER_LAB_SCENARIO_CATALOG", raising=False)
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    session = LiveSession(tmp_path, language)
    try:
        session.send(
            "work-products",
            "note",
            "work_products.create",
            {
                "kind": "text",
                "purpose": "exploration",
                "title": "Notes",
                "content": "Observe sources.",
            },
        )
        start = VersionPoint(**{key: session.state()[key] for key in VersionPoint.model_fields})
        first = session.send(
            "tests",
            "sourced-trial",
            "tests.create",
            {
                "query": "What is the hotel reimbursement limit?"
                if language == "en"
                else "住宿报销上限是多少？",
                "config_version": 0,
            },
        )["result"]["test"]
        assert first["status"] != "failed" and first["citations"]
        if excluded == "parent":
            session.send(
                "work-products",
                "later-note",
                "work_products.create",
                {
                    "kind": "text",
                    "purpose": "exploration",
                    "title": "Later notes",
                    "content": "Inspect a later interval.",
                },
            )
            start = VersionPoint(**{key: session.state()[key] for key in VersionPoint.model_fields})
        other = session.send(
            "tests",
            "unsourced-trial",
            "tests.create",
            {
                "query": "How many rings does Saturn have?"
                if language == "en"
                else "土星有多少个环？",
                "config_version": 0,
            },
        )["result"]["test"]
        assert other["status"] != "failed" and not other["citations"]
        end = VersionPoint(**{key: session.state()[key] for key in VersionPoint.model_fields})
        session.point_file.write_bytes(json_bytes(end))
        auth = session.app.state.v2_store.authenticate(
            session.session_id, session.token_file.read_text()
        )
        signed = issue(
            auth,
            purpose="dataset_export",
            from_point=start,
            through_point=end,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            key=session.key_file.read_bytes(),
        )
        session.grant_file.write_bytes(json_bytes(signed.model_dump(mode="json")))
        response = session.export(tmp_path / "export")
        assert response.returncode == 0, response.stdout + response.stderr
        report = json.loads(response.stdout)
        assert report["families"]["relation"]["records"] == 1
        assert len(report["quarantined"]) == 1
        rejected = report["quarantined"][0]
        if excluded == "source":
            assert rejected["ref"]["object_id"] == first["id"]
        else:
            assert "ref" not in rejected
            exported_text = "\n".join(
                path.read_text() for path in (tmp_path / "export").rglob("*") if path.is_file()
            )
            assert first["id"] not in exported_text
            assert first["query"] not in exported_text
        assert rejected["reason"] == "research_authorization_window"
        assert first["answer"] not in json.dumps(rejected, ensure_ascii=False)
        assert first["citations"][0]["object_id"] not in json.dumps(rejected, ensure_ascii=False)
        before = {
            str(path.relative_to(tmp_path / "export")): path.read_bytes()
            for path in (tmp_path / "export").rglob("*")
            if path.is_file()
        }
        state = session.state()
        repeated = session.export(tmp_path / "export")
        assert repeated.returncode == 0, repeated.stdout + repeated.stderr
        assert repeated.stdout == response.stdout
        assert before == {
            str(path.relative_to(tmp_path / "export")): path.read_bytes()
            for path in (tmp_path / "export").rglob("*")
            if path.is_file()
        }
        assert session.state() == state
        policies = tmp_path / "unapproved-policies.json"
        policies.write_bytes(json_bytes({}))
        refused = command(
            "publish",
            "--export",
            tmp_path / "export/audit/export",
            "--source-root",
            tmp_path / "export",
            "--policies",
            policies,
            "--output",
            tmp_path / "release",
        )
        assert refused.returncode == 2
        assert json.loads(refused.stdout)["error"] == "no_publishable_records"
        assert not (tmp_path / "release").exists()
    finally:
        session.close()
