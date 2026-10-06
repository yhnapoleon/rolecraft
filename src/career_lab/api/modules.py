"""Explicit installation point. No imports, code execution or model from user input."""
from dataclasses import dataclass
from typing import Callable, Literal, get_args, get_origin
from pydantic import BaseModel, ValidationError
from career_lab.contracts.v2 import *
from career_lab.storage.v2_store import V2Store,Mutation,TransactionResult

class CreateSessionV2(V2):
    schema_version: Literal[2]
    scenario: Identifier

class V2Response(V2):
    result: dict[str,JsonValue]

class JobEnvelope(V2):
    origin_request_id: Identifier
    job_id: Identifier
    context: JobContextSnapshot
    command: Command
    operation: Identifier
    capability: Literal['read','act','submit','delegate'] = 'act'

@dataclass(frozen=True)
class ScenarioRegistration:
    bindings: SessionBindings
    baseline_config: AssistantConfig
    resources: dict
    scenario_state: ScenarioStateV2 | None = None

@dataclass(frozen=True)
class Operation:
    name: str
    capability: str
    request_model: type[V2]
    handler: Callable
    mutates: bool = True
    response_model: type[V2] | None = None
    approval_policy: Callable | None = None
    action_name: str | None = None
    action_field: str | None = None
    service_mode: bool = False
    event_projector: Callable | None = None

# Public API/tool installation whitelist. Internal snapshot/restore is deliberately absent.
PUBLIC_OPERATIONS={
 'requests.read','actions','tests.create','tests.list','turns.create','submissions.create','submissions.list',
 'feedback.create','feedback.read','approvals.resolve','materials.list','timeline','evidence.read',
 'work_items.create','work_items.list','work_items.update','work_items.batch','work_products.adopt','work_products.create','work_products.list',
 'work_products.versions.create','work_products.versions.list','work_products.shares.create',
 'work_products.shares.change','workspace_imports','reviews.create','reviews.read','revision_cycles',
 'observation','tools','delegations.create','delegations.revoke',
}

class ExtensionRegistry:
    def __init__(self):
        self.scenarios={};self.operations={};self.cli={};self.job_handlers={};self.reference_resolvers={};self.contextual_reference_resolvers=set()
    def register_reference_resolver(self,kind,resolver,*,contextual=False):
        if kind in self.reference_resolvers:raise ValueError('reference resolver already registered')
        self.reference_resolvers[kind]=resolver
        if contextual:self.contextual_reference_resolvers.add(kind)
    def register_scenario(self,name,scenario:ScenarioRegistration):
        if name in self.scenarios:raise ValueError('scenario already registered')
        self.scenarios[name]=scenario
    def register(self,operation:Operation):
        if operation.name=='requests.read' and (operation.mutates or operation.capability!='read'):raise ValueError('request result lookup is read-only')
        if operation.name not in PUBLIC_OPERATIONS:raise ValueError('not a public module slot')
        if operation.name in self.operations:raise ValueError('operation already installed')
        if operation.capability not in {'read','act','submit','delegate'}:raise ValueError('invalid public capability')
        if operation.mutates and operation.capability=='read':raise ValueError('read capability cannot mutate')
        if not issubclass(operation.request_model,V2):raise TypeError('v2 request model required')
        if operation.service_mode and operation.name not in {'delegations.create','delegations.revoke'}:raise ValueError('service mode reserved for auth control plane')
        self.operations[operation.name]=operation
    def projector_for_action(self,action):
        """Select only from installed registrations and a persisted action name.

        Dynamic string fields are not proof of routing. Ambiguous registrations
        fail closed rather than selecting another module's projector.
        """
        matches=[]
        for op in self.operations.values():
            if not op.mutates:continue
            if op.action_field:
                field=op.request_model.model_fields.get(op.action_field)
                matched=field is not None and get_origin(field.annotation) is Literal and action in get_args(field.annotation)
            else:matched=action==(op.action_name or op.name)
            if matched:matches.append(op)
        if len(matches)>1:raise ProtocolError('event_projection_ambiguous',status=503)
        return matches[0].event_projector if matches else None

    def register_cli(self,name,configure_parser):
        if name in self.cli:raise ValueError('CLI already registered')
        self.cli[name]=configure_parser
    def install_cli(self,subparsers):
        for name,configure in self.cli.items():configure(subparsers.add_parser(name))
    def register_job(self,name,handler):
        if name in self.job_handlers:raise ValueError('job already registered')
        self.job_handlers[name]=handler

