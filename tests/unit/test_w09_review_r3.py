"""Second-round independent-review counterexamples; synthetic ports only."""
from dataclasses import replace
import json
import pytest
from test_w09_core import (ACTION, ToolLoopPolicy, ActiveAcquisitionPolicy, EnvironmentDouble,
    fragment, observation, ActionOutcome, ObservedStep, action_json, ModelDouble, ReferenceRunner,
    manifest, BeliefState, digest, PolicyContext, PortError)
from test_w09_copies import SnapshotDouble, POINT, LINEAGE, H
from career_lab.reference_agent.acquisition import execute_copies, resume_candidate
from career_lab.contracts.v2 import BeliefFact


@pytest.mark.parametrize('policy_type', [ToolLoopPolicy, ActiveAcquisitionPolicy])
@pytest.mark.parametrize('origin', ['unknown', 'learner_known', 'actual_disclosure'])
def test_f1_successful_step_history_uses_the_same_source_boundary(tmp_path, policy_type, origin):
    marker = 'HISTORY-CANARY-' + origin
    class MemoryResult(EnvironmentDouble):
        def execute(self, sid, command, timeout):
            self.calls.append(command); self.seq += 1
            source = fragment(marker, seq=self.seq, channel='reply' if origin == 'actual_disclosure' else 'memory')
            obs = observation(self.seq, (source,))
            return ActionOutcome('success', obs, ObservedStep(id='ORIGINAL-SERVICE-STEP', action='read',
                as_of=obs.as_of, observations=(marker,), evidence_refs=(source.ref,), outcome='success'), request_id=command.request_id)
    choice = action_json() if policy_type is ToolLoopPolicy else json.dumps({'candidates':[ACTION.model_dump(mode='json')], 'selected_id':ACTION.id, 'reason':'inspect'})
    model = ModelDouble([choice, '{"stop":"blocked"}'])
    authorizer = (lambda obs, source: 'learner_known') if origin == 'learner_known' else None
    result = ReferenceRunner(MemoryResult(), policy_type(), model, source_authorizer=authorizer).run(manifest(), goal='read sources', output=tmp_path)
    payload = json.loads(model.calls[1][1]['content'])
    assert len(model.calls) == 2
    assert (marker in json.dumps(model.calls[1])) == (origin != 'unknown')
    assert (marker in payload['history'][0]['observations']) == (origin != 'unknown')
    assert marker in result['steps'][0]['observations']  # Raw audit still available.
    assert result['steps'][0]['id'] == 'ORIGINAL-SERVICE-STEP'


@pytest.mark.parametrize('policy_type', [ToolLoopPolicy, ActiveAcquisitionPolicy])
def test_f1_quote_and_unattributed_history_cannot_bypass_projection(tmp_path, policy_type):
    marker = 'UNAUTHORIZED-QUOTE'
    class PoisonedQuotes(EnvironmentDouble):
        def execute(self, sid, command, timeout):
            self.calls.append(command); self.seq += 1
            safe = fragment('legitimate visible reply', seq=self.seq, channel='reply')
            poisoned = safe.ref.model_copy(update={'quote':marker,'span_start':0,'span_end':len(marker)})
            obs = observation(self.seq, (safe.model_copy(update={'ref':poisoned}),))
            return ActionOutcome('success', obs, ObservedStep(id='quote-step', action='read', as_of=obs.as_of,
                observations=(marker,), evidence_refs=(poisoned,), outcome='success'), request_id=command.request_id)
    choice = action_json() if policy_type is ToolLoopPolicy else json.dumps({'candidates':[ACTION.model_dump(mode='json')], 'selected_id':ACTION.id, 'reason':'inspect'})
    model = ModelDouble([choice, '{"stop":"blocked"}'])
    ReferenceRunner(PoisonedQuotes(),policy_type(),model).run(manifest(),goal='x',output=tmp_path)
    assert marker not in json.dumps(model.calls[1])
    assert 'legitimate visible reply' in json.dumps(model.calls[1])


def test_f1_active_belief_requires_authorized_source_statement():
    obs = observation(sources=(fragment('approved fact'),))
    forged = BeliefState(session_id='s',as_of=obs.as_of,facts=(BeliefFact(id='capacity',status='known',statement='BELIEF-CANARY',observed_refs=(obs.visible_sources[0].ref,)),),observation_hashes=(digest(obs),))
    c = PolicyContext('x',obs,forged,(),0)
    assert 'BELIEF-CANARY' not in json.dumps(ActiveAcquisitionPolicy().payload(c))


