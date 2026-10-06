import { describe,it,expect } from 'vitest';
import { WorkspaceClient,draftOf,type Transport } from './client';
import { MemoryCoordinator } from './test-support';
import { buildBrowserImport } from './import-browser';
import type { WorkProductVersion } from './contract-types';

function fixture() {
  let reads=0;
  const values=new Map<string,string>();const storage={getItem:(k:string)=>{reads++;control.readHook?.(reads);return values.get(k)??null;},setItem:(k:string,v:string)=>{values.set(k,v);}};
  const coordinator=new MemoryCoordinator();let next=0;
  const products=['p1','p2'].map(id=>({product_id:id,session_id:'s',version:1,kind:'text',title:id,purpose:'freeform',content:'base '+id,
    content_hash:'0'.repeat(64),cycle:{session_id:'s',kind:'cycle',object_id:'c',version:1},author:{id:'h',kind:'human'},executor:{id:'h',kind:'human'},created_at:'2026-10-06T13:00:00Z',legacy:null,removed_at:null})) as WorkProductVersion[];
  const server={products,tasks:[] as any[],as_of:{business_seq:7,workspace_revision:1,storage_revision:11}};
  const sent:any[]=[];const receipts=new Map<string,any>();const control={lose:false,reject:0,code:'',gate:undefined as Promise<void>|undefined,readHook:null as ((count:number)=>void)|null};
  const error=(status:number,code:string)=>Object.assign(Error(code),{status,code});
  const transport:Transport=async(path,body:any)=>{
    if(!body)return {items:structuredClone(path.includes('work-items')?server.tasks:server.products),as_of:{...server.as_of},next_cursor:null};
    sent.push(structuredClone(body));
    if(control.gate)await control.gate;
    if(control.reject){const status=control.reject;control.reject=0;throw error(status,control.code||'rejected');}
    if(receipts.has(body.request_id))return structuredClone(receipts.get(body.request_id));
    if(body.operation==='workspace_imports' && body.payload.mode==='preview')return {package_id:body.payload.package_id,mode:'preview',id_map:{},unresolved:[],as_of:{...server.as_of},applied:false};
    if(body.expected_version!==server.as_of.business_seq||body.expected_workspace_revision!==server.as_of.workspace_revision)throw error(409,'version_conflict');
    let object:any;
    if(body.operation==='work_products.versions.create'){
      const index=server.products.findIndex(p=>p.product_id===body.payload.product_id);const p=server.products[index];
      if(body.payload.expected_head!==p.version)throw error(409,'object_version_conflict');
      object={...p,...body.payload,version:p.version+1};server.products[index]=object;
    }else if(body.operation==='work_items.create'){
      object={id:'t'+next,session_id:'s',revision:1,...body.payload};server.tasks.push(object);
    }else if(body.operation==='workspace_imports' && body.payload.mode==='apply'){
      if(body.payload.preview_storage_revision!==server.as_of.storage_revision)throw error(409,'import_preview_stale');
    }else object={session_id:'s',id:'result',...body.payload};
    server.as_of.workspace_revision++;server.as_of.storage_revision++;
    const result=body.operation==='workspace_imports' && body.payload.mode==='apply'?{package_id:body.payload.package_id,mode:'apply',id_map:{},unresolved:[],as_of:{...server.as_of},applied:true}:{object:structuredClone(object),as_of:{...server.as_of}};
    receipts.set(body.request_id,result);if(control.lose){control.lose=false;throw Error('lost response');}return result;
  };
  const client=()=>new WorkspaceClient('s',storage,transport,()=>`request-${++next}`,{coordinator});
  const externalEdit=()=>{server.products[0]={...server.products[0],version:server.products[0].version+1,content:'other client content'};server.as_of.workspace_revision++;server.as_of.storage_revision++;};
  return {storage,coordinator,server,sent,control,client,externalEdit,readCount:()=>reads};
}

