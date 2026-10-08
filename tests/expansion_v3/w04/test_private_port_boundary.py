"""Controlled PrivateGenerationPort exercises module audience checks.

This fixture writes one bounded native RoleContext record. It does not pretend
that c7 has a production full prompt/stance/attempt carrier or role snapshot port.
"""
from dataclasses import replace
import pytest
from career_lab.contracts.v2 import (
    RoleContext,DisclosedFragment,EvidenceRefV2,ObjectRef,Command,TurnInput,ProtocolError,digest,
)
from career_lab.runtime.context_v2 import ContextPort,RoleFrame
from career_lab.runtime.roles_v2 import RoleService
from career_lab.runtime.model_adapter import ScriptedModel,ModelReply
from career_lab.storage.v2_store import ObjectWrite,references
from career_lab.storage.v2_lifecycle import point
from career_lab.api.modules import ExtensionRegistry,Gateway
from career_lab.jobs.repository import JobRepository
from career_lab.jobs.worker import Worker,ClaimedHandler
from test_context import package,catalog,state
from test_runtime import common_store


class ControlledSnapshot:
    def __init__(self,package,catalog):self.package,self.catalog=package,catalog
    def project_fixed(self,view,auth,role):
        scenario=state(self.package).model_copy(update={'session_id':auth.session_id})
        scenario=scenario.model_copy(update={'current_config':scenario.current_config.model_copy(update={'session_id':auth.session_id})})
        return RoleFrame(auth.session_id,role,point(view.state),self.catalog.binding,scenario)


class ControlledPrivatePort:
    def __init__(self,audience=('system','tech_lead'),empty=False,wrong_role=False):
        self.audience,self.empty,self.wrong_role=audience,empty,wrong_role;self.attempts=[];self.generations=[];self.plans=[];self.claims=set()
    def require_available(self):pass
    def claim_model_call(self,envelope,auth,phase,revision):
        key=(auth.session_id,envelope.origin_request_id,phase)
        if key in self.claims:return False
        self.claims.add(key);return True

    def record_attempt(self,envelope,auth,attempt,error):self.attempts.append((attempt,error))
    def prepare(self,view,envelope,auth,generation):
        self.generations.append(generation)
        if self.empty:return ()
        # Native protected carrier with public reply dependency, no private back-edge.
        ref=ObjectRef(session_id=auth.session_id,kind='role_context',object_id='bounded-audit',version=1)
        source=EvidenceRefV2(**generation.reply_ref.model_dump(),observed_at_seq=view.state.business_seq)
        context=RoleContext(session_id=auth.session_id,role_id='business_lead' if self.wrong_role else generation.role_id,
            as_of=point(view.state),sources=(DisclosedFragment(ref=source,text='BOUNDED_AUDIT_ONLY',channel='memory',verification='verified'),),
            conversations=(generation.reply_ref,),context_hash=digest('bounded test audit, not production prompt persistence'))
        write=ObjectWrite(ref=ref,expected_head=0,content=context.model_dump(mode='json'),visible_to=self.audience,
                          dependencies=references(context.model_dump(mode='json')))
        self.plans.append(write);return (write,)


class ControlledReplyVerifier:
    """Fixtures only: no claim of natural-language verification."""
    retries=0
    def check(self,snapshot,auth,request,text,*,record_attempt,begin_call=None):
        from career_lab.storage.role_memory import ReplyVerification,stance_digest
        from career_lab.contracts.v2 import FileRef
        if begin_call:begin_call('role_reply_review','controlled-no-model-fixture')
        return ReplyVerification('consistent',True,stance_digest(snapshot.stance_state),digest(text),snapshot.context.as_of,
            FileRef(path='controlled-no-model-fixture.json',sha256=digest('fixture only')))


def wired_case(tmp_path,package,catalog,port):
    store,auth=common_store(tmp_path,catalog)
    model=ScriptedModel([ModelReply(text='我需要先核对依据。')])
    service=RoleService(ContextPort(catalog,ControlledSnapshot(package,catalog)),model,private_port=port,reply_verifier=ControlledReplyVerifier())
    registry=ExtensionRegistry();service.install(registry);gateway=Gateway(store,registry)
    view=store.view(auth);body=TurnInput(role_id='tech_lead',text='请核对').model_dump(mode='json')
    command=Command(schema_version=2,request_id='role-turn',operation='turns.create',expected_version=view.state.business_seq,
                    expected_workspace_revision=view.state.workspace_revision,payload=body)
    queued=gateway.dispatch(auth,'turns.create',command.model_dump(mode='json'))
    jobs=JobRepository(store.db);worker=Worker(jobs,{'v2.role_turn':ClaimedHandler(lambda payload,claim:gateway.run_job('v2.role_turn',payload,claim=claim))})
    return store,auth,model,worker,queued['result']['queued_jobs'][0],service


