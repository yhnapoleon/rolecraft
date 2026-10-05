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

describe('batch 1 server authority and legacy recovery', () => {
  function fixture() {
    const world: any = { session_id: 's', version: 0, logical_time: 0, resources: { capacity: 30, dev_days: 3, deadline_day: 7 }, configs: {}, material_versions: { policy: 1 }, indexed_versions: { policy: 1 }, applied_rules: [], pending_requests: [], action_count: 0, config_version: 1, status: 'active' };
    const data: any = { timeline: { events: [], turns: [], mode: 'saved' }, tests: [], artifacts: [], submissions: [] };
    const transport = vi.fn<Transport>(async (path, body) => {
      if (path === '/sessions') return { session_id: 's', token: 'test-token', state: world };
      if (path === '/sessions/s') return { state: world };
      if (path.endsWith('/materials')) return [];
      const key = path.split('/').at(-1)!;
      if (body === undefined && key in data) return data[key];
      throw new ApiError('not found', 404, 'not_found');
    });
    const storage = memory(), state = engine.newState(), live = new LiveWorkbench(engine, storage, transport);
    live.attach(state, () => {});
    return { live, state, storage, world, data, transport };
  }
  const timestamp = '2026-10-05T01:02:03.000000Z';
  const testRecord = (id = 'test') => ({ id, query: '政策？', answer: '真实回答', fallback: false, mode: 'local', citations: [], source_versions: { policy: 1 }, indexed_versions: { policy: 1 }, config_version: 1, as_of_seq: 1, stale: false, created_at: timestamp });
  it('restores server questions, timestamps and task contexts without local conversation records', async () => {
    const { live, data } = fixture(); const a = await live.start('pilot');
    data.timeline.turns = [{ role_id: 'tech_lead', trace_id: 'trace', text: '回答', question: '原提问', as_of_seq: 1, created_at: timestamp, context: { task_id: 'original-task', work_id: 'work', attachments: [{ type: 'test', id: 'test' }] } }];
    data.timeline.events = [{ seq: 1, event_type: 'update_pilot', payload: {}, created_at: timestamp }];
    await live.store.sync();
    expect(a.conversations.technical).toHaveLength(2);
    expect(a.conversations.technical[0]).toMatchObject({ text: '原提问', traceId: 'trace', createdAt: timestamp });
    expect(a.turnTask.trace).toBe('original-task');
    expect(a.events.find((e: any) => e.server).createdAt).toBe(timestamp);
    live.store.update('s', { questions: { trace: 'outdated local question' } });
    expect(a.conversations.technical[0].text).toBe('原提问');
  });
  it('keeps legacy local questions, task links and observed times when fields are missing or null', async () => {
    const { live, data } = fixture(); const a = await live.start('pilot');
    a.turnTask.trace = 'local-task'; a.turnTimes = { trace: { answered: timestamp } };
    live.store.update('s', { questions: { trace: 'local question' } });
    data.timeline.turns = [{ role_id: 'tech_lead', trace_id: 'trace', text: '回答', as_of_seq: 1, question: null, created_at: null }];
    await live.store.sync();
    expect(a.conversations.technical[0].text).toBe('local question');
    expect(a.turnTask.trace).toBe('local-task');
    expect(a.turnTimes.trace.answered).toBe(timestamp);
  });
  it('recovers lists without inventing task ownership and retains local notes for existing tests', async () => {
    const { live, data } = fixture(); const a = await live.start('pilot');
    live.store.update('s', { tests: [testRecord()], testNotes: { test: { expected: 'local expectation', diagnosis: 'local observation' } } });
    a.tests[0].taskId = a.tasks[0].id;
    data.tests = [testRecord('new'), { ...testRecord(), answer: 'server-authoritative' }];
    data.artifacts = [{ id: 'draft', version: 2, config_version: 1, content: { goal: 'submitted goal' }, created_at: timestamp }];
    data.submissions = [{ id: 'sub', artifact_id: 'draft', config_version: 1, as_of_seq: 5, created_at: timestamp }];
    await live.store.sync(); await live.store.sync();
    expect(a.tests).toHaveLength(2);
    expect(a.tests.find((t: any) => t.id === 'new')).toMatchObject({ taskId: null, config: null, createdAt: timestamp });
    expect(a.tests.find((t: any) => t.id === 'test')).toMatchObject({ taskId: a.tasks[0].id, expectation: 'local expectation', answer: 'server-authoritative' });
    expect(live.session(a)!.testNotes.test.diagnosis).toBe('local observation');
    expect(live.session(a)!.artifact!.id).toBe('draft');
    expect(a.submittedAt).toBe(timestamp);
  });
  it('treats absent legacy list endpoints as optional but surfaces real network failures', async () => {
    const { live, transport } = fixture(); const a = await live.start('pilot');
    live.store.update('s', { tests: [testRecord()] });
    const original = transport.getMockImplementation()!;
    transport.mockImplementation(async (path, body, session) => { if (/\/(tests|artifacts|submissions)$/.test(path)) throw new ApiError('not found', 404); return original(path, body, session); });
    await live.store.sync(); expect(live.store.getSnapshot().connected).toBe(true); expect(a.tests).toHaveLength(1);
    transport.mockImplementation(async (path, body, session) => { if (path.endsWith('/tests')) throw new ApiError('offline'); return original(path, body, session); });
    await live.store.sync(); expect(live.store.getSnapshot().error).toContain('offline'); expect(a.tests).toHaveLength(1);
  });
  it('uses job kind and role after reload, with a legacy fallback', async () => {
    const { live, transport, storage } = fixture(); await live.start('pilot');
    transport.mockImplementationOnce(async () => ({ job_id: 'job' })); await live.store.sendTurn('supervisor', 'Question');
    const restored = new WorkspaceStore(storage, transport);
    expect(pendingTurnRole(restored.active())).toBe('supervisor');
    transport.mockImplementationOnce(async () => ({ id: 'job', status: 'running', attempt: 1, kind: 'turn', role_id: 'tech_lead', result: null, error: null }));
    await restored.poll(); expect(pendingTurnRole(restored.active())).toBe('tech_lead');
    const feedback: any = { submission_id: 'sub', items: [], overflow: true };
    transport.mockImplementationOnce(async () => ({ id: 'job', status: 'completed', attempt: 1, kind: 'feedback', role_id: null, result: feedback, error: null }));
    await restored.poll(); expect(restored.active()!.feedback).toEqual(feedback); expect(restored.active()!.questions).toEqual({});
  });
  it('updates approved resources immediately even if the subsequent refresh is interrupted', async () => {
    const { live, transport, world } = fixture(); const a = await live.start('pilot');
    transport.mockImplementationOnce(async () => ({ approved: true, state: { ...world, resources: { ...world.resources, capacity: 60 } } }));
    transport.mockImplementationOnce(async () => { throw new ApiError('offline'); });
    await live.store.approval('capacity_approved'); expect(a.world.capacity).toBe(60);
  });
  it('persists denial details without manufacturing events or successful approval', async () => {
    const { live, transport, data } = fixture(); const a = await live.start('pilot');
    const details = { missing: { human_fallback: true, work_items: ['human_fallback'] } };
    data.timeline.approval_denials = [{ id: 'denied', rule_id: 'capacity_approved', request_id: 'r', code: 'approval_plan_incomplete', details, created_at: timestamp }];
    transport.mockImplementationOnce(async () => { throw new ApiError('requested plan lacks necessary work or human fallback', 422, 'approval_plan_incomplete', details); });
    await live.store.approval('capacity_approved');
    expect(a.world.capacity).toBe(30); expect(a.backend.version).toBe(0);
    expect(a.approvalDenials[0].details).toEqual(details);
    expect(a.events.filter((e: any) => e.type === 'approval_denied')).toHaveLength(1);
    expect(live.store.getSnapshot().error).toContain('缺人工兜底');
  });
  it('retries failed feedback explicitly and clears the old failure once queued', async () => {
    const { live, transport } = fixture(); const a = await live.start('pilot');
    live.store.update('s', { submission: { id: 'sub', artifact_id: 'a', config_version: 1, as_of_seq: 1 }, feedbackFailure: { id: 'job', kind: 'feedback', status: 'failed', attempt: 3, result: null, error: 'RuntimeError' } });
    transport.mockImplementationOnce(async (_, body) => { expect(body).toEqual({ submission_id: 'sub', retry: true }); return { job_id: 'job' }; });
    await live.feedback(a, true); expect(live.session(a)!.feedbackFailure).toBeUndefined(); expect(live.session(a)!.pending!.jobId).toBe('job');
  });
  it('restores submitted records without fetching nonexistent feedback while its job is pending', async () => {
    const { live, transport, world, data } = fixture(); await live.start('pilot');
    world.status = 'submitted';
    data.timeline.events = [{ seq: 3, event_type: 'submit_plan', payload: { object_id: 'sub' } }];
    data.submissions = [{ id: 'sub', artifact_id: 'a', config_version: 1, as_of_seq: 2 }];
    live.store.update('s', { pending: { kind: 'feedback', path: '/feedback', body: { submission_id: 'sub' }, label: 'review', created: timestamp, jobId: 'job' } });
    await live.store.sync();
    expect(live.store.active()!.submission!.id).toBe('sub');
    expect(transport.mock.calls.some(([path]) => path.includes('/feedback/sub'))).toBe(false);
  });
  it('journals turn context for identical retries and leaves legacy requests unchanged', async () => {
    const { live, storage, transport } = fixture(); const a = await live.start('pilot');
    const context = { task_id: 'task', work_id: 'work', attachments: [{ type: 'work' as const, id: 'work', version: 2 }] };
    transport.mockImplementationOnce(async () => { throw new ApiError('offline'); });
    await expect(live.turn(a, 'technical', 'Question', context)).rejects.toThrow('offline');
    const original = structuredClone(live.session(a)!.pending!.body);
    const restored = new WorkspaceStore(storage, transport);
    transport.mockImplementationOnce(async (_, body) => { expect(body).toEqual(original); return { job_id: 'job' }; });
    await restored.execute(); expect(restored.active()!.pending!.body).toMatchObject(context);
    restored.update('s', { pending: undefined });
    transport.mockImplementationOnce(async (_, body: any) => { expect(Object.keys(body).sort()).toEqual(['request_id', 'role_id', 'text']); return { job_id: 'legacy' }; });
    await restored.sendTurn('supervisor', 'No context');
  });
});

