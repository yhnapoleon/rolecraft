import {describe,it,expect,vi} from 'vitest';
import {WorkspaceSlotController,productInput,productRef,readPage} from './slot-controller';
import type {V4HostAdapter,V4HostSnapshot,V4CommandResult} from '../../../v4-host';
import type {WorkspaceProductRead} from '../contract-types';
const at={business_seq:0,workspace_revision:1,storage_revision:1};
const product=(extra:Partial<WorkspaceProductRead>={}):WorkspaceProductRead=>({session_id:'s',product_id:'p',version:1,kind:'text',purpose:'exploration',title:'Draft',content:'original',content_hash:'a'.repeat(64),cycle:{session_id:'s',kind:'cycle',object_id:'c',version:1},author:{kind:'human',id:'learner'},executor:{kind:'human',id:'learner'},created_at:'2026-10-07T00:00:00Z',visibility:'private',...extra});
function fixture(){
  let p=product();let point={...at};
  const drafts=new Map<string,unknown>(),operations:Record<string,boolean>={};
  for(const op of ['work_items.list','work_items.create','work_items.update','work_items.batch','work_products.list','work_products.create','work_products.versions.list','work_products.versions.create','work_products.shares.create','work_products.shares.change','work_products.adopt'])operations[op]=true;
  let snapshot:V4HostSnapshot={session:{protocol:2,sessionId:'s',workLanguage:'zh',scenarioHash:'fixed'},uiLanguage:'zh',state:'active',asOf:point,currentTask:null,currentProduct:productRef(p),busy:false,storageError:false,available:operations};
  const page=(items:any[])=>({schema_version:2,items,as_of:point,next_cursor:null});
  const host:V4HostAdapter={snapshot:()=>snapshot,subscribe:()=>()=>{},
    query:vi.fn(async(op)=>op==='work_items.list'?page([]):{...page([p]),shares:[],sharing_complete:true}),
    command:vi.fn(async(op:string,input:Readonly<Record<string,unknown>>):Promise<V4CommandResult>=>{
      if(op==='work_products.versions.create'){
        if(input.expected_head!==p.version)throw Error('object_version_conflict');
        p={...p,...input,version:p.version+1,visibility:'private'} as WorkspaceProductRead;
      }
      point={...point,workspace_revision:point.workspace_revision+1,storage_revision:point.storage_revision+1};snapshot={...snapshot,asOf:point};
      return {requestId:'host-request',status:'confirmed',result:{object:p,as_of:point}};
    }),
    recover:vi.fn(async():Promise<V4CommandResult>=>({requestId:'host-request',status:'pending',result:null})),
    retry:vi.fn(async():Promise<V4CommandResult>=>({requestId:'explicit-next-request',status:'pending',result:null})),
    draft:<T>(_slot:string,key:string)=>drafts.get(key) as T|undefined,
    keepDraft:vi.fn(async(_slot,key,value)=>{drafts.set(key,structuredClone(value));}),flushDrafts:vi.fn(async()=>{}),
    openReference:vi.fn(async()=>{}),chooseEvidence:vi.fn(async()=>[]),selectTask:vi.fn(),selectProduct:vi.fn(ref=>{snapshot={...snapshot,currentProduct:ref};}),announce:vi.fn()};
  const c=new WorkspaceSlotController(host);c.update(snapshot);
  return {c,host,drafts,get product(){return p;},get snapshot(){return snapshot;},setProduct:(value:WorkspaceProductRead)=>{p=value;point={...point,storage_revision:point.storage_revision+1};},setSession:(sid:string)=>{snapshot={...snapshot,session:{protocol:2,sessionId:sid,workLanguage:'en',scenarioHash:'other'},currentProduct:null};c.update(snapshot);}};
}