class SessionAccess(str):
    def __new__(cls,sid,context):
        value=super().__new__(cls,sid);value.context=context;return value

def public_state(state):
    # Scenario-specific resource/milestone projections belong to the installed observation module.
    return state.model_dump(mode='json',exclude={'resources','applied_milestones'})

class Gateway:
    def __init__(self,store:V2Store,registry:ExtensionRegistry):self.store,self.registry=store,registry
    def create(self,request:CreateSessionV2):
        scenario=self.registry.scenarios.get(request.scenario)
        if scenario is None:raise ProtocolError('scenario_module_unavailable',status=503)
        state,token=self.store.create_session(scenario.bindings,scenario.baseline_config,scenario.resources,scenario_state=scenario.scenario_state)
        return {'schema_version':2,'session_id':state.session_id,'token':token,'state':public_state(state)}
    def dispatch(self,auth,name,body=None,route_params=None):
        if name=='jobs.refresh':
            command=Command.model_validate(body)
            if command.operation!='jobs.refresh' or command.payload!={'job_id':(route_params or {}).get('job_id')}:raise ProtocolError('operation_route_mismatch',status=403)
            result=self.store.refresh_job(auth,command,command.payload['job_id'])
            return self.public_result(auth,result)
        if name=='requests.read':
            query=RequestResultQuery.model_validate(body or route_params)
            return self.request_result(auth,query.request_id).model_dump(mode='json')
        op=self.registry.operations.get(name)
        if op is None:raise ProtocolError('module_unavailable',f'{name} is not installed',503)
        params=route_params or {}
        self.store.authorize(auth,op.capability)
        if op.mutates:
            command=Command.model_validate(body)
            payload=op.request_model.model_validate(command.payload)
            expected_action=getattr(payload,op.action_field) if op.action_field else (op.action_name or op.name)
            if command.operation!=expected_action:raise ProtocolError('operation_route_mismatch',status=403)
            command=Command.model_validate(command.model_dump(mode='json')|{'payload':payload.model_dump(mode='json')})
            # Endpoint object IDs are part of the fingerprint and cannot be silently substituted.
            if params:
                for key,value in params.items():
                    if command.payload.get(key)!=value:raise ProtocolError('route_object_mismatch',status=409)
            if op.service_mode:
                self.store.authorize(auth,op.capability,command.operation)
                result=op.handler(self.store,payload,auth,command.request_id)
                if op.response_model is None:raise ProtocolError('module_response_contract_missing',status=503)
                try:result=op.response_model.model_validate(result.model_dump(mode='json') if isinstance(result,BaseModel) else result)
                except ValidationError as exc:raise ProtocolError('module_response_invalid',status=503) from exc
                return {'schema_version':2,'result':result.model_dump(mode='json')}
            result=self.store.execute(auth,command,op.handler,capability=op.capability,approval_policy=op.approval_policy)
            return self.public_result(auth,result,self.registry.projector_for_action(command.operation) if result.replayed else op.event_projector)
        self.store.authorize(auth,op.capability,op.action_name or op.name)
        payload=op.request_model.model_validate(body or params)
        result=op.handler(self.store.view(auth),payload,auth)
        if op.response_model is None:raise ProtocolError('module_response_contract_missing',status=503)
        try:
            result=op.response_model.model_validate(result.model_dump(mode='json') if isinstance(result,BaseModel) else result)
        except ValidationError as exc:
            raise ProtocolError('module_response_invalid',status=503) from exc
        return {'schema_version':2,'result':result.model_dump(mode='json')}
    def request_result(self,auth,request_id):
        meta,response,links=self.store.request_result(auth,request_id)
        jobs=[]
        for link in links:
            effect=link.pop('effect');effect_operation=link.pop('effect_operation',None)
            projector=self.registry.projector_for_action(effect_operation) if effect_operation is not None else None
            jobs.append(RequestJobResult(**link,effect=PublicTransactionResult.model_validate(self.public_result(auth,effect,projector)) if effect is not None else None))
        status='completed'
        if any(j.status in {'queued','running'} for j in jobs):status='pending'
        elif any(j.status=='failed' for j in jobs):status='failed'
        elif any(j.status=='needs_context' for j in jobs):status='needs_context'
        elif any(j.effect is None for j in jobs):status='unresolved'
        return RequestResult(session_id=auth.session_id,request_id=request_id,operation=meta['operation'],executor=response.executor,
            status=status,response=PublicTransactionResult.model_validate(self.public_result(auth,response,self.registry.projector_for_action(meta['operation']))),jobs=tuple(jobs))

    def public_result(self,auth,result,event_projector=None):
        readable='read' in auth.capabilities
        visible={canonical(x.ref) for x in self.store.view(auth).objects} if readable else set()
        events=[]
        for event in result.events:
            if not readable or auth.actor_id not in event.visible_to:continue
            if auth.allowed_objects is not None and any(canonical(ref) not in visible for ref in event.refs):continue
            if event_projector:
                projected=event_projector(event,auth)
                if projected is None:continue
                projected=PublicEvent.model_validate(projected.model_dump(mode='json'))
                if (projected.id,projected.seq,projected.transaction_id)!=(event.id,event.seq,event.transaction_id):raise ProtocolError('event_projection_identity_mismatch')
            else:
                # Default output contains no unfiltered scenario payload. W02 installs a scoped projector.
                projected=PublicEvent.model_validate(event.model_dump(mode='json',exclude={'visible_to','data'})|{'data':{}})
            events.append(projected)
        public=PublicTransactionResult(transaction_id=result.transaction_id,boundary=result.boundary,executor=result.executor,state=PublicState.model_validate(public_state(result.state)),objects=tuple(x for x in result.objects if canonical(x) in visible),events=tuple(events),result=result.result if readable else {},replayed=result.replayed)
        return public.model_dump(mode='json')

    def run_job(self,name,payload,*,claim=None):
        from career_lab.jobs.worker import WorkerClaim
        if not isinstance(claim, WorkerClaim):raise ProtocolError('worker_claim_required',status=409)
        envelope=JobEnvelope.model_validate(payload)
        handler=self.registry.job_handlers.get(name)
        if handler is None:raise ProtocolError('module_unavailable',status=503)
        if envelope.operation!=name:raise ProtocolError('job_kind_invalid')
        from career_lab.jobs.repository import JobRepository
        import time
        leased=JobRepository(self.store.db).get(envelope.job_id)
        if (claim.job_id!=envelope.job_id or leased['kind']!=name or leased['payload']!=payload
                or leased['status']!='running' or leased['lease_until']<=time.time()
                or (leased['lease_token'],leased['worker_id'],leased['attempt'])!=(claim.lease_token,claim.worker_id,claim.attempt)):
            raise ProtocolError('worker_lease_lost',status=409)
        auth=self.store.guard_job(envelope.context,envelope.capability,check_context=False)
        prior=self.store.replay(auth,envelope.command,envelope.capability)
        if prior is not None:return self.public_result(auth,prior,self.registry.projector_for_action(envelope.command.operation))
        self.store.guard_job(envelope.context,envelope.capability,command=envelope.command)
        derived_subject=self.store.fixed_feedback_subject(envelope.command)
        plan=handler(self.store.job_view(auth,envelope.context,command=envelope.command),envelope,auth)
        # External calls can repeat on transient failure; deterministic failures stop.
        self.store.guard_job(envelope.context,envelope.capability,command=envelope.command)
        result=self.store.execute(auth,envelope.command,lambda *_:plan,capability=envelope.capability,worker_fence=claim,derived_subject=derived_subject,job_context=envelope.context)
        return self.public_result(auth,result,self.registry.projector_for_action(envelope.command.operation))


def make_step_result(transaction:TransactionResult,observation:Observation,step:ObservedStep,consumption:ActualConsumption,*,origin_request_id=None,model_attempts=()):
    point=VersionPoint(**transaction.state.model_dump(include={'business_seq','workspace_revision','storage_revision'}))
    if observation.as_of!=point or observation.actor!=transaction.executor:raise ProtocolError('step_observation_mismatch',status=409)
    if step.request_id!=transaction.boundary.request_id:raise ProtocolError('step_request_mismatch',status=409)
    origin=origin_request_id or transaction.boundary.request_id
    return StepResult(request_id=origin,effect_request_id=transaction.boundary.request_id if origin!=transaction.boundary.request_id else None,status='success',executor=transaction.executor,observation=observation,step=step,boundary=transaction.boundary,replayed=transaction.replayed,model_attempts=model_attempts,actual_consumption=consumption)
