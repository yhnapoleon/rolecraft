"""No arbitrary HTTP proxy: only the fixed public business routes are callable."""
import time,re,asyncio,json
from urllib.parse import quote
import httpx
from pydantic import ValidationError
from career_lab.contracts import v2 as C
from .catalog import ROUTES
from .credentials import load_credentials,redact


class RemoteFailure(Exception):
    def __init__(self,code,status=0):self.code,self.status=code,status;super().__init__(code)


def safe_id(value):
    if not isinstance(value,str) or not value or any(c in value for c in '/\\%\r\n') or value in {'.','..'}:raise RemoteFailure('route_object_invalid',422)
    return quote(value,safe='')


class HttpAgentClient:
    def __init__(self,config_path,*,timeout=15.0):
        if not 0<timeout<=30:raise ValueError('invalid timeout')
        self.config_path=config_path;self.timeout=timeout

    def _request(self,credentials,method,suffix,body=None,query=None,deadline=None,*,operation=None):
        url=credentials.api_url+'/sessions/'+safe_id(credentials.session_id)+suffix
        timeout=self.timeout if deadline is None else min(self.timeout,max(0.001,deadline-time.monotonic()))
        async def execute():
            async with asyncio.timeout(timeout):
                async with httpx.AsyncClient(timeout=timeout,follow_redirects=False,trust_env=False) as client:
                    async with client.stream(method,url,headers={'Authorization':'Bearer '+credentials.token},json=body,params=query) as response:
                        raw=bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw)>8_000_000:raise RemoteFailure('response_unconfirmed')
                        return response.status_code,bytes(raw)
        try:status,raw=asyncio.run(execute())
        except (httpx.HTTPError,TimeoutError):raise RemoteFailure('response_unconfirmed') from None
        try:value=json.loads(raw)
        except ValueError:raise RemoteFailure('response_unconfirmed') from None
        if not 200<=status<300:
            code=value.get('code') if isinstance(value,dict) else None
            if not isinstance(code,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,95}',code) or credentials.token in code:code='request_failed'
            raise RemoteFailure(code,status)
        if not isinstance(value,dict) or value.get('schema_version')!=2:raise RemoteFailure('response_unconfirmed')
        from .public_output import project_public_output
        return redact(project_public_output(value,operation=operation),credentials.token)

    def observation(self,session_id,query=None,*,credentials=None,deadline=None):
        credentials=credentials or load_credentials(self.config_path)
        if session_id!=credentials.session_id:raise RemoteFailure('session_route_mismatch',404)
        value=self._request(credentials,'GET','/observation',query=query or {},deadline=deadline)
        try:observation=C.Observation.model_validate(value['result'])
        except (KeyError,ValidationError):raise RemoteFailure('observation_contract_invalid') from None
        if observation.session_id!=session_id or observation.actor.kind!='external_agent':raise RemoteFailure('delegation_required',403)
        return observation

    def tools(self):
        credentials=load_credentials(self.config_path)
        return self.observation(credentials.session_id).tools

    def call(self,name,arguments,*,deadline=None):
        if not isinstance(arguments,dict):raise RemoteFailure('tool_arguments_invalid',422)
        credentials=load_credentials(self.config_path)
        if arguments.get('session_id')!=credentials.session_id:raise RemoteFailure('session_route_mismatch',404)
        observation=self.observation(credentials.session_id,credentials=credentials,deadline=deadline)
        tool=next((t for t in observation.tools if t.name==name),None)
        if tool is None:raise RemoteFailure('tool_unknown',404)
        if not tool.available:raise RemoteFailure(tool.unavailable_code or 'tool_unavailable',503)
        # Slot/action routing is internal. Public ToolSchema is not extended.
        operation=name if name in ROUTES else {'submit':'submissions.create','begin_revision':'revision_cycles'}.get(name,'actions')
        if operation not in ROUTES:raise RemoteFailure('tool_unavailable',503)
        route=ROUTES[operation]
        if route.method=='GET':
            if set(arguments)-{'session_id','query'}:raise RemoteFailure('tool_arguments_invalid',422)
            raw_query=arguments.get('query',{})
            if not isinstance(raw_query,dict):raise RemoteFailure('tool_arguments_invalid',422)
            payload=dict(raw_query);body=None
        else:
            if set(arguments)-{'session_id','command'}:raise RemoteFailure('tool_arguments_invalid',422)
            try:command=C.Command.model_validate(arguments['command'])
            except (KeyError,ValidationError):raise RemoteFailure('tool_arguments_invalid',422) from None
            if command.operation!=name:raise RemoteFailure('operation_route_mismatch',403)
            payload=command.payload;body=command.model_dump(mode='json')
            if operation=='work_products.versions.create':
                if payload.get('removed') or not self._editable_head(credentials,observation,payload,deadline):raise RemoteFailure('lifecycle_permission_unavailable',503)
                if (command.expected_version,command.expected_workspace_revision)!=(observation.as_of.business_seq,observation.as_of.workspace_revision):raise RemoteFailure('version_conflict',409)
        suffix=route.path
        for key in route.ids:
            if key not in payload:raise RemoteFailure('route_object_required',422)
            suffix=suffix.replace('{'+key+'}',safe_id(payload[key]))
        query={k:v for k,v in payload.items() if k not in route.ids and v is not None} if body is None else None
        return self._request(credentials,route.method,suffix,body,query,deadline,operation=name)

    def _editable_head(self,credentials,observation,payload,deadline=None):
        product_id=payload.get('product_id');head=next((p for p in observation.products if p.object_id==product_id),None)
        if head is None or payload.get('expected_head')!=head.version:return False
        # Read the exact version through the ordinary authorized version list.
        response=self._request(credentials,'GET','/work-products/'+safe_id(product_id)+'/versions',query={'cursor':0,'limit':100},deadline=deadline)
        try:page=response['result']['result'];rows=page['items']
        except (KeyError,TypeError):raise RemoteFailure('workspace_contract_invalid') from None
        current=next((p for p in rows if p.get('version')==head.version),None)
        # Never guess across a truncated history page; future DTO/endpoint by032.
        return current is not None and current.get('removed_at') is None

    def wait_request(self,session_id,request_id,*,seconds=5.0,interval=0.1):
        if not 0<=seconds<=30 or not 0.02<=interval<=1:raise ValueError('invalid wait budget')
        end=time.monotonic()+seconds;last=None
        while True:
            try:last=self.call('requests.read',{'session_id':session_id,'query':{'request_id':request_id}},deadline=end if seconds>0 else None)
            except RemoteFailure as error:
                if last is not None and error.code=='response_unconfirmed' and time.monotonic()>=end:return last
                raise
            if last.get('status') not in {'pending','needs_context'} or time.monotonic()>=end:return last
            if last.get('status')=='needs_context':return last
            time.sleep(min(interval,max(0,end-time.monotonic())))
