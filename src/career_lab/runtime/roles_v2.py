"""Public role utterances, private generation plans and common-worker handlers."""
from time import monotonic
from dataclasses import replace
import math
import httpx
from uuid import uuid4

from pydantic import ValidationError
from career_lab.api.modules import Operation
from career_lab.contracts.v2 import (
    Command, DisclosureRecord, EvidenceRefV2, ModelAttemptUsage, ObjectRead,
    ObjectRef, ProtocolError, ProviderMessage, RoleContext, TurnInput, digest,
)
from career_lab.contracts.v2.projection import project_disclosures
from career_lab.runtime.context_v2 import ContextPort, clean_ref, internal_alias_in, role_text, require_work_language, ROLE_PROMPT_REVISION
from career_lab.runtime.model_adapter import ModelReply
from career_lab.storage.role_memory import (
    PrivateGeneration, PublicSpokenEvidence, RoleStanceEvidence, RoleTurn, RoleReply, RoleDisplay,
    object_write, parse_public_reply, resolve_stance,
)
from career_lab.storage.v2_lifecycle import point
from career_lab.storage.v2_store import JobRequest, Mutation


class RoleModelTransient(ProtocolError):
    def __init__(self, code):
        self.error_code=code
        super().__init__(code,"role model temporarily unavailable",status=503)


class LocalRoleModel:
    """Offline example only; continuity must be in context, never this model's echo."""
    revision="w04-local-extractive-v3"
    retries=0
    def complete(self,messages,tools):
        import json
        ctx=json.loads(messages[0]["content"].split("\nCONTEXT\n",1)[1])
        language=require_work_language(ctx.get('work_language'))
        separator='; ' if language=='en' else '；'
        lines=[role_text(language,'local_mode'), role_text(language,'responsibilities')+separator.join(ctx['responsibilities'])]
        for source in ctx['sources'][:4]:lines.append(f"[{source['display_name']}] {source['text']}")
        if ctx['omissions']['learner_scope']:lines.append(role_text(language,'scope_omitted'))
        lines.append(role_text(language,'discussion_only'))
        return ModelReply(text="\n".join(lines))


def actual_disclosures(snapshot,auth,reply_ref,text,*,included_sources=None):
    """Internal fact/source mapping; not learner-readable, never display by default."""
    selected=snapshot.generation_sources(auth) if included_sources is None else included_sources
    return tuple(DisclosureRecord(fact_id=fid,source=clean_ref(source.ref),reply_ref=reply_ref,
                 quote=source.text,verification="verified",displayed_at_seq=None)
                 for source in selected if source.text and source.text in text for fid in source.fact_ids)


def actual_opinions(snapshot,reply_ref,text):
    """Match actually spoken declared stances, without asserting world truth/G0."""
    if snapshot.source_binding is None:raise ProtocolError("role_stance_source_unavailable",status=409)
    return tuple(RoleStanceEvidence(snapshot.role.id,reply_ref,snapshot.source_binding,field,index,quote)
        for field in ("responsibilities","goals","acceptable_conditions","unacceptable_conditions")
        for index,quote in enumerate(getattr(snapshot.role,field)) if quote and quote in text)


def displayed_disclosures(reply,reply_ref,*,displayed_at_seq):
    # Public provenance is the actual utterance. The private audit alone maps this
    # utterance to underlying materials and fact IDs.
    source=EvidenceRefV2(**reply_ref.model_dump(),observed_at_seq=reply.as_of.business_seq)
    records=tuple(DisclosureRecord(fact_id=x.label,source=source,reply_ref=reply_ref,quote=x.quote,
                  verification=x.verification,displayed_at_seq=displayed_at_seq) for x in reply.spoken_evidence)
    return project_disclosures(reply.text,records,session_id=reply.session_id,as_of_seq=displayed_at_seq)


