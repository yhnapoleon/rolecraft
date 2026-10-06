import { readFileSync } from 'node:fs';
import { runInThisContext } from 'node:vm';
import { describe, expect, it, vi } from 'vitest';
import { ApiError, type Transport } from './api';
import { LiveWorkbench, fromPilot, toPilot } from './workbench-live';
import { STORAGE_KEY, WorkspaceStore } from './store';
import type { World } from './types';

const mod = { exports: {} as any };
runInThisContext('(function(module){' + readFileSync(new URL('../public/workbench-engine.js', import.meta.url), 'utf8') + '\n})')(mod);
export const engine = mod.exports;
export function memory() { const values = new Map<string,string>(); return { getItem:(k:string) => values.get(k) ?? null, setItem:(k:string,v:string) => { values.set(k,v); } }; }
const config = {participants:20,domains:['faq','policy'],update:'daily',fallback:'human',workItems:['scope','fallback'],launchDay:7};

describe('HTML workbench authority and mapping', () => {
  it('binds Gateway credentials to the selected attempt without copying them into work data', async () => {
    const live = new LiveWorkbench(engine, memory()); const attempt = { id: 's' };
    let token = 'first';
    vi.spyOn(live, 'session').mockImplementation(a => a?.id === 's' ? { id: 's', token } as any : undefined);
    const fetcher = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ schema_version: 2, result: { items: [] } })));
    const send = live.gatewayTransport(attempt, fetcher);
    await send('/sessions/s/work-items'); token = 'second'; await send('/sessions/s/work-items');
    expect(fetcher.mock.calls[0][1]?.headers).toEqual({ Authorization: 'Bearer first' });
    expect(fetcher.mock.calls[1][1]?.headers).toEqual({ Authorization: 'Bearer second' });
    expect(attempt).toEqual({ id: 's' });
    await expect(send('/sessions/other/work-items')).rejects.toMatchObject({ code: 'session_route_mismatch' });
  });

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

