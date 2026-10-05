import { request, sessionPath, type Transport } from './api';
import { blankPilot, WorkspaceStore } from './store';
import type { Deliverable, LocalSession, Pilot, RoleId, Scenario } from './types';

// The HTML workbench owns local notes; WorkspaceStore owns all server authority.
// No credential is copied into an attempt, task package, screenshot or export.
type Attempt = any;
type Engine = Record<string, (...args: any[]) => any> & Record<string, any>;
const scenarios: Record<string, Scenario> = { pilot: 'pm_pilot', urgent: 'pm_pilot_urgent', capacity: 'pm_pilot_capacity15' };
export const roleIds: Record<string, RoleId> = { manager: 'supervisor', business: 'business_lead', technical: 'tech_lead' };
const workIds: Record<string, string> = { scope: 'scope_filter', fallback: 'human_fallback', realtime: 'realtime_sync' };
export const fromPilot = (p: Pilot) => ({ participants: p.participants, domains: p.knowledge_domains.map(d => d === 'stable_faq' ? 'faq' : d), update: p.update_strategy === 'manual_policy' ? 'manual' : p.update_strategy, fallback: p.fallback, workItems: p.work_items.map(w => Object.keys(workIds).find(k => workIds[k] === w) || w), launchDay: p.launch_day });
export function toPilot(c: any): Pilot {
  if (!['daily', 'realtime', 'manual'].includes(c.update) || !['human', 'none'].includes(c.fallback)) throw new Error('这项设置没有对应的后端接口。');
  if (c.domains.some((d: string) => !['faq', 'policy'].includes(d)) || c.workItems.some((w: string) => !workIds[w])) throw new Error('未知知识范围或工作项。');
  return { participants: c.participants, knowledge_domains: c.domains.map((d: string) => d === 'faq' ? 'stable_faq' : d), launch_day: c.launchDay, update_strategy: c.update === 'manual' ? 'manual_policy' : c.update, fallback: c.fallback, work_items: c.workItems.map((w: string) => workIds[w]) };
}

