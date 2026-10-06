"""W09 module tests. All model/environment doubles are explicitly synthetic."""
import json
from pathlib import Path

import pytest

from career_lab.contracts.v2 import (
    ActionProposal, BeliefState, Budget, DisclosedFragment, EvidenceRefV2, Executor,
    FileRef, Lineage, ModelAttemptUsage, Observation, ObservedStep, RunManifest,
    SourceIdentity, ToolSchema, VersionPoint, digest,
)
from career_lab.reference_agent.belief import check_observation, update_belief
from career_lab.reference_agent.legal import validate_action, validate_schema
from career_lab.reference_agent.policies import (
    ActiveAcquisitionPolicy, ChecklistPolicy, ToolLoopPolicy, PolicyContext,
)
from career_lab.reference_agent.ports import ActionOutcome, ModelOutput, PortError
from career_lab.reference_agent.runner import ReferenceRunner
from career_lab.reference_agent.journal import RunJournal

H = "a" * 64
ACTOR = Executor(id="research-credential", kind="reference_agent")
PARAMS = {"type": "object", "properties": {"query": {"type": "string"}},
          "required": ["query"], "additionalProperties": False}
ACTION = ActionProposal(id="read", tool="read", arguments={"query": "requirements"}, purpose="Investigate")
REF = FileRef(path="fixture.json", sha256=H)


def observation(seq=0, sources=(), tools=None):
    if tools is None:
        tools = (ToolSchema(name="read", capability="read", parameters=PARAMS,
                            parameters_hash=digest(PARAMS), available=True),)
    return Observation(session_id="s", actor=ACTOR,
        as_of=VersionPoint(business_seq=seq, workspace_revision=seq, storage_revision=seq),
        visible_sources=sources, tools=tools, next_seq=seq)


def fragment(text="capacity 30", seq=0, channel="material", fact="capacity", session="s"):
    return DisclosedFragment(
        ref=EvidenceRefV2(session_id=session, kind="document", object_id="brief", version=1,
                          observed_at_seq=seq), text=text, channel=channel, fact_ids=(fact,))


def manifest(**updates):
    value = RunManifest(id="run", session_id="s", executor=ACTOR, scenario=REF,
        runtime=REF, evaluation=REF, seed=7, split="dev",
        budget=Budget(model_calls=8, tokens=200000, actions=8, wall_seconds=100),
        provider="synthetic-test-double", model_revision="fake-v1",
        source=SourceIdentity(base_commit="8"*40, source_digest=H),
        lineage=Lineage(structure_id="test-fixture", component_id="component",
                        run_id="run", session_id="s"))
    return value.model_copy(update=updates)


class EnvironmentDouble:
    def __init__(self, effects=None):
        self.seq, self.calls, self.observations, self.effects = 0, [], 0, list(effects or [])
        self.saved = {}
        self.poll_calls = 0

    def observe(self, sid, timeout):
        self.observations += 1
        return observation(self.seq)

    def execute(self, sid, command, timeout):
        self.calls.append(command)
        if command.request_id in self.saved:
            return self.saved[command.request_id]
        if self.effects:
            effect = self.effects.pop(0)
            if isinstance(effect, BaseException):
                raise effect
            if effect is not None:
                return effect
        self.seq += 1
        obs = observation(self.seq, (fragment(seq=self.seq),))
        result = ActionOutcome("success", obs, ObservedStep(id=command.request_id, action="read",
            as_of=obs.as_of, observations=("actually returned text",), evidence_refs=(),
            outcome="success"), request_id=command.request_id)
        self.saved[command.request_id] = result
        return result

    def reconcile(self, sid, command, timeout):
        return self.saved.get(command.request_id)

    def poll(self, sid, jid, timeout):
        self.poll_calls += 1
        return ActionOutcome("pending", job_id=jid)


