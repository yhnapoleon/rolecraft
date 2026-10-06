"""Regression cases derived from 031's independent review. Synthetic ports only."""
from dataclasses import replace
import json

import pytest
from test_w09_core import (
    ACTION, ACTOR, ActionOutcome, ActiveAcquisitionPolicy, Budget, ChecklistPolicy,
    EnvironmentDouble, ModelDouble, Observation, ObservedStep, PortError,
    ReferenceRunner, RunJournal, ToolLoopPolicy, fragment, manifest, observation,
)
from test_w09_copies import SnapshotDouble, POINT, LINEAGE, H, execute_copies


class CrashAfterEffect(EnvironmentDouble):
    def execute(self, sid, command, timeout):
        exists = command.request_id in self.saved
        result = super().execute(sid, command, timeout)
        if not exists:
            raise KeyboardInterrupt()
        return result


@pytest.mark.parametrize('expired,legacy_terminal', [(False, False), (True, False), (False, True)])
def test_r1_reconcile_after_last_action_or_deadline(tmp_path, expired, legacy_terminal):
    now = [100.0]
    env = CrashAfterEffect()
    runner = ReferenceRunner(env, ChecklistPolicy([ACTION]), clock=lambda: now[0])
    m = manifest(budget=Budget(model_calls=0, actions=1, wall_seconds=1))
    with pytest.raises(KeyboardInterrupt):
        runner.run(m, goal='recover', output=tmp_path)
    if legacy_terminal:
        journal = RunJournal(tmp_path / 'run'); state = journal.load()
        state['status'] = 'failed'; state['reason_code'] = 'transport_timeout'
        journal.save(state)
    if expired:
        now[0] = 102.0
    result = runner.run(m, goal='recover', output=tmp_path, resume=True)
    assert len(result['steps']) == 1 and result['pending'] is None
    assert len(env.saved) == 1 and len(env.calls) == 1
    assert result['action_attempts'] == 1 and result['reconcile_attempts'] == 1


@pytest.mark.parametrize('retries', [0, 2])
def test_r1_ambiguous_timeout_can_be_reconciled_without_post(tmp_path, retries):
    class TimeoutAfterEffect(EnvironmentDouble):
        def execute(self, sid, command, timeout):
            super().execute(sid, command, timeout)
            raise PortError('transport_timeout', retryable=True, ambiguous=True)
    env = TimeoutAfterEffect(); runner = ReferenceRunner(env, ChecklistPolicy([ACTION]), max_retries=retries)
    m = manifest(budget=Budget(model_calls=0, actions=1, wall_seconds=100))
    first = runner.run(m, goal='recover', output=tmp_path)
    assert first['status'] == 'unresolved' and first['pending']
    result = runner.run(m, goal='recover', output=tmp_path, resume=True)
    assert len(result['steps']) == 1 and result['pending'] is None
    assert len(env.calls) == 1 and len(env.saved) == 1


def test_r1_unknown_result_has_bounded_repeatable_read_only_recovery(tmp_path):
    class Unknown(EnvironmentDouble):
        lookups = 0
        def execute(self, sid, command, timeout):
            self.calls.append(command)
            raise PortError('transport_timeout', retryable=True, ambiguous=True)
        def reconcile(self, sid, command, timeout):
            self.lookups += 1
            assert timeout <= 3
            return None
    env = Unknown(); runner = ReferenceRunner(env, ChecklistPolicy([ACTION]), max_reconciles=2, reconcile_wall_seconds=3)
    runner.run(manifest(), goal='x', output=tmp_path)
    for n in (2, 4):
        r = runner.run(manifest(), goal='x', output=tmp_path, resume=True)
        assert r['status'] == 'unresolved' and r['pending'] and not r['steps']
        assert env.lookups == n and len(env.calls) == 1


@pytest.mark.parametrize('correlation', [None, 'OTHER-REQUEST'])
def test_r2_missing_or_wrong_correlation_never_enters_history(tmp_path, correlation):
    class Wrong(EnvironmentDouble):
        def execute(self, sid, command, timeout):
            self.calls.append(command)
            return ActionOutcome('success', observation(), ObservedStep(
                id='SOURCE-STEP', action='read', as_of=observation().as_of,
                observations=('WRONG RESULT CANARY',), evidence_refs=(), outcome='success'), request_id=correlation)
    env = Wrong()
    r = ReferenceRunner(env, ChecklistPolicy([ACTION])).run(manifest(), goal='x', output=tmp_path)
    assert r['status'] == 'unresolved' and not r['steps'] and r['pending']
    assert r['reason_code'] in {'result_request_missing', 'result_request_mismatch'}
    assert 'WRONG RESULT CANARY' not in json.dumps(r)


