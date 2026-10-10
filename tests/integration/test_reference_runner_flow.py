"""Reference-runner public entry and recovery against the installed protocol."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import JsonValue
from runner_fixture import live_run
from test_bundle_registry_flow import write_json

from career_lab.contracts.v2.core import ProtocolError
from career_lab.contracts.v2.research import RunManifest
from career_lab.delegations import http_transport
from career_lab.delegations.credentials import Credentials
from career_lab.reference_agent.runner import run_checklist
from career_lab.registry.v3.store import BundleRegistry


def test_RUN_01_cli_rejects_implicit_draft_protocol(tmp_path: Path) -> None:
    path = tmp_path / "old-run.json"
    path.write_text(json.dumps({"id": "old-run", "status": "draft"}))
    result = subprocess.run(
        [sys.executable, "-m", "career_lab.reference_agent", "validate", "--manifest", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.stdout.strip(), result.stderr
    assert result.returncode == 2
    assert json.loads(result.stdout) == {"error": "run_protocol_unsupported", "executed": False}


def test_RUN_03_reference_worker_failure_is_preserved_without_redispatch(tmp_path: Path) -> None:
    from runner_fixture import live_run

    from career_lab.jobs.worker import Worker
    from career_lab.reference_agent.runner import run_checklist

    with live_run(tmp_path) as run:
        first = run_checklist(**run.arguments)
        assert first["status"] == "pending"
        assert len(first["results"]) == 1
        worker = Worker(run.app.state.jobs, run.app.state.handlers)
        assert worker.run_once()
        resumed = run_checklist(**run.arguments, resume=True)
        assert resumed["status"] == "failed"
        assert resumed["results"][0]["jobs"][0]["error_code"] == "public_actor_required"
        assert len(resumed["results"]) == 1
        assert resumed["dispatch_count"] == 1
        assert not worker.run_once()
        assert run_checklist(**run.arguments, resume=True) == resumed
        saved = (run.arguments["output"] / "checkpoint.json").read_text()
        assert run.token not in saved


def test_RUN_02_fixed_http_test_completes_and_recovers_original_result(tmp_path: Path) -> None:
    from runner_fixture import live_run

    from career_lab.reference_agent.runner import run_checklist

    with live_run(tmp_path, "tests.create") as run:
        first = run_checklist(**run.arguments)
        assert first["status"] == "completed"
        assert first["results"][0]["response"]["result"]["test"]["citations"]
        assert first["dispatch_count"] == 1
        assert run_checklist(**run.arguments, resume=True) == first


def test_RUN_02_lost_http_response_recovers_only_the_original_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from runner_fixture import live_run

    from career_lab.reference_agent.runner import run_checklist

    original = http_transport.request_json
    sent = []
    reads = []

    def lost_response(
        credentials: Credentials, method: str, suffix: str, *args: object, **kwargs: object
    ) -> dict[str, JsonValue]:
        response = original(credentials, method, suffix, *args, **kwargs)
        if method == "POST" and suffix.endswith("/tests"):
            sent.append(response["boundary"]["request_id"])
            raise http_transport.RemoteFailure("response_unconfirmed")
        if method == "GET" and "/requests/" in suffix:
            reads.append(suffix)
        return response

    with live_run(tmp_path, "tests.create") as run:
        monkeypatch.setattr(http_transport, "request_json", lost_response)
        interrupted = run_checklist(**run.arguments)
        assert interrupted["status"] == "unresolved"
        assert interrupted["error_code"] == "request_result_unresolved"
        recovered = run_checklist(**run.arguments, resume=True)
        assert recovered["status"] == "completed"
        assert recovered["dispatch_count"] == 1
        assert sent == [recovered["results"][0]["request_id"]]
        assert len(reads) == 1
        assert len(recovered["results"]) == 1


@pytest.mark.parametrize("language", ["zh", "en"])
def test_RUN_01_formal_cli_executes_fixed_current_manifest(tmp_path: Path, language: str) -> None:
    from runner_fixture import live_run

    with live_run(tmp_path, "tests.create", language=language) as run:
        names = {
            "manifest_path": "manifest",
            "registry_path": "registry",
            "credentials_path": "credentials",
        }
        args = [sys.executable, "-m", "career_lab.reference_agent", "run"]
        for key, value in run.arguments.items():
            args.extend(["--" + names.get(key, key.replace("_", "-")), str(value)])
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        assert result.stdout.strip(), result.stderr
        assert result.returncode == 0, result.stdout
        saved = json.loads(result.stdout)
        assert saved["status"] == "completed"
        assert saved["dispatch_count"] == 1
        assert saved["business_terminal_verified"] is False
        assert saved["manifest"]["status"] == "completed"
        assert saved["manifest"]["actual_consumption"]["actions"] == 1
        assert saved["manifest"]["actual_consumption"]["usage_complete"] is False
        assert run.token not in result.stdout + result.stderr


def test_RUN_budget_expires_during_state_read_without_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    from runner_fixture import live_run

    from career_lab.reference_agent.runner import run_checklist

    original = http_transport.request_json
    posts = []

    def delayed_state(
        credentials: Credentials, method: str, suffix: str, *args: object, **kwargs: object
    ) -> dict[str, JsonValue]:
        response = original(credentials, method, suffix, *args, **kwargs)
        if method == "GET" and "/requests/" not in suffix:
            time.sleep(0.05)
        if method == "POST":
            posts.append(suffix)
        return response

    with live_run(tmp_path, "tests.create") as run:
        manifest_path = run.arguments["manifest_path"]
        manifest = json.loads(manifest_path.read_text())
        manifest["budget"]["wall_seconds"] = 0.02
        manifest_path.write_text(json.dumps(manifest))
        monkeypatch.setattr(http_transport, "request_json", delayed_state)
        result = run_checklist(**run.arguments)
        assert result["status"] == "failed"
        assert result["error_code"] == "run_budget_exhausted"
        assert result["dispatch_count"] == 0
        assert posts == []


def test_RUN_04_manifest_cannot_forge_executor_before_http_effects(tmp_path: Path) -> None:
    from runner_fixture import live_run

    from career_lab.contracts.v2.core import ProtocolError
    from career_lab.reference_agent.runner import run_checklist

    with live_run(tmp_path, "tests.create") as run:
        path = run.arguments["manifest_path"]
        value = json.loads(path.read_text())
        value["executor"]["id"] = "forged-reference-identity"
        path.write_text(json.dumps(value))
        with pytest.raises(ProtocolError) as failure:
            run_checklist(**run.arguments)
        assert failure.value.code == "reference_executor_required"
        assert not run.arguments["output"].exists()


def test_RUN_03_worker_parked_context_is_preserved(tmp_path: Path) -> None:
    from runner_fixture import live_run

    from career_lab.reference_agent.runner import run_checklist

    with live_run(tmp_path) as run:
        first = run_checklist(**run.arguments)
        assert first["status"] == "pending"
        # Public queue boundary: a worker parks its real claimed job for context.
        job = run.app.state.jobs.claim_job("context-worker")
        assert job is not None
        run.app.state.jobs.needs_context(job, "context_stale")
        result = run_checklist(**run.arguments, resume=True)
        assert result["status"] == "needs_context"
        assert result["manifest"]["status"] == "blocked"
        assert result["dispatch_count"] == 1
        assert result["results"][0]["jobs"][0]["error_code"] == "context_stale"


def test_RUN_03_worker_ack_without_effect_stays_unresolved(tmp_path: Path) -> None:
    from runner_fixture import live_run

    from career_lab.reference_agent.runner import run_checklist

    with live_run(tmp_path) as run:
        assert run_checklist(**run.arguments)["status"] == "pending"
        # Inject the worker crash boundary after acknowledgement, before effect commit.
        job = run.app.state.jobs.claim_job("incomplete-worker")
        assert job is not None
        run.app.state.jobs.complete(job["id"], job["lease_token"], {})
        result = run_checklist(**run.arguments, resume=True)
        assert result["status"] == "unresolved"
        assert result["manifest"]["status"] == "blocked"
        assert result["dispatch_count"] == 1
        assert result["pending"] is not None


def test_RUN_02_invalid_recovery_response_keeps_committed_action_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from runner_fixture import live_run

    from career_lab.reference_agent.runner import run_checklist

    original = http_transport.request_json

    def malformed(
        credentials: Credentials, method: str, suffix: str, *args: object, **kwargs: object
    ) -> dict[str, JsonValue]:
        response = original(credentials, method, suffix, *args, **kwargs)
        if "/requests/" in suffix:
            return {"schema_version": 2}
        return response

    with live_run(tmp_path, "tests.create") as run:
        monkeypatch.setattr(http_transport, "request_json", malformed)
        result = run_checklist(**run.arguments)
        assert result["status"] == "unresolved"
        assert result["error_code"] == "request_result_invalid"
        assert result["dispatch_count"] == 1
        assert result["pending"] is not None


def test_RUN_02_crash_after_first_saved_effect_resumes_remaining_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from runner_fixture import live_run

    from career_lab.reference_agent.runner import run_checklist

    original = os.replace
    crashed = False

    def disk_interrupt(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        nonlocal crashed
        original(source, target)
        if Path(target).name == "checkpoint.json":
            value = json.loads(Path(target).read_text())["state"]
            if not crashed and len(value["results"]) == 1 and value["pending"] is None:
                crashed = True
                raise OSError("crash after durable first effect")

    with live_run(tmp_path, "tests.create", action_count=2) as run:
        monkeypatch.setattr(os, "replace", disk_interrupt)
        with pytest.raises(OSError, match="crash after durable"):
            run_checklist(**run.arguments)
        resumed = run_checklist(**run.arguments, resume=True)
        assert resumed["status"] == "completed"
        assert resumed["dispatch_count"] == 2
        assert len(resumed["results"]) == 2


@pytest.mark.parametrize("language", ["zh", "en"])
def test_RUN_reference_observation_uses_actual_public_acquisition(
    tmp_path: Path, language: str
) -> None:
    import httpx
    from runner_fixture import live_run

    from career_lab.contracts.v2.world import Observation

    with live_run(tmp_path, "tests.create", language=language) as run:
        credentials = json.loads(run.arguments["credentials_path"].read_text())
        prefix = credentials["api_url"] + "/sessions/" + credentials["session_id"]
        with httpx.Client(
            headers={"Authorization": "Bearer " + run.token}, trust_env=False
        ) as client:
            response = client.get(prefix + "/observation")
            assert response.status_code == 200, response.text
            observation = Observation.model_validate(response.json()["result"])
            assert observation.actor.kind == "reference_agent"
            assert observation.visible_sources == ()
            assert observation.catalog
            assert not any(
                t.available and t.name == "work_products.adopt" for t in observation.tools
            )
            assert any(t.available and t.name == "read_material" for t in observation.tools)
            state = observation.as_of.model_dump(mode="json")
            result = client.post(
                prefix + "/actions",
                json={
                    "schema_version": 2,
                    "operation": "read_material",
                    "request_id": "acquire-brief",
                    "expected_version": state["business_seq"],
                    "expected_workspace_revision": state["workspace_revision"],
                    "payload": {
                        "tool": "read_material",
                        "material": {
                            "session_id": credentials["session_id"],
                            "kind": "material",
                            "object_id": observation.catalog[0].id,
                            "version": observation.catalog[0].version,
                        },
                    },
                },
            )
            assert result.status_code == 200, result.text
            acquired = client.get(prefix + "/observation")
            assert acquired.status_code == 200, acquired.text
            observed = Observation.model_validate(acquired.json()["result"])
            assert observed.visible_sources
            assert all(not f.fact_ids for f in observed.visible_sources)
            assert all(f.acquired_via == "material_read" for f in observed.visible_sources)
            assert all(f.ref.kind == "material" for f in observed.visible_sources)


def test_S1_checklist_requires_the_registered_evaluation_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from runner_fixture import live_run
    from test_bundle_registry_flow import write_json

    from career_lab.contracts.v2.core import ProtocolError
    from career_lab.contracts.v2.research import RunManifest
    from career_lab.reference_agent.runner import run_checklist
    from career_lab.registry.v3.store import BundleRegistry

    with live_run(tmp_path, "tests.create") as run:
        registry = BundleRegistry(run.arguments["registry_path"])
        original = registry.load(run.arguments["evaluation_id"])
        manifest = RunManifest.model_validate_json(run.arguments["manifest_path"].read_bytes())
        other = original.model_copy(
            update={
                "id": "different-evaluation",
                "revision": "replacement",
                "graders": (*original.graders, manifest.evaluation),
            }
        )
        source = tmp_path / "source"
        root = write_json(source, "other-evaluation.json", other)
        run.arguments["evaluation_id"] = registry.register("evaluation", source, root)
        calls = []
        request = http_transport.request_json

        def observed_request(
            credentials: Credentials, method: str, suffix: str, *args: object, **kwargs: object
        ) -> dict[str, JsonValue]:
            calls.append(method)
            return request(credentials, method, suffix, *args, **kwargs)

        monkeypatch.setattr(http_transport, "request_json", observed_request)
        with pytest.raises(ProtocolError) as rejected:
            run_checklist(**run.arguments)
        assert rejected.value.code == "registry_manifest_mismatch"
        assert calls == []
        assert not run.arguments["output"].exists()


def test_S2_same_run_name_with_new_fixed_command_has_its_own_result(tmp_path: Path) -> None:
    from runner_fixture import live_run
    from test_bundle_registry_flow import write_json

    from career_lab.contracts.v2.research import RunManifest
    from career_lab.reference_agent.runner import run_checklist
    from career_lab.registry.v3.store import BundleRegistry

    with live_run(tmp_path, "tests.create") as run:
        first = run_checklist(**run.arguments)
        registry = BundleRegistry(run.arguments["registry_path"])
        manifest = RunManifest.model_validate_json(run.arguments["manifest_path"].read_bytes())
        runtime = registry.load(run.arguments["runtime_id"])
        checklist = json.loads(registry.resolve_file(run.arguments["runtime_id"], manifest.policy))
        query = "A different question for the replacement run"
        checklist["actions"][0]["arguments"]["query"] = query
        source = tmp_path / "source"
        policy = write_json(source, "reference/replacement-checklist.json", checklist)
        runtime_ref = write_json(
            source,
            "reference/replacement-runtime.json",
            runtime.model_copy(update={"revision": "replacement", "tools": policy}),
        )
        arguments = dict(run.arguments)
        arguments["runtime_id"] = registry.register("runtime", source, runtime_ref)
        arguments["manifest_path"] = tmp_path / "replacement-run.json"
        arguments["manifest_path"].write_text(
            manifest.model_copy(update={"runtime": runtime_ref, "policy": policy}).model_dump_json()
        )
        arguments["output"] = tmp_path / "replacement-output"
        second = run_checklist(**arguments)
        recovered = run_checklist(**arguments, resume=True)
        assert second["status"] == "completed", second["error_code"]
        assert recovered == second
        assert second["results"][0]["request_id"] != first["results"][0]["request_id"]
        assert second["results"][0]["response"]["result"]["test"]["query"] == query
        assert first["results"][0]["response"]["result"]["test"]["query"] != query


def test_S2_resume_with_changed_manifest_keeps_checkpoint_and_sends_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with live_run(tmp_path, "tests.create") as run:
        first = run_checklist(**run.arguments)
        assert first["status"] == "completed", first["error_code"]
        output = run.arguments["output"]
        before = {path: path.read_bytes() for path in output.rglob("*") if path.is_file()}
        registry = BundleRegistry(run.arguments["registry_path"])
        manifest = RunManifest.model_validate_json(run.arguments["manifest_path"].read_bytes())
        runtime = registry.load(run.arguments["runtime_id"])
        checklist = json.loads(registry.resolve_file(run.arguments["runtime_id"], manifest.policy))
        checklist["actions"][0]["arguments"]["query"] = "A changed question for the same output"
        source = tmp_path / "source"
        policy = write_json(source, "reference/changed-checklist.json", checklist)
        runtime_ref = write_json(
            source,
            "reference/changed-runtime.json",
            runtime.model_copy(update={"revision": "changed", "tools": policy}),
        )
        arguments = dict(run.arguments)
        arguments["runtime_id"] = registry.register("runtime", source, runtime_ref)
        arguments["manifest_path"] = tmp_path / "changed-run.json"
        arguments["manifest_path"].write_text(
            manifest.model_copy(update={"runtime": runtime_ref, "policy": policy}).model_dump_json()
        )
        methods = []
        request = http_transport.request_json

        def observed_request(
            credentials: Credentials, method: str, suffix: str, *args: object, **kwargs: object
        ) -> dict[str, JsonValue]:
            methods.append(method)
            return request(credentials, method, suffix, *args, **kwargs)

        monkeypatch.setattr(http_transport, "request_json", observed_request)
        with pytest.raises(ProtocolError) as rejected:
            run_checklist(**arguments, resume=True)
        assert (rejected.value.status, rejected.value.code) == (409, "resume_identity_mismatch")
        assert [method for method in methods if method != "GET"] == []
        assert {path: path.read_bytes() for path in output.rglob("*") if path.is_file()} == before


def test_S2_confirmed_request_conflict_never_recovers_another_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from runner_fixture import live_run

    from career_lab.reference_agent.runner import run_checklist

    with live_run(tmp_path, "tests.create") as run:
        request = http_transport.request_json
        claimed = False
        recoveries = []

        def conflicting_request(
            credentials: Credentials, method: str, suffix: str, *args: object, **kwargs: object
        ) -> dict[str, JsonValue]:
            nonlocal claimed
            if method == "POST" and suffix.endswith("/tests") and not claimed:
                claimed = True
                other = json.loads(json.dumps(kwargs["body"]))
                other["payload"]["query"] = "Another command owns this request identity"
                competing = request(
                    credentials, method, suffix, *args, **(kwargs | {"body": other})
                )
                assert competing["schema_version"] == 2
            if method == "GET" and "/requests/" in suffix:
                recoveries.append(suffix)
            return request(credentials, method, suffix, *args, **kwargs)

        monkeypatch.setattr(http_transport, "request_json", conflicting_request)
        first = run_checklist(**run.arguments)
        resumed = run_checklist(**run.arguments, resume=True)
        assert first["status"] == "failed"
        assert first["error_code"] == "request_id_reused"
        assert resumed == first
        assert recoveries == []
        assert first["results"] == []


def test_S2_conflict_before_checkpoint_commit_cannot_recover_the_competing_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from runner_fixture import live_run

    from career_lab.reference_agent.journal import RunJournal
    from career_lab.reference_agent.runner import run_checklist

    with live_run(tmp_path, "tests.create") as run:
        request = http_transport.request_json
        save = RunJournal.save
        claimed = False
        crashed = False

        def competing_request(
            credentials: Credentials, method: str, suffix: str, *args: object, **kwargs: object
        ) -> dict[str, JsonValue]:
            nonlocal claimed
            if method == "POST" and suffix.endswith("/tests") and not claimed:
                claimed = True
                other = json.loads(json.dumps(kwargs["body"]))
                other["payload"]["query"] = "A competing command owns the request"
                competing = request(
                    credentials, method, suffix, *args, **(kwargs | {"body": other})
                )
                assert competing["schema_version"] == 2
            return request(credentials, method, suffix, *args, **kwargs)

        def interrupted_save(journal: RunJournal, state: dict[str, JsonValue]) -> None:
            nonlocal crashed
            if not crashed and state["status"] == "failed":
                crashed = True
                raise OSError("interrupted before conflict checkpoint commit")
            return save(journal, state)

        monkeypatch.setattr(http_transport, "request_json", competing_request)
        monkeypatch.setattr(RunJournal, "save", interrupted_save)
        with pytest.raises(OSError, match="before conflict checkpoint"):
            run_checklist(**run.arguments)
        resumed = run_checklist(**run.arguments, resume=True)
        assert resumed["status"] == "failed"
        assert resumed["error_code"] == "request_id_reused"
        assert resumed["results"] == []
        assert resumed["dispatch_count"] == 1


def test_reference_transport_rejects_oversized_http_response(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from runner_fixture import server_url

    from career_lab.contracts.v2.core import Executor, ProtocolError
    from career_lab.delegations.credentials import Credentials
    from career_lab.reference_agent.ports import HttpEnvironment
    from career_lab.reference_agent.request_identity import RequestIdentity

    app = FastAPI()

    @app.get("/sessions/session")
    def oversized() -> dict[str, JsonValue]:
        return {"schema_version": 2, "body": "x" * 8_000_001}

    with server_url(app) as url:
        credentials = Credentials(url, "session", "synthetic-transport-secret")
        executor = Executor(kind="reference_agent", id="reference")
        environment = HttpEnvironment(
            credentials, executor, RequestIdentity(tmp_path / "unused.db", credentials, executor)
        )
        with pytest.raises(ProtocolError) as rejected:
            environment.request("GET", "")
        assert rejected.value.code == "request_result_unresolved"
        assert credentials.token not in str(rejected.value)