class ModelDouble:
    provider = "synthetic-test-double"
    revision = "fake-v1"
    output_token_limit = 512
    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), []
    def complete(self, messages, tools, *, request_id, attempt_id, timeout, seed):
        self.calls.append(messages)
        raw = self.outputs.pop(0)
        if isinstance(raw, BaseException):
            raise raw
        status, text = raw if isinstance(raw, tuple) else ("success", raw)
        return ModelOutput(text, ModelAttemptUsage(request_id=request_id, attempt_id=attempt_id,
            provider=self.provider, model_revision=self.revision, status=status,
            input_tokens=20 if status == "success" else None,
            output_tokens=10 if status == "success" else None,
            elapsed_seconds=0.1, usage_known=status == "success"))


def context(obs=None):
    obs = obs or observation()
    return PolicyContext("investigate", obs, update_belief(None, obs), (), 7)


def action_json():
    return json.dumps({"action": ACTION.model_dump(mode="json")})


def test_belief_only_observed_not_prompt_or_invented_world():
    obs = observation(sources=(fragment(),))
    b = update_belief(None, obs)
    assert b.facts[0].statement == "capacity 30"
    assert len(b.facts) == 1 and "future" not in b.model_dump_json()
    assert update_belief(b, obs) == b
    memory = observation(1, (fragment("secret 100", channel="memory", seq=1),))
    assert update_belief(b, memory).facts == b.facts
    with pytest.raises(PortError, match="unfiltered"):
        check_observation(observation(sources=(fragment(channel="role_prompt"),)), "s", ACTOR)


def test_prompt_membership_cannot_enter_typed_observation():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Observation.model_validate(observation().model_dump() | {"prompt_fact_ids": ["secret"]})


def test_conflict_retains_sources_and_times_without_overwrite():
    first = update_belief(None, observation(sources=(fragment(),)))
    second = update_belief(first, observation(1, (fragment("capacity 60", seq=1),)))
    assert [x.status for x in second.facts] == ["conflict", "conflict"]
    assert {x.statement for x in second.facts} == {"capacity 30", "capacity 60"}
    assert [x.observed_refs[0].observed_at_seq for x in second.facts] == [0, 1]


@pytest.mark.parametrize("obs,code", [
    (observation().model_copy(update={"session_id": "other"}), "identity"),
    (observation(sources=(fragment(session="other"),)), "source"),
    (observation(sources=(fragment(seq=99),)), "source"),
])
def test_observation_rejects_wrong_session_and_future(obs, code):
    with pytest.raises(PortError, match=code):
        check_observation(obs, "s", ACTOR)


def test_stale_observation_cannot_erase_belief():
    b = update_belief(None, observation(2))
    with pytest.raises(PortError, match="stale"):
        update_belief(b, observation(1))


@pytest.mark.parametrize("bad", [
    {}, {"query": 7}, {"query": "x", "executor": "human"}, {"query": True},
])
def test_action_parameters_fail_closed(bad):
    with pytest.raises(PortError, match="invalid_parameters"):
        validate_action(ACTION.model_copy(update={"arguments": bad}), observation())


def test_unavailable_action_rejected():
    with pytest.raises(PortError, match="tool_unavailable"):
        validate_action(ACTION, observation(tools=()))


def test_schema_refs_enum_and_unsupported_keyword():
    schema = {"$defs": {"q": {"type": "integer", "minimum": 0}},
              "type": "object", "properties": {"q": {"$ref": "#/$defs/q"}},
              "required": ["q"], "additionalProperties": False}
    validate_schema({"q": 0}, schema)
    with pytest.raises(PortError):
        validate_schema({"q": -1}, schema)
    with pytest.raises(PortError, match="unsupported"):
        validate_schema("x", {"type": "string", "unknownKeyword": 1})


def test_policies_have_different_visible_inputs_and_no_authority():
    ordinary = ToolLoopPolicy()
    active = ActiveAcquisitionPolicy()
    assert "belief" not in ordinary.payload(context())
    assert "belief" in active.payload(context())
    choice = ordinary.choose(context(), lambda messages: action_json())
    assert choice.action == ACTION
    chosen = active.choose(context(), lambda _: json.dumps({
        "candidates": [ACTION.model_dump(mode="json")], "selected_id": ACTION.id,
        "reason": "Resolve known gap"}))
    assert chosen.action == ACTION
    assert chosen.candidates == (ACTION,)


