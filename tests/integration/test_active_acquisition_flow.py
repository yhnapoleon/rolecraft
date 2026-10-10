"""Tool-loop behavior through the public runner and real HTTP workspace."""

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from pydantic import JsonValue
from runner_fixture import LiveRun, live_run
from test_bundle_registry_flow import write_json

from career_lab.contracts.v2.research import RunManifest, RuntimeBundle
from career_lab.registry.v3.store import BundleRegistry
from career_lab.runtime.model_adapter import ModelReply


def prepare_loop(
    run: LiveRun, replies: list[dict[str, JsonValue]], *, calls: int = 3, actions: int = 3
) -> None:
    source = run.arguments["manifest_path"].parent / "source"
    previous = RuntimeBundle.model_validate_json((source / "reference/runtime.json").read_bytes())
    model_ref = write_json(
        source,
        "reference/controlled.json",
        {
            "provider": "controlled",
            "revision": "mechanism-v1",
            "replies": replies,
        },
    )
    runtime = previous.model_copy(update={"id": "reference-loop", "model": model_ref})
    runtime_ref = write_json(source, "reference/loop.json", runtime)
    registry = BundleRegistry(run.arguments["registry_path"])
    run.arguments["runtime_id"] = registry.register("runtime", source, runtime_ref)
    path = run.arguments["manifest_path"]
    manifest = RunManifest.model_validate_json(path.read_bytes())
    manifest = manifest.model_copy(
        update={
            "runtime": runtime_ref,
            "provider": "controlled",
            "model_revision": "mechanism-v1",
            "budget": manifest.budget.model_copy(update={"actions": actions, "model_calls": calls}),
        }
    )
    path.write_text(manifest.model_dump_json())


