import { createGatewayTransport, type GatewayCredentials, type GatewayTransport } from './gateway-transport';
import { ApiError } from './api';
import { WorkspaceClient } from './features/workspace/client';
import { workspaceGatewayTransport } from './features/workspace/gateway-adapter';

export type Ref = { schema_version?: 2; session_id: string; kind: string; object_id: string; version: number; config_version?: number | null; [key:string]: any };
export type VerticalSession = GatewayCredentials & { createdAt: string; workLanguage: 'zh' };
type SavedRequest = { path:string; command:any; status:'pending'|'completed'|'rejected'; result?:any; error?:string };
const credentialsKey='rolecraft.live.workspace.v2.sessions';

/** One credential repository for v2. Legacy sessions are kept in their original
 * v1 store; credentials never enter feature drafts or exports. */
export class VerticalSessions {
  constructor(readonly storage: Storage) {}
  read(): { sessions:VerticalSession[]; active?:string } {
    const raw=this.storage.getItem(credentialsKey);
    if(!raw)return {sessions:[]};
    const value=JSON.parse(raw);
    if(value.schema!==2 || !Array.isArray(value.sessions) || !value.sessions.every((s:any)=>typeof s.sessionId==='string'&&typeof s.token==='string'&&s.workLanguage==='zh'))throw Error('无法读取会话凭据；请保留浏览器数据。');
    return value;
  }
  active() { const value=this.read();return value.sessions.find(s=>s.sessionId===value.active); }
  async create():Promise<VerticalSession> {
    return navigator.locks.request(credentialsKey,async()=>{
      const prior=this.read();this.storage.setItem(credentialsKey,JSON.stringify({schema:2,...prior}));
      const response=await fetch('/api/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({schema_version:2,scenario:'pm_pilot_v2'}),redirect:'error',signal:AbortSignal.timeout(20000)});
      const body=await response.json();
      if(!response.ok)throw new ApiError(body.error||'无法创建练习',response.status,body.code);
      if(body.schema_version!==2||!body.session_id||!body.token)throw Error('创建结果尚未确认，请保留本页。');
      const session:VerticalSession={sessionId:body.session_id,token:body.token,createdAt:new Date().toISOString(),workLanguage:'zh'};
      this.storage.setItem(credentialsKey,JSON.stringify({schema:2,sessions:[...prior.sessions,session],active:session.sessionId}));
      return session;
    });
  }
}

export class VerticalClient {
  readonly raw:GatewayTransport;
  readonly workspace:WorkspaceClient;
  state:any;
  timeline:any={objects:[]};
  materials:any[]=[];
  private listeners=new Set<()=>void>();
  constructor(readonly session:VerticalSession,readonly storage:Storage) {
    this.raw=createGatewayTransport(()=>session);
    this.workspace=new WorkspaceClient(session.sessionId,storage,workspaceGatewayTransport(this.raw));
  }
  subscribe(fn:()=>void) {this.listeners.add(fn);return ()=>{this.listeners.delete(fn);};}
  path(suffix:string) {return '/sessions/'+encodeURIComponent(this.session.sessionId)+suffix;}
  async get(suffix:string) {return this.raw(this.path(suffix)) as Promise<any>;}
  async page(suffix:string) {const value=await this.get(suffix);return value.result.result;}
  async refresh(notify=true) {
    const [state,timeline,materials]=await Promise.all([this.get(''),this.page('/timeline'),this.page('/materials')]);
    this.state=state.state;this.timeline=timeline;this.materials=materials.materials;
    const workspacePoint=this.workspace.snapshot().asOf;
    if(workspacePoint && (workspacePoint.business_seq!==this.state.business_seq || workspacePoint.workspace_revision!==this.state.workspace_revision))await this.workspace.refresh();
    if(notify)this.listeners.forEach(fn=>fn());
  }
  requestKey(id:string) {return 'rolecraft.v2.request.'+this.session.sessionId+'.'+id;}
  async command(path:string,operation:string,payload:any,id:string=crypto.randomUUID()):Promise<any> {
    return navigator.locks.request('rolecraft.v2.command.'+this.session.sessionId,async()=>{
      // A new user action gets the actual current boundary. Recovery below keeps
      // the original command unchanged and never silently sends a second POST.
      const existing=this.storage.getItem(this.requestKey(id));
      if(existing)return this.recover(id);
      const state=(await this.get('')).state;
      const command={schema_version:2,request_id:id,expected_version:state.business_seq,expected_workspace_revision:state.workspace_revision,operation,payload};
      const saved:SavedRequest={path,command,status:'pending'};
      this.storage.setItem(this.requestKey(id),JSON.stringify(saved));
      try {
        const result=await this.raw(this.path(path),command) as any;
        if(result.boundary?.request_id!==id)throw new ApiError('结果身份无法核对，请恢复原请求。',0,'response_unconfirmed');
        this.storage.setItem(this.requestKey(id),JSON.stringify({...saved,status:'completed',result}));
        try {await this.refresh();} catch { /* The committed result remains authoritative; explicit refresh can recover the view. */ }
        return result;
      } catch(error) {
        if(error instanceof ApiError && error.status>0)this.storage.setItem(this.requestKey(id),JSON.stringify({...saved,status:'rejected',error:error.code}));
        throw error;
      }
    });
  }
  async recover(id:string) {return this.get('/requests/'+encodeURIComponent(id));}
  async wait(id:string,onUpdate?:(value:any)=>void) {
    for(let i=0;i<40;i++) {
      const value=await this.recover(id);onUpdate?.(value);
      if(value.status!=='pending'){await this.refresh();return value;}
      await new Promise(resolve=>setTimeout(resolve,1000));
    }
    throw Error('后台仍在处理，问题已保存。请稍后恢复原请求。');
  }
  async read(ref:Ref) {
    if(ref.session_id!==this.session.sessionId)throw Error('引用不属于当前练习。');
    if(ref.kind==='material' && this.state?.status==='active') {
      const result=await this.command('/actions','read_material',{tool:'read_material',material:this.bare(ref)});
      this.keepEvidence(result.result.fragments);
      return {ref,content:{fragments:result.result.fragments}};
    }
    const query=ref.config_version==null?'':'?config_version='+ref.config_version;
    const value=await this.get('/objects/'+encodeURIComponent(ref.kind)+'/'+encodeURIComponent(ref.object_id)+'/'+ref.version+query);
    if(ref.kind==='material')this.keepEvidence(value.content.fragments);return value;
  }
  private keepEvidence(fragments:any[]) {const previous:any[]=JSON.parse(this.draft('evidence-cache','[]'));const values=new Map(previous.map(r=>[JSON.stringify(r),r]));for(const f of fragments??[])if(f.ref?.quote)values.set(JSON.stringify(f.ref),f.ref);this.keep('evidence-cache',JSON.stringify([...values.values()]));}
  bare(ref:Ref) {return {schema_version:2,session_id:ref.session_id,kind:ref.kind,object_id:ref.object_id,version:ref.version,config_version:ref.config_version??null};}
  ref(kind:string,id:string,version=1):Ref {return {schema_version:2,session_id:this.session.sessionId,kind,object_id:id,version,config_version:null};}
  objects(kind:string) {return this.timeline.objects.filter((r:any)=>r.ref.kind===kind);}
  draftKey(name:string) {return 'rolecraft.v2.draft.'+this.session.sessionId+'.'+name;}
  draft(name:string,fallback='') {return this.storage.getItem(this.draftKey(name))??fallback;}
  keep(name:string,value:string) {this.storage.setItem(this.draftKey(name),value);}
}