describe('test work execution provenance', () => {
  async function setup() {
    const storage = memory(), state = engine.newState();
    const world: World = { session_id: 'work-session', version: 1, logical_time: 1, resources: { capacity: 30, dev_days: 3, deadline_day: 7 }, configs: { pilot: toPilot(config) }, material_versions: { policy: 1 }, indexed_versions: { policy: 1 }, applied_rules: [], pending_requests: [], action_count: 1, config_version: 1, status: 'active' };
    const saved = new Map<string, any>();
    const controls = { drop: false, conflict: false, gate: undefined as Promise<void> | undefined };
    const materialHistory = new Map<number, any[]>();
    const historyFailures = new Set<number>();
    const transport = vi.fn<Transport>(async (path, body: any) => {
      if (path === '/sessions') return { session_id: world.session_id, token: 'mock-token', state: structuredClone(world) };
      if (path.includes('/materials?as_of_seq=')) {
        const seq = Number(path.split('as_of_seq=')[1]);
        if (historyFailures.has(seq)) throw new ApiError('temporary history failure');
        if (!materialHistory.has(seq)) throw new ApiError('snapshot not found', 404);
        return structuredClone(materialHistory.get(seq));
      }
      if (path.endsWith('/materials')) return [{ id: 'policy', version: 1, title: '政策', content: '500' }];
      if (path.endsWith('/timeline')) return { events: [], turns: [], mode: 'saved_replay_no_model_calls' };
      if (!body && path === '/sessions/' + world.session_id) return { state: structuredClone(world) };
      if (body === undefined && path.endsWith('/tests')) return structuredClone([...saved.values()]);
      if (body === undefined && /\/(artifacts|submissions)$/.test(path)) return [];
      if (path.endsWith('/tests')) {
        if (controls.conflict) { controls.conflict = false; world.config_version++; throw new ApiError('config version is not current', 409); }
        if (controls.gate) await controls.gate;
        if (!saved.has(body.request_id)) {
          saved.set(body.request_id, { id: 'test-' + saved.size, query: body.query, answer: '实际回答', citations: [{ material_id: 'policy', version: 1 }], fallback: false, mode: 'local-extractive', stale: false, config_version: body.config_version, as_of_seq: world.version, source_versions: { policy: 1 }, indexed_versions: { policy: 1 } });
          world.version++;
        }
        if (controls.drop) { controls.drop = false; throw new ApiError('lost response'); }
        return structuredClone(saved.get(body.request_id));
      }
      throw new Error('Unexpected request: ' + path);
    });
    const live = new LiveWorkbench(engine, storage, transport); live.attach(state, () => {});
    const a = await live.start('pilot');
    const work = engine.createArtifact(a, { title: '政策测试', body: '测试计划', purpose: '测试计划', taskId: a.tasks[0].id });
    // Fixture the already-validated local work. Import validation has its own engine tests.
    Object.assign(work, { kind: 'test_set', cases: [
      { id: 'case-a', revision: 1, question: '住宿上限？', intent: '核对政策', expectation: '引用政策', refs: [{ id: 'policy', version: 1 }] },
      { id: 'case-b', revision: 1, question: '住宿上限？', intent: '检查回答', expectation: '引用政策', refs: [] },
    ] });
    const input = (index = 0) => { const row = work.cases[index]; return { question: row.question, expectation: row.expectation, taskId: work.taskId, workId: work.id, workRevision: work.revision, caseId: row.id, caseRevision: row.revision }; };
    return { storage, state, world, saved, controls, transport, live, a, work, input, materialHistory, historyFailures };
  }

  function investigation(f: Awaited<ReturnType<typeof setup>>, runId: string) {
    const work = engine.createArtifact(f.a, { title: '政策来源调查', body: '对照旧回答与资料', purpose: '自由作品', taskId: f.work.taskId });
    Object.assign(work, { kind: 'investigation', question: '旧回答为什么不同？', blocks: [{ id: 'retest-block', revision: 1, type: 'retest', testId: runId }] });
    const baseline = f.a.tests.find((t: any) => t.id === runId);
    const input = () => ({ question: baseline.question, expectation: baseline.expectation, taskId: work.taskId, investigationId: work.id, investigationRevision: work.revision, blockId: work.blocks[0].id, blockRevision: work.blocks[0].revision, baselineRunId: runId });
    return { work, input };
  }

  it('recovers a lost successful result into its original row after reload and later edits', async () => {
    const f = await setup(); f.controls.drop = true;
    await expect(f.live.test(f.a, f.input())).rejects.toThrow(/lost response/);
    const pending = structuredClone(f.live.session(f.a)!.pending!);
    expect(pending.localRun).toMatchObject({ workId: f.work.id, workRevision: 1, caseId: 'case-a', caseRevision: 1, intent: '核对政策', refs: [{ id: 'policy', version: 1 }] });
    f.work.cases[0].question = '修改后的问题'; f.work.cases[0].revision++; f.work.revision++;
    const restoredState = structuredClone(f.state);
    const restored = new LiveWorkbench(engine, f.storage, f.transport); restored.attach(restoredState, () => {});
    const a = restoredState.attempts.find((x: any) => x.id === f.a.id);
    await restored.retry(a);
    expect(f.saved.size).toBe(1);
    const calls = f.transport.mock.calls.filter(([p, body]) => p.endsWith('/tests') && body !== undefined);
    expect(calls).toHaveLength(2); expect(calls[1][1]).toEqual(calls[0][1]);
    expect(a.tests).toHaveLength(1);
    expect(a.tests[0]).toMatchObject({ question: '住宿上限？', taskId: f.work.taskId, workId: f.work.id, workRevision: 1, caseId: 'case-a', caseRevision: 1, expectation: '引用政策', intent: '核对政策', config });
    expect(a.tests[0].createdAt).toBe(pending.localRun!.createdAt);
    expect(a.artifacts.find((x: any) => x.id === f.work.id).cases[0].question).toBe('修改后的问题');
    const restoredAgain = new LiveWorkbench(engine, f.storage, f.transport), stateAgain = structuredClone(restoredState);
    restoredAgain.attach(stateAgain, () => {});
    expect(stateAgain.attempts.find((x: any) => x.id === f.a.id).tests[0].caseId).toBe('case-a');
  });

  it('recovers server-listed tests without losing pending work provenance or authoritative timestamps', async () => {
    const f = await setup(); f.controls.drop = true;
    await expect(f.live.test(f.a, f.input())).rejects.toThrow(/lost response/);
    const pending = structuredClone(f.live.session(f.a)!.pending!);
    const server = f.saved.get(String(pending.body.request_id))!;
    server.created_at = '2026-10-05T01:02:03.000000Z';
    // Refresh can discover the successful server result before the lost POST is retried.
    await f.live.store.sync(f.a.id);
    expect(f.a.tests).toHaveLength(1);
    expect(f.live.session(f.a)!.pending).toEqual(pending);
    f.live.store.update(f.a.id, { testNotes: { [server.id]: { expected: '引用政策', diagnosis: '已核对原文' } } });
    f.work.cases[0].question = '后续修改的问题'; f.work.cases[0].revision++; f.work.revision++;
    const recovered = new LiveWorkbench(engine, f.storage, f.transport), state = structuredClone(f.state);
    recovered.attach(state, () => {});
    const a = state.attempts.find((item: any) => item.id === f.a.id);
    await recovered.retry(a); await recovered.store.sync(a.id);
    expect(a.tests).toHaveLength(1);
    expect(a.tests[0]).toMatchObject({ createdAt: server.created_at, workId: f.work.id, workRevision: 1, caseId: 'case-a', caseRevision: 1, question: '住宿上限？', diagnosis: '已核对原文' });
    expect(recovered.session(a)!.testRunMeta![server.id]).toEqual(pending.localRun);
    expect(recovered.session(a)!.pending).toBeUndefined();
    expect(f.transport.mock.calls.filter(([path, body]) => path.endsWith('/tests') && body !== undefined)).toHaveLength(2);
  });

  it('rejects a second click while pending and keeps in-flight edits out of the execution snapshot', async () => {
    const f = await setup(); let finish!: () => void;
    f.controls.gate = new Promise<void>(resolve => { finish = resolve; });
    const running = f.live.test(f.a, f.input());
    await expect(f.live.test(f.a, f.input())).rejects.toThrow(/上一请求/);
    f.work.revision++; f.work.cases[0].revision++; f.work.cases[0].expectation = '新的预期';
    finish(); const result = await running;
    expect(result).toMatchObject({ caseRevision: 1, workRevision: 1, expectation: '引用政策' });
    expect(f.transport.mock.calls.filter(([p, body]) => p.endsWith('/tests') && body !== undefined)).toHaveLength(1);
  });

  it('keeps identical questions in separate rows and appends a deliberate retest', async () => {
    const f = await setup();
    const one = await f.live.test(f.a, f.input(0)), two = await f.live.test(f.a, f.input(1)), again = await f.live.test(f.a, f.input(0));
    expect(f.a.tests.map((x: any) => x.caseId)).toEqual(['case-a', 'case-b', 'case-a']);
    expect(new Set([one.id, two.id, again.id]).size).toBe(3);
    expect(new Set(f.a.tests.map((x: any) => x.requestId)).size).toBe(3);
    const session = f.live.session(f.a)!;
    f.live.store.update(f.a.id, { testNotes: { ...session.testNotes, [one.id]: { expected: '引用政策', diagnosis: '这个回答还需核对' } } });
    expect(f.a.tests.find((x: any) => x.id === one.id).diagnosis).toBe('这个回答还需核对');
  });

  it('projects the returned version maps without substituting the world index', async () => {
    const f = await setup(); const run = await f.live.test(f.a, f.input());
    const session = f.live.session(f.a)!;
    f.live.store.update(f.a.id, {
      world: { ...session.world, material_versions: { policy: 2, faq: 1 }, indexed_versions: { policy: 1, faq: 1 } },
      tests: session.tests.map(t => ({ ...t, source_versions: { policy: 2, faq: 1 }, indexed_versions: { policy: 2, faq: 1 } })),
    });
    const projected = f.a.tests.find((t: any) => t.id === run.id);
    expect(projected.sourceVersions).toEqual({ policy: 2, faq: 1 });
    expect(projected.indexedVersions).toEqual({ policy: 2, faq: 1 });
    expect(f.a.world.indexVersion).toBe(1);
    projected.sourceVersions.policy = 999;
    expect(f.live.session(f.a)!.tests[0].source_versions.policy).toBe(2);
  });

  it('refuses test-work evidence changes when paused, submitted, unadopted or storage failed', async () => {
    const f = await setup(); const run = await f.live.test(f.a, f.input());
    const evidence = { id: run.id, version: run.configVersion, type: 'test' };
    const activeWorld = f.live.session(f.a)!.world;
    const initial = structuredClone(f.work);
    for (const status of ['paused', 'submitted'] as const) {
      f.live.store.update(f.a.id, { world: { ...activeWorld, status } });
      expect(() => f.live.engine.addEvidence(f.a, f.work.id, evidence)).toThrow(/只读/);
      expect(f.work).toEqual(initial);
    }
    f.live.store.update(f.a.id, { world: activeWorld });
    f.work.adopted = false;
    expect(() => f.live.engine.addEvidence(f.a, f.work.id, evidence)).toThrow(/采用/);
    f.work.adopted = true;
    f.storage.setItem = () => { throw new Error('quota'); };
    f.live.store.update(f.a.id, {});
    expect(() => f.live.engine.addEvidence(f.a, f.work.id, evidence)).toThrow(/存储/);
    expect(f.work).toEqual(initial);
    // Ordinary local notes retain their existing behavior.
    const note = engine.createArtifact(f.a, { title: '普通作品', body: '笔记' });
    expect(() => f.live.engine.addEvidence(f.a, note.id, evidence)).not.toThrow();
    expect(note.evidence).toHaveLength(1);
  });

  it('refuses unadopted, mismatched or stale row associations without sending', async () => {
    const f = await setup(); const original = f.input();
    f.work.adopted = false; await expect(f.live.test(f.a, original)).rejects.toThrow(/采用/); f.work.adopted = true;
    for (const changed of [{ workId: 'missing' }, { caseId: 'missing' }, { workRevision: 0 }, { caseRevision: 2 }, { question: '其他问题' }, { expectation: '其他预期' }, { taskId: f.a.tasks[1].id }]) {
      await expect(f.live.test(f.a, { ...original, ...changed })).rejects.toThrow(/测试行/);
    }
    expect(f.transport.mock.calls.some(([p, body]) => p.endsWith('/tests') && body !== undefined)).toBe(false);
  });

  it('blocks new runs and evidence for removed work while keeping ordinary single tests usable', async () => {
    const f = await setup(); const run = await f.live.test(f.a, f.input());
    engine.removeArtifact(f.a, f.work.id);
    const removed = structuredClone(f.work);
    await expect(f.live.test(f.a, f.input())).rejects.toThrow(/已移除/);
    expect(() => f.live.engine.addEvidence(f.a, f.work.id, { id: run.id, version: run.configVersion, type: 'test' })).toThrow(/已移除/);
    expect(f.work).toEqual(removed);
    const note = engine.createArtifact(f.a, { title: '待移除笔记', body: '普通正文' });
    engine.removeArtifact(f.a, note.id);
    expect(() => f.live.engine.addEvidence(f.a, note.id, { id: 'policy', version: 1, type: 'material' })).toThrow(/已移除/);
    const ordinary = await f.live.test(f.a, { question: '普通问题' });
    expect(ordinary.workId).toBeUndefined();
    expect(f.transport.mock.calls.filter(([p, body]) => p.endsWith('/tests') && body !== undefined)).toHaveLength(2);
    engine.restoreArtifact(f.a, f.work.id);
    const restoredRun = await f.live.test(f.a, f.input());
    expect(restoredRun.workId).toBe(f.work.id);
  });

  it('recovers an existing pending test after its work is removed without restoring the work', async () => {
    const f = await setup(); f.controls.drop = true;
    await expect(f.live.test(f.a, f.input())).rejects.toThrow(/lost response/);
    const pending = structuredClone(f.live.session(f.a)!.pending!);
    engine.removeArtifact(f.a, f.work.id);
    const removed = structuredClone(f.work), state = structuredClone(f.state);
    const live = new LiveWorkbench(engine, f.storage, f.transport); live.attach(state, () => {});
    const a = state.attempts.find((x: any) => x.id === f.a.id);
    await live.retry(a);
    expect(f.saved.size).toBe(1);
    expect(f.transport.mock.calls.filter(([p, body]) => p.endsWith('/tests') && body !== undefined)[1][1]).toEqual(pending.body);
    expect(a.tests[0]).toMatchObject({ workId: f.work.id, workRevision: 1, caseId: 'case-a', caseRevision: 1 });
    expect(a.artifacts.find((x: any) => x.id === f.work.id)).toEqual(removed);
    expect(live.session(a)?.pending).toBeUndefined();
    expect(engine.currentArtifacts(a).some((x: any) => x.id === f.work.id)).toBe(false);
  });

  it('excludes removed work and its draft from delivery and new task-package snapshots', async () => {
    const f = await setup();
    const note = engine.createArtifact(f.a, { title: '已移除独有标题', body: '已移除独有正文', taskId: f.work.taskId });
    note.draft = { title: '已移除草稿标题', body: '已移除草稿正文', purpose: note.purpose };
    engine.removeArtifact(f.a, note.id);
    const delivery = f.live.draftFromWorks(f.a);
    const pkg = f.live.package(f.a, null, { record: true, requestId: 'after-removal', artifactIds: [note.id, f.work.id] });
    expect(pkg.artifacts.map((x: any) => x.id)).toEqual([f.work.id]);
    expect(pkg.inputVersions.map((x: any) => x.artifactId)).toEqual([f.work.id]);
    expect(pkg.inputSnapshot.artifacts.map((x: any) => x.artifactId)).toEqual([f.work.id]);
    expect(f.a.exports.at(-1).inputSnapshot.artifacts.map((x: any) => x.artifactId)).toEqual([f.work.id]);
    expect(delivery + JSON.stringify(pkg)).not.toMatch(/已移除独有|已移除草稿/);
    expect(f.a.artifacts.find((x: any) => x.id === note.id).draft.body).toBe('已移除草稿正文');
  });

  it('retrieves the exact cited old index version instead of the newer source at test time', async () => {
    const f = await setup(); const run = await f.live.test(f.a, f.input());
    const session = f.live.session(f.a)!;
    const newer = { id: 'policy', version: 2, title: '新政策', content: '400' }, older = { id: 'policy', version: 1, title: '旧政策', content: '500' };
    f.live.store.update(f.a.id, { materials: [newer], tests: session.tests.map(t => ({ ...t, as_of_seq: 5, source_versions: { policy: 2 }, indexed_versions: { policy: 1 }, stale: true })) });
    f.materialHistory.set(5, [newer]); f.materialHistory.set(0, [older]);
    const result = await f.live.citationSource(f.a, run.id, 'policy');
    expect(result).toEqual({ material: older, requestedVersion: 1 });
    const calls = f.transport.mock.calls.filter(([p]) => p.includes('as_of_seq='));
    expect(calls.map(([p]) => p)).toEqual(['/sessions/work-session/materials?as_of_seq=5', '/sessions/work-session/materials?as_of_seq=0']);
    result.material!.content = 'altered locally';
    expect((await f.live.citationSource(f.a, run.id, 'policy')).material!.content).toBe('500');
    expect(f.transport.mock.calls.filter(([p]) => p.includes('as_of_seq='))).toHaveLength(2);
  });

  it('does not invent unknown source versions or permanently cache failed history reads', async () => {
    const f = await setup(); const run = await f.live.test(f.a, f.input());
    const newer = { id: 'policy', version: 2, title: '当前政策', content: '400' };
    f.live.store.update(f.a.id, { materials: [newer] });
    f.materialHistory.set(run.asOfSeq, [newer]); f.materialHistory.set(0, [newer]);
    const unknown = await f.live.citationSource(f.a, run.id, 'policy');
    expect(unknown.material).toBeNull(); expect(unknown.requestedVersion).toBe(1); expect(unknown.reason).toBeTruthy();
    f.historyFailures.add(0);
    expect(await f.live.materialVersion(f.a, 'policy', 1)).toBeNull();
    f.historyFailures.delete(0);
    f.materialHistory.set(0, [{ id: 'policy', version: 1, title: '旧政策', content: '500' }]);
    expect((await f.live.citationSource(f.a, run.id, 'policy')).material?.version).toBe(1);
  });

  it('uses a visible activation snapshot for an intermediate version and rejects unreadable references', async () => {
    const f = await setup(); const run = await f.live.test(f.a, f.input());
    const session = f.live.session(f.a)!;
    f.live.store.update(f.a.id, { world: { ...session.world, version: 9 }, materials: [{ id: 'policy', version: 3, title: '政策三版', content: '300' }], timeline: { ...session.timeline, events: [{ seq: 4, event_type: 'policy_updated', actor_id: 'learner', payload: { material_versions: [{ material_id: 'policy', version: 2 }] } }] } });
    f.materialHistory.set(9, [{ id: 'policy', version: 3, title: '政策三版', content: '300' }]);
    f.materialHistory.set(4, [{ id: 'policy', version: 2, title: '政策二版', content: '400' }]);
    expect((await f.live.materialVersion(f.a, 'policy', 2))?.content).toBe('400');
    const before = f.transport.mock.calls.length;
    await expect(f.live.citationSource(f.a, 'another-session-run', 'policy')).rejects.toThrow(/当前会话/);
    await expect(f.live.citationSource(f.a, run.id, 'tech_private')).rejects.toThrow(/引用/);
    await expect(f.live.materialVersion(f.a, 'tech_private', 1)).rejects.toThrow(/不可读取/);
    await expect(f.live.materialVersion(f.a, 'policy', 4)).rejects.toThrow(/不可读取/);
    await expect(f.live.materialVersion({ ...f.a, id: 'other-session' }, 'policy', 1)).rejects.toThrow(/不可读取/);
    expect(f.transport.mock.calls.length).toBe(before);
  });

  it('restores investigation retests to their original block after the view changes', async () => {
    const f = await setup(); const baseline = await f.live.test(f.a, f.input());
    const inv = investigation(f, baseline.id); f.controls.drop = true;
    await expect(f.live.test(f.a, inv.input())).rejects.toThrow(/lost response/);
    const pending = structuredClone(f.live.session(f.a)!.pending!);
    expect(pending.localRun).toMatchObject({ investigationId: inv.work.id, investigationRevision: 1, blockId: 'retest-block', blockRevision: 1, baselineRunId: baseline.id });
    expect(pending.localRun?.workId).toBeUndefined(); expect(pending.localRun?.caseId).toBeUndefined();
    inv.work.revision++; inv.work.blocks[0].revision++; inv.work.blocks[0].label = '新的标签';
    const state = structuredClone(f.state), restored = new LiveWorkbench(engine, f.storage, f.transport); restored.attach(state, () => {});
    const a = state.attempts.find((x: any) => x.id === f.a.id); await restored.retry(a);
    expect(f.saved.size).toBe(2);
    expect(a.tests.at(-1)).toMatchObject({ investigationId: inv.work.id, investigationRevision: 1, blockId: 'retest-block', blockRevision: 1, baselineRunId: baseline.id, question: baseline.question });
    expect(f.transport.mock.calls.filter(([p, body]) => p.endsWith('/tests') && body !== undefined).at(-1)?.[1]).toEqual(pending.body);
    expect(a.artifacts.find((w: any) => w.id === inv.work.id).revision).toBe(2);
  });

  it('refuses stale, unadopted, removed or forged investigation retest associations', async () => {
    const f = await setup(); const baseline = await f.live.test(f.a, f.input()); const inv = investigation(f, baseline.id);
    for (const override of [{ investigationRevision: 0 }, { blockRevision: 2 }, { blockId: 'unknown' }, { baselineRunId: 'other-session-run' }, { question: 'different question' }, { taskId: f.a.tasks[1].id }]) await expect(f.live.test(f.a, { ...inv.input(), ...override })).rejects.toThrow(/调查视图/);
    inv.work.adopted = false; await expect(f.live.test(f.a, inv.input())).rejects.toThrow(/调查视图/); inv.work.adopted = true;
    inv.work.removedAt = 'removed'; await expect(f.live.test(f.a, inv.input())).rejects.toThrow(/调查视图/); inv.work.removedAt = null;
    inv.work.blocks[0].type = 'note'; await expect(f.live.test(f.a, inv.input())).rejects.toThrow(/调查视图/); inv.work.blocks[0].type = 'retest';
    await expect(f.live.test(f.a, { ...inv.input(), ...f.input() })).rejects.toThrow(/一个作品入口/);
    expect(f.transport.mock.calls.filter(([p, body]) => p.endsWith('/tests') && body !== undefined)).toHaveLength(1);
  });

  it('exports only selected investigation materials with real current or cached exact bodies', async () => {
    const f = await setup(); const baseline = await f.live.test(f.a, f.input()); const inv = investigation(f, baseline.id);
    const newer = { id: 'policy', version: 2, title: '新政策', content: '400' };
    f.live.store.update(f.a.id, { materials: [newer] });
    inv.work.blocks.push({ id: 'source-current', revision: 1, type: 'source_check', testId: baseline.id, material: { id: 'policy', version: 2 } });
    const selected = { artifactIds: [inv.work.id] };
    expect(f.live.package(f.a, null, selected).materials.map((m: any) => m.version)).toEqual([2]);
    expect(f.live.package(f.a, null, { ...selected, materialIds: [] }).materials).toEqual([]);
    expect(f.live.package(f.a, null, { artifactIds: [] }).materials).toEqual([]);
    inv.work.blocks[1].material.version = 1;
    expect(f.live.package(f.a, null, selected).materials).toEqual([]);
    f.materialHistory.set(0, [{ id: 'policy', version: 1, title: '旧政策', content: '500' }]);
    await f.live.materialVersion(f.a, 'policy', 1);
    const pkg = f.live.package(f.a, null, selected);
    expect(pkg.materials).toEqual([{ id: 'policy', version: 1, title: '旧政策', content: '500' }]);
    expect(pkg.inputSnapshot.materials).toEqual([{ id: 'policy', version: 1 }]);
    inv.work.blocks.push({ id: 'private', revision: 1, type: 'source_check', testId: baseline.id, material: { id: 'tech_private', version: 1 } });
    expect(JSON.stringify(f.live.package(f.a, null, selected).materials)).not.toContain('tech_private');
  });

  it('keeps the work intact after a configuration conflict and does not silently resubmit', async () => {
    const f = await setup(), before = structuredClone(f.work); f.controls.conflict = true;
    await expect(f.live.test(f.a, f.input())).rejects.toThrow(/重新操作/);
    expect(f.live.session(f.a)?.pending).toBeUndefined(); expect(f.a.tests).toEqual([]); expect(f.work).toEqual(before);
    expect(f.transport.mock.calls.filter(([p, body]) => p.endsWith('/tests') && body !== undefined)).toHaveLength(1);
  });

  it('retains the ordinary single-question path and blocks read-only or unavailable storage', async () => {
    const f = await setup();
    const run = await f.live.test(f.a, { question: '普通问题', expectation: '普通预期', taskId: f.work.taskId });
    expect(run).toMatchObject({ question: '普通问题', expectation: '普通预期', taskId: f.work.taskId, config });
    expect(run.workId).toBeUndefined();
    const session = f.live.session(f.a)!;
    f.live.store.update(f.a.id, { world: { ...session.world, status: 'submitted' } });
    await expect(f.live.test(f.a, f.input())).rejects.toThrow(/锁定/);
    f.live.store.update(f.a.id, { world: { ...session.world, status: 'active', configs: {} } });
    await expect(f.live.test(f.a, f.input())).rejects.toThrow(/配置/);
    f.live.store.update(f.a.id, { world: session.world });
    f.storage.setItem = () => { throw new Error('quota'); };
    await expect(f.live.test(f.a, f.input())).rejects.toThrow(/存储/);
    expect(f.transport.mock.calls.filter(([p, body]) => p.endsWith('/tests') && body !== undefined)).toHaveLength(1);
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
  it('keeps test-work and investigation provenance together with server list recovery', async () => {
    const { live, state, storage, real } = setup();
    const a = await live.start('pilot'); await live.config(a, config);
    const work = engine.createArtifact(a, { kind: 'test_set', title: '整合验证', purpose: '测试计划', taskId: a.tasks[1].id, cases: [{ question: '住宿报销上限是多少？', intent: '核对政策来源', expectation: '引用实际政策', refs: [] }] });
    const row = work.cases[0];
    const first = await live.test(a, { question: row.question, expectation: row.expectation, taskId: work.taskId, workId: work.id, workRevision: work.revision, caseId: row.id, caseRevision: row.revision });
    const investigation = engine.createArtifact(a, { kind: 'investigation', title: '整合后的来源核对', purpose: '探索笔记', question: '回答用了哪一版？', taskId: work.taskId, blocks: [{ type: 'source_check', testId: first.id, material: { id: 'policy', version: a.world.policyVersion } }, { type: 'retest', testId: first.id }] });
    const block = investigation.blocks[1];
    const rerun = await live.test(a, { question: first.question, expectation: first.expectation, taskId: work.taskId, investigationId: investigation.id, investigationRevision: investigation.revision, blockId: block.id, blockRevision: block.revision, baselineRunId: first.id });
    const restored = new LiveWorkbench(engine, storage, real), restoredState = structuredClone(state);
    restored.attach(restoredState, () => {}); await restored.store.sync(a.id);
    const recovered = restoredState.attempts.find((item: any) => item.id === a.id);
    expect(recovered.tests).toHaveLength(2);
    expect(recovered.tests.find((run: any) => run.id === first.id)).toMatchObject({ workId: work.id, caseId: row.id, question: row.question });
    expect(recovered.tests.find((run: any) => run.id === rerun.id)).toMatchObject({ investigationId: investigation.id, blockId: block.id, baselineRunId: first.id });
    expect(recovered.tests.every((run: any) => run.createdAt.endsWith('Z'))).toBe(true);
    expect((await restored.citationSource(recovered, first.id, 'policy')).material?.version).toBe(first.citations.find((ref: any) => ref.id === 'policy').version);
    expect(restored.store.getSnapshot().error).toBe('');
  }, 20000);

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
    const minimal = { ...session, materials: [], tests: [], testNotes: {}, testRunMeta: {}, questions: {}, timeline: { events: [], turns: [], mode: '' } };
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
