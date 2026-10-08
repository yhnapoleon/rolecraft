"""MCP 2026-07-28 stateless tools, plus explicit 2025-11-25 compatibility.

Only tools/discovery/ping are advertised. No sampling, execution, roots, resource
fetch, tasks extension or server-initiated requests. Business identity is never
inferred from clientInfo or JSON-RPC IDs.
"""
import json,re
from pydantic import ValidationError
from career_lab.delegations.http_client import RemoteFailure

MODERN='2026-07-28';LEGACY='2025-11-25'
VERSION='io.modelcontextprotocol/protocolVersion'
CAPABILITIES='io.modelcontextprotocol/clientCapabilities'
SERVER='io.modelcontextprotocol/serverInfo'
INFO={'name':'rolecraft-workspace','version':'w06-development-1'}


class RpcFailure(Exception):
    def __init__(self,code,message,data=None):self.code,self.message,self.data=code,message,data


class Protocol:
    def __init__(self,backend):self.backend=backend;self.legacy_version=None;self.initialized=False

    def _metadata(self,request):
        params=request.get('params',{})
        if not isinstance(params,dict):raise RpcFailure(-32602,'Invalid params')
        meta=params.get('_meta',{})
        if not isinstance(meta,dict):raise RpcFailure(-32602,'Invalid metadata')
        if VERSION in meta:
            version=meta[VERSION]
            if not isinstance(version,str):raise RpcFailure(-32602,'Invalid protocol version')
            if version!=MODERN:raise RpcFailure(-32022,'Unsupported protocol version',{'supported':[MODERN]})
            if CAPABILITIES not in meta or not isinstance(meta[CAPABILITIES],dict):raise RpcFailure(-32602,'Missing per-request client capabilities')
            return MODERN,{k:v for k,v in params.items() if k!='_meta'}
        if self.legacy_version and self.initialized:return LEGACY,{k:v for k,v in params.items() if k!='_meta'}
        raise RpcFailure(-32602,'Modern requests require per-request version and capabilities; legacy clients must initialize')

    def _result(self,result,version,*,cache=False):
        if version==MODERN:
            result={'resultType':'complete',**result,'_meta':{SERVER:INFO}}
            if cache:result.update(ttlMs=0,cacheScope='private')
        return result

    def handle(self,request):
        if not isinstance(request,dict) or request.get('jsonrpc')!='2.0' or not isinstance(request.get('method'),str):raise RpcFailure(-32600,'Invalid request')
        if 'id' not in request:return self.notification(request)
        if type(request['id']) not in (str,int):raise RpcFailure(-32600,'Invalid request ID')
        method=request['method'];params=request.get('params',{})
        if method=='initialize':
            if self.legacy_version is not None:raise RpcFailure(-32600,'Already initialized')
            if not isinstance(params,dict) or not isinstance(params.get('protocolVersion'),str) or not isinstance(params.get('capabilities'),dict) or not isinstance(params.get('clientInfo'),dict) or any(not isinstance(params['clientInfo'].get(k),str) for k in ('name','version')):raise RpcFailure(-32602,'Invalid initialize params')
            self.legacy_version=LEGACY
            return {'protocolVersion':LEGACY,'capabilities':{'tools':{}},'serverInfo':INFO,
                'instructions':'Only explicitly delegated RoleCraft operations. JSON-RPC id is not the business request_id.'}
        version,params=self._metadata(request)
        if method=='server/discover':
            if params:raise RpcFailure(-32602,'Discovery accepts metadata only')
            return self._result({'supportedVersions':[MODERN,LEGACY],'capabilities':{'tools':{}},
                'instructions':'Every business call must carry session_id. Keep command.request_id unchanged after an unknown result.'},version,cache=True)
        if method=='ping':return self._result({},version)
        if method=='tools/list':
            if set(params)-{'cursor'}:raise RpcFailure(-32602,'Invalid tool-list params')
            cursor=params.get('cursor','0')
            if not isinstance(cursor,str) or not re.fullmatch(r'0|[1-9][0-9]{0,5}',cursor):raise RpcFailure(-32602,'Invalid cursor')
            tools=sorted((t for t in self.backend.tools() if t.available),key=lambda t:t.name)
            start=int(cursor)
            if start>len(tools):raise RpcFailure(-32602,'Invalid cursor')
            result={'tools':[{'name':t.name,'description':'Authorized RoleCraft '+t.capability+' operation. Existing server permissions and business rules apply. Preserve exact citation kind, object_id and version. config_version belongs only on kind=config references; omit it on material/test/product references. After an unknown result, read requests.read; re-execution requires an explicit user decision.',
                'inputSchema':t.parameters,'annotations':{'readOnlyHint':t.capability=='read','openWorldHint':False}} for t in tools[start:start+50]]}
            if start+50<len(tools):result['nextCursor']=str(start+50)
            return self._result(result,version,cache=True)
        if method=='tools/call':
            if set(params)-{'name','arguments'} or not isinstance(params.get('name'),str) or not isinstance(params.get('arguments',{}),dict):raise RpcFailure(-32602,'Invalid tool-call params')
            name=params['name'];known={t.name for t in self.backend.tools()}
            if name not in known:raise RpcFailure(-32602,'Unknown tool')
            try:
                result=self.backend.call(name,params.get('arguments',{}))
                return self._result({'content':[{'type':'text','text':json.dumps(result,ensure_ascii=False,separators=(',',':'))}],
                    'structuredContent':result,'isError':False},version)
            except RemoteFailure as error:
                return self._result({'content':[{'type':'text','text':error.code}],
                    'structuredContent':{'code':error.code,'status':error.status,'retry_rule':'Recover the original request read-only. Re-execution requires an explicit user decision; never mint a new request_id to replace an unknown result.'},'isError':True},version)
            except ValidationError:
                return self._result({'content':[{'type':'text','text':'tool_arguments_invalid'}],'isError':True},version)
        raise RpcFailure(-32601,'Method not supported')

    def notification(self,request):
        if request['method']=='notifications/initialized' and self.legacy_version:self.initialized=True
        return None