def test_controlled_private_port_success_has_exact_audiences_and_no_world_effect(tmp_path,package,catalog):
    port=ControlledPrivatePort();store,auth,model,worker,jid,service=wired_case(tmp_path,package,catalog,port)
    before=store.view(auth).state
    worker.run_once();job=worker.jobs.get(jid)
    assert job['status']=='completed',job
    assert len(model.calls)==1 and len(port.generations)==1 and len(port.attempts)==1
    public=next(x for x in store.view(auth).objects if x.ref.kind=='role_reply')
    assert set(public.visible_to)=={'learner','tech_lead'}
    assert set(port.plans[0].visible_to)=={'system','tech_lead'}
    assert all(r.kind!='role_context' for r in public.dependencies)
    assert store.view(auth).state.resources==before.resources and store.view(auth).state.business_seq==before.business_seq
    private_ref=port.plans[0].ref
    with pytest.raises(ProtocolError):store.read(auth,private_ref)
    assert private_ref not in [x.ref for x in store.view(auth).objects]
    internal=store.read(store.role_reader(auth.session_id,'tech_lead'),private_ref)
    assert 'BOUNDED_AUDIT_ONLY' in internal.model_dump_json()
    assert internal.dependencies==(public.ref,)
    with pytest.raises(ProtocolError):store.read(store.role_reader(auth.session_id,'business_lead'),private_ref)
    assert 'BOUNDED_AUDIT_ONLY' not in str(job['result'])


@pytest.mark.parametrize('audience',[(),('learner','tech_lead'),('system','learner','tech_lead'),('system','business_lead')])
def test_controlled_wrong_private_audience_stops_before_commit(tmp_path,package,catalog,audience):
    port=ControlledPrivatePort(audience=audience);store,auth,model,worker,jid,service=wired_case(tmp_path,package,catalog,port)
    before=store.view(auth).state
    worker.run_once();job=worker.jobs.get(jid)
    assert job['status']=='failed' and job['error']=='role_private_audit_invalid'
    assert store.view(auth).state==before
    assert not [x for x in store.view(auth).objects if x.ref.kind=='role_reply']
    assert len(model.calls)==1


@pytest.mark.parametrize('empty,wrong_role,error',[(True,False,'role_private_audit_incomplete'),(False,True,'role_private_audit_invalid')])
def test_controlled_missing_or_wrong_role_audit_is_rejected(tmp_path,package,catalog,empty,wrong_role,error):
    port=ControlledPrivatePort(empty=empty,wrong_role=wrong_role)
    store,auth,model,worker,jid,service=wired_case(tmp_path,package,catalog,port)
    worker.run_once();job=worker.jobs.get(jid)
    assert job['status']=='failed' and job['error']==error
    assert not [x for x in store.view(auth).objects if x.ref.kind=='role_reply']


def test_provider_stays_closed_without_durable_claim_port(tmp_path,package,catalog):
    port=ControlledPrivatePort();port.claim_model_call=None
    store,auth,model,worker,jid,_=wired_case(tmp_path,package,catalog,port)
    try:
        worker.run_once();job=worker.jobs.get(jid)
        assert job['error']=='role_attempt_guard_unavailable' and not model.calls
    finally:store.db.engine.dispose()


@pytest.mark.parametrize("first_outcome",["returned","timeout"])
def test_model_claim_survives_worker_reconstruction_before_commit(tmp_path,package,catalog,first_outcome):
    """A controlled durable port exercises the new production callback contract."""
    import sqlite3
    from career_lab.api.modules import JobEnvelope
    class DurablePort(ControlledPrivatePort):
        def claim_model_call(self,envelope,auth,phase,revision):
            con=sqlite3.connect(tmp_path/'model-claims.db')
            try:
                con.execute('create table if not exists calls (session text, request text, phase text, primary key(session,request,phase))')
                try:con.execute('insert into calls values (?,?,?)',(auth.session_id,envelope.origin_request_id,phase));con.commit();return True
                except sqlite3.IntegrityError:return False
            finally:con.close()
    port=DurablePort();store,auth,model,worker,jid,service=wired_case(tmp_path,package,catalog,port)
    try:
        envelope=JobEnvelope.model_validate(worker.jobs.get(jid)['payload'])
        # Direct handler evaluation models a process loss after provider return,
        # before public/private mutation commit. No shared worker code is changed.
        view=store.view(auth)
        if first_outcome=='timeout':
            from career_lab.runtime.roles_v2 import RoleModelTransient
            def timeout(messages,tools):model.calls.append(messages);raise TimeoutError()
            model.complete=timeout
            with pytest.raises(RoleModelTransient):service.generate(view,envelope,auth)
        else:service.generate(view,envelope,auth)
        # A provider/model configuration change is not user authorization to retry.
        model.revision='different-provider-model-configuration'
        replacement=RoleService(service.port,model,private_port=DurablePort(),reply_verifier=ControlledReplyVerifier())
        with pytest.raises(ProtocolError) as exc:replacement.generate(view,envelope,auth)
        assert exc.value.code=='role_model_call_already_claimed' and len(model.calls)==1
    finally:store.db.engine.dispose()


def test_provider_without_reply_verifier_stops_before_any_model_call(tmp_path,package,catalog):
    port=ControlledPrivatePort();store,auth,model,worker,jid,service=wired_case(tmp_path,package,catalog,port)
    service.reply_verifier=None
    try:
        worker.run_once();job=worker.jobs.get(jid)
        assert job['error']=='role_reply_verifier_unavailable' and not model.calls and not port.claims
    finally:store.db.engine.dispose()


def test_local_reply_with_installed_reviewer_still_requires_durable_claim(tmp_path,package,catalog):
    from career_lab.runtime.roles_v2 import LocalRoleModel
    port=ControlledPrivatePort();port.claim_model_call=None
    store,auth,model,worker,jid,service=wired_case(tmp_path,package,catalog,port)
    service.model=LocalRoleModel()  # A real reviewer could still call an external provider.
    try:
        worker.run_once();job=worker.jobs.get(jid)
        assert job['error']=='role_attempt_guard_unavailable' and not port.attempts
    finally:store.db.engine.dispose()
