import { readFileSync } from 'node:fs';
import { runInThisContext } from 'node:vm';
import { describe, expect, it, vi } from 'vitest';
import { ApiError, type Transport } from './api';
import { LiveWorkbench, fromPilot, toPilot } from './workbench-live';
import { STORAGE_KEY, WorkspaceStore } from './store';

const mod = { exports: {} as any };
runInThisContext('(function(module){' + readFileSync(new URL('../public/workbench-engine.js', import.meta.url), 'utf8') + '\n})')(mod);
export const engine = mod.exports;
export function memory() { const values = new Map<string,string>(); return { getItem:(k:string) => values.get(k) ?? null, setItem:(k:string,v:string) => { values.set(k,v); } }; }
const config = {participants:20,domains:['faq','policy'],update:'daily',fallback:'human',workItems:['scope','fallback'],launchDay:7};

describe('HTML workbench authority and mapping', () => {
  it('maps every old API configuration field in both directions, including manual policy and launch day', () => {
    for (const update of ['daily','realtime','manual']) expect(fromPilot(toPilot({...config,update}))).toEqual({...config,update});
    expect(toPilot({...config,update:'realtime',workItems:['realtime','fallback']})).toMatchObject({update_strategy:'realtime',work_items:['realtime_sync','human_fallback']});
    expect(() => toPilot({...config,fallback:'date'})).toThrow();
    expect(() => toPilot({...config,domains:['private']})).toThrow();
  });
  it('prohibits every simulation path that could manufacture a backend result', () => {
    const live=new LiveWorkbench(engine,memory());
    for(const method of ['runTest','reply','updateConfig','refreshIndex','requestResources','resolveResources','triggerPolicyUpdate','submit','revise','suggestPriorities','readMaterial']) expect(()=>live.engine[method]({})).toThrow(/后端/);
  });
  it('local ordering and adoption cannot fabricate colleague messages or approvals', () => {
    const live=new LiveWorkbench(engine,memory()); const state=engine.newState(); const a=engine.createAttempt(state,'pilot');
    for(const task of a.tasks) live.engine.moveTask(a,task.id,{priority:'first'});
    const x=engine.createArtifact(a,{title:'agent',body:'通过了',source:'external-agent',adopted:false}); live.engine.adoptArtifact(a,x.id);
    expect(a.nudges).toEqual([]); expect(Object.values(a.conversations).flat()).toEqual([]);
    expect(a.world.devDays).toBe(3); expect(a.events.some((e:any)=>e.type==='colleague_nudged')).toBe(false);
  });
  it('exports only actual permitted, read backend materials and never bearer credentials', () => {
    const live=new LiveWorkbench(engine,memory()); const a=engine.createAttempt(engine.newState(),'pilot');
    a.backend={materials:[{id:'brief',version:1,title:'服务端委托',body:'server-only-content'},{id:'business',version:1,title:'需求',body:'not-opened'}]};
    const pkg=live.package(a,null,{requestId:'r1',record:true});
    expect(pkg.materials.map((m:any)=>m.id)).toEqual(['brief']); expect(pkg.materials[0].body).toBe('server-only-content');
    expect(JSON.stringify(pkg)).not.toMatch(/token|Bearer|tech_private/);
    expect(a.exports[0].requestId).toBe('r1');
  });
  it('citation bodies come from backend results, not caller-supplied text', () => {
    const live=new LiveWorkbench(engine,memory()); const a=engine.createAttempt(engine.newState(),'pilot');
    a.backend={materials:[{id:'policy',version:2,title:'政策',body:'actual policy'}]};
    const x=engine.createArtifact(a,{title:'note'});
    live.engine.addEvidence(a,x.id,{id:'policy',version:2,type:'material',body:'fake policy'});
    expect(x.evidence[0].body).toBe('actual policy');
    expect(()=>live.engine.addEvidence(a,x.id,{id:'policy',version:1,type:'material'})).toThrow();
  });
  it('collects the latest editor draft even before its blur event commits a new version', () => {
    const live=new LiveWorkbench(engine,memory()); const a=engine.createAttempt(engine.newState(),'pilot');
    const x=engine.createArtifact(a,{title:'note',body:'old'}); x.draft={title:'edited',body:'latest body',purpose:'试点决定'};
    const content=live.draftFromWorks(a); expect(content).toContain('latest body'); expect(content).toContain('edited'); expect(content).not.toContain('\nold');
  });
  it('does not send non-idempotent session creation when storage is unavailable or corrupt', async () => {
    const transport=vi.fn<Transport>();
    const full=new WorkspaceStore({getItem:()=>null,setItem:()=>{throw Error('quota');}},transport); await full.create('pm_pilot');
    const corrupt=new WorkspaceStore({getItem:()=>'{',setItem:()=>{}},transport); await corrupt.create('pm_pilot');
    const invalid=new WorkspaceStore({getItem:()=>JSON.stringify({schema:1,sessions:[{}]}),setItem:()=>{}},transport); await invalid.create('pm_pilot');
    expect(invalid.getSnapshot().storageError).toBe(true);
    expect(transport).not.toHaveBeenCalled(); expect(full.getSnapshot().storageError).toBe(true);
  });
});