class CandidatePort(SnapshotDouble):
    def __init__(self, status='success', correlation='correct'):
        super().__init__(); self.status=status; self.correlation=correlation; self.command=None; self.child=None
    def execute(self, sid, command, timeout):
        self.calls.append((sid,command));self.command=command;self.child=sid
        request_id = command.request_id if self.correlation=='correct' else None if self.correlation=='missing' else 'OTHER-REQUEST'
        if self.status=='pending':
            return ActionOutcome('pending',job_id='job-1',request_id=request_id)
        obs=observation(3).model_copy(update={'session_id':sid})
        return ActionOutcome('success',obs,ObservedStep(id='SOURCE-CANDIDATE-STEP',action=command.operation,as_of=obs.as_of,
            observations=('candidate result',),evidence_refs=(),outcome='success'),request_id=request_id)


def run_candidate(port):
    return execute_copies(port,session_id='s',as_of=POINT,candidates=[ACTION],decision_id='d',lineage=LINEAGE,split='dev')[0]


@pytest.mark.parametrize('status', ['success','pending'])
@pytest.mark.parametrize('correlation', ['missing','wrong'])
def test_f2_candidate_rejects_unbound_results(status,correlation):
    p=CandidatePort(status,correlation);r=run_candidate(p)
    assert r['status']=='failed' and r['error_code'] in {'result_request_missing','result_request_mismatch'}
    assert r['command_request_id']==p.command.request_id
    assert r['step'] is None and r['job_id'] is None and r['observation'] is None


def test_f2_candidate_preserves_source_step_and_distinct_command_id():
    p=CandidatePort();r=run_candidate(p)
    assert r['status']=='success' and r['step']['id']=='SOURCE-CANDIDATE-STEP'
    assert r['command_request_id']==p.command.request_id and r['step']['id']!=r['command_request_id']


@pytest.mark.parametrize('fault', ['request','missing','job','missing_job'])
def test_f2_candidate_poll_rejects_unrelated_result_and_keeps_original_binding(fault):
    p=CandidatePort('pending');r=run_candidate(p)
    class Poll:
        def poll(self,sid,jid,timeout):
            obs=observation(3).model_copy(update={'session_id':sid})
            req='OTHER-REQUEST' if fault=='request' else None if fault=='missing' else p.command.request_id
            job='OTHER-JOB' if fault=='job' else None if fault=='missing_job' else jid
            return ActionOutcome('success',obs,ObservedStep(id='WRONG-RESULT',action=p.command.operation,as_of=obs.as_of,
                observations=('OTHER RESULT CANARY',),evidence_refs=(),outcome='success'),request_id=req,job_id=job)
    result=resume_candidate(r,Poll())
    assert result['status']=='unresolved' and result['step'] is None
    assert result['job_binding']==r['job_binding'] and result['job_id']=='job-1'
    assert 'OTHER RESULT CANARY' not in json.dumps(result)


def test_f2_candidate_pending_then_completed_with_same_job_binding():
    p=CandidatePort('pending');r=run_candidate(p)
    class Poll:
        def poll(self,sid,jid,timeout):
            obs=observation(3).model_copy(update={'session_id':sid})
            return ActionOutcome('success',obs,ObservedStep(id='ASYNC-SERVICE-STEP',action=p.command.operation,as_of=obs.as_of,
                observations=('completed',),evidence_refs=(),outcome='success'),request_id=p.command.request_id,job_id=jid)
    result=resume_candidate(r,Poll())
    assert result['status']=='success' and result['step']['id']=='ASYNC-SERVICE-STEP'
    assert result['job_binding']==r['job_binding'] and len(p.calls)==1
    assert r['status']=='pending'  # Historical pending record remains unchanged.


def test_f2_tampered_candidate_binding_cannot_poll():
    r=run_candidate(CandidatePort('pending'));r['job_id']='OTHER-JOB'
    class NoCalls:
        def poll(self,*args):raise AssertionError('must not poll')
    with pytest.raises(PortError,match='binding_invalid'):
        resume_candidate(r,NoCalls())