describe('R1 cross-instance merge and queue ownership',()=>{
  it('fails closed without a cross-tab coordinator and keeps the unsaved input visible',async()=>{
    const f=fixture();const c=new WorkspaceClient('s',f.storage,async()=>{});
    await expect(c.keepDraft('p1',{kind:'text',content:'keep in memory'})).rejects.toThrow('Web Locks');
    expect(c.snapshot().storageError).toBe(true);expect(c.snapshot().journal.drafts.p1.content).toBe('keep in memory');
    expect(f.storage.getItem(c.key)).toBeNull();
  });
  it('preserves different product drafts from stale writers including simultaneous starts',async()=>{
    const f=fixture(),a=f.client(),b=f.client();await Promise.all([a.refresh(),b.refresh()]);
    await Promise.all([a.keepDraft('p1',{...draftOf(a.snapshot().products[0]),content:'tab A'}),b.keepDraft('p2',{...draftOf(b.snapshot().products[1]),content:'tab B'})]);
    const reopened=f.client();expect(reopened.snapshot().journal.drafts.p1.content).toBe('tab A');expect(reopened.snapshot().journal.drafts.p2.content).toBe('tab B');
    expect(reopened.snapshot().journal.draftBases.p1?.product.version).toBe(1);
  });
  it('cannot erase another tab pending request while typing or start a competing mutation',async()=>{
    const f=fixture(),a=f.client(),b=f.client();await Promise.all([a.refresh(),b.refresh()]);
    await a.keepDraft('p1',{...draftOf(a.snapshot().products[0]),content:'A saved once'});f.control.lose=true;
    await expect(a.save(a.snapshot().products[0])).rejects.toThrow('lost response');
    const original=structuredClone(a.snapshot().journal.pending!.command);
    await b.keepDraft('p2',{...draftOf(b.snapshot().products[1]),content:'B still typing'});
    await expect(b.createTask({title:'must wait'})).rejects.toThrow('先恢复');
    const reopened=f.client();expect(reopened.snapshot().journal.pending!.command).toEqual(original);
    await reopened.retry();expect(f.server.products[0].version).toBe(2);
    expect(reopened.snapshot().journal.drafts.p2.content).toBe('B still typing');expect(f.sent).toHaveLength(2);
  });
  it('coordinates competing initial mutations, rather than both claiming the queue',async()=>{
    const f=fixture(),a=f.client(),b=f.client();await Promise.all([a.refresh(),b.refresh()]);
    let release!:()=>void;f.control.gate=new Promise<void>(r=>{release=r;});
    const first=a.createTask({title:'A'});await new Promise(r=>setTimeout(r,0));
    await expect(b.createTask({title:'B'})).rejects.toThrow('先恢复');release();await first;
    expect(f.sent).toHaveLength(1);expect(f.server.tasks).toHaveLength(1);
  });
  it('retains both same-product drafts when a stale writer replaces the visible head',async()=>{
    const f=fixture(),a=f.client(),b=f.client();await Promise.all([a.refresh(),b.refresh()]);
    await a.keepDraft('p1',{...draftOf(a.snapshot().products[0]),content:'branch A'});
    await b.keepDraft('p1',{...draftOf(b.snapshot().products[0]),content:'branch B'});
    const journal=f.client().snapshot().journal;
    expect(journal.drafts.p1.content).toBe('branch B');expect(journal.alternatives.p1[0].draft.content).toBe('branch A');
  });
  it('binds payload/base/token before pending and rejects an edit interleaved at the flush boundary',async()=>{
    const f=fixture(),a=f.client();await a.refresh();await a.keepDraft('p1',{...draftOf(a.snapshot().products[0]),content:'A to send'});
    const b=f.client();await b.refresh();const draftB={...b.snapshot().journal.drafts.p1,content:'B NEW UNSENT TEXT'};
    const start=f.readCount();let writingB:Promise<void>|undefined;
    f.control.readHook=count=>{if(count===start+2){f.control.readHook=null;queueMicrotask(()=>{writingB=b.keepDraft('p1',draftB);});}};
    await expect(a.save(a.snapshot().products[0])).rejects.toThrow('新输入');await writingB;
    const journal=f.client().snapshot().journal;
    expect(f.sent).toHaveLength(0);expect(journal.pending).toBeUndefined();
    expect(journal.drafts.p1.content).toBe('B NEW UNSENT TEXT');expect(f.server.products[0].content).toBe('base p1');
    await b.save(b.snapshot().products[0]);expect(f.server.products[0].content).toBe('B NEW UNSENT TEXT');
  });
  it('does not discard a draft when replaying a legacy pending record with mismatched payload/token',async()=>{
    const f=fixture(),a=f.client();await a.refresh();await a.keepDraft('p1',{...draftOf(a.snapshot().products[0]),content:'A was sent'});
    f.control.lose=true;await expect(a.save(a.snapshot().products[0])).rejects.toThrow('lost response');
    // Reconstruct the persisted r2 failure shape; do not modify the controller.
    const journal=JSON.parse(f.storage.getItem(a.key)!);
    journal.drafts.p1.content='B never sent';journal.draftTokens.p1='legacy-misbinding-token';journal.draftWriters.p1='writer-B';
    journal.pending.draft=structuredClone(journal.drafts.p1);journal.pending.draftToken=journal.draftTokens.p1;
    f.storage.setItem(a.key,JSON.stringify(journal));
    const reopened=f.client();await reopened.retry();
    expect(f.server.products[0].content).toBe('A was sent');expect(f.server.products[0].version).toBe(2);
    expect(reopened.snapshot().journal.drafts.p1.content).toBe('B never sent');
    expect(reopened.snapshot().journal.draftBases.p1?.product.version).toBe(1);expect(reopened.snapshot().journal.pending).toBeUndefined();
  });
});

