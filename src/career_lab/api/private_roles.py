"""Trusted private-role integration. Default installation keeps generation closed.

The module-owned RoleService remains responsible for dialogue behavior. This port
only binds it to the common fixed snapshot, actual lease and private persistence.
"""
from career_lab.contracts.v2 import *
from career_lab.api.modules import Operation,StoreJobHandler
from career_lab.api.role_snapshot import FixedRoleSnapshotPort,activated_catalog
from career_lab.runtime.context_v2 import ContextPort
from career_lab.runtime.roles_v2 import RoleService
from career_lab.storage.role_memory import RoleTurn,RoleReply,RoleDisplay
from career_lab.storage.v2_store import ObjectWrite,references


class PrivateRoleGenerationPort:
    def __init__(self,store,catalog,view,envelope,auth,*,max_context_chars=24000):
        self.store,self.catalog,self.view,self.envelope,self.auth=store,catalog,view,envelope,auth
        self.max_context_chars=max_context_chars;self.permit=None;self.snapshot=None;self.attempts=[];self.prepared=None

    def require_available(self):
        if self.permit is None:
            if self.view.worker_claim is None:raise ProtocolError('worker_claim_required',status=409)
            self.permit,self.snapshot=self.store.begin_role_execution(self.view,self.envelope,self.auth,self.view.worker_claim,self.catalog,max_context_chars=self.max_context_chars)

    def _audit(self,*,phase,context,received,memories,used,attempts,reply=None,error=None):
        permit=self.permit
        messages,_=self.snapshot.messages(self.auth,max_chars=self.max_context_chars)
        scope=RoleAuditScope(**{key:getattr(self.auth,key) for key in RoleAuditScope.model_fields if key!='schema_version'})
        return RoleGenerationAudit(phase=phase,job_id=permit.claim.job_id,job_attempt=permit.claim.attempt,worker_id=permit.claim.worker_id,lease_token_hash=digest(permit.claim.lease_token),request=ObjectRef.model_validate(self.envelope.command.payload['subject']),reply=reply,scope=scope,prompt_messages=tuple(ProviderMessage.model_validate(m) for m in messages),prompt_hash=permit.prompt_hash,history_revision=permit.history_revision,refresh_count=self.envelope.context.refresh_count,attempts=tuple(attempts),error_code=error,
            received_shares=tuple(RoleAuditReceivedShare(share=r.share,product=r.product,role_id=r.role_id,received_at=r.received_at,fragment=r.fragment) for r in received),
            memories=tuple(RoleAuditMemory(fragment=m.fragment,role_id=m.role_id,learner_refs=m.learner_refs,provenance=m.provenance) for m in memories),used_sources=tuple(used))

    def record_attempt(self,envelope,auth,attempt,error_code):
        self.require_available()
        if envelope!=self.envelope or auth!=self.auth or self.attempts:raise ProtocolError('role_attempt_identity_invalid',status=403)
        if (error_code is None)!=(attempt.status=='success'):raise ProtocolError('role_attempt_status_invalid',status=403)
        selected,_=self.snapshot.select_sources(auth,self.max_context_chars)
        audit=self._audit(phase='attempt',context=self.snapshot.context,received=self.snapshot.received_shares,memories=self.snapshot.memories,used=selected,attempts=(attempt,),error=error_code)
        context=self.snapshot.context.model_copy(update={'generation_audit':audit})
        self.store.record_role_attempt(self.permit,context)
        self.attempts.append(attempt)

    def prepare(self,view,envelope,auth,generation):
        self.require_available()
        if view is not self.view or envelope!=self.envelope or auth!=self.auth or tuple(self.attempts)!=generation.attempts:raise ProtocolError('role_private_identity_invalid',status=403)
        if generation.prompt_hash!=self.permit.prompt_hash or generation.history_revision!=self.permit.history_revision or generation.role_id!=self.permit.role_id:raise ProtocolError('role_private_context_mismatch',status=409)
        audit=self._audit(phase='completed',context=generation.context,received=generation.received_shares,memories=generation.memories,used=generation.used_sources,attempts=generation.attempts,reply=generation.reply_ref)
        context=RoleContext.model_validate(generation.context.model_dump(mode='json')|{'generation_audit':audit.model_dump(mode='json')})
        ref=ObjectRef(session_id=auth.session_id,kind='role_context',object_id='generation-'+digest([envelope.job_id,envelope.context.refresh_count])[:24],version=1)
        self.prepared=ObjectWrite(ref=ref,expected_head=0,content=context.model_dump(mode='json'),visible_to=('system',generation.role_id),dependencies=references(context.model_dump(mode='json')))
        return (self.prepared,)

    def authorize(self,plan):
        if self.prepared is None or [w for w in plan.writes if w.ref.kind=='role_context']!=[self.prepared]:raise ProtocolError('role_private_plan_changed',status=403)
        return self.store.authorize_role_plan(self.permit,plan)


def install_private_role_runtime(registry,catalog,model,*,enable_generation=False,max_context_chars=24000):
    """Same registry for API/worker. Real business activation remains opt-in.

    Keep enable_generation false until the coordinator-fixed repaired W04 input
    and cumulative acceptance are installed. Tests use labelled controlled models.
    """
    for kind,model_type in (('role_turn',RoleTurn),('role_reply',RoleReply),('role_display',RoleDisplay)):registry.register_object_model(kind,model_type)
    enqueue=RoleService(ContextPort(catalog),model,max_context_chars=max_context_chars)
    registry.register(Operation('turns.create','act',TurnInput,enqueue.enqueue,ready=enable_generation,unavailable_code=None if enable_generation else 'role_integration_not_accepted'))
    def generate(store,view,envelope,auth):
        if not enable_generation:raise ProtocolError('role_integration_not_accepted',status=409)
        current_catalog=activated_catalog(catalog,view.private_scenario_state)
        port=PrivateRoleGenerationPort(store,current_catalog,view,envelope,auth,max_context_chars=max_context_chars)
        service=RoleService(ContextPort(current_catalog,FixedRoleSnapshotPort(store,current_catalog)),model,max_context_chars=max_context_chars,private_port=port)
        return port.authorize(service.generate(view,envelope,auth))
    registry.register_job('v2.role_turn',StoreJobHandler(generate, retry_on_error=False))
    return registry