def test_r2_source_step_identity_remains_distinct_from_command(tmp_path):
    class Distinct(EnvironmentDouble):
        def execute(self, sid, command, timeout):
            result = super().execute(sid, command, timeout)
            return replace(result, step=result.step.model_copy(update={'id': 'SERVICE-STEP-42'}))
    r = ReferenceRunner(Distinct(), ChecklistPolicy([ACTION])).run(manifest(), goal='x', output=tmp_path)
    row = r['steps'][0]
    assert row['id'] == 'SERVICE-STEP-42'
    assert row['command_request_id'] != row['id']


@pytest.mark.parametrize('fault', ['alias', 'state_session', 'version', 'prefix', 'resources'])
def test_r3_bad_restore_rejected_before_any_candidate_dispatch(fault):
    class Bad(SnapshotDouble):
        def restore(self, snap, session_id, request_id):
            result = super().restore(snap, session_id, request_id)
            if fault == 'alias':
                return result.model_copy(update={'session_id': 'shared-copy', 'state': result.state.model_copy(update={'session_id': 'shared-copy'})})
            if fault == 'state_session':
                return result.model_copy(update={'state': result.state.model_copy(update={'session_id': 'other'})})
            if fault == 'version':
                return result.model_copy(update={'state': result.state.model_copy(update={'business_seq': 99})})
            if fault == 'resources':
                return result.model_copy(update={'state': result.state.model_copy(update={'resources': {'capacity': 999}})})
            return result.model_copy(update={'prefix_digest': 'b'*64})
    port = Bad()
    results = execute_copies(port, session_id='s', as_of=POINT,
        candidates=[ACTION, ACTION.model_copy(update={'id': 'second'})], decision_id='d', lineage=LINEAGE, split='dev')
    assert len(results) == 2 and all(x['error_code'] == 'unsafe_candidate_restore' for x in results)
    assert port.calls == [] and port.parent == H


@pytest.mark.parametrize('policy_type', [ToolLoopPolicy, ActiveAcquisitionPolicy])
@pytest.mark.parametrize('origin', ['unknown', 'learner_known', 'role_private', 'prompt_only'])
def test_r4_final_provider_messages_follow_memory_origin(tmp_path, policy_type, origin):
    marker = 'MEMORY-' + origin
    class Memory(EnvironmentDouble):
        def observe(self, sid, timeout):
            return observation(sources=(fragment(marker, channel='memory'),))
    model = ModelDouble(['{"stop":"blocked"}'])
    # Trusted codec authority, not a client-supplied flag or a guess from channel.
    authorizer = None if origin == 'unknown' else lambda obs, frag: origin
    r = ReferenceRunner(Memory(), policy_type(), model, source_authorizer=authorizer).run(
        manifest(), goal='x', output=tmp_path)
    messages = json.dumps(model.calls)
    assert (marker in messages) == (origin == 'learner_known')
    if origin == 'learner_known':
        assert r['belief']['facts'][0]['statement'] == marker
    elif origin == 'unknown':
        assert r['quarantined_sources'] and not r['belief']['facts']
        assert marker not in json.dumps(r)
    else:
        assert r['reason_code'] == 'private_memory_rejected' and model.calls == []


@pytest.mark.parametrize('channel', ['role_private', 'prompt_only', 'role_prompt'])
def test_r4_explicit_private_sources_block_all_model_calls(tmp_path, channel):
    class Private(EnvironmentDouble):
        def observe(self, sid, timeout):
            return observation(sources=(fragment('PRIVATE-CANARY', channel=channel),))
    model = ModelDouble([])
    r = ReferenceRunner(Private(), ToolLoopPolicy(), model).run(manifest(), goal='x', output=tmp_path)
    assert r['reason_code'] == 'unfiltered_observation' and model.calls == []
    assert 'PRIVATE-CANARY' not in json.dumps(r)