def record_reply_display(view,command,auth):
    body=ObjectRead.model_validate(command.payload)
    if body.ref.kind!="role_reply" or body.as_of is not None:raise ProtocolError("reply_display_invalid")
    reply=parse_public_reply(view.get(body.ref).content)
    if reply.status!="completed":raise ProtocolError("reply_unavailable",status=409)
    display=RoleDisplay(id="display-"+digest([auth.session_id,command.request_id])[:24],
             session_id=auth.session_id,reply=body.ref,as_of=point(view.state),executor=auth.executor)
    write=object_write("role_display",display)
    return Mutation(writes=(write,),result={"display":write.ref.model_dump(mode="json"),
        "disclosures":[x.model_dump(mode="json") for x in displayed_disclosures(reply,body.ref,displayed_at_seq=view.state.business_seq)]})


def _usage(raw,key):
    values=raw.usage if isinstance(raw,ModelReply) else raw.get('usage',{}) if isinstance(raw,dict) else {}
    value=values.get(key) if isinstance(values,dict) else None
    return value if type(value) is int and value>=0 else None


def generate_plan(snapshot,auth,request,reply_ref,model,*,generation_cycle=None,refresh_count=0,
                  max_context_chars=24000,record_attempt,stance_verifier=None,stance_producer=None,begin_call=None):
    """One model invocation. The caller supplies W01's protected attempt sink."""
    if (request.session_id!=auth.session_id or request.executor!=auth.executor
        or snapshot.context.role_id!=request.input.role_id or reply_ref.kind!='role_reply'
        or reply_ref.session_id!=auth.session_id):raise ProtocolError("role_generation_identity_invalid",status=403)
    if snapshot.source_binding is None:raise ProtocolError("role_stance_source_unavailable",status=409)
    require_work_language(snapshot.work_language)
    if getattr(model,'retries',0):raise ProtocolError("role_provider_retry_budget_uncontrolled",status=409)
    stance=snapshot.stance_state;resolutions=[]
    if stance is None:raise ProtocolError('role_stance_context_invalid',status=409)
    proposals=snapshot.stance_proposals
    if stance_producer is not None:
        if getattr(stance_producer,'retries',0)!=0:raise ProtocolError('role_provider_retry_budget_uncontrolled',status=409)
        proposals=(*proposals,*stance_producer.propose(snapshot,auth,request,
            record_attempt=record_attempt,begin_call=begin_call))
    for proposal in proposals:
        resolution=resolve_stance(stance,proposal,snapshot.stance_facts,snapshot.context.as_of,stance_verifier,
            before_check=(lambda verifier,p:begin_call('stance_support:'+p.id,getattr(verifier,'revision',type(verifier).__name__))) if begin_call else None)
        resolutions.append(resolution);stance=resolution.state
    effective=replace(snapshot,stance_state=stance,question=request.input.text)
    messages,omitted,source_aliases=effective.build_prompt(auth,max_chars=max_context_chars)
    if begin_call is not None:begin_call("role_reply",model.revision)
    started=monotonic();raw=None;status="success";error=None
    try:
        raw=model.complete(messages,[])
        response=ModelReply.model_validate(raw.model_dump(mode="json") if isinstance(raw,ModelReply) else raw)
        if response.tool_calls or not response.text.strip():raise ValueError("invalid role response")
    except (TimeoutError,httpx.TimeoutException):
        status,error="timeout","role_model_timeout"
    except (ValidationError,ValueError,TypeError):
        status,error="failed","role_model_invalid"
    except Exception:
        status,error="failed","role_model_transport"
    if error is None:
        private_ids={f.id for f in snapshot.private_facts if f.disclosure.mode!='public'}
        private_metadata=('prompt_messages','prompt_fact_ids','context_hash','acceptable_conditions','unacceptable_conditions')
        if (snapshot.scrub(response.text)!=response.text or snapshot.has_private_identifier(response.model_dump(mode='json')) or internal_alias_in(response.text)
            or any(fid in response.text for fid in private_ids)
            or messages[0]['content'] in response.text or any(key in response.text for key in private_metadata)):
            status,error="failed","role_output_blocked"
    input_tokens,output_tokens=_usage(raw,'prompt_tokens'),_usage(raw,'completion_tokens')
    usage=raw.usage if isinstance(raw,ModelReply) else raw.get('usage',{}) if isinstance(raw,dict) else {}
    cost=usage.get('cost') if isinstance(usage,dict) else None
    cost=float(cost) if type(cost) in {int,float} and math.isfinite(cost) and cost>=0 else None
    attempt=ModelAttemptUsage(request_id=request.id,attempt_id=uuid4().hex,
        expected_model_revision=model.revision,provider=None,model_revision=None,status=status,
        input_tokens=input_tokens,output_tokens=output_tokens,cost=cost,elapsed_seconds=monotonic()-started,
        usage_known=input_tokens is not None and output_tokens is not None)
    # Failure/timeout usage (including unknown) is recorded before propagating.
    record_attempt(attempt,error)
    if error in {'role_output_blocked','role_model_invalid'}:raise ProtocolError(error,status=422)
    if error is not None:raise RoleModelTransient(error)
    selected,_=snapshot.select_sources(auth,max_context_chars)
    internal=actual_disclosures(snapshot,auth,reply_ref,response.text,included_sources=selected)
    public=tuple(PublicSpokenEvidence(label=f"utterance-{i+1}",quote=x.quote,verification=x.verification)
                 for i,x in enumerate(internal))
    reply=RoleReply(id=reply_ref.object_id,session_id=auth.session_id,role_id=request.input.role_id,
        request=ObjectRef(session_id=auth.session_id,kind="role_turn",object_id=request.id,version=request.version),
        question=request.input.text,text=response.text,status="completed",as_of=snapshot.context.as_of,
        executor=auth.executor,origin_cycle=request.origin_cycle,generation_cycle=generation_cycle,
        spoken_evidence=public,omission_count=len(omitted)+snapshot.permission_omissions(auth))
    context=snapshot.context.model_copy(update={'actual_disclosures':internal})
    private=PrivateGeneration(role_id=reply.role_id,reply_ref=reply_ref,context=context,
        prompt_messages=tuple(ProviderMessage.model_validate(m) for m in messages),prompt_hash=digest(messages),
        history_revision=snapshot.history_revision,received_shares=snapshot.received_shares,
        memories=snapshot.memories,refresh_count=refresh_count,attempts=(attempt,),used_sources=selected,
        opinions=actual_opinions(snapshot,reply_ref,response.text),source_aliases=source_aliases,
        stance_state=stance,stance_resolutions=tuple(resolutions),
        work_language=snapshot.work_language,prompt_template_revision=ROLE_PROMPT_REVISION)
    # The question is immutable learner-authored input, not generated disclosure.
    # All generated fields still pass the guard; do not selectively redact input.
    snapshot.require_public(reply.model_dump(mode="json",exclude={'question'}))
    return reply,private


