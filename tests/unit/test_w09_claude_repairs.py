"""Bounded fixes from Claude review; no new research metrics or experiments."""
from pathlib import Path
import pytest
from career_lab.contracts.v2 import ProtocolError
from career_lab.runtime.model_adapter import ModelReply
from career_lab.reference_agent.model import AdapterModel
from career_lab.reference_agent.ports import PortError
from career_lab.reference_agent.legal import validate_schema
from test_w09_core import (manifest,EnvironmentDouble,ReferenceRunner,ToolLoopPolicy,ChecklistPolicy,
    ACTION,ActionOutcome,observation,fragment)
from test_w09_copies import SnapshotDouble,POINT,LINEAGE,execute_copies


class TimedBackend:
    revision='fake-v1'
    retries=0
    timeout=45.0
    def __init__(self):self.calls=[]
    def complete(self,messages,tools):
        self.calls.append(self.timeout)
        return ModelReply(text='{"stop":"blocked"}',usage={'prompt_tokens':2,'completion_tokens':1})


def test_default_45_second_backend_is_clamped_to_runner_budget(tmp_path):
    backend=TimedBackend();model=AdapterModel(backend,'synthetic-test-double')
    result=ReferenceRunner(EnvironmentDouble(),ToolLoopPolicy(),model).run(manifest(),goal='x',output=tmp_path)
    assert len(backend.calls)==1 and 0<backend.calls[0]<=30
    assert backend.timeout==45 and result['model_calls']==1
    assert not any(x['code']=='model_call_failed' for x in result['errors'])


def test_preflight_failure_has_real_cause_and_zero_dispatch_budget(tmp_path):
    class ReadOnly(TimedBackend):
        @property
        def timeout(self):return 45
    backend=ReadOnly();model=AdapterModel(backend,'synthetic-test-double')
    result=ReferenceRunner(EnvironmentDouble(),ToolLoopPolicy(),model).run(manifest(),goal='x',output=tmp_path)
    assert result['reason_code']=='provider_timeout_uncontrollable'
    assert result['model_calls']==result['charged_tokens']==0
    assert result['manifest']['attempts']==[] and backend.calls==[]


def test_upstream_protocol_error_is_saved_not_running(tmp_path):
    class Missing(EnvironmentDouble):
        def observe(self,*args):raise ProtocolError('environment_adapter_unavailable',status=503)
    result=ReferenceRunner(Missing(),ChecklistPolicy([ACTION])).run(manifest(),goal='x',output=tmp_path)
    assert result['status']=='failed' and result['reason_code']=='environment_adapter_unavailable'


def test_candidate_protocol_errors_do_not_drop_other_rows():
    class Missing(SnapshotDouble):
        def environment(self,restored):raise ProtocolError('environment_adapter_unavailable',status=503)
    rows=execute_copies(Missing(),session_id='s',as_of=POINT,candidates=[ACTION,ACTION.model_copy(update={'id':'next'})],decision_id='d',lineage=LINEAGE,split='dev')
    assert len(rows)==2 and all(r['error_code']=='environment_adapter_unavailable' for r in rows)


def test_poll_does_not_switch_to_a_different_job(tmp_path):
    class Wrong(EnvironmentDouble):
        def poll(self,*args):return ActionOutcome('pending',job_id='other')
    env=Wrong([ActionOutcome('pending',job_id='original')])
    result=ReferenceRunner(env,ChecklistPolicy([ACTION])).run(manifest(),goal='x',output=tmp_path)
    assert result['reason_code']=='result_job_mismatch' and result['pending']['job_id']=='original'


def test_post_action_private_observation_is_quarantined_terminal(tmp_path):
    class Private(EnvironmentDouble):
        def execute(self,*args):
            value=super().execute(*args)
            from dataclasses import replace
            return replace(value,observation=observation(1,(fragment('private',seq=1,channel='role_private'),)))
    env=Private();runner=ReferenceRunner(env,ChecklistPolicy([ACTION]))
    result=runner.run(manifest(),goal='x',output=tmp_path)
    assert result['status']=='failed' and result['pending'] is None and result['quarantined_pending']
    runner.run(manifest(),goal='x',output=tmp_path,resume=True)
    assert len(env.calls)==1


def test_recursive_schema_is_bounded():
    with pytest.raises(PortError,match='unsupported_tool_schema'):
        validate_schema({}, {'$ref':'#/$defs/X','$defs':{'X':{'$ref':'#/$defs/X'}}})