def test_active_cannot_choose_unproposed_or_illegal_candidate():
    for selected in ("absent", "read"):
        with pytest.raises(PortError):
            ActiveAcquisitionPolicy().choose(context(), lambda _: json.dumps({
                "candidates": [ACTION.model_copy(update={"tool": "grant_resources"}).model_dump(mode="json")],
                "selected_id": selected, "reason": "bad"}))


def test_checklist_run_records_actual_steps_and_does_not_claim_success(tmp_path):
    env = EnvironmentDouble()
    result = ReferenceRunner(env, ChecklistPolicy([ACTION])).run(
        manifest(), goal="investigate", output=tmp_path)
    assert result["reason_code"] == "unverified_checklist_exhausted"
    assert result["status"] == "stopped"
    assert result["action_attempts"] == 1
    assert result["steps"][0]["observations"] == ["actually returned text"]
    assert (tmp_path / "run" / "observations.json").is_file()
    before = len(env.calls)
    replay = ReferenceRunner(env, ChecklistPolicy([ACTION])).run(
        manifest(), goal="investigate", output=tmp_path, resume=True)
    assert replay == result and len(env.calls) == before


def test_model_stop_requires_independent_terminal_evaluator(tmp_path):
    model = ModelDouble(['{"stop":"proposed_complete","reason":"done"}'])
    result = ReferenceRunner(EnvironmentDouble(), ToolLoopPolicy(), model).run(
        manifest(), goal="investigate", output=tmp_path)
    assert result["status"] == "stopped"
    assert result["reason_code"] == "unverified_proposed_complete"


def test_accepted_no_go_not_filtered_by_path_enum(tmp_path):
    def evaluate(m, obs, steps):
        return {"evaluation": m.evaluation.model_dump(mode="json"), "accepted": True,
                "purpose": "no_go", "reason": "synthetic evaluator test; not real acceptance"}
    result = ReferenceRunner(EnvironmentDouble(), ChecklistPolicy([]), evaluator=evaluate).run(
        manifest(), goal="a justified stop", output=tmp_path)
    assert result["status"] == "completed" and result["evaluation"]["purpose"] == "no_go"


def test_budget_counts_retries_and_preserves_errors(tmp_path):
    env = EnvironmentDouble([PortError("rate_limited", retryable=True)])
    r = ReferenceRunner(env, ChecklistPolicy([ACTION])).run(manifest(), goal="x", output=tmp_path)
    assert r["action_attempts"] == 2 and env.calls[0] == env.calls[1]
    assert len(env.saved) == 1
    assert r["errors"][0]["code"] == "rate_limited"


def test_permission_denied_stops_without_looping(tmp_path):
    env = EnvironmentDouble([PortError("forbidden")])
    r = ReferenceRunner(env, ChecklistPolicy([ACTION])).run(manifest(), goal="x", output=tmp_path)
    assert r["status"] == "failed" and r["reason_code"] == "forbidden"
    assert len(env.calls) == 1 and r["steps"][0]["outcome"] == "failed"


def test_model_retries_are_metered_including_unknown_usage(tmp_path):
    model = ModelDouble([("timeout", ""), '{"stop":"blocked"}'])
    r = ReferenceRunner(EnvironmentDouble(), ToolLoopPolicy(), model).run(
        manifest(), goal="x", output=tmp_path)
    assert r["model_calls"] == 2
    assert [x["status"] for x in r["manifest"]["attempts"]] == ["timeout", "success"]
    assert r["charged_tokens"] > 30  # Unknown first call retained reservation.
    assert r["manifest"]["attempts"][0]["input_tokens"] is None


@pytest.mark.parametrize("budget,expected", [
    (Budget(model_calls=0, actions=5, wall_seconds=100), "model_budget_exhausted"),
    (Budget(model_calls=5, tokens=1, actions=5, wall_seconds=100), "token_budget_exhausted"),
    (Budget(model_calls=5, actions=5, wall_seconds=100, currency_limit=0), "provider_cost_reservation_unavailable"),
])
def test_budget_denial_before_model_dispatch(tmp_path, budget, expected):
    model = ModelDouble([])
    r = ReferenceRunner(EnvironmentDouble(), ToolLoopPolicy(), model).run(
        manifest(budget=budget), goal="x", output=tmp_path)
    assert r["reason_code"] == expected and model.calls == []