export class LiveWorkbench {
  readonly store: WorkspaceStore;
  readonly engine: Engine;
  private state: any;
  private notify = (_changed: boolean) => {};
  private signature = '';
  private metadata = new Map<string, { taskId?: string; config?: any; createdAt?: string }>();
  constructor(readonly base: Engine, storage: Pick<Storage, 'getItem' | 'setItem'>, private transport: Transport = request) {
    this.store = new WorkspaceStore(storage, transport);
    this.engine = { ...base,
      scenarios: base.scenarios.map((s: any) => s.id === 'urgent' ? { ...s, deadline: 5 } : s),
      getMaterials: (a: Attempt) => a.backend?.materials || [],
      maybeTriggerEvents: () => false, checkCommitment: () => {}, checkFocus: () => {},
      coach: () => ({ items: [] }), review: () => ({ observations: [] }),
      preparePackage: (a: Attempt, taskId: string | null, scope: any) => this.package(a, taskId, scope),
      addEvidence: (a: Attempt, id: string, ev: any) => this.addEvidence(a, id, ev),
    };
    // Some local editing methods call simulation helpers internally. Strip those
    // synthetic colleague messages instead of displaying them beside real turns.
    for (const name of ['saveArtifact', 'moveTask', 'restoreOrder', 'adoptArtifact', 'updateTask']) {
      this.engine[name] = (...args: any[]) => {
        const result = base[name](...args);
        args[0].nudges = [];
        args[0].events = args[0].events.filter((e: any) => !['colleague_note', 'colleague_nudged', 'nudge'].includes(e.type));
        for (const role of Object.keys(roleIds)) args[0].conversations[role] = args[0].conversations[role].filter((m: any) => m.mode !== 'simulated');
        return result;
      };
    }
    for (const name of ['runTest', 'reply', 'updateConfig', 'refreshIndex', 'requestResources', 'resolveResources', 'triggerPolicyUpdate', 'submit', 'revise', 'suggestPriorities', 'readMaterial', 'applySuggestion']) {
      this.engine[name] = () => { throw new Error('此操作必须由后端确认；没有切换为本地模拟。'); };
    }
    this.store.subscribe(() => this.changed());
  }
  attach(state: any, notify: (changed: boolean) => void) {
    this.state = state; this.notify = notify;
    const snap = this.store.getSnapshot();
    for (const s of snap.workspace.sessions) this.ensureAttempt(s);
    if (!state.activeId && snap.workspace.active) state.activeId = snap.workspace.active;
    if (state.activeId && snap.workspace.sessions.some(s => s.id === state.activeId)) this.store.select(state.activeId);
    this.changed();
  }
  private ensureAttempt(s: LocalSession, opts?: any) {
    let a = this.state.attempts.find((x: Attempt) => x.id === s.id);
    if (!a) {
      const previous = this.state.activeId;
      a = this.base.createAttempt(this.state, Object.keys(scenarios).find(k => scenarios[k] === s.scenario), opts);
      a.id = s.id; a.createdAt = s.created; a.selectedTaskId = null; a.nudges = [];
      a.events = []; // Seed cards are local organization, not server actions.
      this.state.activeId = previous;
    }
    return a;
  }
  private changed() {
    if (!this.state) return;
    const snap = this.store.getSnapshot();
    for (const s of snap.workspace.sessions) this.project(this.ensureAttempt(s), s);
    const signature = JSON.stringify(snap.workspace.sessions.map(s => [s.id, s.world, s.materials, s.timeline, s.tests, s.feedback, s.pending?.jobId, s.pending?.job?.status, !!s.pending, s.feedbackFailure, s.failedTurn]));
    const changed = signature !== this.signature; this.signature = signature;
    this.notify(changed);
  }
  project(a: Attempt, s: LocalSession) {
    const w = s.world;
    a.world = { capacity: w.resources.capacity, devDays: w.resources.dev_days, deadline: w.resources.deadline_day, policyVersion: w.material_versions.policy, indexVersion: w.indexed_versions.policy };
    a.config = fromPilot(w.configs.pilot || blankPilot()); a.configVersion = w.config_version;
    a.configDraft = s.configDraft ? fromPilot(s.configDraft) : null;
    a.backend = { status: w.status, version: w.version, configured: !!w.configs.pilot, materials: s.materials.map(m => ({ ...m, body: m.content })), pendingRequests: w.pending_requests, submissionId: this.store.submissionId(s) };
    a.nudges = [];
    a.tests = s.tests.map(t => {
      const previous = a.tests.find((p: any) => p.id === t.id) || {};
      const meta = this.metadata.get(t.id) || previous;
      return { id: t.id, question: t.query, answer: t.answer, citations: t.citations.map(c => ({ id: c.material_id, version: c.version, title: s.materials.find(m => m.id === c.material_id)?.title || c.material_id })), expectation: s.testNotes[t.id]?.expected || '', policyVersion: t.source_versions.policy, indexVersion: t.indexed_versions.policy, configVersion: t.config_version, config: meta.config || null, taskId: meta.taskId || null, createdAt: meta.createdAt || '', mode: t.mode, asOfSeq: t.as_of_seq };
    });
    a.conversations = Object.fromEntries(Object.entries(roleIds).map(([role, id]) => [role, s.timeline.turns.filter(t => t.role_id === id).flatMap(t => [
      ...(s.questions[t.trace_id] ? [{ role: 'user', text: s.questions[t.trace_id], createdAt: '' }] : []),
      { role: 'colleague', text: t.text, createdAt: '', model: t.model_revision, traceId: t.trace_id },
    ])]));
    // Server events are projected separately from local editing events.
    a.events = a.events.filter((e: any) => !e.server && !['colleague_note', 'colleague_nudged', 'nudge'].includes(e.type));
    for (const e of s.timeline.events) a.events.push({ id: 'server-' + e.seq, server: true, type: e.event_type === 'read_material' ? 'material_read' : e.event_type, text: '后端 · ' + e.event_type + ' · #' + e.seq, createdAt: '', detail: { ...e.payload, materialId: e.payload.material_id }, seq: e.seq });
    a.requests = w.pending_requests.map(id => ({ id, status: 'pending', reason: id === 'capacity_approved' ? '扩容申请' : '资源与延期申请' }));
    a.submissions = this.store.submissionId(s) ? [{ id: this.store.submissionId(s), createdAt: '', artifacts: [] }] : [];
  }
  session(a?: Attempt) { return a ? this.store.getSnapshot().workspace.sessions.find(s => s.id === a.id) : this.store.active(); }
  async start(caseId: string, opts?: any) {
    if (!scenarios[caseId]) throw new Error('后端不支持这个情境。');
    const id = await this.store.create(scenarios[caseId]);
    if (!id) throw new Error(this.store.getSnapshot().error || '会话未创建。');
    const a = this.ensureAttempt(this.store.active()!, opts); if (opts) Object.assign(a, opts);
    this.state.activeId = id; this.project(a, this.store.active()!); return a;
  }
  select(a: Attempt) { if (!this.session(a)) throw new Error('找不到会话凭据，请保留原浏览器存档。'); this.store.select(a.id); }
  async perform(a: Attempt, fn: () => Promise<unknown> | undefined, allowSubmitted = false) {
    this.select(a);
    const s = this.session(a)!; const snap = this.store.getSnapshot();
    if (snap.busy || s.pending) throw new Error('上一请求还未确认，请先等待或重试原请求。');
    if (snap.storageError) throw new Error('存储不可用，已暂停服务端写入。');
    if (!allowSubmitted && s.world.status !== 'active') throw new Error(s.world.status === 'submitted' ? '这次交付已锁定。可以查看反馈，或新建练习。' : '练习已暂停，请先恢复。');
    await fn(); this.changed();
    const after = this.store.getSnapshot();
    if (after.error) throw new Error(after.error);
  }
  async action(a: Attempt, tool: string, args: Record<string, unknown> = {}) { await this.perform(a, () => this.store.action(tool, args), tool === 'resume'); }
  async read(a: Attempt, materialId: string) {
    if (!a.backend.materials.some((m: any) => m.id === materialId)) throw new Error('当前会话不可读取这份资料。');
    if (this.session(a)!.world.status === 'active') await this.action(a, 'read_material', { material_id: materialId });
    else await this.store.sync(a.id); // Paused/submitted sessions remain readable; do not invent a read event.
  }
  async config(a: Attempt, c: any) {
    const plan = toPilot(c); this.select(a); this.store.update(a.id, { configDraft: plan });
    await this.action(a, 'update_pilot', { plan });
  }
  async test(a: Attempt, input: any) {
    if (!a.backend.configured) throw new Error('先打开“试点设置”并应用一次配置，再测试助手。');
    const s = this.session(a)!; const before = new Set(s.tests.map(t => t.id));
    const config = structuredClone(a.config); const stamp = new Date().toISOString();
    this.store.update(a.id, { inputs: { ...s.inputs, expected: input.expectation || '' } });
    await this.perform(a, () => this.store.test(input.question));
    const t = this.session(a)!.tests.find(t => !before.has(t.id));
    if (!t) throw new Error('测试尚未获确认，请重试原请求。');
    this.metadata.set(t.id, { taskId: input.taskId, config, createdAt: stamp }); this.changed();
    return a.tests.find((x: any) => x.id === t.id);
  }
  async turn(a: Attempt, role: string, text: string) {
    if (!roleIds[role] || !text.trim() || text.length > 4000) throw new Error('消息需要 1–4000 个字符。');
    await this.perform(a, () => this.store.sendTurn(roleIds[role], text));
    const s = this.session(a)!;
    this.store.update(a.id, { inputs: { ...s.inputs, messages: { ...s.inputs.messages, [roleIds[role]]: '' } } });
  }
  async save(a: Attempt, draft: Deliverable) { this.store.update(a.id, { draft }); await this.perform(a, () => this.store.saveArtifact()); }
  async submit(a: Attempt) { await this.perform(a, () => this.store.submit()); }
  async feedback(a: Attempt) {
    if (!this.store.submissionId(this.session(a)!)) throw new Error('正式交付后才可生成后端反馈。');
    await this.perform(a, () => this.store.feedback(), true);
  }
  async savedFeedback(a: Attempt) {
    const s = this.session(a)!; const id = this.store.submissionId(s);
    if (!id) throw new Error('尚无正式交付。');
    const feedback = await this.transport(sessionPath(s, '/feedback/' + encodeURIComponent(id)), undefined, s);
    this.store.update(s.id, { feedback }); return feedback;
  }
  async history(a: Attempt, seq?: number) { const s = this.session(a)!; return this.transport(sessionPath(s, '/materials' + (seq === undefined ? '' : '?as_of_seq=' + seq)), undefined, s); }
  async evidence(a: Attempt, criterion: string, id: string) { const s = this.session(a)!; return this.transport(sessionPath(s, '/evidence/' + [this.store.submissionId(s), criterion, id].map(encodeURIComponent).join('/')), undefined, s); }
  async relation(a: Attempt, claim: string) { await this.perform(a, () => this.store.relation(claim), true); }
  async retry(a: Attempt) { this.select(a); await this.store.execute(a.id); }
  async refresh(a?: Attempt) { await this.store.health(); if (a) await this.store.sync(a.id); }
  draftFromWorks(a: Attempt) {
    const list = this.base.currentArtifacts(a);
    return list.map((x: any) => {
      const view = x.draft ? { ...x, ...x.draft } : x;
      return '## ' + view.title + '（' + view.purpose + '，v' + x.revision + (x.draft ? ' 后的草稿' : '') + '）\n' + view.body + (x.evidence.length ? '\n依据：' + x.evidence.map((e: any) => e.title + ' [' + e.id + '@' + e.version + ']').join('；') : '');
    }).join('\n\n');
  }
  private addEvidence(a: Attempt, artifactId: string, ev: any) {
    const target = a.artifacts.find((x: any) => x.id === artifactId);
    const actual = ev.type === 'test' ? a.tests.find((x: any) => x.id === ev.id && x.configVersion === ev.version) : a.backend.materials.find((x: any) => x.id === ev.id && x.version === ev.version);
    if (!target || !actual) throw new Error('只能引用当前会话实际返回的资料或测试。');
    const safe = { id: actual.id, title: ev.type === 'test' ? '测试：' + actual.question : actual.title, version: ev.version, body: ev.type === 'test' ? actual.answer : actual.body, type: ev.type };
    if (!target.evidence.some((e: any) => e.id === safe.id && e.version === safe.version)) target.evidence.push(safe);
  }
  package(a: Attempt, taskId: string | null, scope: any = {}) {
    const read = new Set(['brief', ...a.events.filter((e: any) => e.server && e.type === 'material_read').map((e: any) => e.detail.materialId)]);
    const artifacts = this.base.currentArtifacts(a).filter((x: any) => (!taskId || x.taskId === taskId) && (!scope.artifactIds || scope.artifactIds.includes(x.id)));
    const requestId = scope.requestId || crypto.randomUUID();
    const inputVersions = artifacts.map((x: any) => ({ artifactId: x.id, revision: x.revision }));
    const result = structuredClone({ schema: 'practice-task-package/v1', requestId, mode: 'backend-evidence-local-notes', exportedAt: new Date().toISOString(), scenario: { id: a.scenarioId, title: a.title }, task: a.tasks.find((t: any) => t.id === taskId) || null, materials: a.backend.materials.filter((m: any) => read.has(m.id) && (!scope.materialIds || scope.materialIds.includes(m.id))), artifacts, tests: a.tests.filter((t: any) => !scope.testIds || scope.testIds.includes(t.id)), inputVersions, instructions: '仅用本包可见资料。作品回传是本地草稿，不批准资源、不执行动作；结论必须核查。', returnFormat: { requestId, artifact: { title: '作品标题', purpose: '自由作品', body: 'Markdown 正文' } } });
    if (scope.record) { a.exports ||= []; a.exports.push({ requestId, taskId, inputVersions, createdAt: result.exportedAt }); }
    return result;
  }
}