describe('W03 slot through the single host adapter',()=>{
  it('saves domain input only and preserves structured payload and evidence',async()=>{
    const f=fixture();f.setProduct(product({kind:'investigation',structured_payload:{type:'investigation',question:'why',blocks:[{id:'b',type:'note',text:'keep',test_ref:{session_id:'s',kind:'test',object_id:'actual-test',version:1}}]},evidence_refs:[{session_id:'s',kind:'material',object_id:'source',version:1,observed_at_seq:0}]}));
    await f.c.refresh();await f.c.edit({title:'Revised'});await f.c.editInvestigation('review_note','Still uncertain');await f.c.save();
    expect(f.host.command).toHaveBeenCalledTimes(1);
    const [op,payload]=vi.mocked(f.host.command).mock.calls[0];
    expect(op).toBe('work_products.versions.create');expect(payload.expected_head).toBe(1);
    for(const key of ['request_id','expected_version','expected_workspace_revision','token','schema_version'])expect(payload).not.toHaveProperty(key);
    expect(payload.structured_payload).toMatchObject({blocks:[{id:'b',text:'keep',test_ref:{object_id:'actual-test',version:1}}],review_note:'Still uncertain'});
    expect(f.c.draft()).toBeUndefined();expect(f.product.version).toBe(2);
  });
  it('keeps text after another head arrives and requires explicit comparison',async()=>{
    const f=fixture();await f.c.refresh();await f.c.edit({content:'local text'});const token=f.c.draft()!.token;
    f.setProduct(product({version:2,content:'other client'}));await f.c.refresh();
    expect(f.c.draft()?.value.content).toBe('local text');await expect(f.c.save()).rejects.toThrow('draft_conflict');expect(f.host.command).not.toHaveBeenCalled();
    await f.c.save({head:2,token});expect(f.product.content).toBe('local text');expect(f.product.version).toBe(3);
  });
  it('does not clear newer typing when the older save response arrives',async()=>{
    const f=fixture();await f.c.refresh();await f.c.edit({content:'sent text'});
    let finish!:(value:V4CommandResult)=>void;vi.mocked(f.host.command).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
    const pending=f.c.save();await vi.waitFor(()=>expect(f.host.command).toHaveBeenCalledTimes(1));
    await f.c.edit({content:'newer unsent text'});f.setProduct(product({version:2,content:'sent text'}));
    finish({requestId:'host-request',status:'confirmed',result:{object:f.product,as_of:at}});await pending;
    expect(f.c.draft()?.value.content).toBe('newer unsent text');expect(f.c.conflict()).toBe(true);expect(f.host.selectProduct).not.toHaveBeenCalled();
  });
  it('never automatically recovers or retries a pending command',async()=>{
    const f=fixture();await f.c.refresh();await f.c.edit({content:'awaiting response'});
    vi.mocked(f.host.command).mockResolvedValueOnce({requestId:'original',status:'pending',result:null});await f.c.save();await f.c.refresh();
    expect(f.host.recover).not.toHaveBeenCalled();expect(f.host.retry).not.toHaveBeenCalled();expect(f.c.blocked()).toBe(true);
    vi.mocked(f.host.recover).mockResolvedValueOnce({requestId:'original',status:'failed',result:null});await f.c.recover();
    expect(f.host.recover).toHaveBeenCalledWith('original');expect(f.host.command).toHaveBeenCalledTimes(1);expect(f.host.retry).not.toHaveBeenCalled();
    await f.c.recover(true);expect(f.host.retry).toHaveBeenCalledWith('original');expect(f.c.state.receipt?.requestId).toBe('explicit-next-request');
    expect(f.drafts.get('s:request-pointer')).not.toHaveProperty('payload');
  });
  it('keeps an unexpected acknowledgement unconfirmed and retains the draft',async()=>{
    const f=fixture();await f.c.refresh();await f.c.edit({content:'my text'});
    vi.mocked(f.host.command).mockResolvedValueOnce({requestId:'original',status:'confirmed',result:{object:product({product_id:'other',version:2}),as_of:at}});
    await expect(f.c.save()).rejects.toThrow('unconfirmed_saved_product');expect(f.c.draft()?.value.content).toBe('my text');expect(f.c.state.receipt?.status).toBe('unconfirmed');expect(f.c.blocked()).toBe(true);
  });
  it('does not show a late response from the previous session',async()=>{
    const f=fixture();let finish!:(value:unknown)=>void;
    vi.mocked(f.host.query).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));const reading=f.c.refresh();f.setSession('other');
    finish({items:[],as_of:at,next_cursor:null});await reading;expect(f.c.state.products).toEqual([]);expect(f.c.state.shares).toEqual([]);
  });
  it('shares the current saved version once, never a local draft',async()=>{
    const f=fixture();await f.c.refresh();await f.c.share('tech_lead','Read this version');
    expect(f.host.command).toHaveBeenCalledWith('work_products.shares.create',{product_id:'p',product_version:1,recipient_role:'tech_lead',question:'Read this version',purpose:'discussion'});
    await f.c.edit({content:'not shared'});expect(()=>f.c.share('business_lead','')).toThrow('save_before_sharing');expect(f.host.command).toHaveBeenCalledTimes(1);
  });
  it('refuses a stale comparison and leaves both texts intact',async()=>{
    const f=fixture();await f.c.refresh();await f.c.edit({content:'mine'});const token=f.c.draft()!.token;
    f.setProduct(product({version:2,content:'second'}));await f.c.refresh();f.setProduct(product({version:3,content:'third'}));
    await expect(f.c.save({head:2,token})).rejects.toThrow('comparison_changed');expect(f.c.draft()?.value.content).toBe('mine');expect(f.product.content).toBe('third');expect(f.host.command).not.toHaveBeenCalled();
  });
  it('cannot edit a removed product into an implicit restoration',async()=>{
    const f=fixture();f.setProduct(product({removed_at:'2026-10-07T00:00:00Z'}));await f.c.refresh();
    await expect(f.c.edit({content:'x'})).rejects.toThrow('editing_unavailable');expect(f.host.command).not.toHaveBeenCalled();
    await f.c.remove(false);expect(f.host.command).toHaveBeenCalledWith('work_products.versions.create',expect.objectContaining({removed:false,expected_head:1}));
  });
});

