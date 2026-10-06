"""Single-attempt provider port. Adapters own transport; no hidden retries or credentials."""
from datetime import datetime,timezone
from typing import Protocol, Callable, Literal
import time
import math
import json
from pydantic import ValidationError
from .core import *

class ProviderMessage(V2):
    role: Literal['system','user','assistant','tool']
    content: str
    tool_call_id: str | None = None

class ProviderTool(V2):
    name: Identifier
    description: str
    parameters: dict[str,JsonValue]

class ProviderRequest(V2):
    request_id: Identifier
    attempt_id: Identifier
    provider: Identifier
    model_revision: Identifier
    prompt_revision: Identifier
    messages: tuple[ProviderMessage,...]
    tools: tuple[ProviderTool,...] = ()
    tools_digest: Hash
    deadline: Timestamp
    output_limit: PositiveInt
    seed: NonNegativeInt | None = None
    decode: dict[str,JsonValue] = {}
    @model_validator(mode='after')
    def tool_identity(self):
        if digest([t.model_dump(mode='json') for t in self.tools])!=self.tools_digest:raise ValueError('tools digest mismatch')
        return self

class ProviderCapabilities(V2):
    seed_supported: bool
    decode_parameters: tuple[str,...]
    max_output_tokens: PositiveInt

class ProviderReply(V2):
    provider: Identifier
    model_revision: Identifier
    text: str
    tool_calls: tuple[dict[str,JsonValue],...] = ()
    input_tokens: NonNegativeInt | None = None
    output_tokens: NonNegativeInt | None = None
    cost: Annotated[float,Field(ge=0)] | None = None

class ProviderReceipt(V2):
    raw_response: JsonValue | None = None
    received_text: str | None = None
    actual_provider: str | None = None
    actual_model_revision: str | None = None
    input_tokens: NonNegativeInt | None = None
    output_tokens: NonNegativeInt | None = None
    cost: Annotated[float,Field(ge=0)] | None = None
    validation_errors: tuple[str,...] = ()


def received_receipt(raw):
    value=raw.model_dump(mode='json') if isinstance(raw,ProviderReply) else raw
    try:
        # A detached JSON copy cannot later be mutated by a transport callback.
        saved=json.loads(json.dumps(value,ensure_ascii=False,allow_nan=False))
    except (TypeError,ValueError):saved=None
    data=value if isinstance(value,dict) else {}
    def identity(key):
        v=data.get(key)
        return v.strip() if isinstance(v,str) and v.strip() else None
    def tokens(key):
        v=data.get(key)
        return v if type(v) is int and v>=0 else None
    cost=data.get('cost')
    cost=float(cost) if type(cost) in {int,float} and math.isfinite(cost) and cost>=0 else None
    return ProviderReceipt(raw_response=saved,received_text=data.get('text') if isinstance(data.get('text'),str) else None,actual_provider=identity('provider'),actual_model_revision=identity('model_revision'),input_tokens=tokens('input_tokens'),output_tokens=tokens('output_tokens'),cost=cost)

class ProviderResult(V2):
    request_id: Identifier
    status: Literal['success','unavailable','invalid','timeout','failed']
    expected_provider: Identifier | None = None
    expected_model_revision: Identifier | None = None
    received: ProviderReceipt | None = None
    reply: ProviderReply | None = None
    attempts: tuple[ModelAttemptUsage,...] = Field(max_length=1)
    error_code: str | None = None

class ProviderPort(Protocol):
    def call(self, request:ProviderRequest) -> ProviderResult: ...

class SingleAttemptProvider:
    """Transport must honor remaining_seconds; actual supplier validation is separate."""
    def __init__(self,provider,revision,capabilities:ProviderCapabilities,transport:Callable):
        self.provider,self.revision,self.capabilities,self.transport=provider,revision,capabilities,transport
    def call(self,request):
        request=ProviderRequest.model_validate(request.model_dump(mode='json'))
        remaining=(request.deadline-datetime.now(timezone.utc)).total_seconds()
        error=None
        if remaining<=0:error='provider_deadline_exceeded'
        elif (request.provider,request.model_revision)!=(self.provider,self.revision):error='provider_identity_mismatch'
        elif request.output_limit>self.capabilities.max_output_tokens:error='provider_output_limit_unsupported'
        elif request.seed is not None and not self.capabilities.seed_supported:error='provider_seed_unsupported'
        elif set(request.decode)-set(self.capabilities.decode_parameters):error='provider_decode_unsupported'
        if error:return ProviderResult(request_id=request.request_id,status='timeout' if remaining<=0 else 'unavailable',attempts=(),error_code=error,expected_provider=self.provider,expected_model_revision=self.revision)
        started=time.monotonic();reply=None;received=None;status='success';error=None
        try:
            raw=self.transport(request,remaining) # exactly one invocation; no provider retry loop here
            received=received_receipt(raw)
            reply=ProviderReply.model_validate(raw.model_dump(mode='json') if isinstance(raw,ProviderReply) else raw)
            if (reply.provider,reply.model_revision)!=(self.provider,self.revision):status,error='invalid','provider_identity_mismatch'
            elif reply.output_tokens is not None and reply.output_tokens>request.output_limit:status,error='invalid','provider_output_limit_exceeded'
        except ValidationError as exc:
            status,error='invalid','provider_response_invalid'
            if received is not None:
                received=received.model_copy(update={'validation_errors':tuple('.'.join(map(str,x['loc']))+':'+x['type'] for x in exc.errors())})
                if received.actual_provider is None or received.actual_model_revision is None:error='provider_identity_missing'
        except TimeoutError:status,error='timeout','provider_timeout'
        except Exception:status,error='failed','provider_call_failed'
        elapsed=time.monotonic()-started
        if elapsed>remaining:status,error='timeout','provider_deadline_exceeded'
        known=received is not None and received.input_tokens is not None and received.output_tokens is not None
        attempt=ModelAttemptUsage(request_id=request.request_id,attempt_id=request.attempt_id,
            expected_provider=self.provider,expected_model_revision=self.revision,
            provider=received.actual_provider if received else None,
            model_revision=received.actual_model_revision if received else None,
            status='success' if status=='success' else ('timeout' if status=='timeout' else 'failed'),
            input_tokens=received.input_tokens if received else None,output_tokens=received.output_tokens if received else None,
            cost=received.cost if received else None,elapsed_seconds=elapsed,usage_known=known)
        return ProviderResult(request_id=request.request_id,status=status,reply=reply,received=received,
            expected_provider=self.provider,expected_model_revision=self.revision,attempts=(attempt,),error_code=error)
