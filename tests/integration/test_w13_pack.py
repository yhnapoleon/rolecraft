"""Engineer handoff through the normal session API and public CLI."""

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from test_w13_legacy_fixture import released_sources

from career_lab.api.vertical_runtime import create_runtime_app, default_installed_scenario

ROOT = Path(__file__).resolve().parents[2]


Session = tuple[
    FastAPI,
    httpx.Client,
    str,
    dict[str, str],
    Callable[..., dict[str, Any]],
    dict[str, Any],
    Callable[..., subprocess.CompletedProcess[str]],
    Path,
    Path,
]


@contextmanager
def local_http(app: FastAPI) -> Iterator[httpx.Client]:
    """Real HTTP on an OS-assigned port, with explicit server and socket cleanup."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "HTTP server did not start"
        url = "http://127.0.0.1:" + str(sock.getsockname()[1])
        with httpx.Client(base_url=url, timeout=10, trust_env=False) as client:
            yield client
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive(), "HTTP server did not stop"


def source_environment() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONSAFEPATH": "1"}


def published_split_fixture(root: Path, language: str, split: str) -> Path:
    """Author an isolated test input, then publish its new identity through rebind."""
    from career_lab.scenarios.v2.loader import load_package
    from career_lab.scenarios.v2.rebind import rebind
    from career_lab.scenarios.v2.release import PROTOCOL, read_release

    catalog = json.loads((ROOT / "tests/regression/published-catalog-legacy.json").read_text())
    entry = next(row for row in catalog["scenarios"] if row["work_language"] == language)
    original = ROOT / entry["root"]
    package = load_package(original)
    assert package.content_hash == entry["scenario_hash"]
    assert read_release(package) is None
    draft = root / "authored-test-input"
    draft.mkdir()
    for ref in package.bundle.files:
        target = draft / ref.path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original / ref.path, target)
    manifest = package.bundle.model_dump(mode="json")
    manifest["split"] = split
    locale_path = draft / "locale.json"
    locale = json.loads(locale_path.read_text())
    locale["split"] = split
    locale_path.write_text(json.dumps(locale))
    for member in manifest["files"]:
        if member["path"] == "locale.json":
            member["sha256"] = hashlib.sha256(locale_path.read_bytes()).hexdigest()
    (draft / "manifest.json").write_text(json.dumps(manifest))
    output = root / "published-test-candidate"
    rebind(
        draft,
        output,
        protocol=PROTOCOL,
        contract_revision=(ROOT / "docs/contracts/expansion-v3/revision.txt").read_text().strip(),
        scenario_revision="isolated-test-candidate",
        runtime_revision="isolated-test-candidate",
    )
    candidate = load_package(output)
    release = read_release(candidate)
    assert release is not None and release.content_metadata["split"] == split
    assert release.review.status == "not_recorded"
    assert load_package(original).content_hash == entry["scenario_hash"]
    return output


@pytest.fixture(params=["zh", "en"])
def session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> Iterator[Session]:
    monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(tmp_path / "archive"))
    monkeypatch.delenv("CAREER_LAB_SCENARIO_CATALOG", raising=False)
    database = tmp_path / "source.db"
    language = request.param["language"] if isinstance(request.param, dict) else request.param
    scenario = default_installed_scenario()
    if language == "en":
        scenario = scenario / "locales" / "en"
    if isinstance(request.param, dict):
        scenario = published_split_fixture(tmp_path, language, request.param["split"])
    app = create_runtime_app("sqlite:///" + str(database), scenario_root=scenario)
    request.addfinalizer(app.state.store.close)
    with local_http(app) as client:
        response = client.post(
            "/sessions",
            json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
        )
        assert response.status_code == 200, response.text
        created = response.json()
        sid = created["session_id"]
        headers = {"Authorization": "Bearer " + created["token"]}
        credentials = tmp_path / "credentials.json"
        credentials.write_text(
            json.dumps(
                {"api_url": str(client.base_url), "session_id": sid, "token": created["token"]}
            )
        )
        credentials.chmod(0o600)

        def send(
            path: str,
            key: str,
            operation: str,
            payload: dict[str, Any],
            method: str = "POST",
        ) -> dict[str, Any]:
            state = client.get("/sessions/" + sid, headers=headers).json()["state"]
            result = client.request(
                method,
                "/sessions/" + sid + "/" + path,
                headers=headers,
                json={
                    "schema_version": 2,
                    "request_id": key,
                    "operation": operation,
                    "payload": payload,
                    "expected_version": state["business_seq"],
                    "expected_workspace_revision": state["workspace_revision"],
                },
            )
            assert result.status_code == 200, result.text
            return result.json()

        trial = send(
            "tests",
            "baseline",
            "tests.create",
            {
                "query": "What is the weather on Mars?" if language == "en" else "火星天气如何？",
                "config_version": 0,
            },
        )["result"]["test"]

        def cli(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "career_lab.engineer",
                    args[0],
                    "--database",
                    str(database),
                    "--credentials",
                    str(credentials),
                    "--scenario",
                    str(scenario),
                    *args[1:],
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
                env=source_environment(),
            )

        yield app, client, sid, headers, send, trial, cli, tmp_path, credentials


def test_pack_exports_actual_authorized_baseline_without_changing_session(session: Session) -> None:
    app, client, sid, headers, send, trial, cli, root, credentials = session
    before = client.get("/sessions/" + sid + "/timeline", headers=headers).json()
    result = cli("pack", "--test", trial["id"], "--output", str(root / "pack"))
    assert result.returncode == 0, result.stderr
    index = json.loads((root / "pack" / "index.json").read_text())
    pack = json.loads((root / "pack" / "pack.json").read_text())
    assert pack["config"]["config_version"] == 0
    assert pack["failures"][0]["object_id"] == trial["id"]
    saved = json.loads((root / "pack" / index["tests"][0]["path"]).read_text())
    assert saved == trial
    public = json.loads((root / "pack" / "public-probes.json").read_text())
    assert {p["id"] for p in public} == {"F01", "F04", "F05", "F12"}
    assert all(set(p) == {"id", "query"} for p in public)
    exported = "\n".join(p.read_text() for p in (root / "pack").iterdir())
    assert json.loads(credentials.read_text())["token"] not in exported
    assert "fact_ids" not in exported and "role_context" not in exported
    assert client.get("/sessions/" + sid + "/timeline", headers=headers).json() == before


def test_reproduce_keeps_the_original_stale_index_after_parent_refresh(session: Session) -> None:
    from career_lab.scenarios.v2.module import ref_for

    app, client, sid, headers, send, trial, cli, root, _ = session
    base = app.state.scenario_v2.package.baseline(sid)
    send(
        "configuration",
        "apply",
        "configuration.apply",
        {
            "base": ref_for("config", base).model_dump(mode="json"),
            "settings": {"work_items": ["scope_filter", "human_fallback"], "fallback": "human"},
        },
    )
    query = (
        "What is the hotel reimbursement limit per night?"
        if app.state.scenario_v2.work_language == "en"
        else "住宿报销上限是多少？"
    )
    stale = send("tests", "stale", "tests.create", {"query": query, "config_version": 1})["result"][
        "test"
    ]
    assert stale["citations"][0]["version"] == 1 and "500" in stale["answer"]
    assert stale["execution"]["source_versions"]["policy"] == 2
    assert cli("pack", "--test", stale["id"], "--output", str(root / "pack")).returncode == 0
    send("actions", "refresh", "refresh_index", {"tool": "refresh_index"})
    fresh = send("tests", "fresh", "tests.create", {"query": stale["query"], "config_version": 1})[
        "result"
    ]["test"]
    assert "400" in fresh["answer"] and fresh["citations"][0]["version"] == 2
    before = client.get("/sessions/" + sid + "/timeline", headers=headers).json()
    result = cli("reproduce", "--pack", str(root / "pack"), "--output", str(root / "reproduction"))
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((root / "reproduction" / "report.json").read_text())
    assert report["results"][0]["matches_record"] is True
    assert "500" in report["results"][0]["reproduced"]["answer"]
    assert client.get("/sessions/" + sid + "/timeline", headers=headers).json() == before


def test_repeated_export_and_reproduction_are_immutable(session: Session) -> None:
    _, _, _, _, _, trial, cli, root, _ = session
    args = ("pack", "--test", trial["id"], "--output", str(root / "pack"))
    first = cli(*args)
    assert first.returncode == 0, first.stdout
    original = {p.name: p.read_bytes() for p in (root / "pack").iterdir()}
    assert cli(*args).stdout == first.stdout
    assert {p.name: p.read_bytes() for p in (root / "pack").iterdir()} == original
    args = ("reproduce", "--pack", str(root / "pack"), "--output", str(root / "reproduction"))
    first = cli(*args)
    assert first.returncode == 0, first.stdout
    report = (root / "reproduction" / "report.json").read_bytes()
    assert cli(*args).stdout == first.stdout
    assert (root / "reproduction" / "report.json").read_bytes() == report


def test_rehashed_forged_pack_is_rejected_against_original_sources(session: Session) -> None:
    import hashlib

    _, _, _, _, _, trial, cli, root, _ = session
    assert cli("pack", "--test", trial["id"], "--output", str(root / "pack")).returncode == 0
    index_file = root / "pack" / "index.json"
    index = json.loads(index_file.read_text())
    test_file = root / "pack" / index["tests"][0]["path"]
    forged = json.loads(test_file.read_text())
    forged["answer"] = "Forged successful answer"
    test_file.write_text(json.dumps(forged))
    index["tests"][0]["sha256"] = hashlib.sha256(test_file.read_bytes()).hexdigest()
    index_file.write_text(json.dumps(index))
    result = cli("reproduce", "--pack", str(root / "pack"), "--output", str(root / "reproduction"))
    assert result.returncode == 1 and json.loads(result.stdout)["code"] == "engineer_pack_changed"
    assert not (root / "reproduction").exists()


def test_export_includes_a_usable_language_specific_handoff_guide(session: Session) -> None:
    app, _, _, _, _, trial, cli, root, _ = session
    assert cli("pack", "--test", trial["id"], "--output", str(root / "pack")).returncode == 0
    guide = (root / "pack" / "README.md").read_text()
    assert "career-lab-engineer reproduce" in guide
    assert ("原始运行库" in guide) == (app.state.scenario_v2.work_language == "zh")


def test_missing_test_and_invalid_credentials_never_publish_a_pack(session: Session) -> None:
    _, _, _, _, _, trial, cli, root, credentials = session
    result = cli("pack", "--test", "missing-test", "--output", str(root / "missing"))
    assert result.returncode == 1 and "engineer_test_unavailable" in result.stdout
    value = json.loads(credentials.read_text())
    value["token"] = "deliberately-invalid-private-token"
    credentials.write_text(json.dumps(value))
    result = cli("pack", "--test", trial["id"], "--output", str(root / "denied"))
    assert result.returncode == 1 and "token_invalid" in result.stdout
    assert value["token"] not in result.stdout + result.stderr
    assert not (root / "missing").exists() and not (root / "denied").exists()


def test_revoked_delegation_cannot_reproduce_a_previously_exported_pack(session: Session) -> None:
    from datetime import datetime, timedelta

    _, client, sid, headers, send, trial, cli, root, credentials = session
    delegation = send(
        "delegations",
        "grant",
        "delegations.create",
        {
            "agent_label": "engineer",
            "capabilities": ["read", "act"],
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
    )["result"]["result"]
    value = json.loads(credentials.read_text())
    value["token"] = delegation["token"]
    credentials.write_text(json.dumps(value))
    assert cli("pack", "--test", trial["id"], "--output", str(root / "pack")).returncode == 0
    did = delegation["delegation"]["id"]
    send(
        "delegations/" + did,
        "revoke",
        "delegations.revoke",
        {"delegation_id": did},
        method="DELETE",
    )
    result = cli("reproduce", "--pack", str(root / "pack"), "--output", str(root / "reproduction"))
    assert result.returncode == 1
    assert not (root / "reproduction").exists()


@pytest.mark.parametrize("scope", ["read_only", "missing_config", "wrong_action"])
def test_delegate_scope_is_preserved_by_engineering_commands(session: Session, scope: str) -> None:
    from datetime import datetime, timedelta

    _, _, _, _, send, trial, cli, root, credentials = session
    payload = {
        "agent_label": "limited-engineer",
        "capabilities": ["read"],
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    if scope == "missing_config":
        payload["allowed_objects"] = [trial["id"]]
    if scope == "wrong_action":
        payload["allowed_actions"] = ["timeline"]
    delegation = send("delegations", "grant", "delegations.create", payload)["result"]["result"]
    value = json.loads(credentials.read_text())
    value["token"] = delegation["token"]
    credentials.write_text(json.dumps(value))
    packed = cli("pack", "--test", trial["id"], "--output", str(root / "pack"))
    if scope == "read_only":
        assert packed.returncode == 0, packed.stdout
        result = cli(
            "reproduce", "--pack", str(root / "pack"), "--output", str(root / "reproduction")
        )
        assert result.returncode == 1 and "capability_forbidden" in result.stdout
        assert not (root / "reproduction").exists()
    else:
        assert packed.returncode == 1
        assert not (root / "pack").exists()


@pytest.mark.parametrize("damage", ["changed_config", "missing_member", "path_escape"])
def test_invalid_package_fails_without_a_success_report(session: Session, damage: str) -> None:
    _, _, _, _, _, trial, cli, root, _ = session
    assert cli("pack", "--test", trial["id"], "--output", str(root / "pack")).returncode == 0
    if damage == "changed_config":
        (root / "pack" / "config.json").write_text("{}")
    elif damage == "missing_member":
        (root / "pack" / "public-probes.json").unlink()
    else:
        path = root / "pack" / "index.json"
        index = json.loads(path.read_text())
        index["tests"][0]["path"] = "../credentials.json"
        path.write_text(json.dumps(index))
    result = cli("reproduce", "--pack", str(root / "pack"), "--output", str(root / "reproduction"))
    assert result.returncode == 1 and not result.stderr
    assert not (root / "reproduction").exists()


def test_reproduction_records_its_actual_executor_separately_from_the_original_test(
    session: Session,
) -> None:
    from datetime import datetime, timedelta

    _, _, _, _, send, trial, cli, root, credentials = session
    assert cli("pack", "--test", trial["id"], "--output", str(root / "pack")).returncode == 0
    assert (
        cli("reproduce", "--pack", str(root / "pack"), "--output", str(root / "human")).returncode
        == 0
    )
    human = json.loads((root / "human" / "report.json").read_text())
    grant = send(
        "delegations",
        "grant",
        "delegations.create",
        {
            "agent_label": "engineer",
            "capabilities": ["read", "act"],
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
    )["result"]["result"]
    value = json.loads(credentials.read_text())
    value["token"] = grant["token"]
    credentials.write_text(json.dumps(value))
    assert (
        cli("reproduce", "--pack", str(root / "pack"), "--output", str(root / "agent")).returncode
        == 0
    )
    agent = json.loads((root / "agent" / "report.json").read_text())
    assert human["executor"]["kind"] == "human"
    assert agent["executor"]["kind"] == "external_agent"
    assert agent["executor"]["delegation_id"] == grant["delegation"]["id"]
    assert human["results"] == agent["results"]
    # The existing human report cannot be relabelled by another executor.
    denied = cli("reproduce", "--pack", str(root / "pack"), "--output", str(root / "human"))
    assert denied.returncode == 1
    assert json.loads((root / "human" / "report.json").read_text()) == human


def test_cli_imports_tested_source() -> None:
    probe = subprocess.run(
        [sys.executable, "-c", "import career_lab.engineer; print(career_lab.engineer.__file__)"],
        cwd=ROOT,
        env=source_environment(),
        capture_output=True,
        text=True,
        check=True,
    )
    assert Path(probe.stdout.strip()).resolve().is_relative_to(ROOT / "src")
    module = subprocess.run(
        [sys.executable, "-m", "career_lab.engineer", "--help"],
        cwd=ROOT,
        env=source_environment(),
        capture_output=True,
        text=True,
    )
    installed = subprocess.run(
        [str(Path(sys.executable).parent / "career-lab-engineer"), "--help"],
        cwd=ROOT,
        env=source_environment(),
        capture_output=True,
        text=True,
    )
    assert module.returncode == installed.returncode == 0, module.stderr
    assert module.stdout == installed.stdout


def export_released_pack(session: Session) -> Path:
    _, _, _, _, _, trial, cli, root, credentials = session
    # Run the unmodified released exporter over a real API-created session.
    # A copied release package avoids importing the installed checkout by accident.
    release = root / "release"
    for relative, content in released_sources().items():
        target = release / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    # Other imports resolve to the tested source; only the released exporter is pinned.
    package = release / "src/career_lab/__init__.py"
    package.write_text(
        package.read_text() + "\n__path__.append(" + repr(str(ROOT / "src/career_lab")) + ")\n"
    )
    argv = [
        "pack",
        "--test",
        trial["id"],
        "--output",
        str(root / "pack"),
        "--database",
        str(root / "source.db"),
        "--credentials",
        str(credentials),
        "--scenario",
        str(session[0].state.scenario_v2.package.root),
    ]
    program = "from career_lab.engineer.cli import main; raise SystemExit(main())"
    exported = subprocess.run(
        [sys.executable, "-c", program, *argv],
        cwd=root,
        env={**source_environment(), "PYTHONPATH": str(release / "src")},
        capture_output=True,
        text=True,
    )
    assert exported.returncode == 0, exported.stdout + exported.stderr
    return root / "pack"


def test_old_pack_survives_documentation_upgrade(session: Session) -> None:
    _, _, _, _, _, _, cli, root, _ = session
    export_released_pack(session)
    original = {p.name: p.read_bytes() for p in (root / "pack").iterdir()}
    result = cli("reproduce", "--pack", str(root / "pack"), "--output", str(root / "result"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert {p.name: p.read_bytes() for p in (root / "pack").iterdir()} == original
    assert json.loads((root / "result/report.json").read_text())["status"] == "reproduced"


def test_guide_and_help_describe_credentials(session: Session) -> None:
    _, _, _, _, _, trial, cli, root, _ = session
    assert cli("pack", "--test", trial["id"], "--output", str(root / "pack")).returncode == 0
    guide = (root / "pack/README.md").read_text()
    help_text = cli("pack", "--help").stdout
    for text in (guide, help_text):
        assert "W06" not in text
        assert all(field in text for field in ("api_url", "session_id", "token", "0600"))


def test_reproduction_reports_execution_metadata(session: Session) -> None:
    _, _, _, _, _, trial, cli, root, _ = session
    assert cli("pack", "--test", trial["id"], "--output", str(root / "pack")).returncode == 0
    result = cli("reproduce", "--pack", str(root / "pack"), "--output", str(root / "result"))
    assert result.returncode == 0, result.stdout
    report = json.loads((root / "result/report.json").read_text())
    assert report["results"][0]["execution"]["cost_complete"] is True
    assert report["results"][0]["execution"]["attempts"] == []
    assert report["model_calls"] == 0
    assert report["mode"] == "isolated_reexecution_without_model_calls"


def test_pack_versions_documentation_separately(session: Session) -> None:
    _, _, _, _, _, trial, cli, root, _ = session
    assert cli("pack", "--test", trial["id"], "--output", str(root / "pack")).returncode == 0
    index = json.loads((root / "pack/index.json").read_text())
    assert index["schema_version"] == 2
    assert index["tool_versions"]["career-lab-engineer"]
    assert index["template_version"]
    # Documentation has its own checksum and can evolve without changing data identity.
    import hashlib

    original_id = json.loads((root / "pack/pack.json").read_text())["id"]
    guide = root / "pack/README.md"
    guide.write_text(guide.read_text() + "\nUpdated environment operator instructions.\n")
    index["guide"]["sha256"] = hashlib.sha256(guide.read_bytes()).hexdigest()
    pack_path = root / "pack/pack.json"
    pack = json.loads(pack_path.read_text())
    pack["requirements"] = ["Configuration-only handoff; keep the source record."]
    pack_path.write_text(
        json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    )
    index["pack"]["sha256"] = hashlib.sha256(pack_path.read_bytes()).hexdigest()
    index["template_version"] = "next-template"
    (root / "pack/index.json").write_text(
        json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    )
    result = cli("reproduce", "--pack", str(root / "pack"), "--output", str(root / "result"))
    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["pack_id"] == original_id


def test_missing_source_database_fails(session: Session) -> None:
    _, _, _, _, _, trial, cli, root, _ = session
    absent = root / "missing.db"
    result = cli(
        "pack", "--test", trial["id"], "--output", str(root / "pack"), "--database", str(absent)
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["code"] == "engineer_database_unavailable"
    assert not absent.exists() and not (root / "pack").exists()


def test_too_many_tests_fail(session: Session) -> None:
    _, _, _, _, _, _, cli, root, _ = session
    selection = [value for number in range(101) for value in ("--test", "test-" + str(number))]
    result = cli("pack", *selection, "--output", str(root / "pack"))
    assert result.returncode == 1
    assert json.loads(result.stdout)["code"] == "engineer_test_selection_required"
    assert not (root / "pack").exists()


def test_wrong_scenario_fails(session: Session) -> None:
    app, _, _, _, _, trial, cli, root, _ = session
    assert cli("pack", "--test", trial["id"], "--output", str(root / "pack")).returncode == 0
    other = default_installed_scenario()
    if app.state.scenario_v2.work_language == "zh":
        other = other / "locales/en"
    result = cli(
        "reproduce",
        "--pack",
        str(root / "pack"),
        "--output",
        str(root / "result"),
        "--scenario",
        str(other),
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["code"] == "scenario_binding_mismatch"
    assert not (root / "result").exists()


def test_pack_materials_follow_scenario_metadata(session: Session) -> None:
    _, client, sid, headers, _, trial, cli, root, _ = session
    visible = client.get("/sessions/" + sid + "/materials", headers=headers)
    assert visible.status_code == 200, visible.text
    # The investigation domain also contains briefs, interviews and access lists.
    # Only the loader's authored failure-case pair belongs in this handoff.
    visible_ids = {row["id"] for row in visible.json()["result"]["result"]["materials"]}
    assert {"failures", "trial_details", "brief"} <= visible_ids
    expected = {"failures", "trial_details"}
    assert cli("pack", "--test", trial["id"], "--output", str(root / "pack")).returncode == 0
    materials = json.loads((root / "pack/materials.json").read_text())
    assert {row["id"] for row in materials} == expected


def test_behavior_change_is_not_success(session: Session) -> None:
    from datetime import datetime, timedelta

    app, client, sid, headers, send, _, cli, root, _ = session
    grant = send(
        "delegations",
        "limited-source",
        "delegations.create",
        {
            "agent_label": "limited-source",
            "capabilities": ["read", "act"],
            "allowed_objects": [app.state.scenario_v2.package.baseline(sid).id],
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
    )["result"]["result"]
    state = client.get("/sessions/" + sid, headers=headers).json()["state"]
    response = client.post(
        "/sessions/" + sid + "/tests",
        headers={"Authorization": "Bearer " + grant["token"]},
        json={
            "schema_version": 2,
            "request_id": "limited-test",
            "operation": "tests.create",
            "expected_version": state["business_seq"],
            "expected_workspace_revision": state["workspace_revision"],
            "payload": {
                "query": "reimbursement" if app.state.scenario_v2.work_language == "en" else "报销",
                "config_version": 0,
            },
        },
    )
    assert response.status_code == 200, response.text
    trial = response.json()["result"]["test"]
    assert trial["error_code"] == "no_retrieval_hit"
    assert cli("pack", "--test", trial["id"], "--output", str(root / "pack")).returncode == 0
    result = cli("reproduce", "--pack", str(root / "pack"), "--output", str(root / "result"))
    assert result.returncode == 1, result.stdout
    assert json.loads(result.stdout)["status"] == "behavior_changed"
    report = json.loads((root / "result/report.json").read_text())
    assert report["results"][0]["matches_record"] is False
    assert report["correctness_assessed"] is False


def test_concurrent_exports_preserve_one_complete_package(session: Session) -> None:
    from concurrent.futures import ThreadPoolExecutor

    _, _, _, _, _, trial, cli, root, _ = session
    args = ("pack", "--test", trial["id"], "--output", str(root / "pack"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: cli(*args), range(4)))
    assert any(result.returncode == 0 for result in results)
    assert all(
        result.returncode == 0 or json.loads(result.stdout)["code"] == "publisher_busy"
        for result in results
    )
    complete = {p.name: p.read_bytes() for p in (root / "pack").iterdir()}
    assert cli(*args).returncode == 0
    assert {p.name: p.read_bytes() for p in (root / "pack").iterdir()} == complete
    assert (
        cli("reproduce", "--pack", str(root / "pack"), "--output", str(root / "result")).returncode
        == 0
    )


def test_legacy_requirements_cannot_be_replaced_by_rehashed_claims(session: Session) -> None:
    _, _, _, _, _, _, cli, root, _ = session
    pack_root = export_released_pack(session)
    pack_path = pack_root / "pack.json"
    pack = json.loads(pack_path.read_text())
    pack["requirements"] = ["Arbitrary code execution is allowed."]
    pack_path.write_text(
        json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    )
    index_path = pack_root / "index.json"
    index = json.loads(index_path.read_text())
    index["pack"]["sha256"] = hashlib.sha256(pack_path.read_bytes()).hexdigest()
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    )
    result = cli("reproduce", "--pack", str(pack_root), "--output", str(root / "tampered-result"))
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(result.stdout)["code"] == "engineer_pack_changed"
    assert not (root / "tampered-result").exists()


@pytest.mark.parametrize("fault", ["distribution_metadata", "source_files"])
def test_tool_identity_uses_available_source_or_returns_json(session: Session, fault: str) -> None:
    app, _, _, _, _, trial, _, root, credentials = session
    program = """