import { pendingTurnRole, serverText } from './store';
import { request } from './api';
import { setPreference } from './app/i18n';
describe('batch 1 error transport and translations', () => {
  it('preserves code and structured details through the production request function', async () => {
    const details = { missing: { human_fallback: true } };
    const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ error: 'original message', code: 'approval_plan_incomplete', details }), { status: 422 }));
    try { await expect(request('/test', {})).rejects.toMatchObject({ message: 'original message', status: 422, code: 'approval_plan_incomplete', details }); }
    finally { fetcher.mockRestore(); }
  });
  it.each(['version_conflict','session_paused','session_submitted','config_not_current','artifact_config_mismatch','material_unavailable','invalid_pause_resume','config_required','reason_required','request_unavailable','unknown_domain_or_work_item','request_id_reused','query_length','unknown_scenario','unknown_role','token_required','token_invalid','relation_not_configured','not_found','invalid_request','approval_no_pending_request','approval_needs_config','approval_plan_incomplete','approval_unsupported_rule','approval_not_needed_or_over_limit'])('translates %s by code in both languages without relying on the server wording', code => {
    try {
      setPreference('zh'); expect(serverText('changed server wording', code)).toMatch(/[一-鿿]/);
      setPreference('en'); expect(serverText('changed server wording', code)).not.toMatch(/[一-鿿]/); expect(serverText('changed server wording', code)).not.toBe('changed server wording');
    } finally { setPreference('zh'); }
  });
  it('retains old text fallback and translates detailed denial limits', () => {
    expect(serverText('expected 0; current 3')).toBe(serverText('changed', 'version_conflict'));
    expect(serverText('unrecognized legacy detail')).toBe('unrecognized legacy detail');
    const details = { requested: { capacity: 90 }, current: { capacity: 30 }, limit: { capacity: 60 } };
    expect(serverText('', 'approval_not_needed_or_over_limit', details)).toContain('申请 90，当前 30，上限 60');
  });
});