def read_reply(run: LiveRun, material_id: str = "brief", version: int = 1) -> dict[str, JsonValue]:
    sid = json.loads(run.arguments["manifest_path"].read_text())["session_id"]
    return {
        "tool_calls": [
            {
                "id": "read-brief",
                "name": "read_material",
                "arguments": {
                    "tool": "read_material",
                    "material": {
                        "session_id": sid,
                        "kind": "material",
                        "object_id": material_id,
                        "version": version,
                    },
                },
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 1},
    }


def test_BEL_01_only_actual_authorized_observations_become_knowledge(tmp_path: Path) -> None:
    from career_lab.reference_agent.loop import run_loop

    with live_run(tmp_path, "tests.create") as run:
        prepare_loop(
            run, [read_reply(run), {"usage": {"prompt_tokens": 2, "completion_tokens": 1}}]
        )
        report = run_loop(**run.arguments, strategy="active", goal="Check the pilot brief")
        assert report["status"] == "completed"
        assert report["quality_claim"] == "controlled_mechanism_only"
        assert report["observations"][0]["visible_sources"] == []
        acquired = report["observations"][-1]["visible_sources"]
        assert acquired
        facts = report["belief"]["observed"]["facts"]
        assert {f["statement"] for f in facts} == {f["text"] for f in acquired}
        assert all(f["observed_refs"] for f in facts)
        assert all(not f["fact_ids"] for f in acquired)
        assert report["business_terminal_verified"] is False
        assert run.token not in json.dumps(report)


def test_BEL_02_changed_source_spans_keep_both_versions_and_conflict(tmp_path: Path) -> None:
    from career_lab.reference_agent.loop import run_loop

    with live_run(tmp_path, "tests.create") as run:
        sid = json.loads(run.arguments["manifest_path"].read_text())["session_id"]
        config = run.app.state.scenario_v2.package.baseline(sid).model_copy(
            update={"version": 2, "config_version": 1, "participants": 17}
        )
        change = {
            "tool_calls": [
                {
                    "id": "configure",
                    "name": "apply_config",
                    "arguments": {
                        "tool": "apply_config",
                        "config": config.model_dump(mode="json"),
                    },
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        }
        prepare_loop(
            run,
            [
                read_reply(run, "policy"),
                change,
                read_reply(run, "policy", 2),
                {"usage": {"prompt_tokens": 2, "completion_tokens": 1}},
            ],
            calls=4,
            actions=4,
        )
        report = run_loop(**run.arguments, strategy="active", goal="Check the changing policy")
        assert report["status"] == "completed", report["error_code"]
        facts = report["belief"]["observed"]["facts"]
        limits = [
            fact for fact in facts if "500" in fact["statement"] or "400" in fact["statement"]
        ]
        assert len(limits) == 2
        assert {fact["status"] for fact in limits} == {"conflict"}
        assert {ref["version"] for fact in limits for ref in fact["observed_refs"]} == {1, 2}
        assert (
            len({ref["observed_at_seq"] for fact in limits for ref in fact["observed_refs"]}) == 2
        )


def test_BEL_03_sourced_thoughts_plan_and_revision_survive_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from career_lab.contracts.v2.core import digest
    from career_lab.contracts.v2.world import Observation
    from career_lab.reference_agent.loop import run_loop
    from career_lab.runtime.model_adapter import ScriptedModel

    with live_run(tmp_path, "tests.create") as run:
        credentials = json.loads(run.arguments["credentials_path"].read_text())
        response = httpx.get(
            credentials["api_url"] + "/sessions/" + credentials["session_id"] + "/observation",
            headers={"Authorization": "Bearer " + run.token},
            trust_env=False,
        )
        assert response.status_code == 200
        observed_hash = digest(Observation.model_validate(response.json()["result"]))
        action = read_reply(run)
        call = action["tool_calls"][0]
        action["text"] = json.dumps(
            {
                "unknowns": [
                    {"statement": "Is the brief current?", "observation_hashes": [observed_hash]}
                ],
                "hypotheses": [
                    {
                        "statement": "The brief may have changed.",
                        "observation_hashes": [observed_hash],
                    }
                ],
                "plan": [
                    {
                        "id": "read",
                        "tool": call["name"],
                        "purpose": "Check the source",
                        "arguments": call["arguments"],
                    }
                ],
            }
        )
        prepare_loop(run, [action, {"usage": {"prompt_tokens": 2, "completion_tokens": 1}}])
        report = run_loop(**run.arguments, strategy="active", goal="Check the brief")
        belief = report["belief"]
        assert belief["unknowns"][0]["statement"] == "Is the brief current?"
        assert belief["hypotheses"][0]["observation_hashes"] == [observed_hash]
        assert belief["plan"][0]["tool"] == "read_material"
        assert belief["goal"] == "Check the brief"
        assert belief["revision"] >= 2
        assert "The brief may have changed." not in {
            f["statement"] for f in belief["observed"]["facts"]
        }

        def no_new_model_call(*args: object, **kwargs: object) -> None:
            raise AssertionError("history reread called the provider")

        monkeypatch.setattr(ScriptedModel, "complete", no_new_model_call)
        assert (
            run_loop(**run.arguments, strategy="active", goal="Check the brief", resume=True)
            == report
        )


def install_nested_usage(run: LiveRun, monkeypatch: pytest.MonkeyPatch, *, known: bool) -> None:
    from dataclasses import replace

    from career_lab.assistant.v2.service import TestExecution
    from career_lab.contracts.v2.core import ModelAttemptUsage

    execute = run.app.state.scenario_v2.assistant.run

    def with_receipt(*args: object, **kwargs: object) -> TestExecution:
        actual = execute(*args, **kwargs)
        receipt = ModelAttemptUsage(
            request_id=actual.result.id,
            attempt_id="controlled-nested-attempt",
            provider="controlled",
            model_revision="mechanism-v1",
            status="success",
            input_tokens=10 if known else None,
            output_tokens=2 if known else None,
            cost=0.25 if known else None,
            elapsed_seconds=0.01,
            usage_known=known,
        )
        metadata = actual.result.execution.model_copy(
            update={"attempts": (receipt,), "cost_complete": known}
        )
        return replace(actual, result=actual.result.model_copy(update={"execution": metadata}))

    # Controlled receipt at the assistant host boundary; retrieval, HTTP, transaction
    # persistence and the reference runner remain production behavior.
    monkeypatch.setattr(run.app.state.scenario_v2.assistant, "run", with_receipt)


def test_BEL_04_nested_unknown_usage_stops_before_another_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from career_lab.reference_agent.loop import run_loop

    with live_run(tmp_path, "tests.create") as run:
        install_nested_usage(run, monkeypatch, known=False)
        testing = {
            "tool_calls": [
                {
                    "id": "test",
                    "name": "tests.create",
                    "arguments": {
                        "query": "住宿报销上限是多少？",
                        "config_version": 0,
                    },
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "cost": 0.0},
        }
        prepare_loop(run, [testing, {"usage": {"prompt_tokens": 2, "completion_tokens": 1}}])
        report = run_loop(**run.arguments, strategy="ordinary", goal="Test the policy answer")
        assert report["status"] == "failed"
        assert report["error_code"] == "nested_usage_unknown"
        assert len(report["attempts"]) == 1
        assert len(report["execution"]["results"]) == 1
        assert report["execution"]["results"][0]["response"]["result"]["test"]["answer"]
        usage = report["execution"]["manifest"]["actual_consumption"]
        assert usage["model_attempt_count"] == 2
        assert usage["cost"] is None
        assert usage["cost_complete"] is False
        assert report["belief"]["consumption"] == usage
        result = report["execution"]["results"][0]
        assert report["unknown_usage_sources"] == [result["request_id"] + ":test_cost"]


@pytest.mark.parametrize("strategy", ["ordinary", "active"])
@pytest.mark.parametrize(
    "limit,value", [("tokens", 3), ("model_calls", 1), ("actions", 1), ("currency_limit", 1)]
)
def test_BEL_05_equal_limits_stop_each_strategy_before_another_call(
    tmp_path: Path, strategy: str, limit: str, value: int
) -> None:
    from career_lab.reference_agent.loop import run_loop

    with live_run(tmp_path, "tests.create") as run:
        first = read_reply(run)
        first["usage"]["cost"] = 1.0  # Controlled receipt units; no paid provider is called.
        prepare_loop(run, [first, {"usage": {"prompt_tokens": 2, "completion_tokens": 1}}])
        path = run.arguments["manifest_path"]
        manifest = RunManifest.model_validate_json(path.read_bytes())
        manifest = manifest.model_copy(
            update={"budget": manifest.budget.model_copy(update={limit: value})}
        )
        path.write_text(manifest.model_dump_json())
        report = run_loop(**run.arguments, strategy=strategy, goal="Check the pilot brief")
        assert report["status"] == "failed"
        assert report["error_code"] == "run_budget_exhausted"
        assert len(report["attempts"]) == 1
        assert report["execution"]["dispatch_count"] == 1
        assert report["execution"]["manifest"]["budget"] == manifest.budget.model_dump(mode="json")
        actual = report["execution"]["manifest"]["actual_consumption"]
        assert actual["input_tokens"] == 2
        assert actual["output_tokens"] == 1
        assert actual["model_attempt_count"] == 1


@pytest.mark.parametrize(
    "bad_output", ["notes", "multiple_actions", "unavailable_tool", "empty_call_id"]
)
def test_BEL_06_invalid_output_is_one_failed_attempt_without_self_repair(
    tmp_path: Path, bad_output: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from career_lab.reference_agent.loop import run_loop
    from career_lab.runtime.model_adapter import ScriptedModel

    with live_run(tmp_path, "tests.create") as run:
        reply = read_reply(run)
        if bad_output == "notes":
            reply["text"] = "This is not a structured decision"
        elif bad_output == "multiple_actions":
            reply["tool_calls"] *= 2
        elif bad_output == "empty_call_id":
            reply["tool_calls"][0]["id"] = ""
        else:
            reply["tool_calls"][0]["name"] = "run_arbitrary_code"
        prepare_loop(run, [reply, read_reply(run)])
        report = run_loop(**run.arguments, strategy="active", goal="Check the pilot brief")
        assert report["status"] == "failed"
        assert len(report["attempts"]) == 1
        assert report["attempts"][0]["status"] == "failed"
        assert report["execution"]["dispatch_count"] == 0
        assert report["execution"]["manifest"]["status"] == "failed"

        def forbidden_retry(*args: object, **kwargs: object) -> None:
            raise AssertionError("failed provider was retried")

        monkeypatch.setattr(ScriptedModel, "complete", forbidden_retry)
        assert (
            run_loop(**run.arguments, strategy="active", goal="Check the pilot brief", resume=True)
            == report
        )


@pytest.mark.parametrize("language", ["zh", "en"])
def test_BEL_03_formal_loop_cli_recovers_the_saved_run(tmp_path: Path, language: str) -> None:
    with live_run(tmp_path, "tests.create", language=language) as run:
        prepare_loop(
            run, [read_reply(run), {"usage": {"prompt_tokens": 2, "completion_tokens": 1}}]
        )
        names = {
            "manifest_path": "manifest",
            "registry_path": "registry",
            "credentials_path": "credentials",
        }
        args = [
            sys.executable,
            "-m",
            "career_lab.reference_agent",
            "loop",
            "--strategy",
            "active",
            "--goal",
            "核对委托" if language == "zh" else "Check the brief",
        ]
        for key, value in run.arguments.items():
            args.extend(["--" + names.get(key, key.replace("_", "-")), str(value)])
        first = subprocess.run(args, capture_output=True, text=True, check=False)
        assert first.returncode == 0, first.stdout + first.stderr
        second = subprocess.run([*args, "--resume"], capture_output=True, text=True, check=False)
        assert second.returncode == 0, second.stdout + second.stderr
        assert json.loads(second.stdout) == json.loads(first.stdout)
        assert json.loads(first.stdout)["quality_claim"] == "controlled_mechanism_only"
        assert run.token not in first.stdout + first.stderr + second.stdout + second.stderr


def test_evaluation_root_identity_cannot_be_replaced_by_a_dependency(tmp_path: Path) -> None:
    from career_lab.contracts.v2.core import ProtocolError
    from career_lab.reference_agent.loop import run_loop

    with live_run(tmp_path, "tests.create") as run:
        prepare_loop(
            run, [read_reply(run), {"usage": {"prompt_tokens": 2, "completion_tokens": 1}}]
        )
        registry = BundleRegistry(run.arguments["registry_path"])
        original = registry.load(run.arguments["evaluation_id"])
        manifest = RunManifest.model_validate_json(run.arguments["manifest_path"].read_bytes())
        alternate = original.model_copy(
            update={
                "id": original.id + "-alternate",
                "revision": original.revision + "-next",
                "graders": (*original.graders, manifest.evaluation),
            }
        )
        source = tmp_path / "source"
        alternate_ref = write_json(source, "reference/alternate-evaluation.json", alternate)
        run.arguments["evaluation_id"] = registry.register("evaluation", source, alternate_ref)
        with pytest.raises(ProtocolError) as rejected:
            run_loop(**run.arguments, strategy="active", goal="Check the pilot brief")
        assert rejected.value.code == "registry_manifest_mismatch"
        assert not run.arguments["output"].exists()


def test_BEL_03_committed_model_reply_survives_crash_before_action_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from career_lab.reference_agent.loop import run_loop

    with live_run(tmp_path, "tests.create") as run:
        prepare_loop(
            run, [read_reply(run), {"usage": {"prompt_tokens": 2, "completion_tokens": 1}}]
        )
        original = os.replace
        interrupted = False

        def crash_after_commit(source: str | Path, destination: str | Path) -> None:
            nonlocal interrupted
            original(source, destination)
            if Path(destination) != run.arguments["output"] / "checkpoint.json":
                return
            state = json.loads(Path(destination).read_text())["state"]
            if (
                not interrupted
                and state["attempts"]
                and state["attempts"][-1]["status"] == "success"
                and not state["model_pending"]
                and not state["actions"]
            ):
                interrupted = True
                raise OSError("lost disk acknowledgement")

        monkeypatch.setattr(os, "replace", crash_after_commit)
        with pytest.raises(OSError, match="lost disk acknowledgement"):
            run_loop(**run.arguments, strategy="active", goal="Check the pilot brief")
        resumed = run_loop(
            **run.arguments, strategy="active", goal="Check the pilot brief", resume=True
        )
        assert resumed["status"] == "completed", resumed["error_code"]
        assert resumed["execution"]["dispatch_count"] == 1
        assert len(resumed["execution"]["results"]) == 1
        assert len(resumed["attempts"]) == 2
        assert resumed["observations"][-1]["visible_sources"]


@pytest.mark.parametrize(
    "usage,error",
    [
        ({}, "run_usage_unknown"),
        ({"prompt_tokens": 99, "completion_tokens": 1}, "run_budget_exhausted"),
    ],
)
def test_BEL_04_unaccounted_or_over_budget_reply_cannot_dispatch_an_action(
    tmp_path: Path, usage: dict[str, JsonValue], error: str
) -> None:
    from career_lab.reference_agent.loop import run_loop

    with live_run(tmp_path, "tests.create") as run:
        reply = read_reply(run)
        reply["usage"] = usage
        prepare_loop(run, [reply, {}])
        path = run.arguments["manifest_path"]
        manifest = RunManifest.model_validate_json(path.read_bytes())
        path.write_text(
            manifest.model_copy(
                update={"budget": manifest.budget.model_copy(update={"tokens": 3})}
            ).model_dump_json()
        )
        report = run_loop(**run.arguments, strategy="active", goal="Check the brief")
        assert report["status"] == "failed"
        assert report["error_code"] == error
        assert report["execution"]["dispatch_count"] == 0
        assert len(report["attempts"]) == 1


def test_BEL_05_recovery_cannot_expand_the_fixed_budget(tmp_path: Path) -> None:
    from career_lab.contracts.v2.core import ProtocolError, digest
    from career_lab.reference_agent.loop import run_loop

    with live_run(tmp_path, "tests.create") as run:
        prepare_loop(
            run, [read_reply(run), {"usage": {"prompt_tokens": 2, "completion_tokens": 1}}]
        )
        run_loop(**run.arguments, strategy="active", goal="Check the brief")
        checkpoint = run.arguments["output"] / "checkpoint.json"
        payload = json.loads(checkpoint.read_text())
        payload["state"]["execution"]["manifest"]["budget"]["model_calls"] = 99
        # Re-seal deliberately: this exercises immutable input binding beyond corruption detection.
        payload["checkpoint_hash"] = digest(payload["state"])
        checkpoint.write_text(json.dumps(payload))
        with pytest.raises(ProtocolError) as rejected:
            run_loop(**run.arguments, strategy="active", goal="Check the brief", resume=True)
        assert rejected.value.code == "resume_manifest_mismatch"


def test_BEL_03_decision_is_not_silently_rebased_after_concurrent_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from career_lab.reference_agent.loop import run_loop
    from career_lab.runtime.model_adapter import ScriptedModel

    with live_run(tmp_path, "tests.create") as run:
        prepare_loop(
            run, [read_reply(run), {"usage": {"prompt_tokens": 2, "completion_tokens": 1}}]
        )
        credentials = json.loads(run.arguments["credentials_path"].read_text())
        prefix = credentials["api_url"] + "/sessions/" + credentials["session_id"]
        original = ScriptedModel.complete
        changed = False

        def concurrent_work(
            model: ScriptedModel,
            messages: list[dict[str, JsonValue]],
            tools: list[dict[str, JsonValue]],
        ) -> ModelReply:
            nonlocal changed
            reply = original(model, messages, tools)
            if not changed:
                with httpx.Client(
                    headers={"Authorization": "Bearer " + run.token}, trust_env=False
                ) as client:
                    state = client.get(prefix).json()["state"]
                    written = client.post(
                        prefix + "/work-products",
                        json={
                            "schema_version": 2,
                            "operation": "work_products.create",
                            "request_id": "concurrent-work",
                            "expected_version": state["business_seq"],
                            "expected_workspace_revision": state["workspace_revision"],
                            "payload": {
                                "kind": "text",
                                "purpose": "exploration",
                                "content": "Concurrent note",
                            },
                        },
                    )
                    assert written.status_code == 200, written.text
                changed = True
            return reply

        monkeypatch.setattr(ScriptedModel, "complete", concurrent_work)
        report = run_loop(**run.arguments, strategy="active", goal="Check the brief")
        assert report["status"] == "failed"
        assert report["error_code"] == "reference_context_changed"
        assert report["execution"]["dispatch_count"] == 0
        assert len(report["attempts"]) == 1


def test_BEL_01_model_receives_actual_tool_results_without_private_fact_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from career_lab.reference_agent.loop import run_loop
    from career_lab.runtime.model_adapter import ScriptedModel

    captured: list[dict[str, JsonValue]] = []
    original = ScriptedModel.complete

    def capture(
        model: ScriptedModel,
        messages: list[dict[str, JsonValue]],
        tools: list[dict[str, JsonValue]],
    ) -> ModelReply:
        captured.append(json.loads(messages[-1]["content"]))
        return original(model, messages, tools)

    with live_run(tmp_path, "tests.create") as run:
        prepare_loop(
            run, [read_reply(run), {"usage": {"prompt_tokens": 2, "completion_tokens": 1}}]
        )
        monkeypatch.setattr(ScriptedModel, "complete", capture)
        report = run_loop(**run.arguments, strategy="ordinary", goal="Check the brief")
        assert report["status"] == "completed"
        assert len(captured) == 2
        assert captured[0]["tool_results"] == []
        received = captured[1]["tool_results"]
        assert len(received) == 1
        assert received[0]["operation"] == "read_material"
        fragments = received[0]["response"]["result"]["fragments"]
        assert fragments
        assert all("fact_ids" not in fragment for fragment in fragments)
        assert {fragment["text"] for fragment in fragments} == {
            fragment["text"] for fragment in report["observations"][-1]["visible_sources"]
        }
        assert "belief" not in captured[0]


def test_BEL_03_active_candidates_costs_and_selection_are_saved_per_decision(
    tmp_path: Path,
) -> None:
    from career_lab.reference_agent.loop import run_loop

    with live_run(tmp_path, "tests.create") as run:
        reply = read_reply(run)
        brief = reply["tool_calls"][0]
        technical = read_reply(run, "technical")["tool_calls"][0]
        estimates = {
            "actions": 1,
            "model_calls": 0,
            "tokens": 0,
            "wall_seconds": 1,
            "currency_limit": 0,
        }
        reply["text"] = json.dumps(
            {
                "plan": [
                    {
                        "id": "brief",
                        "tool": brief["name"],
                        "arguments": brief["arguments"],
                        "purpose": "Resolve the task goal",
                        "expected_cost": estimates,
                    },
                    {
                        "id": "technical",
                        "tool": technical["name"],
                        "arguments": technical["arguments"],
                        "purpose": "Check constraints",
                        "expected_cost": estimates,
                    },
                ]
            }
        )
        prepare_loop(run, [reply, {"usage": {"prompt_tokens": 2, "completion_tokens": 1}}])
        report = run_loop(**run.arguments, strategy="active", goal="Check the brief")
        assert report["status"] == "completed"
        assert len(report["decisions"]) == 2
        decision = report["decisions"][0]
        assert {candidate["id"] for candidate in decision["candidates"]} == {"brief", "technical"}
        assert decision["selected_id"] == "brief"
        assert all(
            candidate["expected_cost"]["actions"] == 1 for candidate in decision["candidates"]
        )
        assert decision["session_id"] == report["observations"][0]["session_id"]
        assert decision["as_of"] == report["observations"][0]["as_of"]
        assert report["execution"]["manifest"]["actual_consumption"]["cost"] is None


def test_BEL_01_public_function_schemas_and_aliases_drive_the_same_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from career_lab.delegations.openai_tools import function_name
    from career_lab.reference_agent.loop import run_loop
    from career_lab.runtime.model_adapter import ScriptedModel

    declared: list[list[dict[str, JsonValue]]] = []
    original = ScriptedModel.complete

    def capture(
        model: ScriptedModel,
        messages: list[dict[str, JsonValue]],
        tools: list[dict[str, JsonValue]],
    ) -> ModelReply:
        declared.append(tools)
        return original(model, messages, tools)

    with live_run(tmp_path, "tests.create") as run:
        reply = read_reply(run)
        reply["tool_calls"][0]["name"] = function_name("read_material")
        prepare_loop(run, [reply, {"usage": {"prompt_tokens": 2, "completion_tokens": 1}}])
        monkeypatch.setattr(ScriptedModel, "complete", capture)
        report = run_loop(**run.arguments, strategy="ordinary", goal="Check the brief")
        assert report["status"] == "completed", report["error_code"]
        assert declared[0]
        readable = next(
            tool["function"]
            for tool in declared[0]
            if tool["function"]["name"] == function_name("read_material")
        )
        assert "tool" in readable["parameters"]["properties"]
        assert "command" not in readable["parameters"]["properties"]
        assert readable["parameters"]["properties"]["tool"]["const"] == "read_material"
        assert report["execution"]["results"][0]["operation"] == "read_material"


def test_BEL_06_failed_provider_commit_is_terminal_after_disk_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from career_lab.reference_agent.loop import run_loop
    from career_lab.runtime.model_adapter import ScriptedModel

    calls = []

    def fail_provider(*args: object, **kwargs: object) -> ModelReply:
        calls.append("called")
        raise TimeoutError("controlled transport failure")

    with live_run(tmp_path, "tests.create") as run:
        prepare_loop(run, [{}, {}])
        monkeypatch.setattr(ScriptedModel, "complete", fail_provider)
        original = os.replace
        interrupted = False

        def crash_after_failure(source: str | Path, destination: str | Path) -> None:
            nonlocal interrupted
            original(source, destination)
            if Path(destination) != run.arguments["output"] / "checkpoint.json":
                return
            state = json.loads(Path(destination).read_text())["state"]
            if (
                not interrupted
                and state["attempts"]
                and state["attempts"][-1]["status"] == "failed"
                and not state["model_pending"]
            ):
                interrupted = True
                raise OSError("failure acknowledgement lost")

        monkeypatch.setattr(os, "replace", crash_after_failure)
        with pytest.raises(OSError, match="failure acknowledgement lost"):
            run_loop(**run.arguments, strategy="active", goal="Check the brief")
        resumed = run_loop(**run.arguments, strategy="active", goal="Check the brief", resume=True)
        assert resumed["status"] == "failed"
        assert len(calls) == 1
        assert len(resumed["attempts"]) == 1


def test_BEL_06_action_payload_must_match_the_selected_tool(tmp_path: Path) -> None:
    from career_lab.reference_agent.loop import run_loop

    with live_run(tmp_path, "tests.create") as run:
        reply = read_reply(run)
        reply["tool_calls"][0]["arguments"]["tool"] = "refresh_index"
        prepare_loop(run, [reply])
        report = run_loop(**run.arguments, strategy="active", goal="Check the brief")
        assert report["status"] == "failed"
        assert report["error_code"] == "reference_candidate_invalid"
        assert report["execution"]["dispatch_count"] == 0
        assert report["attempts"][0]["status"] == "failed"


def test_BEL_04_known_nested_receipt_contributes_to_actual_totals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from career_lab.reference_agent.loop import run_loop

    with live_run(tmp_path, "tests.create") as run:
        install_nested_usage(run, monkeypatch, known=True)
        testing = {
            "tool_calls": [
                {
                    "id": "nested-test",
                    "name": "tests.create",
                    "arguments": {"query": "住宿报销上限是多少？", "config_version": 0},
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "cost": 0.0},
        }
        stop = {"usage": {"prompt_tokens": 2, "completion_tokens": 1, "cost": 0.0}}
        prepare_loop(run, [testing, stop])
        report = run_loop(**run.arguments, strategy="ordinary", goal="Test the policy answer")
        assert report["status"] == "completed", report["error_code"]
        usage = report["execution"]["manifest"]["actual_consumption"]
        assert usage["model_attempt_count"] == 3
        assert usage["input_tokens"] == 14
        assert usage["output_tokens"] == 4
        assert usage["cost"] == 0.25
        assert usage["cost_complete"] is True
        assert usage["usage_complete"] is True
        assert report["unknown_usage_sources"] == []


@pytest.mark.parametrize("location", ["value", "key"])
def test_BEL_01_successful_http_credential_echo_never_reaches_model_or_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str
) -> None:
    from career_lab.delegations import http_transport
    from career_lab.delegations.credentials import Credentials
    from career_lab.reference_agent.loop import run_loop
    from career_lab.runtime.model_adapter import ScriptedModel

    exchange = http_transport.request_json
    complete = ScriptedModel.complete
    prompts: list[str] = []

    def echoed(
        credentials: Credentials, method: str, suffix: str, **kwargs: object
    ) -> dict[str, JsonValue]:
        value = exchange(credentials, method, suffix, **kwargs)
        if "/requests/" in suffix:
            if location == "key":
                value["response"]["result"][credentials.token] = "echo"
            else:
                value["response"]["result"]["credential_echo"] = credentials.token
        return value

    def capture(
        model: ScriptedModel,
        messages: list[dict[str, JsonValue]],
        tools: list[dict[str, JsonValue]],
    ) -> ModelReply:
        prompts.append(json.dumps(messages))
        return complete(model, messages, tools)

    with live_run(tmp_path, "tests.create") as run:
        prepare_loop(
            run, [read_reply(run), {"usage": {"prompt_tokens": 2, "completion_tokens": 1}}]
        )
        monkeypatch.setattr(http_transport, "request_json", echoed)
        monkeypatch.setattr(ScriptedModel, "complete", capture)
        report = run_loop(**run.arguments, strategy="ordinary", goal="Check the brief")
        assert report["status"] == "completed", report["error_code"]
        assert run.token not in json.dumps(report)
        assert run.token not in "".join(prompts)
        assert run.token not in (run.arguments["output"] / "checkpoint.json").read_text()


def test_BEL_05_exhausted_model_budget_stops_before_nested_tool_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from career_lab.reference_agent.loop import run_loop

    with live_run(tmp_path, "tests.create") as run:
        install_nested_usage(run, monkeypatch, known=True)
        testing = {
            "tool_calls": [
                {
                    "id": "nested-test",
                    "name": "tests.create",
                    "arguments": {"query": "住宿报销上限是多少？", "config_version": 0},
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "cost": 0.0},
        }
        prepare_loop(run, [testing], calls=1)
        report = run_loop(**run.arguments, strategy="ordinary", goal="Test the policy answer")
        assert report["status"] == "failed"
        assert report["error_code"] == "run_budget_exhausted"
        assert report["execution"]["dispatch_count"] == 0
        assert report["execution"]["results"] == []
        assert report["execution"]["manifest"]["actual_consumption"]["model_attempt_count"] == 1