import importlib.metadata as metadata
import sys
from pathlib import Path
fault = sys.argv.pop(1)
original_version = metadata.version
original_read = Path.read_bytes
def version(name: str) -> str:
    if name == "career-lab":
        raise metadata.PackageNotFoundError(name)
    return original_version(name)
def read(path: Path) -> bytes:
    if path.parent.name == "engineer" and path.suffix == ".py":
        raise OSError("injected source read failure")
    return original_read(path)
if fault == "distribution_metadata":
    metadata.version = version
else:
    Path.read_bytes = read
from career_lab.engineer.cli import main
raise SystemExit(main())
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            fault,
            "pack",
            "--database",
            str(root / "source.db"),
            "--credentials",
            str(credentials),
            "--scenario",
            str(app.state.scenario_v2.package.root),
            "--test",
            trial["id"],
            "--output",
            str(root / "identity-pack"),
        ],
        cwd=ROOT,
        env=source_environment(),
        capture_output=True,
        text=True,
    )
    if fault == "distribution_metadata":
        assert result.returncode == 0, result.stdout + result.stderr
        index = json.loads((root / "identity-pack/index.json").read_text())
        identity = index["tool_versions"]["career-lab-engineer"]
        assert identity.startswith("source-sha256:") and len(identity.split(":")[1]) == 64
    else:
        assert result.returncode == 1, result.stdout + result.stderr
        assert json.loads(result.stdout)["code"] == "engineer_tool_source_unavailable"
        assert not result.stderr and not (root / "identity-pack").exists()