describe('R2 persistent draft baseline',()=>{
  it('does not rebase an old draft on refresh/reload; requires explicit merge before saving',async()=>{
    const f=fixture(),a=f.client();await a.refresh();await a.keepDraft('p1',{...draftOf(a.snapshot().products[0]),content:'A based on v1'});
    f.externalEdit();const reloaded=f.client();await reloaded.refresh();
    await expect(reloaded.save(reloaded.snapshot().products[0])).rejects.toThrow('草稿基准');
    expect(f.sent).toHaveLength(0);expect(f.server.products[0].content).toBe('other client content');
    expect(reloaded.snapshot().journal.draftBases.p1?.product.version).toBe(1);
    const token=reloaded.snapshot().journal.draftTokens.p1;
    await reloaded.confirmMerge('p1',{...reloaded.snapshot().journal.drafts.p1,content:'explicit merged A and B'},2,token);
    await reloaded.save(reloaded.snapshot().products[0]);expect(f.sent[0].payload.expected_head).toBe(2);
    expect(f.server.products[0].content).toBe('explicit merged A and B');
  });
  it('the backend still sees the original expected_head if server changes after the last read',async()=>{
    const f=fixture(),a=f.client();await a.refresh();await a.keepDraft('p1',{...draftOf(a.snapshot().products[0]),content:'old draft'});
    f.server.products[0]={...f.server.products[0],version:2,content:'B'};
    await expect(a.save(a.snapshot().products[0])).rejects.toThrow('object_version_conflict');
    expect(f.sent[0].payload.expected_head).toBe(1);expect(f.server.products[0].content).toBe('B');
  });
  it('migrates old draft1 notes without inventing a base or changing the original archive',async()=>{
    const f=fixture();const raw=JSON.stringify({schema:1,sessionId:'s',drafts:{p1:{kind:'text',content:'legacy draft'}},conflicts:{}});
    f.storage.setItem('rolecraft.workspace.feature.v2.s',raw);const c=f.client();await c.refresh();
    await expect(c.save(c.snapshot().products[0])).rejects.toThrow('草稿基准');
    expect(c.snapshot().journal.draftBases.p1).toBeNull();expect(f.sent).toHaveLength(0);
    expect(f.storage.getItem('rolecraft.workspace.feature.v2.s')).toBe(raw);
  });
  it('does not advance a baseline when the user-confirmed server head changes again',async()=>{
    const f=fixture(),c=f.client();await c.refresh();await c.keepDraft('p1',{...draftOf(c.snapshot().products[0]),content:'draft'});
    f.externalEdit();await c.refresh();const token=c.snapshot().journal.draftTokens.p1;f.externalEdit();
    await expect(c.confirmMerge('p1',c.snapshot().journal.drafts.p1,2,token)).rejects.toThrow('又有变化');
    expect(c.snapshot().journal.draftBases.p1?.product.version).toBe(1);
  });
});

