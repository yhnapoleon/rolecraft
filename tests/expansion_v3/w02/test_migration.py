"""Migration safety under the exact currently registered public input."""

from pathlib import Path
import hashlib, json
import pytest
from fastapi.testclient import TestClient

from career_lab.contracts.v2 import ProtocolError
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry
from career_lab.scenarios.v2.module import ScenarioModule
from .migration_support import inspect_transition, stage_registered_migration
from career_lab.scenarios.v2.loader import load_package

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "scenarios/pm_pilot/v2"
CURRENT = ROOT / "docs/contracts/expansion-v3/manifest.json"
REVISION = "expansion-v3-" + hashlib.sha256(CURRENT.read_bytes()).hexdigest()


def test_preflight_does_not_treat_equal_schemas_as_semantic_compatibility(tmp_path):
    candidate = json.loads(CURRENT.read_bytes())
    candidate["review_fixes"] = {
        **candidate.get("review_fixes", {}),
        "new": "implementation changed",
    }
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(candidate))
    revision = "expansion-v3-" + hashlib.sha256(path.read_bytes()).hexdigest()
    result = inspect_transition(SOURCE, CURRENT, path, revision)
    assert result["requires_rebuild"]
    assert result["changed_consumed_schemas"] == []
    assert not result["semantic_compatibility_verified"]
    assert not result["public_input_installed"]


def test_uninstalled_revision_cannot_be_written_into_runtime(tmp_path):
    before = (SOURCE / "manifest.json").read_bytes()
    with pytest.raises(ProtocolError, match="migration manifest mismatch"):
        stage_registered_migration(
            SOURCE,
            tmp_path / "candidate",
            expected_revision="expansion-v3-" + "f" * 64,
            scenario_revision="2.3.1-preflight",
            runtime_revision="preflight",
        )
    assert not (tmp_path / "candidate").exists()
    assert (SOURCE / "manifest.json").read_bytes() == before


def test_real_current_input_rebuild_preserves_business_data_and_old_bundle(tmp_path):
    before = {
        p.relative_to(SOURCE).as_posix(): p.read_bytes() for p in SOURCE.rglob("*") if p.is_file()
    }
    destination = tmp_path / "rebuilt"
    report = stage_registered_migration(
        SOURCE,
        destination,
        expected_revision=REVISION,
        scenario_revision="2.3.1-preflight",
        runtime_revision="preflight-current-input",
    )
    assert report["candidate_constructor"] == "passed"
    assert not report["candidate_installed"] and not report["compatibility_approved"]
    assert load_package(destination).bundle.revision == "2.3.1-preflight"
    assert all((SOURCE / path).read_bytes() == raw for path, raw in before.items())
    assert (SOURCE / "research/public-case-records.json").read_bytes() == (
        destination / "research/public-case-records.json"
    ).read_bytes()


def test_same_revision_or_existing_destination_rejected(tmp_path):
    old = load_package(SOURCE)
    with pytest.raises(ProtocolError, match="new scenario revision"):
        stage_registered_migration(
            SOURCE,
            tmp_path / "candidate",
            expected_revision=REVISION,
            scenario_revision=old.bundle.revision,
            runtime_revision="another",
        )
    target = tmp_path / "exists"
    target.mkdir()
    with pytest.raises(ProtocolError, match="destination exists"):
        stage_registered_migration(
            SOURCE,
            target,
            expected_revision=REVISION,
            scenario_revision="2.3.1",
            runtime_revision="another",
        )


def test_rebuilt_current_input_runs_real_gateway_c0(tmp_path):
    target = tmp_path / "candidate"
    stage_registered_migration(
        SOURCE,
        target,
        expected_revision=REVISION,
        scenario_revision="2.3.1-preflight",
        runtime_revision="preflight-current-input",
    )
    module = ScenarioModule(target)
    app = create_app(
        "sqlite:///" + str(tmp_path / "app.db"), extensions=module.install(ExtensionRegistry())
    )
    with TestClient(app) as client:
        made = client.post("/sessions", json={"schema_version": 2, "scenario": "pm_pilot_v2"})
        assert made.status_code == 200, made.text
        data = made.json()
        sid = data["session_id"]
        headers = {"Authorization": "Bearer " + data["token"]}
        response = client.post(
            f"/sessions/{sid}/tests",
            headers=headers,
            json={
                "schema_version": 2,
                "request_id": "c0",
                "expected_version": 0,
                "expected_workspace_revision": 0,
                "operation": "tests.create",
                "payload": {"query": "住宿报销上限是多少？", "config_version": 0},
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["result"]["test"]["config_ref"]["config_version"] == 0
    app.state.store.close()


def test_constructor_still_rejects_a_fully_resealed_wrong_foundation(tmp_path):
    target = tmp_path / "candidate"
    stage_registered_migration(
        SOURCE,
        target,
        expected_revision=REVISION,
        scenario_revision="2.3.1-preflight",
        runtime_revision="preflight-current-input",
    )
    source_path = target / "runtime/source-files.json"
    source = json.loads(source_path.read_bytes())
    source["foundation_contract_sha256"] = "0" * 64
    source_path.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n")
    runtime_path = target / "runtime/bundle.json"
    runtime = json.loads(runtime_path.read_bytes())
    runtime["source"]["overlay"]["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    runtime_path.write_text(json.dumps(runtime, ensure_ascii=False, indent=2) + "\n")
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for item in manifest["files"]:
        if item["path"] in {"runtime/source-files.json", "runtime/bundle.json"}:
            item["sha256"] = hashlib.sha256((target / item["path"]).read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    with pytest.raises(ProtocolError) as error:
        ScenarioModule(target)
    assert error.value.code == "runtime_contract_mismatch" and error.value.status == 409


def test_current_delivery_constructor_matches_its_manifest():
    assert (
        ScenarioModule(SOURCE).package.content_hash
        == hashlib.sha256((SOURCE / "manifest.json").read_bytes()).hexdigest()
    )


def test_preflight_reports_removed_public_implementation(tmp_path):
    candidate = json.loads(CURRENT.read_bytes())
    removed = next(iter(candidate["source_files"]))
    del candidate["source_files"][removed]
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(candidate))
    revision = "expansion-v3-" + hashlib.sha256(path.read_bytes()).hexdigest()
    assert (
        removed
        in inspect_transition(SOURCE, CURRENT, path, revision)["changed_public_implementations"]
    )


def test_migration_does_not_write_under_the_previous_release():
    target = SOURCE / "migration-must-not-create"
    with pytest.raises(ProtocolError, match="destination inside source"):
        stage_registered_migration(
            SOURCE,
            target,
            expected_revision=REVISION,
            scenario_revision="2.3.1-preflight",
            runtime_revision="preflight-current-input",
        )
    assert not target.exists()


def test_rule_changes_cannot_be_relabelled_as_input_only_migration(tmp_path, monkeypatch):
    import yaml
    from . import migration_support as migration

    original = migration.build_seed

    def altered_rules(root, cases):
        original(root, cases)
        path = root / "scenario.yaml"
        rules = yaml.safe_load(path.read_text())
        rules["approval_limits"]["capacity"] += 10
        path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=True))

    monkeypatch.setattr(migration, "build_seed", altered_rules)
    with pytest.raises(ProtocolError, match="business rules changed"):
        stage_registered_migration(
            SOURCE,
            tmp_path / "candidate",
            expected_revision=REVISION,
            scenario_revision="2.3.1-preflight",
            runtime_revision="preflight-current-input",
        )