it('accepts frozen read envelopes and rejects cross-session or falsely private scoped rows',()=>{
  const page={items:[product()],as_of:at,next_cursor:null,shares:[],sharing_complete:true};
  expect(readPage({schema_version:2,result:{schema_version:2,result:page}},'s','product').items).toHaveLength(1);
  expect(()=>readPage({...page,items:[product({session_id:'foreign'})]},'s','product')).toThrow('invalid_workspace_identity');
  expect(()=>readPage({...page,sharing_complete:false},'s','product')).toThrow('incomplete_private_projection');
});

it('consumes the committed V4DataHost read-only RequestResult envelope',async()=>{
  const f=fixture();await f.c.refresh();await f.c.edit({content:'recovered exact text'});
  vi.mocked(f.host.command).mockResolvedValueOnce({requestId:'original',status:'unconfirmed',result:null});await f.c.save();
  f.setProduct(product({version:2,content:'recovered exact text'}));
  vi.mocked(f.host.recover).mockResolvedValueOnce({requestId:'original',status:'confirmed',result:{schema_version:2,session_id:'s',request_id:'original',operation:'work_products.versions.create',status:'completed',read_only:true,jobs:[],response:{result:{object:f.product,as_of:at}}}});
  await f.c.recover();expect(f.c.draft()).toBeUndefined();expect(f.c.state.receipt?.status).toBe('confirmed');expect(f.host.command).toHaveBeenCalledTimes(1);expect(f.host.retry).not.toHaveBeenCalled();
});

it('orders tasks using their actual revisions and pauses without changing product content',async()=>{
  const f=fixture();await f.c.refresh();
  const base={session_id:'s',created_at:'2026-10-07T00:00:00Z',updated_at:'2026-10-07T00:00:00Z',status:'open' as const,priority:0};
  const first={...base,id:'first',title:'Test first',revision:7,order:0},second={...base,id:'second',title:'Write later',revision:11,order:1};
  f.c.state.tasks=[first,second];await f.c.moveTask(second,-1);
  expect(f.host.command).toHaveBeenCalledWith('work_items.batch',{updates:[{item_id:'second',expected_revision:11,order:0},{item_id:'first',expected_revision:7,order:1}]});
  await f.c.patchTask(first,{status:'paused'});expect(f.host.command).toHaveBeenLastCalledWith('work_items.update',{item_id:'first',expected_revision:7,status:'paused'});expect(f.product.content).toBe('original');
});

it('acknowledges a canonical purpose after editing an original Chinese-valued control',async()=>{
  const f=fixture();f.setProduct(product({purpose:'探索笔记'}));await f.c.refresh();await f.c.edit({purpose:'试点决定',content:'same text survives'});await f.c.save();
  expect(f.host.command).toHaveBeenCalledWith('work_products.versions.create',expect.objectContaining({purpose:'commitment',content:'same text survives'}));expect(f.c.draft()).toBeUndefined();
});

it('saves the original task form priority and splits atomically using the shown revision',async()=>{
  const f=fixture();await f.c.refresh();const task={session_id:'s',id:'t',revision:4,title:'Original',goal:'note',priority:1,status:'open' as const,created_at:'now',updated_at:'now'};f.c.state.tasks=[task];
  await f.c.saveTaskForm({id:'t',baseRevision:4,title:'Renamed',goal:'kept note',priority:2,split:'New child'});
  expect(f.host.command).toHaveBeenCalledWith('work_items.batch',{updates:[{item_id:'t',expected_revision:4,title:'Renamed',goal:'kept note',priority:2}],creates:[{title:'New child',parent:{session_id:'s',kind:'task',object_id:'t',version:4},priority:2}]});
  expect(()=>f.c.saveTaskForm({id:'t',baseRevision:3,title:'stale',goal:'',priority:0,split:''})).toThrow('task_conflict');expect(f.host.command).toHaveBeenCalledTimes(1);
});