describe('R3 known rejection versus unknown execution outcome',()=>{
  it.each([400,401,403,404,409,422])('releases a first-attempt %i refusal while preserving the exact input for review',async(status)=>{
    const f=fixture(),c=f.client();await c.refresh();f.control.reject=status;
    await expect(c.createTask({title:'keep this task'})).rejects.toThrow();
    expect(c.snapshot().journal.pending).toBeUndefined();const [id,r]=Object.entries(c.snapshot().journal.rejected)[0];
    expect(r.request.command.payload?.title).toBe('keep this task');
    const reloaded=f.client();await reloaded.resubmitRejected(id);
    expect(f.sent[0].request_id).not.toBe(f.sent[1].request_id);expect(f.server.tasks).toHaveLength(1);
  });
  it.each(['work_products.shares.create','work_products.adopt'])('unlocks non-draft %s conflicts without silently changing the payload',async(operation)=>{
    const f=fixture(),c=f.client();await c.refresh();f.control.reject=409;f.control.code='version_conflict';
    const payload={product_id:'p1',expected_head:1,kind:'text',content:'base p1',recipient_role:'tech_lead'};
    await expect(c.mutate(operation,'/module-test',payload)).rejects.toThrow();
    const id=Object.keys(c.snapshot().journal.rejected)[0];await c.resubmitRejected(id);
    expect(f.sent[1].payload).toEqual(payload);expect(f.sent[1].request_id).not.toBe(f.sent[0].request_id);
  });
  it('requires a new import preview and explicit apply, retaining the refused import payload',async()=>{
    const f=fixture(),c=f.client();await c.refresh();
    const input=await buildBrowserImport({id:'old',tasks:[],artifacts:[{id:'a',kind:'text',body:'kept'}],events:[]},{taskIds:[],productIds:['a']});
    const preview=await c.previewImport(input);f.externalEdit();await c.refresh();
    await expect(c.applyImport(input,preview)).rejects.toThrow('import_preview_stale');
    expect(c.snapshot().journal.pending).toBeUndefined();const id=Object.keys(c.snapshot().journal.rejected)[0];
    await expect(c.resubmitRejected(id)).rejects.toThrow('重新预览');
    const recovery=await c.repreviewRejectedImport(id);expect(recovery.preview.as_of.storage_revision).toBe(f.server.as_of.storage_revision);
    await c.applyImport(recovery.input,recovery.preview,id);
    const applies=f.sent.filter(x=>x.operation==='workspace_imports' && x.payload.mode==='apply');expect(applies).toHaveLength(2);
    expect(applies[0].request_id).not.toBe(applies[1].request_id);expect(c.snapshot().journal.rejected[id].request.command.payload?.items).toEqual(input.items);
  });
  it('keeps the same key after unknown success, even if a later retry is denied before lookup',async()=>{
    const f=fixture(),c=f.client();await c.refresh();f.control.lose=true;
    await expect(c.createTask({title:'only once'})).rejects.toThrow('lost response');
    const original=structuredClone(c.snapshot().journal.pending!.command);const reopened=f.client();
    f.control.reject=401;f.control.code='credential_expired';await expect(reopened.retry()).rejects.toThrow();
    expect(reopened.snapshot().journal.pending!.command).toEqual(original);expect(reopened.snapshot().journal.rejected).toEqual({});
    await reopened.retry();expect(f.server.tasks).toHaveLength(1);expect(f.sent.every(x=>x.request_id===original.request_id)).toBe(true);
  });
  it('keeps an ambiguous 503 pending rather than letting later mutations pass',async()=>{
    const f=fixture(),c=f.client();await c.refresh();f.control.reject=503;
    await expect(c.createTask({title:'uncertain'})).rejects.toThrow();
    expect(c.snapshot().journal.pending).toBeDefined();await expect(c.createTask({title:'new'})).rejects.toThrow('先恢复');
  });
});