def test_action_budget_stops_before_dispatch(tmp_path):
    env = EnvironmentDouble()
    m = manifest(budget=Budget(model_calls=0, actions=0, wall_seconds=100))
    r = ReferenceRunner(env, ChecklistPolicy([ACTION])).run(m, goal="x", output=tmp_path)
    assert r["reason_code"] == "action_budget_exhausted" and not env.calls


def test_pending_job_returns_bounded_then_resumes_poll_not_action(tmp_path):
    env = EnvironmentDouble([ActionOutcome("pending", job_id="job-1")])
    runner = ReferenceRunner(env, ChecklistPolicy([ACTION]), max_polls=2)
    first = runner.run(manifest(), goal="x", output=tmp_path)
    assert first["status"] == "waiting" and env.poll_calls == 2 and len(env.calls) == 1
    runner.run(manifest(), goal="x", output=tmp_path, resume=True)
    assert env.poll_calls == 4 and len(env.calls) == 1


def test_resume_reuses_command_after_process_crash_post_effect(tmp_path):
    class CrashAfterEffect(EnvironmentDouble):
        def execute(self, sid, command, timeout):
            saved = command.request_id in self.saved
            outcome = super().execute(sid, command, timeout)
            if not saved:
                raise KeyboardInterrupt()
            return outcome
    env = CrashAfterEffect()
    runner = ReferenceRunner(env, ChecklistPolicy([ACTION]))
    with pytest.raises(KeyboardInterrupt):
        runner.run(manifest(), goal="x", output=tmp_path)
    checkpoint = RunJournal(tmp_path / "run").load()
    assert checkpoint["pending"] and len(env.saved) == 1
    result = runner.run(manifest(), goal="x", output=tmp_path, resume=True)
    assert len(env.saved) == 1 and len(result["steps"]) == 1
    assert len(env.calls) == 1 and result["reconcile_attempts"] == 1


def test_unknown_inflight_model_is_not_silently_recalled(tmp_path):
    model = ModelDouble([KeyboardInterrupt()])
    runner = ReferenceRunner(EnvironmentDouble(), ToolLoopPolicy(), model)
    with pytest.raises(KeyboardInterrupt):
        runner.run(manifest(), goal="x", output=tmp_path)
    result = runner.run(manifest(), goal="x", output=tmp_path, resume=True)
    assert result["reason_code"] == "model_interrupted_usage_unknown"
    assert len(model.calls) == 1
    assert result["manifest"]["attempts"][0]["status"] == "unknown"


def test_resume_identity_and_checkpoint_tampering_rejected(tmp_path):
    runner = ReferenceRunner(EnvironmentDouble(), ChecklistPolicy([]))
    runner.run(manifest(), goal="x", output=tmp_path)
    with pytest.raises(PortError, match="identity"):
        runner.run(manifest(), goal="changed", output=tmp_path, resume=True)
    p = tmp_path / "run" / "checkpoint.json"
    data = json.loads(p.read_text()); data["state"]["goal"] = "tampered"; p.write_text(json.dumps(data))
    with pytest.raises(PortError, match="checkpoint_hash"):
        runner.run(manifest(), goal="x", output=tmp_path, resume=True)


def test_repeated_invalid_choices_stop_bounded(tmp_path):
    model = ModelDouble(["{}", "{}", "{}"])
    result = ReferenceRunner(EnvironmentDouble(), ToolLoopPolicy(), model).run(
        manifest(), goal="x", output=tmp_path)
    assert result["reason_code"] == "repeated_invalid_choice"
    assert result["model_calls"] == 3


