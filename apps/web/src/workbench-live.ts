import { request, sessionPath, type Transport } from './api';
import { T } from './app/i18n';
import { blankPilot, WorkspaceStore } from './store';
import type { Deliverable, LocalSession, Material, Pilot, RoleId, Scenario, TestRunOrigin } from './types';

// The HTML workbench owns local notes; WorkspaceStore owns all server authority.
// No credential is copied into an attempt, task package, screenshot or export.
type Attempt = any;
type Engine = Record<string, (...args: any[]) => any> & Record<string, any>;
const scenarios: Record<string, Scenario> = { pilot: 'pm_pilot', urgent: 'pm_pilot_urgent', capacity: 'pm_pilot_capacity15' };
export const roleIds: Record<string, RoleId> = { manager: 'supervisor', business: 'business_lead', technical: 'tech_lead' };
const workIds: Record<string, string> = { scope: 'scope_filter', fallback: 'human_fallback', realtime: 'realtime_sync' };
export const fromPilot = (p: Pilot) => ({ participants: p.participants, domains: p.knowledge_domains.map(d => d === 'stable_faq' ? 'faq' : d), update: p.update_strategy === 'manual_policy' ? 'manual' : p.update_strategy, fallback: p.fallback, workItems: p.work_items.map(w => Object.keys(workIds).find(k => workIds[k] === w) || w), launchDay: p.launch_day });
export function toPilot(c: any): Pilot {
  if (!['daily', 'realtime', 'manual'].includes(c.update) || !['human', 'none'].includes(c.fallback)) throw new Error(T('这项设置没有对应的后端接口。', 'This setting has no server equivalent.'));
  if (c.domains.some((d: string) => !['faq', 'policy'].includes(d)) || c.workItems.some((w: string) => !workIds[w])) throw new Error(T('未知知识范围或工作项。', 'Unknown knowledge area or work item.'));
  return { participants: c.participants, knowledge_domains: c.domains.map((d: string) => d === 'faq' ? 'stable_faq' : d), launch_day: c.launchDay, update_strategy: c.update === 'manual' ? 'manual_policy' : c.update, fallback: c.fallback, work_items: c.workItems.map((w: string) => workIds[w]) };
}

