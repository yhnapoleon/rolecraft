/** Controlled host fixture, loaded only by test-page.html?mode=v4-slot. Not a runtime or v4 product route. */
import type { V4HostAdapter, V4HostSnapshot, V4CommandResult } from '../../v4-host';
import type { ObjectRef, EvidenceRefV2 } from '../../contracts-v2';
import { mount as mountRole } from './v4-slot';
import { mount as mountRequests } from './v4-request-slot';
import { setPreference } from '../../app/i18n';
import { V4DataHost } from '../../v4-data-host';
const sid='w04-slot-fixture';
const reference=(kind:string,id:string,version=1)=>({schema_version:2,session_id:sid,kind,object_id:id,version}) as ObjectRef;
export async function start(root:HTMLElement,useRealHost=false){
  root.replaceChildren();
  root.innerHTML='<div class="rail-body"><div class="chat-head">Host colleague header / 技术负责人</div><div class="thread" data-role-id="tech_lead">OLD_PLACEHOLDER</div><form class="composer"><textarea id="chat-input" name="text" rows="2"></textarea><button type="submit" class="btn primary">Send</button></form></div><hr><div class="sheet-body"><div class="res-now">Host resource heading</div><form id="res-form" class="stack"><label><input type="radio" name="kind" value="request_capacity" checked>Capacity</label><label><input type="radio" name="kind" value="request_resources">Engineering</label><label class="field"><span>Reason</span><textarea name="reason" class="textarea" required></textarea></label><button type="submit" class="btn primary">Request</button></form><div id="resource-results"></div></div>';
  const legacy={inputs:0,submits:0};root.addEventListener('input',()=>{legacy.inputs++;});root.addEventListener('submit',event=>{event.preventDefault();legacy.submits++;});
  const thread=root.querySelector<HTMLElement>('.thread')!;const composer=root.querySelector<HTMLFormElement>('.composer')!;
  const form=root.querySelector<HTMLFormElement>('#res-form')!;const results=root.querySelector<HTMLElement>('#resource-results')!;
  const calls:any[]=[];const drafts=new Map<string,unknown>();const listeners=new Set<()=>void>();const rows:any[]=[];const receipts=new Map<string,V4CommandResult>();
  let seq=0;let point=0;let mode:'normal'|'unconfirmed'|'failed'='normal';let offline=false;let hold:()=>void=()=>{};let held=false;
  const resources={capacity:30,dev_days:3,deadline_day:7};
  let snapshot:V4HostSnapshot={session:{protocol:2,sessionId:sid,workLanguage:'zh',scenarioHash:'f'.repeat(64)},uiLanguage:'zh',state:'active',asOf:{business_seq:0,workspace_revision:0,storage_revision:0},currentTask:reference('task','task-a',3),currentProduct:reference('product','private-plan',3),busy:false,storageError:false,semantic:{roles:'waiting_model',feedback:'waiting_model',assistant:'waiting_model'},
    available:{timeline:true,'work_products.list':true,'turns.create':true,'turns.display':true,'jobs.refresh':true,actions:true,'approvals.resolve':true}};
  let realHost:V4DataHost|undefined;
  const emit=()=>{point++;snapshot={...snapshot,asOf:{business_seq:point,workspace_revision:point,storage_revision:point}};if(realHost)void realHost.query('workbench.read');else for(const listener of listeners)listener();};
  const row=(kind:string,id:string,content:any,version=1)=>({ref:reference(kind,id,version),content:{schema_version:2,id,session_id:sid,version,...content}});
  const latest=(kind:string,id:string)=>rows.filter(r=>r.ref.kind===kind&&r.ref.object_id===id).sort((a,b)=>b.ref.version-a.ref.version)[0];
  const controlled:V4HostAdapter={
    snapshot:()=>snapshot,subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},
    async query(op,input){calls.push(['query',op,input]);if(offline)throw Error('offline fixture');
      if(op==='timeline')return {schema_version:2,result:{role_mode:'local_reference',objects:structuredClone(rows),as_of:snapshot.asOf,workspace:{resources:{...resources},material_titles:{'public-guide:2':'试点准入说明'}}}};
      if(op==='work_products.list')return {result:{items:[{session_id:sid,product_id:'private-plan',version:3,content:'PRIVATE_DRAFT_V3'}],shares:[{session_id:sid,id:'shared-plan',version:1,recipient_role:'tech_lead',product:reference('product','private-plan',2),revoked_at:null}],sharing_complete:true,next_cursor:null,as_of:snapshot.asOf}};
      throw Error('Unknown fixture query');},
    async command(op,input){
      calls.push(['command',op,structuredClone(input)]);const action=op==='resolve_approval'?'approvals.resolve':op==='actions'?String(input.tool):op;const requestId='host-request-'+(++seq);const nextMode=mode;mode='normal';
      if(held)await new Promise<void>(resolve=>{hold=resolve;});
      let result:any={};
      if(nextMode==='failed'){const value:V4CommandResult={requestId,status:'failed',result:{}};receipts.set(requestId,value);return value;}
      if(action==='turns.create'){
        const id='turn-'+seq;rows.push(row('role_turn',id,{input:structuredClone(input)}));result={turn:reference('role_turn',id),question:input.text,role_id:input.role_id,status:'queued'};
      }else if(action==='turns.display'){
        rows.push(row('role_display','display-'+seq,{reply:input.ref}));result={display:reference('role_display','display-'+seq)};
      }else if(action==='request_business'){
        const id='request-'+seq;rows.push(row('business_request',id,{requested:input.terms,reason:input.reason,status:'pending'}));result={request:reference('business_request',id)};
      }else if(action==='approvals.resolve'||action==='accept_counteroffer'){
        const ref=input.request as ObjectRef;const previous=latest('business_request',ref.object_id);if(!previous||previous.ref.version!==ref.version)throw Error('stale fixture request');
        const accepted=action==='accept_counteroffer';const counter=!accepted&&Number(previous.content.requested.capacity)>60;
        const status=accepted?'accepted':counter?'countered':'approved';const terms=accepted?input.terms:previous.content.requested;
        const decision=row('business_decision','decision-'+seq,{request:previous.ref,status,granted:counter?{}:terms,countered:counter?{capacity:60}:{},reason:counter?'规则核实：可提供60个名额。':'规则核实：这些资源已批准。'});rows.push(decision);
        rows.push(row('business_request',ref.object_id,{...previous.content,status},ref.version+1));rows.at(-1).content.version=ref.version+1;
        if(!counter)Object.assign(resources,terms);result={decision:decision.content,request:rows.at(-1).ref};
      }else throw Error('Unknown fixture command');
      const value:V4CommandResult={requestId,status:action==='turns.create'?'pending':'confirmed',result};receipts.set(requestId,value);queueMicrotask(emit);
      return nextMode==='unconfirmed'?{requestId,status:'unconfirmed',result:{}}:value;
    },
    async recover(id){calls.push(['recover',id]);if(offline)throw Error('offline fixture');const value=receipts.get(id);if(!value)throw Error('Unknown request');return structuredClone(value);},
    async retry(id){calls.push(['retry',id]);const value=receipts.get(id);if(!value)throw Error('Unknown request');return structuredClone(value);},
    draft:<T>(slot:string,key:string)=>drafts.get(slot+':'+key) as T|undefined,
    async keepDraft(slot,key,value){drafts.set(slot+':'+key,structuredClone(value));},async flushDrafts(){},
    async openReference(ref){calls.push(['open',ref]);},async chooseEvidence(){return [{...reference('material','public-guide',2),observed_at_seq:0}] as EvidenceRefV2[];},
    selectTask(){},selectProduct(){},announce(message,kind){calls.push(['announce',message,kind]);},
  };
  const wire=new Map<string,{command:any;response:any}>();const storage=new Map<string,string>();
  const state=()=>({session_id:sid,status:snapshot.state,...snapshot.asOf});
  const json=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status});
  const fetcher:typeof fetch=async(url,init)=>{
    const path=new URL(String(url),'http://fixture.local').pathname;
    const base='/api/sessions/'+sid;
    if(!init?.body){
      calls.push(['http-read',path]);
      if(offline)throw Error('controlled transport loss');
      if(path===base)return json({schema_version:2,state:state()});
      if(path===base+'/workbench')return json({schema_version:2,result:{result:{session:snapshot.session,state:state(),as_of:snapshot.asOf,available:snapshot.available,semantic:snapshot.semantic}}});
      if(path.startsWith(base+'/requests/')){
        const id=decodeURIComponent(path.slice((base+'/requests/').length));const saved=wire.get(id);
        if(!saved)return json({schema_version:2,code:'request_not_found'},404);
        const turn=saved.response.result.turn;
        const completed=!turn||rows.some(r=>r.ref.kind==='role_reply'&&r.content.request.object_id===turn.object_id);
        return json({schema_version:2,session_id:sid,request_id:id,operation:saved.command.operation,read_only:true,status:completed?'completed':'pending',response:saved.response,jobs:turn?[{job_id:'job-'+turn.object_id,status:completed?'completed':'queued'}]:[]});
      }
      const operation=path===base+'/timeline'?'timeline':path===base+'/work-products'?'work_products.list':undefined;
      if(operation){const result:any=await controlled.query(operation);return json({schema_version:2,result});}
      return json({schema_version:2,code:'fixture_route_not_found'},404);
    }
    const command=JSON.parse(String(init.body));calls.push(['http-write',path,structuredClone(command)]);
    const result=await controlled.command(command.operation,command.payload);
    if(result.status==='failed')return json({schema_version:2,code:'fixture_rejected',detail:'Controlled validation rejection'},400);
    const stored=receipts.get(result.requestId)!;
    const response={schema_version:2,boundary:{request_id:command.request_id},state:state(),result:stored.result};
    wire.set(command.request_id,{command,response});
    if(result.status==='unconfirmed')throw Error('controlled lost response after server commit');
    return json(response);
  };
  let queue=Promise.resolve();
  const host:V4HostAdapter=useRealHost?(realHost=new V4DataHost({binding:snapshot.session as any,
    credentials:()=>({sessionId:sid,token:'fixture-session-token'}),storage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>{storage.set(key,value);}},
    uiLanguage:()=>snapshot.uiLanguage,openReference:controlled.openReference,chooseEvidence:controlled.chooseEvidence,announce:controlled.announce,fetcher,
    exclusive:<T>(_name:string,action:()=>Promise<T>):Promise<T>=>{const result=queue.then(action);queue=result.then(()=>{},()=>{});return result;},
  })):controlled;
  if(useRealHost)await host.query('workbench.read');
  let role=mountRole({host,nodes:{thread,composer}});let requests=mountRequests({host,nodes:{form,results}});
  Object.assign(window,{slotTest:{calls,drafts,rows,host,resources,storage,useRealHost,legacy,
    next(value:typeof mode){mode=value;},offline(value:boolean){offline=value;},hold(){held=true;},release(){held=false;hold();},
    complete(){const turn=[...rows].reverse().find(r=>r.ref.kind==='role_turn');if(!turn)throw Error('No turn');rows.push(row('role_reply','reply-'+turn.ref.object_id,{request:turn.ref,role_id:turn.content.input.role_id,question:turn.content.input.text,text:'[试点准入说明 · v2] 已保存来源版本。等待模型接入。',status:'completed'}));emit();},
    notify(){emit();},locale(lang:'zh'|'en'){setPreference(lang);snapshot={...snapshot,uiLanguage:lang};emit();},
    remount(){role.destroy();requests.destroy();role=mountRole({host,nodes:{thread,composer}});requests=mountRequests({host,nodes:{form,results}});},
    destroy(){role.destroy();requests.destroy();},switchSession(){snapshot={...snapshot,session:{protocol:2,sessionId:'other-session',workLanguage:'en',scenarioHash:'e'.repeat(64)}};emit();},
  }});
  document.querySelector('#fixture-description')!.textContent=useRealHost?'固定d34d695真实V4DataHost＋受控HTTP边界 · 非正式v4产品验收':'v4插槽受控host验证 · 非正式v4数据层或产品验收';
}
