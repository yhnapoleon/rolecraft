"""Reference-runner public entry and recovery against the installed protocol."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


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
    import httpx
    from runner_fixture import live_run

    from career_lab.reference_agent.runner import run_checklist

    original = httpx.Client.request
    sent = []
    reads = []

    def lost_response(
        client: httpx.Client, method: str, url: httpx.URL | str, *args: object, **kwargs: object
    ) -> httpx.Response:
        response = original(client, method, url, *args, **kwargs)
        if method == "POST" and str(url).endswith("/tests"):
            sent.append(response.status_code)
            raise httpx.ReadError("response lost after commit")
        if method == "GET" and "/requests/" in str(url):
            reads.append(str(url))
        return response

    with live_run(tmp_path, "tests.create") as run:
        monkeypatch.setattr(httpx.Client, "request", lost_response)
        interrupted = run_checklist(**run.arguments)
        assert interrupted["status"] == "unresolved"
        assert interrupted["error_code"] == "request_result_unresolved"
        recovered = run_checklist(**run.arguments, resume=True)
        assert recovered["status"] == "completed"
        assert recovered["dispatch_count"] == 1
        assert sent == [200]
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

    import httpx
    from runner_fixture import live_run

    from career_lab.reference_agent.runner import run_checklist

    original = httpx.Client.request
    posts = []

    def delayed_state(
        client: httpx.Client, method: str, url: httpx.URL | str, *args: object, **kwargs: object
    ) -> httpx.Response:
        response = original(client, method, url, *args, **kwargs)
        if method == "GET" and "/requests/" not in str(url):
            time.sleep(0.05)
        if method == "POST":
            posts.append(str(url))
        return response

    with live_run(tmp_path, "tests.create") as run:
        manifest_path = run.arguments["manifest_path"]
        manifest = json.loads(manifest_path.read_text())
        manifest["budget"]["wall_seconds"] = 0.02
        manifest_path.write_text(json.dumps(manifest))
        monkeypatch.setattr(httpx.Client, "request", delayed_state)
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
    import httpx
    from runner_fixture import live_run

    from career_lab.reference_agent.runner import run_checklist

    original = httpx.Client.request

    def malformed(
        client: httpx.Client, method: str, url: httpx.URL | str, *args: object, **kwargs: object
    ) -> httpx.Response:
        response = original(client, method, url, *args, **kwargs)
        if "/requests/" in str(url):
            return httpx.Response(200, json={"schema_version": 2}, request=response.request)
        return response

    with live_run(tmp_path, "tests.create") as run:
        monkeypatch.setattr(httpx.Client, "request", malformed)
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