export class LiveWorkbench {
  readonly store: WorkspaceStore;
  readonly fromPilot = fromPilot;
  readonly engine: Engine;
  private state: any;
  private notify = (_changed: boolean) => {};
  private signature = '';
  private materialCache = new Map<string, Material>();
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
    for (const name of ['runTest', 'reply', 'updateConfig', 'refreshIndex', 'requestResources', 'resolveResources', 'triggerPolicyUpdate', 'submit', 'revise', 'suggestPriorities', 'readMaterial']) {
      this.engine[name] = () => { throw new Error(T('此操作必须由后端确认；没有切换为本地模拟。', 'This must be confirmed by the server; nothing was simulated locally.')); };
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
    const signature = JSON.stringify(snap.workspace.sessions.map(s => [s.id, s.world, s.materials, s.timeline, s.tests, s.testNotes, s.testRunMeta, s.feedback, s.pending?.jobId, s.pending?.job?.status, !!s.pending, s.feedbackFailure, s.failedTurn]));
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
      const saved = s.testRunMeta?.[t.id];
      const meta = saved || previous;
      return { id: t.id, question: t.query, answer: t.answer, citations: t.citations.map(c => ({ id: c.material_id, version: c.version, title: s.materials.find(m => m.id === c.material_id)?.title || c.material_id })), expectation: s.testNotes[t.id]?.expected ?? saved?.expectation ?? '', diagnosis: s.testNotes[t.id]?.diagnosis || '', policyVersion: t.source_versions.policy, indexVersion: t.indexed_versions.policy, sourceVersions: { ...t.source_versions }, indexedVersions: { ...t.indexed_versions }, configVersion: t.config_version, config: saved ? (saved.config ? fromPilot(saved.config) : null) : previous.config || null, taskId: meta.taskId || null, createdAt: meta.createdAt || '', workId: meta.workId, workRevision: meta.workRevision, caseId: meta.caseId, caseRevision: meta.caseRevision, investigationId: meta.investigationId, investigationRevision: meta.investigationRevision, blockId: meta.blockId, blockRevision: meta.blockRevision, baselineRunId: meta.baselineRunId, requestId: meta.requestId, intent: meta.intent || '', refs: meta.refs || [], mode: t.mode, asOfSeq: t.as_of_seq, fallback: t.fallback, stale: t.stale };
    });
    a.conversations = Object.fromEntries(Object.entries(roleIds).map(([role, id]) => [role, s.timeline.turns.filter(t => t.role_id === id).flatMap(t => [
      ...(s.questions[t.trace_id] ? [{ role: 'user', text: s.questions[t.trace_id], createdAt: '' }] : []),
      { role: 'colleague', text: t.text, createdAt: '', model: t.model_revision, traceId: t.trace_id },
    ])]));
    // Server events are projected separately from local editing events. Local ordering
    // (applySuggestion, moveTask) stays allowed: it never touches server authority.
    a.events = a.events.filter((e: any) => !e.server && !['colleague_note', 'colleague_nudged', 'nudge'].includes(e.type));
    for (const e of s.timeline.events) a.events.push({ id: 'server-' + e.seq, server: true, type: e.event_type === 'read_material' ? 'material_read' : e.event_type, text: '后端 · ' + e.event_type + ' · #' + e.seq, createdAt: '', detail: { ...e.payload, materialId: e.payload.material_id }, seq: e.seq });
    a.requests = w.pending_requests.map(id => ({ id, status: 'pending', reason: id === 'capacity_approved' ? '扩容申请' : '资源与延期申请' }));
    a.submissions = this.store.submissionId(s) ? [{ id: this.store.submissionId(s), createdAt: '', artifacts: [] }] : [];
  }
  session(a?: Attempt) { return a ? this.store.getSnapshot().workspace.sessions.find(s => s.id === a.id) : this.store.active(); }
  async start(caseId: string, opts?: any) {
    if (!scenarios[caseId]) throw new Error(T('后端不支持这个情境。', 'The server does not support this situation.'));
    const id = await this.store.create(scenarios[caseId]);
    if (!id) throw new Error(this.store.getSnapshot().error || T('会话未创建。', 'The session was not created.'));
    const a = this.ensureAttempt(this.store.active()!, opts); if (opts) Object.assign(a, opts);
    this.state.activeId = id; this.project(a, this.store.active()!); return a;
  }
  select(a: Attempt) { if (!this.session(a)) throw new Error(T('找不到会话凭据，请保留原浏览器存档。', 'Session credentials are missing. Keep the original browser data.')); this.store.select(a.id); }
  async perform(a: Attempt, fn: () => Promise<unknown> | undefined, allowSubmitted = false) {
    this.select(a);
    const s = this.session(a)!; const snap = this.store.getSnapshot();
    if (snap.busy || s.pending) throw new Error(T('上一请求还未确认，请先等待或重试原请求。', 'The previous request is not confirmed yet. Wait, or retry it.'));
    if (snap.storageError) throw new Error(T('存储不可用，已暂停服务端写入。', 'Storage is unavailable, so server writes are paused.'));
    if (!allowSubmitted && s.world.status !== 'active') throw new Error(s.world.status === 'submitted' ? T('这次交付已锁定。可以查看反馈，或新建练习。', 'This submission is locked. Read the review or start a new practice.') : T('练习已暂停，请先恢复。', 'The practice is paused. Resume it first.'));
    await fn(); this.changed();
    const after = this.store.getSnapshot();
    if (after.error) throw new Error(after.error);
  }
  async action(a: Attempt, tool: string, args: Record<string, unknown> = {}) { await this.perform(a, () => this.store.action(tool, args), tool === 'resume'); }
  async read(a: Attempt, materialId: string) {
    if (!a.backend.materials.some((m: any) => m.id === materialId)) throw new Error(T('当前会话不可读取这份资料。', 'This document is not available in this session.'));
    if (this.session(a)!.world.status === 'active') await this.action(a, 'read_material', { material_id: materialId });
    else await this.store.sync(a.id); // Paused/submitted sessions remain readable; do not invent a read event.
  }
  async config(a: Attempt, c: any) {
    const plan = toPilot(c); this.select(a); this.store.update(a.id, { configDraft: plan });
    await this.action(a, 'update_pilot', { plan });
  }
  async test(a: Attempt, input: any) {
    const s = this.session(a);
    if (!s?.world.configs.pilot) throw new Error(T('先打开“试点设置”并应用一次配置，再测试助手。', 'Save the pilot settings once before testing the assistant.'));
    if (typeof input.question !== 'string' || !input.question.trim() || Array.from(input.question).length > 4000 || (input.expectation != null && typeof input.expectation !== 'string')) throw new Error(T('测试问题需要 1–4000 个字符，预期表现需要是文字。', 'The question needs 1–4,000 characters and its expectation must be text.'));
    const origin: TestRunOrigin & { expectation: string } = { taskId: input.taskId || null, expectation: input.expectation || '' };
    if (origin.taskId && !a.tasks.some((t: any) => t.id === origin.taskId)) throw new Error(T('找不到测试所属的事项。', 'The task for this test was not found.'));
    const linked = ['workId', 'workRevision', 'caseId', 'caseRevision'].some(k => input[k] !== undefined);
    const investigationLinked = ['investigationId', 'investigationRevision', 'blockId', 'blockRevision', 'baselineRunId'].some(k => input[k] !== undefined);
    if (linked && investigationLinked) throw new Error(T('一次测试只能关联一个作品入口。', 'A test can be linked to only one work entry.'));
    if (linked) {
      const work = a.artifacts.find((w: any) => w.id === input.workId);
      if (work?.removedAt) throw new Error(T('作品已移除，请恢复后再发起测试。', 'This work has been removed. Restore it before starting a test.'));
      const row = work?.cases?.find((c: any) => c.id === input.caseId);
      if (!work?.adopted || work.kind !== 'test_set' || !row || work.revision !== input.workRevision || row.revision !== input.caseRevision ||
          !Number.isInteger(input.workRevision) || input.workRevision < 1 || !Number.isInteger(input.caseRevision) || input.caseRevision < 1 ||
          (work.taskId || null) !== origin.taskId || row.question !== input.question || (row.expectation || '') !== origin.expectation) {
        throw new Error(T('测试行或作品已经变化，或尚未采用。请保存并核对当前行后再运行。', 'The test row or work changed, or has not been adopted. Save and check the current row before running it.'));
      }
      Object.assign(origin, { workId: work.id, workRevision: work.revision, caseId: row.id, caseRevision: row.revision, intent: row.intent || '', refs: structuredClone(row.refs || []) });
    }
    if (investigationLinked) {
      const work = a.artifacts.find((w: any) => w.id === input.investigationId);
      const block = work?.blocks?.find((b: any) => b.id === input.blockId);
      const baseline = s.tests.find(t => t.id === input.baselineRunId);
      if (!work?.adopted || work.removedAt || work.kind !== 'investigation' || !block || block.type !== 'retest' || !baseline ||
          block.testId !== baseline.id || baseline.query !== input.question || (work.taskId || null) !== origin.taskId ||
          work.revision !== input.investigationRevision || block.revision !== input.blockRevision ||
          !Number.isInteger(input.investigationRevision) || input.investigationRevision < 1 || !Number.isInteger(input.blockRevision) || input.blockRevision < 1) {
        throw new Error(T('调查视图或重测入口已变化、未采用或不可用。请保存并核对当前入口后重测。', 'The investigation or retest entry changed, has not been adopted, or is unavailable. Save and check it before retesting.'));
      }
      Object.assign(origin, { investigationId: work.id, investigationRevision: work.revision, blockId: block.id, blockRevision: block.revision, baselineRunId: baseline.id, intent: work.question || '' });
    }
    const before = new Set(s.tests.map(t => t.id));
    await this.perform(a, () => this.store.test(input.question, origin));
    const t = this.session(a)!.tests.find(t => !before.has(t.id));
    if (!t) throw new Error(T('测试尚未获确认，请重试原请求。', 'The test is not confirmed yet. Retry the same request.'));
    return a.tests.find((x: any) => x.id === t.id);
  }
  async turn(a: Attempt, role: string, text: string) {
    if (!roleIds[role] || !text.trim() || text.length > 4000) throw new Error(T('消息需要 1–4000 个字符。', 'Messages need 1–4,000 characters.'));
    await this.perform(a, () => this.store.sendTurn(roleIds[role], text));
    const s = this.session(a)!;
    this.store.update(a.id, { inputs: { ...s.inputs, messages: { ...s.inputs.messages, [roleIds[role]]: '' } } });
  }
  async save(a: Attempt, draft: Deliverable) { this.store.update(a.id, { draft }); await this.perform(a, () => this.store.saveArtifact()); }
  async submit(a: Attempt) { await this.perform(a, () => this.store.submit()); }
  async feedback(a: Attempt) {
    if (!this.store.submissionId(this.session(a)!)) throw new Error(T('正式交付后才可生成后端反馈。', 'The review can only be generated after you submit.'));
    await this.perform(a, () => this.store.feedback(), true);
  }
  async savedFeedback(a: Attempt) {
    const s = this.session(a)!; const id = this.store.submissionId(s);
    if (!id) throw new Error(T('尚无正式交付。', 'Nothing has been submitted yet.'));
    const feedback = await this.transport(sessionPath(s, '/feedback/' + encodeURIComponent(id)), undefined, s);
    this.store.update(s.id, { feedback }); return feedback;
  }
  async history(a: Attempt, seq?: number) { const s = this.session(a)!; return this.transport(sessionPath(s, '/materials' + (seq === undefined ? '' : '?as_of_seq=' + seq)), undefined, s); }
  private visibleMaterial(a: Attempt, id: string, version?: number) {
    const s = this.session(a);
    const current = s?.materials.find(m => m.id === id);
    if (!s || !current || (version !== undefined && (!Number.isInteger(version) || version < 1 || version > current.version))) {
      throw new Error(T('当前会话不可读取这个材料版本。', 'This material version is not readable in the current session.'));
    }
    return { s, current };
  }
  private cacheMaterial(sessionId: string, material: Material) {
    this.materialCache.set(JSON.stringify([sessionId, material.id, material.version]), structuredClone(material));
    return structuredClone(material);
  }
  private async exactMaterial(a: Attempt, id: string, version: number, asOfSeq: number): Promise<Material | null> {
    const { s, current } = this.visibleMaterial(a, id, version);
    if (current.version === version) return this.cacheMaterial(s.id, current);
    const cached = this.materialCache.get(JSON.stringify([s.id, id, version]));
    if (cached) return structuredClone(cached);
    const activations = s.timeline.events.filter(e => e.seq <= asOfSeq && Array.isArray(e.payload.material_versions) && e.payload.material_versions.some((v: any) => v.material_id === id && v.version === version)).map(e => e.seq);
    const candidates = [...new Set([asOfSeq, ...activations.reverse(), 0])].filter(seq => Number.isInteger(seq) && seq >= 0);
    for (const seq of candidates) {
      try {
        const materials = await this.history(a, seq);
        const exact = Array.isArray(materials) && materials.find((m: any) => m.id === id && m.version === version && typeof m.content === 'string');
        if (exact) return this.cacheMaterial(s.id, exact);
      } catch { /* A missing snapshot or temporary failure must not substitute another version. */ }
    }
    return null;
  }
  async citationSource(a: Attempt, runId: string, materialId: string) {
    const s = this.session(a);
    const run = s?.tests.find(t => t.id === runId);
    const citation = run?.citations.find(c => c.material_id === materialId);
    if (!s || !run || !citation) throw new Error(T('该引用不属于当前会话的真实测试。', 'This citation is not part of a real test in the current session.'));
    const material = await this.exactMaterial(a, materialId, citation.version, run.as_of_seq);
    return { material, requestedVersion: citation.version, ...(material ? {} : { reason: T('该引用版本的原文暂未取得；没有用其他版本替代。', 'The cited version could not be retrieved. No other version was substituted.') }) };
  }
  async materialVersion(a: Attempt, id: string, version: number): Promise<Material | null> {
    const { s } = this.visibleMaterial(a, id, version);
    return this.exactMaterial(a, id, version, s.world.version);
  }
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
    if (target?.removedAt) throw new Error(T('作品已移除，请恢复后再添加依据。', 'This work has been removed. Restore it before adding evidence.'));
    if (target?.kind === 'test_set') {
      if (this.session(a)?.world.status !== 'active') throw new Error(T('这次练习只读，不能修改测试作品的依据。', 'This practice is read-only; the test work evidence cannot be changed.'));
      if (!target.adopted) throw new Error(T('先采用测试作品，再添加依据。', 'Adopt the test work before adding evidence.'));
      if (this.store.getSnapshot().storageError) throw new Error(T('存储不可用，不能修改测试作品的依据。', 'Storage is unavailable; the test work evidence cannot be changed.'));
    }
    const actual = ev.type === 'test' ? a.tests.find((x: any) => x.id === ev.id && x.configVersion === ev.version) : a.backend.materials.find((x: any) => x.id === ev.id && x.version === ev.version);
    if (!target || !actual) throw new Error(T('只能引用当前会话实际返回的资料或测试。', 'Only documents and tests returned in this session can be cited.'));
    const safe = { id: actual.id, title: ev.type === 'test' ? '测试：' + actual.question : actual.title, version: ev.version, body: ev.type === 'test' ? actual.answer : actual.body, type: ev.type };
    return this.base.addEvidence(a, artifactId, safe);
  }
  package(a: Attempt, taskId: string | null, scope: any = {}) {
    const read = new Set(['brief', ...a.events.filter((e: any) => e.server && e.type === 'material_read').map((e: any) => e.detail.materialId)]);
    const artifacts = this.base.currentArtifacts(a).filter((x: any) => (!taskId || x.taskId === taskId) && (!scope.artifactIds || scope.artifactIds.includes(x.id)));
    const historicalMaterials: Material[] = [];
    for (const work of artifacts.filter((x: any) => x.kind === 'investigation')) {
      for (const block of (work.blocks || []).filter((b: any) => b.type === 'source_check')) {
        const ref = block.material;
        const citedRun = this.session(a)?.tests.find(t => t.id === block.testId);
        if (!citedRun?.citations.some(c => c.material_id === ref?.id)) continue;
        const current = a.backend.materials.find((m: any) => m.id === ref?.id);
        if (!current || !Number.isInteger(ref.version) || ref.version < 1 || ref.version > current.version || (scope.materialIds && !scope.materialIds.includes(ref.id))) continue;
        if (current.version === ref.version) read.add(ref.id);
        else {
          const cached = this.materialCache.get(JSON.stringify([a.id, ref.id, ref.version]));
          if (cached && !historicalMaterials.some(m => m.id === cached.id && m.version === cached.version)) historicalMaterials.push(structuredClone(cached));
        }
      }
    }
    const requestId = scope.requestId || crypto.randomUUID();
    const inputVersions = artifacts.map((x: any) => ({ artifactId: x.id, revision: x.revision }));
    const materials = [...a.backend.materials.filter((m: any) => read.has(m.id) && (!scope.materialIds || scope.materialIds.includes(m.id))), ...historicalMaterials];
    const tests = a.tests.filter((t: any) => !scope.testIds || scope.testIds.includes(t.id));
    const inputSnapshot = this.base.captureInputSnapshot(a, { artifacts, materials, tests });
    const guide = this.base.buildReturnGuide(requestId);
    const result = structuredClone({ schema: 'practice-task-package/v1', requestId, mode: 'backend-evidence-local-notes', exportedAt: new Date().toISOString(), scenario: { id: a.scenarioId, title: a.title }, task: a.tasks.find((t: any) => t.id === taskId) || null, materials, artifacts, tests, inputVersions, inputSnapshot, ...guide, instructions: T('仅用本包可见资料。作品回传是本地草稿，不批准资源、不执行动作；结论必须核查。', 'Use only what this package contains. Returned work is a local draft: it approves nothing and runs nothing, and its claims must be checked.') + '\n' + guide.instructions });
    if (scope.record) { a.exports ||= []; a.exports.push({ requestId, taskId, inputVersions, inputSnapshot: structuredClone(inputSnapshot), createdAt: result.exportedAt }); }
    return result;
  }
}