class RoleService:
    def __init__(self,context_port,model=None,*,max_context_chars=24000,private_port=None,stance_verifier=None,stance_producer=None):
        self.port,self.model=context_port,model or LocalRoleModel()
        self.max_context_chars,self.private_port=max_context_chars,private_port
        self.stance_verifier,self.stance_producer=stance_verifier,stance_producer

    def enqueue(self,view,command,auth):
        turn=TurnInput.model_validate(command.payload)
        _,heads=self.port.validate_request(view,auth,turn)
        request=RoleTurn(id="turn-"+digest([auth.session_id,command.request_id])[:24],session_id=auth.session_id,
             input=turn,as_of=point(view.state),executor=auth.executor,
             origin_cycle=view.current_cycle.ref if view.current_cycle else None)
        write=object_write("role_turn",request)
        job=Command(schema_version=2,request_id="role-effect-"+digest(command)[:24],
            expected_version=command.expected_version,expected_workspace_revision=command.expected_workspace_revision,
            operation="turns.create",payload={"subject":write.ref.model_dump(mode="json")})
        return Mutation(writes=(write,),jobs=(JobRequest(name="v2.role_turn",command=job,sources=(write.ref,*turn.shares),
            context_hash=digest(request),head_dependencies=heads),),
            result={"turn":write.ref.model_dump(mode="json"),"status":"queued",
                    "question":turn.text,"role_id":turn.role_id,"executor":auth.executor.model_dump(mode="json")})

    def generate(self,view,envelope,auth):
        if self.private_port is None:raise ProtocolError("role_private_storage_unavailable",status=409)
        self.private_port.require_available()
        ref=ObjectRef.model_validate(envelope.command.payload['subject'])
        if ref.kind!='role_turn':raise ProtocolError("role_subject_invalid")
        request=RoleTurn.model_validate(view.get(ref).content)
        if request.executor!=auth.executor:raise ProtocolError("role_executor_mismatch",status=403)
        snapshot=self.port.capture(view,auth,request.input,as_of=envelope.context.as_of)
        reply_ref=ObjectRef(session_id=auth.session_id,kind='role_reply',object_id="reply-"+digest([auth.session_id,envelope.origin_request_id])[:24],version=1)
        claim=getattr(self.private_port,'claim_model_call',None)
        if claim is None and (type(self.model) is not LocalRoleModel or self.stance_producer is not None or self.stance_verifier is not None):
            raise ProtocolError('role_attempt_guard_unavailable',status=409)
        def begin_call(phase,revision):
            # The common port owns a durable at-most-once claim per explicit user
            # retry cycle. Worker leases, HTTP recovery and restarts cannot renew it.
            if claim is not None and claim(envelope,auth,phase,revision) is not True:
                raise ProtocolError('role_model_call_already_claimed',status=409)
        reply,private=generate_plan(snapshot,auth,request,reply_ref,self.model,
            generation_cycle=view.current_cycle.ref if view.current_cycle else None,
            refresh_count=envelope.context.refresh_count,max_context_chars=self.max_context_chars,
            record_attempt=lambda attempt,error:self.private_port.record_attempt(envelope,auth,attempt,error),stance_verifier=self.stance_verifier,
            stance_producer=self.stance_producer,begin_call=begin_call)
        # Only official RoleContext carrier(s) are accepted; do not install a new
        # private kind or conceal a prompt in a learner-readable DTO.
        private_writes=self.private_port.prepare(view,envelope,auth,private)
        if not private_writes:raise ProtocolError("role_private_audit_incomplete",status=409)
        for write in private_writes:
            if write.ref.kind!='role_context' or set(write.visible_to)!={'system',request.input.role_id}:
                raise ProtocolError("role_private_audit_invalid",status=403)
            internal=RoleContext.model_validate(write.content)
            if internal.role_id!=request.input.role_id:raise ProtocolError("role_private_audit_invalid",status=403)
        write=object_write('role_reply',reply,visible_to=('learner',request.input.role_id))
        return Mutation(writes=(write,*private_writes),result={"reply":reply_ref.model_dump(mode='json'),
            "role_id":reply.role_id,"text":reply.text,"question":reply.question,"status":"completed",
            "executor":auth.executor.model_dump(mode='json'),"disclosures":[],"display_ack_required":True,
            "omission_count":reply.omission_count})

    def install(self,registry):
        registry.register(Operation('turns.create','act',TurnInput,self.enqueue))
        registry.register_job('v2.role_turn',self.generate)


