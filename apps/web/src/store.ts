import { ApiError, request, sessionPath, type Transport } from './api';
import { T } from './app/i18n';
import type { Artifact, Deliverable, Feedback, Job, LocalSession, LocalTestRun, Operation, Pilot, RoleId, Scenario, Submission, TestRun, TestRunOrigin, Timeline, Turn, Workspace, World } from './types';

export const STORAGE_KEY = 'rolecraft.live.workspace.v1';
export const emptyDraft = (): Deliverable => ({ goal: '', owner: '', metrics: '', observation_window: '', exit_condition: '', rationale: '' });
export const blankPilot = (): Pilot => ({ participants: 0, knowledge_domains: [], launch_day: 7, update_strategy: 'daily', fallback: 'none', work_items: [] });
export interface Snapshot { workspace: Workspace; busy: boolean; error: string; notice: string; storageError: boolean; model: string; connected: boolean }

export class WorkspaceStore {
  private listeners = new Set<() => void>();
  private state: Snapshot;
  private polling = false;
  constructor(private storage: Pick<Storage, 'getItem' | 'setItem'>, private transport: Transport = request) {
    let workspace: Workspace = { schema: 1, sessions: [] }, error = '';
    try {
      const saved = storage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed.schema !== 1 || !Array.isArray(parsed.sessions) || !parsed.sessions.every(validSession) ||
            (parsed.active && !parsed.sessions.some((s: LocalSession) => s.id === parsed.active))) throw new Error();
        workspace = parsed;
      }
    } catch { error = T('无法读取浏览器存档。请保留原浏览器数据；不要清理站点存储。', 'The saved sessions in this browser could not be read. Keep the browser data; do not clear site storage.'); }
    this.state = { workspace, busy: false, error, notice: '', storageError: Boolean(error), model: '', connected: false };
  }
  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private emit(patch: Partial<Snapshot> = {}) { this.state = { ...this.state, ...patch }; this.listeners.forEach(l => l()); }
  private persist() {
    try { this.storage.setItem(STORAGE_KEY, JSON.stringify(this.state.workspace)); this.emit({ storageError: false }); return true; }
    catch { this.emit({ storageError: true, error: T('本浏览器保存失败。写入已暂停；保留此页面和会话凭据后再处理存储空间。', 'This browser could not save. Server writes are paused; keep this page open before freeing storage.') }); return false; }
  }
  active() { return this.state.workspace.sessions.find(s => s.id === this.state.workspace.active); }
  update(id: string, patch: Partial<LocalSession>) {
    this.state = { ...this.state, workspace: { ...this.state.workspace, sessions: this.state.workspace.sessions.map(s => s.id === id ? { ...s, ...patch } : s) } };
    return this.persist();
  }
  select(id: string) { this.state.workspace = { ...this.state.workspace, active: id }; this.persist(); }
  clearMessage() { this.emit({ error: '', notice: '' }); }
  async health() {
    try { const result = await this.transport('/health'); this.emit({ connected: true, model: result.model }); }
    catch { this.emit({ connected: false, model: '' }); }
  }
  async create(scenario: Scenario) {
    if (this.state.busy || this.state.storageError) return;
    // Prove local persistence works before creating a non-idempotent session.
    if (!this.persist()) return;
    this.emit({ busy: true, error: '', notice: '' });
    try {
      const result = await this.transport('/sessions', { scenario });
      const session: LocalSession = {
        id: result.session_id, token: result.token, scenario, world: result.state,
        created: new Date().toISOString(), materials: [], timeline: { events: [], turns: [], mode: '' },
        draft: emptyDraft(), tests: [], questions: {}, testNotes: {},
        inputs: { question: '', expected: '', messages: {}, capacityReason: '', resourceReason: '' },
      };
      this.state.workspace = { schema: 1, active: session.id, sessions: [...this.state.workspace.sessions, session] };
      this.persist();
      await this.sync(session.id);
      return session.id;
    } catch (e) { this.emit({ error: T('创建会话未获确认；未自动重复创建。', 'Creating the session was not confirmed, so it was not retried automatically. ') + message(e) }); }
    finally { this.emit({ busy: false }); }
  }
  async sync(id = this.state.workspace.active) {
    const s = this.state.workspace.sessions.find(s => s.id === id);
    if (!s) return;
    try {
      const [current, materials, timeline] = await Promise.all([
        this.transport(sessionPath(s), undefined, s),
        this.transport(sessionPath(s, '/materials'), undefined, s),
        this.transport(sessionPath(s, '/timeline'), undefined, s),
      ]);
      const patch: Partial<LocalSession> = { world: current.state as World, materials, timeline: timeline as Timeline };
      // Recover the submission reference from server events; never invent its body.
      if (!s.submission && current.state.status === 'submitted') {
        const event = timeline.events.findLast((e: any) => e.event_type === 'submit_plan');
        if (event?.payload.object_id) {
          try { patch.feedback = await this.transport(sessionPath(s, '/feedback/' + event.payload.object_id), undefined, s); }
          catch (e) { if (!(e instanceof ApiError && e.status === 404)) throw e; }
        }
      }
      this.update(s.id, patch);
      this.emit({ connected: true });
      if (current.state.material_versions.policy > (s.world.material_versions.policy || 0)) {
        this.emit({ notice: T('局面变化：政策源文档已更新到 v' + current.state.material_versions.policy + '，当前索引为 v' + current.state.indexed_versions.policy + '。请到项目资料核对原文。', 'The policy document is now v' + current.state.material_versions.policy + '; the index is v' + current.state.indexed_versions.policy + '.') });
      }
    } catch (e) { this.emit({ error: T('刷新失败：', 'Refresh failed: ') + message(e), connected: false }); }
  }
  submissionId(s: LocalSession) {
    return s.submission?.id || String(s.timeline.events.findLast(e => e.event_type === 'submit_plan')?.payload.object_id || '');
  }
  canWrite(s = this.active()) { return Boolean(s && s.world.status === 'active' && !s.pending && !this.state.busy && !this.state.storageError); }
  async write(kind: Operation['kind'], suffix: string, body: Record<string, unknown>, label: string, localRun?: LocalTestRun) {
    const s = this.active();
    if (!s || this.state.busy || s.pending || this.state.storageError) return;
    if (!['feedback', 'action', 'relation'].includes(kind) && s.world.status !== 'active') return;
    const operation: Operation = { kind, path: suffix, body, label, created: new Date().toISOString(), ...(kind === 'test' ? { localExpected: localRun?.expectation ?? s.inputs.expected, ...(localRun ? { localRun: structuredClone(localRun) } : {}) } : {}) };
    if (!this.update(s.id, { pending: operation })) return;
    await this.execute(s.id);
  }
  action(tool: string, args: Record<string, unknown>) {
    const s = this.active(); if (!s) return;
    const labels: Record<string, string> = { update_pilot: T('试点配置', 'Pilot settings'), refresh_index: T('索引更新', 'Index refresh'), read_material: T('阅读记录', 'Reading'), request_capacity: T('扩容申请', 'Seat request'), request_resources: T('资源申请', 'Resource request'), pause: T('暂停会话', 'Pause'), resume: T('恢复会话', 'Resume') };
    return this.write('action', '/actions', { tool, arguments: args, request_id: crypto.randomUUID(), expected_version: s.world.version }, labels[tool] || T('操作', 'Action'));
  }
  sendTurn(role: RoleId, text: string) {
    return this.write('turn', '/turns', { role_id: role, text, request_id: crypto.randomUUID() }, T('同事回复', 'Colleague reply'));
  }
  test(query: string, origin?: TestRunOrigin & { expectation?: string }) {
    const s = this.active(); if (!s) return;
    if (!s.world.configs.pilot) { this.emit({ error: T('先保存试点设置，再测试助手。', 'Save the pilot settings before testing the assistant.') }); return; }
    if (typeof query !== 'string' || !query.trim() || Array.from(query).length > 4000) { this.emit({ error: T('测试问题需要 1–4000 个字符。', 'The question needs 1–4,000 characters.') }); return; }
    const requestId = crypto.randomUUID();
    const localRun: LocalTestRun = {
      ...structuredClone(origin || { taskId: null }), sessionId: s.id, requestId, query,
      expectation: origin?.expectation ?? s.inputs.expected, config: structuredClone(s.world.configs.pilot || null), createdAt: new Date().toISOString(),
    };
    return this.write('test', '/tests', { query, config_version: s.world.config_version, request_id: requestId }, T('知识助手测试', 'Assistant test'), localRun);
  }
  saveArtifact() { const s = this.active(); if (!s) return; return this.write('artifact', '/artifacts', { content: s.draft, request_id: crypto.randomUUID() }, T('保存交付稿', 'Save deliverable')); }
  submit() {
    const s = this.active(); if (!s?.artifact) return;
    if (s.artifact.config_version !== s.world.config_version || JSON.stringify(s.artifact.content) !== JSON.stringify(s.draft)) {
      this.emit({ error: T('配置或交付文字已变化，请先保存新的交付稿。', 'The settings or the deliverable changed. Save the deliverable again first.') }); return;
    }
    return this.write('submission', '/submissions', { artifact_id: s.artifact.id, config_version: s.world.config_version, request_id: crypto.randomUUID() }, T('固定提交', 'Submission'));
  }
  feedback() { const s = this.active(); if (!s) return; return this.write('feedback', '/feedback', { submission_id: this.submissionId(s) }, T('生成反馈', 'Review')); }
  relation(claim: string) { return this.write('relation', '/relation-checks', { claim, request_id: crypto.randomUUID() }, T('辅助关系判断', 'Evidence check')); }
  approval(rule: string) { const s = this.active(); if (!s) return; return this.write('approval', '/approvals/resolve', { rule_id: rule, request_id: crypto.randomUUID(), expected_version: s.world.version }, T('按场景规则审核申请', 'Approval')); }
  async execute(id = this.state.workspace.active) {
    const s = this.state.workspace.sessions.find(s => s.id === id);
    if (!s?.pending || this.state.busy || this.state.storageError) return;
    if (s.pending.jobId) { await this.poll(id); return; }
    this.emit({ busy: true, error: '', notice: '' });
    const op = s.pending;
    try {
      const result = await this.transport(sessionPath(s, op.path), op.body, s);
      if (op.kind === 'turn' || op.kind === 'feedback') {
        this.update(s.id, { pending: { ...op, jobId: result.job_id } });
        this.emit({ notice: T('任务已入队，等待独立 worker。可以离开页面，返回后继续查询。', 'Queued. You can leave the page and come back.') });
      } else {
        const latest = this.state.workspace.sessions.find(x => x.id === s.id)!;
        const patch: Partial<LocalSession> = { pending: undefined };
        if (op.kind === 'test') {
          if (!validTestResult(result, op)) throw new ApiError(T('测试返回内容与原请求不符，已保留原请求，请核对后重试。', 'The test response did not match its request. The original request has been kept for recovery.'));
          patch.tests = [...latest.tests.filter(t => t.id !== result.id), result as TestRun];
          patch.testNotes = { ...latest.testNotes, [result.id]: latest.testNotes[result.id] || { expected: op.localRun?.expectation ?? op.localExpected ?? '', diagnosis: '' } };
          if (op.localRun) patch.testRunMeta = { ...latest.testRunMeta, [result.id]: structuredClone(op.localRun) };
        }
        if (op.kind === 'artifact') patch.artifact = result as Artifact;
        if (op.kind === 'submission') patch.submission = result as Submission;
        if (op.kind === 'relation') patch.relationResult = result;
        if (op.kind === 'action' && op.body.tool === 'update_pilot') patch.configDraft = undefined;
        if (!this.update(s.id, patch)) {
          // The server may have succeeded, but the browser still needs the exact
          // original operation to recover after storage becomes available.
          this.state.workspace = { ...this.state.workspace, sessions: this.state.workspace.sessions.map(x => x.id === s.id ? { ...x, pending: op } : x) };
          return;
        }
        this.emit({ notice: op.label + T('已由后端保存。', ' saved.') });
        await this.sync(s.id);
      }
    } catch (e) {
      if (!(e instanceof ApiError) || e.status === 0 || e.status >= 500) this.emit({ connected: false });
      // 4xx is a definite rejection; preserve drafts but do not rebase an old action silently.
      const unavailableStudy = op.kind === 'relation' && e instanceof ApiError && e.status === 503 && e.message === 'frozen relation study is not configured';
      if (e instanceof ApiError && ((e.status >= 400 && e.status < 500) || unavailableStudy)) {
        this.update(s.id, { pending: undefined });
        await this.sync(s.id);
      }
      this.emit({ error: unavailableStudy ? T('服务器尚未配置冻结实验，辅助关系判断不可用；其他功能可继续使用。', 'The evidence checker is not configured on the server. Everything else still works.') : message(e) + (e instanceof ApiError && e.status === 409 ? T(' 已刷新状态，请核对后重新操作；草稿仍保留。', ' The state was refreshed; check it and try again. Your draft is kept.') : '') });
    } finally { this.emit({ busy: false }); }
  }
  async poll(id = this.state.workspace.active) {
    const s = this.state.workspace.sessions.find(s => s.id === id);
    if (!s?.pending?.jobId || this.polling || this.state.busy) return;
    this.polling = true;
    const op = s.pending;
    try {
      const job = await this.transport(sessionPath(s, '/jobs/' + op.jobId), undefined, s) as Job;
      if (job.status === 'completed') {
        const patch: Partial<LocalSession> = { pending: undefined, failedTurn: undefined };
        if (op.kind === 'feedback') { patch.feedback = job.result as Feedback; patch.feedbackFailure = undefined; }
        if (op.kind === 'turn') {
          const turn = job.result as Turn;
          patch.questions = { ...s.questions, [turn.trace_id]: String(op.body.text) };
        }
        this.update(s.id, patch);
        this.emit({ error: '', notice: op.label + T('已完成。', ' done.') });
        await this.sync(s.id);
      } else if (job.status === 'failed') {
        this.update(s.id, { pending: undefined, failedTurn: op.kind === 'turn' ? { ...op, job } : undefined, ...(op.kind === 'feedback' ? { feedbackFailure: job } : {}) });
        this.emit({ error: T('任务已失败（' + job.error + '）。后端已尝试 ' + job.attempt + ' 次。', 'The job failed (' + job.error + ') after ' + job.attempt + ' attempts. ') + (op.kind === 'feedback' ? T('现有接口不支持重新执行终态失败的反馈任务，重复申请只会返回原任务。', 'The server cannot rerun a failed review job; asking again returns the same job.') : T('可保留原问题并重新发起一次新回合。', 'You can send the same message again as a new turn.')) });
        await this.sync(s.id);
      } else { this.update(s.id, { pending: { ...op, job } }); }
    } catch (e) { this.emit({ error: T('查询任务失败：', 'Could not check the job: ') + message(e) }); }
    finally { this.polling = false; }
  }
}
function validTestResult(value: any, operation: Operation): value is TestRun {
  return !!value && typeof value.id === 'string' && !!value.id && value.query === operation.body.query &&
    value.config_version === operation.body.config_version && typeof value.answer === 'string' &&
    typeof value.mode === 'string' && typeof value.fallback === 'boolean' && typeof value.stale === 'boolean' &&
    Number.isInteger(value.as_of_seq) && value.as_of_seq >= 0 &&
    validVersions(value.source_versions) && validVersions(value.indexed_versions) && Array.isArray(value.citations) &&
    value.citations.every((c: any) => typeof c.material_id === 'string' && Number.isInteger(c.version) && c.version > 0);
}
function validVersions(value: any) {
  return !!value && typeof value === 'object' && !Array.isArray(value) && Object.values(value).every(v => Number.isInteger(v) && Number(v) > 0);
}
export function message(e: unknown) { return e instanceof ApiError ? serverText(e.message) : e instanceof Error ? e.message : String(e); }
// Server details are English identifiers; say what happened in the interface language.
export function serverText(detail: string) {
  const d = String(detail || '');
  if (/session is submitted/.test(d)) return T('已交付，这次练习只读。', 'Already submitted; this practice is read-only.');
  if (/config version is not current/.test(d)) return T('试点设置刚变过，请重新运行。', 'The pilot settings just changed. Run it again.');
  if (/artifact\/config version mismatch/.test(d)) return T('交付稿保存后设置又变过，请先重新保存。', 'Settings changed after you saved the deliverable. Save it again first.');
  if (/request is unnecessary or exceeds/.test(d)) return T('Priya 没有批准：当前设置不需要这项申请，或超出了可批范围。', 'Priya did not approve: the current settings do not need it, or it exceeds what she can approve.');
  if (/material unavailable/.test(d)) return T('这份资料现在不可读。', 'This document is not available now.');
  if (/invalid pause\/resume/.test(d)) return T('练习状态已变，现在不能暂停或恢复。', 'The practice state changed; it cannot be paused or resumed now.');
  if (/frozen relation study is not configured/.test(d)) return T('辅助证据判断尚未在服务器上配置。', 'The evidence checker is not configured on the server.');
  if (/session token required|invalid session token/.test(d)) return T('会话凭据失效。请保留原浏览器数据。', 'Session credentials are no longer valid. Keep the original browser data.');
  if (/expected -?\d+; current \d+/.test(d)) return T('局面刚变过。', 'The situation just changed.');
  if (/request_id reused|job key conflict/.test(d)) return T('同一个请求编号对应了不同内容，已拒绝。', 'The same request id carried different content, so it was rejected.');
  if (/unknown scenario/.test(d)) return T('服务器不认识这个情境。', 'The server does not know this situation.');
  return d;
}

function validSession(s: any): s is LocalSession {
  return !!s && typeof s.id === 'string' && typeof s.token === 'string' && !!s.token &&
    ['pm_pilot', 'pm_pilot_urgent', 'pm_pilot_capacity15'].includes(s.scenario) &&
    s.world?.session_id === s.id && ['active', 'paused', 'submitted'].includes(s.world?.status) &&
    Number.isInteger(s.world?.version) && !!s.world.resources && !!s.world.configs &&
    !!s.world.material_versions && !!s.world.indexed_versions && Array.isArray(s.world.pending_requests) &&
    Array.isArray(s.materials) && Array.isArray(s.tests) && Array.isArray(s.timeline?.events) &&
    Array.isArray(s.timeline?.turns) && !!s.inputs?.messages && !!s.questions && !!s.testNotes &&
    Object.keys(emptyDraft()).every(k => typeof s.draft?.[k] === 'string');
}