const api=process.env.ROLECRAFT_TEST_API;
describe.runIf(!!api)('real HTTP API + worker through the production frontend adapter',()=>{
  function setup(transport?:Transport,storage=memory(),state=engine.newState()) {
    const seen:string[]=[];
    const real:Transport=async(path,body,session)=>{
      seen.push((body===undefined?'GET ':'POST ')+path.replace(/\/sessions\/[^/]+/,'/sessions/:id').replace(/\/jobs\/[^/]+/,'/jobs/:id'));
      const response=await fetch(api+path,{method:body===undefined?'GET':'POST',headers:{...(body===undefined?{}:{'Content-Type':'application/json'}),...(session?{Authorization:'Bearer '+session.token}:{})},body:body===undefined?undefined:JSON.stringify(body)});
      const data=await response.json(); if(!response.ok)throw new ApiError(data.error||data.detail,response.status); return data;
    };
    const live=new LiveWorkbench(engine,storage,transport||real); live.attach(state,()=>{}); return {live,state,real,seen,storage};
  }
  async function complete(live:LiveWorkbench,a:any) {
    for(let i=0;i<100&&live.session(a)?.pending;i++){await live.store.poll(a.id); if(live.session(a)?.pending)await new Promise(r=>setTimeout(r,100));}
    expect(live.session(a)?.pending).toBeUndefined(); expect(live.session(a)?.failedTurn).toBeUndefined(); expect(live.session(a)?.feedbackFailure).toBeUndefined();
  }
  it('runs three roles, stale/fresh tests, both approvals, delivery, feedback and every evidence link',async()=>{
    const {live,seen}=setup(); const a=await live.start('pilot');
    expect(a.backend.configured).toBe(false); await expect(live.test(a,{question:'住宿上限'})).rejects.toThrow(/配置/);
    await live.config(a,config);
    const first=await live.test(a,{question:'住宿报销上限是多少？',expectation:'按政策回答',taskId:a.tasks[1].id}); expect(first.answer).toContain('500');
    await live.action(a,'read_material',{material_id:'business'}); expect(a.world.policyVersion).toBe(2);
    expect(live.package(a,null).materials.some((m:any)=>m.id==='business')).toBe(true);
    const stale=await live.test(a,{question:first.question}); expect(stale.answer).toContain('500'); expect(stale.indexVersion).toBe(1);
    const historical=await live.history(a,first.asOfSeq); expect(historical.find((m:any)=>m.id==='policy').version).toBe(1);
    await live.action(a,'refresh_index'); const fresh=await live.test(a,{question:first.question}); expect(fresh.answer).toContain('400'); expect(fresh.indexVersion).toBe(2);
    await live.config(a,{...config,participants:50}); await live.action(a,'request_capacity',{reason:'验证50人方案'});
    expect(a.world.capacity).toBe(30); await live.perform(a,()=>live.store.approval('capacity_approved')); expect(a.world.capacity).toBe(60);
    await live.config(a,{...config,participants:50,update:'realtime',workItems:['realtime','fallback'],launchDay:10}); await live.action(a,'request_resources',{reason:'实时同步需要6人日与第10天上线'});
    expect(a.world.devDays).toBe(3); await live.perform(a,()=>live.store.approval('resources_approved')); expect(a.world.devDays).toBe(6); expect(a.world.deadline).toBe(10);
    for(const role of ['manager','business','technical']) {await live.turn(a,role,'请说明你所知道的事实与边界');await complete(live,a);expect(a.conversations[role].at(-1).model).toBe('local-extractive-v1');}
    expect(a.backend.materials.some((m:any)=>m.id==='tech_private')).toBe(false);
    const artifact=engine.createArtifact(a,{title:'真正的交付草稿',purpose:'试点决定',body:'50人，政策实时同步。'});live.engine.addEvidence(a,artifact.id,{id:fresh.id,version:fresh.configVersion,type:'test'});
    const draft={goal:'内部知识试点',owner:'PM',metrics:'正确解答率',observation_window:'一周',exit_condition:'严重错误暂停',rationale:live.draftFromWorks(a)};
    await live.save(a,draft);await live.submit(a);expect(a.backend.status).toBe('submitted');
    const fixedVersion=a.backend.version; await live.read(a,'policy'); expect(a.backend.version).toBe(fixedVersion);
    await expect(live.test(a,{question:'再次测试'})).rejects.toThrow(/锁定/);
    await live.feedback(a);await complete(live,a);const report=await live.savedFeedback(a);expect(report.summary.status).toBe('pending_review');
    let evidenceCount=0;for(const item of report.items)for(const id of item.evidence_ids){const ev=await live.evidence(a,item.criterion_id,id);expect(ev.observed_at_seq).toBeLessThanOrEqual(report.as_of_seq);evidenceCount++;}
    expect(evidenceCount).toBeGreaterThan(0);
    for(const route of ['/actions','/tests','/turns','/artifacts','/submissions','/feedback','/approvals/resolve'])expect(seen.some(v=>v==='POST /sessions/:id'+route)).toBe(true);
    expect(seen.some(v=>v.includes('/materials?as_of_seq='))).toBe(true);expect(seen.some(v=>v.includes('/evidence/'))).toBe(true);
  },30000);
  it('restores an uncertain successful request and retries identical content without duplicate effects',async()=>{
    const base=setup();let drop=false;
    const transport:Transport=async(path,body,session)=>{const value=await base.real(path,body,session);if(drop&&path.endsWith('/actions')){drop=false;throw new ApiError('controlled lost response');}return value;};
    const {live,state,storage}=setup(transport);const a=await live.start('pilot');drop=true;
    await expect(live.config(a,config)).rejects.toThrow(/lost response/);
    const original=structuredClone(live.session(a)!.pending);expect(original).toBeTruthy();
    const before=await base.real('/sessions/'+a.id,undefined,live.session(a));
    const restored=setup(transport,storage,structuredClone(state));const ar=restored.state.attempts.find((x:any)=>x.id===a.id);
    expect(restored.live.session(ar)!.pending).toEqual(original);await restored.live.retry(ar);
    const after=await base.real('/sessions/'+a.id,undefined,live.session(a));expect(after.state.version).toBe(before.state.version);expect(restored.live.session(ar)!.pending).toBeUndefined();expect(ar.configVersion).toBe(1);
  });
  it('handles stale versions without rebasing the action or erasing notes',async()=>{
    const {live,real}=setup();const a=await live.start('pilot');const s=live.session(a)!;const note=engine.createArtifact(a,{title:'不能丢失',body:'my draft'});
    await real('/sessions/'+a.id+'/actions',{tool:'read_material',arguments:{material_id:'brief'},request_id:crypto.randomUUID(),expected_version:s.world.version},s);
    await expect(live.action(a,'pause')).rejects.toThrow(/重新操作/);expect(a.backend.status).toBe('active');expect(a.artifacts.find((x:any)=>x.id===note.id).body).toBe('my draft');expect(live.session(a)!.pending).toBeUndefined();
  });
  it('supports pause/resume, both scenario variants and unconfigured optional analysis without blocking work',async()=>{
    const {live}=setup();const a=await live.start('capacity');expect(a.world.capacity).toBe(15);
    await live.action(a,'pause');expect(a.backend.status).toBe('paused');await expect(live.config(a,config)).rejects.toThrow(/暂停/);await live.action(a,'resume');expect(a.backend.status).toBe('active');
    await expect(live.relation(a,'容量为15人')).rejects.toThrow(/未配置/);expect(live.session(a)!.pending).toBeUndefined();await live.action(a,'read_material',{material_id:'brief'});
    const b=await live.start('urgent');expect(b.world.deadline).toBe(5);expect(live.session(a)!.world.status).toBe('active');
  });
});