def test_deadline_survives_resume_and_idle_time(tmp_path):
    now = [100.0]
    env = EnvironmentDouble([ActionOutcome("pending", job_id="j")])
    runner = ReferenceRunner(env, ChecklistPolicy([ACTION]), clock=lambda: now[0])
    runner.run(manifest(), goal="x", output=tmp_path)
    now[0] = 201.0
    result = runner.run(manifest(), goal="x", output=tmp_path, resume=True)
    assert result["status"] == "waiting" and result["reason_code"] == "job_pending" and len(env.calls) == 1
    assert result["reconcile_attempts"] == 2


def test_exclusive_run_lock(tmp_path):
    first, second = RunJournal(tmp_path), RunJournal(tmp_path)
    with first.locked():
        with pytest.raises(PortError, match="already_active"):
            with second.locked():
                pass


def test_wrong_model_identity_fails_before_dispatch(tmp_path):
    model = ModelDouble([])
    with pytest.raises(PortError, match="model_identity"):
        ReferenceRunner(EnvironmentDouble(), ToolLoopPolicy(), model).run(
            manifest(provider="real-provider"), goal="x", output=tmp_path)
    assert model.calls == []

@pytest.mark.parametrize('policy_name', ['checklist', 'tool_loop', 'active_acquisition'])
def test_each_real_strategy_module_executes_same_fixture_task(tmp_path, policy_name):
    if policy_name == 'checklist':
        policy, model = ChecklistPolicy([ACTION]), None
    elif policy_name == 'tool_loop':
        policy = ToolLoopPolicy()
        model = ModelDouble([action_json(), '{"stop":"proposed_complete"}'])
    else:
        policy = ActiveAcquisitionPolicy()
        response = json.dumps({'candidates': [ACTION.model_dump(mode='json')],
                               'selected_id': ACTION.id, 'reason': 'inspect actual source'})
        model = ModelDouble([response, '{"stop":"proposed_complete"}'])
    env = EnvironmentDouble()
    result = ReferenceRunner(env, policy, model).run(manifest(), goal='fixture task', output=tmp_path)
    assert len(result['steps']) == 1 and result['steps'][0]['outcome'] == 'success'
    assert result['status'] == 'stopped'  # Fixture has no genuine terminal evaluator.
    assert result['manifest']['provider'] == 'synthetic-test-double'


def test_tool_schema_drift_rejected_before_policy(tmp_path):
    env = EnvironmentDouble()
    result = ReferenceRunner(env, ChecklistPolicy([ACTION]), expected_tools_digest='c'*64).run(
        manifest(), goal='x', output=tmp_path)
    assert result['reason_code'] == 'tool_schema_drift' and not env.calls


def test_repeated_stability_checks_do_not_create_negative_diagnosis(tmp_path):
    result = ReferenceRunner(EnvironmentDouble(), ChecklistPolicy([ACTION, ACTION])).run(
        manifest(), goal='stability check', output=tmp_path)
    assert len(result['steps']) == 2 and all(x['outcome'] == 'success' for x in result['steps'])
    assert not any('inefficient' in str(x) or 'redundant' in str(x) for x in result['steps'])


def test_model_bridge_uses_existing_adapter_preserves_identity_and_usage():
    from career_lab.runtime.model_adapter import ScriptedModel, ModelReply
    from career_lab.reference_agent.model import AdapterModel
    adapter = ScriptedModel([ModelReply(text='{}', usage={'prompt_tokens': 3, 'completion_tokens': 2})])
    bridge = AdapterModel(adapter, 'scripted-test-only')
    result = bridge.complete([], [], request_id='r', attempt_id='a', timeout=1, seed=7)
    assert result.usage.model_revision == 'scripted-test-only-v1'
    assert result.usage.usage_known and result.usage.input_tokens == 3
    assert not bridge.seed_supported
    adapter.retries = 2
    with pytest.raises(ValueError, match='hidden'):
        AdapterModel(adapter, 'test')


def test_bridge_does_not_invent_missing_provider_usage():
    from career_lab.runtime.model_adapter import ScriptedModel, ModelReply
    from career_lab.reference_agent.model import AdapterModel
    result = AdapterModel(ScriptedModel([ModelReply(text='{}')]), 'scripted').complete(
        [], [], request_id='r', attempt_id='a', timeout=1, seed=0)
    assert not result.usage.usage_known and result.usage.cost is None