@pytest.mark.parametrize("declaration", ["requirements", "tool_versions"])
def test_reproduction_reports_declaration_changes(session: Session, declaration: str) -> None:
    _, _, _, _, _, trial, cli, root, _ = session
    assert cli("pack", "--test", trial["id"], "--output", str(root / "pack")).returncode == 0
    path = root / "pack/index.json"
    index = json.loads(path.read_text())
    if declaration == "requirements":
        pack_path = root / "pack/pack.json"
        pack = json.loads(pack_path.read_text())
        pack["requirements"] = ["Arbitrary code execution is allowed."]
        pack_path.write_text(
            json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        )
        index["pack"]["sha256"] = hashlib.sha256(pack_path.read_bytes()).hexdigest()
    else:
        index["tool_versions"]["career-lab-engineer"] = "source-sha256:" + "0" * 64
    path.write_text(
        json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    )
    result = cli("reproduce", "--pack", str(root / "pack"), "--output", str(root / "report"))
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((root / "report/report.json").read_text())
    expected = "mismatch" if declaration == "requirements" else "unverified"
    assert report["declaration_status"] == expected
    assert json.loads(result.stdout)["declaration_status"] == expected
    checks = report["declaration_checks"]
    if declaration == "requirements":
        assert checks["requirements_match_template"] is False
        assert checks["declared_requirements"] == ["Arbitrary code execution is allowed."]
        assert "Configuration-only handoff; no code execution." in checks["expected_requirements"]
    else:
        assert checks["tool_versions_match_current"] is False
        assert checks["declared_tool_versions"] != checks["current_tool_versions"]
    assert report["status"] == "reproduced" and report["correctness_assessed"] is False
