/** Test fixture, not a production entry or a real RoleCraft backend. */
import { createRoot } from 'react-dom/client';
import { WorkspacePanel } from './WorkspacePanel';
import { WorkspaceClient, draftOf, type Transport } from './client';
const session=new URLSearchParams(location.search).get('session');
if(!session?.startsWith('w03-r2-test-'))throw Error('A unique test session is required');
const key='w03-r2-synthetic-server:'+session;
const initial=()=>({as_of:{business_seq:7,workspace_revision:1,storage_revision:11},tasks:[],receipts:{} as Record<string,any>,requests:[] as any[],
  products:['p1','p2'].map(id=>({product_id:id,session_id:session,version:1,kind:'text',title:id,purpose:'freeform',content:'base '+id,
    content_hash:'0'.repeat(64),cycle:{session_id:session,kind:'cycle',object_id:'c',version:1},author:{id:'test-human',kind:'human'},executor:{id:'test-human',kind:'human'},
    created_at:'2026-10-06T13:00:00Z',legacy:null,removed_at:null}))});
await navigator.locks.request(key,()=>{if(!localStorage.getItem(key))localStorage.setItem(key,JSON.stringify(initial()));});
const read=()=>JSON.parse(localStorage.getItem(key)!);
const controls={lose:false,delayMs:0,rejectOnce:null as {status:number;code:string}|null};
const transport:Transport=async(path,body:any)=>{
  if(!body){const s=read();return {items:path.includes('/shares')?[]:path.includes('work-items')?s.tasks:s.products,as_of:s.as_of,next_cursor:null};}
  if(controls.delayMs)await new Promise(r=>setTimeout(r,controls.delayMs));
  const result=await navigator.locks.request(key,()=>{
    const s=read();s.requests.push(structuredClone(body));
    const fail=(status:number,code:string)=>{localStorage.setItem(key,JSON.stringify(s));throw Object.assign(Error(code),{status,code});};
    if(controls.rejectOnce){const e=controls.rejectOnce;controls.rejectOnce=null;return fail(e.status,e.code);}
    if(s.receipts[body.request_id]){localStorage.setItem(key,JSON.stringify(s));return s.receipts[body.request_id];}
    if(body.expected_version!==s.as_of.business_seq||body.expected_workspace_revision!==s.as_of.workspace_revision)return fail(409,'version_conflict');
    let object:any;
    if(body.operation==='work_products.edit'){
      const index=s.products.findIndex((p:any)=>p.product_id===body.payload.product_id),p=s.products[index];
      if(body.payload.expected_head!==p.version)return fail(409,'object_version_conflict');
      object={...p,...body.payload,version:p.version+1};s.products[index]=object;
    }else if(body.operation==='work_items.create'){
      object={id:'task-'+body.request_id,session_id:session,revision:1,status:'open',priority:1,order:s.tasks.length,...body.payload};s.tasks.push(object);
    }else return fail(422,'fixture_operation_unsupported');
    s.as_of.workspace_revision++;s.as_of.storage_revision++;
    const response={object,as_of:{...s.as_of}};s.receipts[body.request_id]=response;localStorage.setItem(key,JSON.stringify(s));return response;
  });
  if(controls.lose){controls.lose=false;throw Error('synthetic lost response');}return result;
};
const client=new WorkspaceClient(session,localStorage,transport);
await client.refresh();
createRoot(document.getElementById('root')!).render(<WorkspacePanel client={client} locale="en"/>);
Object.assign(window,{harness:{client,controls,read,draftOf,ready:true,
  async externalEdit(){await navigator.locks.request(key,()=>{const s=read();s.products[0]={...s.products[0],version:s.products[0].version+1,content:'other tab server content'};s.as_of.workspace_revision++;s.as_of.storage_revision++;localStorage.setItem(key,JSON.stringify(s));});},
}});