describe.runIf(!!api)('batch 1 real HTTP recovery', () => {
  it('reopens a session with only credentials and restores questions, contexts, tests and submitted records', async () => {
    const transport: Transport = async (path, body, session) => {
      const response = await fetch(api + path, { method: body === undefined ? 'GET' : 'POST', headers: { ...(body === undefined ? {} : { 'Content-Type': 'application/json' }), ...(session ? { Authorization: 'Bearer ' + session.token } : {}) }, body: body === undefined ? undefined : JSON.stringify(body) });
      const data = await response.json(); if (!response.ok) throw new ApiError(data.error || data.detail, response.status, data.code, data.details); return data;
    };
    const live = new LiveWorkbench(engine, memory(), transport); live.attach(engine.newState(), () => {});
    const a = await live.start('pilot'); await live.config(a, config);
    await live.test(a, { question: '会议室怎么申请？', taskId: a.tasks[0].id });
    await live.test(a, { question: '住宿报销上限？' });
    const context = { task_id: a.tasks[0].id, work_id: 'work-original', attachments: [{ type: 'test' as const, id: a.tests[0].id, version: 1 }] };
    await live.turn(a, 'technical', '原始问题：资料多久更新？', context);
    for (let i = 0; i < 100 && live.session(a)!.pending; i++) { await live.store.poll(a.id); if (live.session(a)!.pending) await new Promise(r => setTimeout(r, 100)); }
    expect(live.session(a)!.pending).toBeUndefined();
    const session = structuredClone(live.session(a)!);
    const minimal = { ...session, materials: [], tests: [], testNotes: {}, questions: {}, timeline: { events: [], turns: [], mode: '' } };
    const storage = memory(); storage.setItem(STORAGE_KEY, JSON.stringify({ schema: 1, active: a.id, sessions: [minimal] }));
    const restored = new LiveWorkbench(engine, storage, transport), state = engine.newState(); restored.attach(state, () => {}); await restored.store.sync(a.id);
    const recovered = state.attempts.find((x: any) => x.id === a.id);
    expect(recovered.tests).toHaveLength(2); expect(recovered.tests.every((t: any) => t.taskId === null && t.createdAt.endsWith('Z'))).toBe(true);
    expect(recovered.conversations.technical[0]).toMatchObject({ text: '原始问题：资料多久更新？', context });
    expect(recovered.conversations.technical[0].createdAt).toMatch(/Z$/);
    expect(recovered.turnTask[recovered.conversations.technical[0].traceId]).toBe(context.task_id);
    const draft = { goal: 'test', owner: 'PM', metrics: 'test', observation_window: '7 days', exit_condition: 'errors', rationale: '真实证据'.repeat(5000) };
    await restored.save(recovered, draft); await restored.submit(recovered); await restored.feedback(recovered);
    for (let i = 0; i < 100 && restored.session(recovered)!.pending; i++) { await restored.store.poll(a.id); if (restored.session(recovered)!.pending) await new Promise(r => setTimeout(r, 100)); }
    const report = restored.session(recovered)!.feedback!;
    expect(report.overflow).toBe(true); expect(report.items.every(i => i.completeness === 'overflow')).toBe(true);
    expect(report.model_revision).toBe('rules-v3');
  }, 30000);
});