def create_role_service(store,catalog,model=None,*,snapshot_port=None,private_port=None,language_port=None,stance_verifier=None,stance_producer=None):
    from career_lab.storage.role_memory import install_role_storage
    install_role_storage(store)
    return RoleService(ContextPort(catalog,snapshot_port,language_port=language_port),model,private_port=private_port,
        stance_verifier=stance_verifier,stance_producer=stance_producer)


class ModelStanceProducer:
    """Optional one-call proposal extraction. Never a support verifier or approval.

    The factory must explicitly install a provider with retries=0. The default
    local service has no producer and makes no additional model calls.
    """
    retries=0
    def __init__(self,model):
        if getattr(model,'retries',0)!=0:raise ProtocolError('role_provider_retry_budget_uncontrolled',status=409)
        self.model=model

    def propose(self,snapshot,auth,request,*,record_attempt,begin_call=None):
        import json
        from career_lab.storage.role_memory import StanceProposal,StanceBasisRef
        if getattr(self.model,'retries',0)!=0:raise ProtocolError('role_provider_retry_budget_uncontrolled',status=409)
        messages,_,_=replace(snapshot,question=request.input.text).build_prompt(auth)
        # Exact fact identities stay server-side; indices map only selected sources.
        selected,_=snapshot.select_sources(auth,24000)
        facts=tuple(f for f in snapshot.stance_facts if any(clean_ref(s.ref)==clean_ref(f.source) for s in selected))
        allowed=[{'index':i,'text':next(s.text for s in selected if clean_ref(s.ref)==clean_ref(f.source))} for i,f in enumerate(facts)]
        positions=[{'key':p.key,'text':p.text} for p in snapshot.stance_state.positions]
        messages=[*messages,{'role':'user','content':json.dumps({'task':
            'Extract at most one proposed change; this does not approve it. Return JSON null if none. Otherwise return exactly position_key, proposed_text, basis_indices, reason. Use the bound work language; preserve original source quotations. Never invent facts.',
            'work_language':snapshot.work_language,'positions':positions,'basis':allowed},ensure_ascii=False)}]
        if begin_call is not None:begin_call('stance_proposal',self.model.revision)
        started=monotonic();raw=None;error=None
        try:
            raw=self.model.complete(messages,[])
            response=ModelReply.model_validate(raw.model_dump(mode='json') if isinstance(raw,ModelReply) else raw)
            if response.tool_calls:raise ValueError('tool response')
            value=json.loads(response.text)
            if value is None:result=()
            else:
                if not isinstance(value,dict) or set(value)!={'position_key','proposed_text','basis_indices','reason'}:raise ValueError('shape')
                if any(type(value[k]) is not str for k in ('position_key','proposed_text','reason')):raise ValueError('text')
                indices=value['basis_indices']
                if not isinstance(indices,list) or any(type(i) is not int or not 0<=i<len(facts) for i in indices):raise ValueError('basis')
                from career_lab.runtime.context_v2 import bare
                result=(StanceProposal('stance-'+digest([request.id,value])[:24],auth.session_id,snapshot.role.id,
                    snapshot.stance_state.revision,value['position_key'],value['proposed_text'],
                    tuple(StanceBasisRef(facts[i].fact_id,bare(facts[i].source)) for i in dict.fromkeys(indices)),
                    snapshot.context.as_of,value['reason']),)
        except (TimeoutError,httpx.TimeoutException):error='role_stance_producer_timeout'
        except Exception:error='role_stance_producer_invalid'
        attempt=ModelAttemptUsage(request_id=request.id,attempt_id=uuid4().hex,expected_model_revision=self.model.revision,provider=None,model_revision=None,
            status='timeout' if error=='role_stance_producer_timeout' else 'failed' if error else 'success',
            input_tokens=_usage(raw,'prompt_tokens'),output_tokens=_usage(raw,'completion_tokens'),elapsed_seconds=monotonic()-started,
            usage_known=_usage(raw,'prompt_tokens') is not None and _usage(raw,'completion_tokens') is not None)
        record_attempt(attempt,error)
        if error:raise ProtocolError(error,status=422)
        return result
