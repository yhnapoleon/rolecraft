import { ApiError, request, sessionPath, type Transport } from './api';
import type { Artifact, Deliverable, Feedback, Job, LocalSession, Operation, Pilot, RoleId, Scenario, Submission, TestRun, Timeline, Turn, Workspace, World } from './types';

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
    } catch { error = '无法读取浏览器存档。请保留原浏览器数据；不要清理站点存储。'; }
    this.state = { workspace, busy: false, error, notice: '', storageError: Boolean(error), model: '', connected: false };
  }
  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private emit(patch: Partial<Snapshot> = {}) { this.state = { ...this.state, ...patch }; this.listeners.forEach(l => l()); }
  private persist() {
    try { this.storage.setItem(STORAGE_KEY, JSON.stringify(this.state.workspace)); this.emit({ storageError: false }); return true; }
    catch { this.emit({ storageError: true, error: '本浏览器保存失败。写入已暂停；保留此页面和会话凭据后再处理存储空间。' }); return false; }
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
    } catch (e) { this.emit({ error: '创建会话未获确认；未自动重复创建。' + message(e) }); }
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
        this.emit({ notice: '局面变化：政策源文档已更新到 v' + current.state.material_versions.policy + '，当前索引为 v' + current.state.indexed_versions.policy + '。请到项目资料核对原文。' });
      }
    } catch (e) { this.emit({ error: '刷新失败：' + message(e), connected: false }); }
  }
  submissionId(s: LocalSession) {
    return s.submission?.id || String(s.timeline.events.findLast(e => e.event_type === 'submit_plan')?.payload.object_id || '');
  }
  canWrite(s = this.active()) { return Boolean(s && s.world.status === 'active' && !s.pending && !this.state.busy && !this.state.storageError); }
  async write(kind: Operation['kind'], suffix: string, body: Record<string, unknown>, label: string) {
    const s = this.active();
    if (!s || this.state.busy || s.pending || this.state.storageError) return;
    if (!['feedback', 'action', 'relation'].includes(kind) && s.world.status !== 'active') return;
    const operation: Operation = { kind, path: suffix, body, label, created: new Date().toISOString(), ...(kind === 'test' ? { localExpected: s.inputs.expected } : {}) };
    if (!this.update(s.id, { pending: operation })) return;
    await this.execute(s.id);
  }
  action(tool: string, args: Record<string, unknown>) {
    const s = this.active(); if (!s) return;
    const labels: Record<string, string> = { update_pilot: '试点配置', refresh_index: '索引更新', read_material: '阅读记录', request_capacity: '扩容申请', request_resources: '资源申请', pause: '暂停会话', resume: '恢复会话' };
    return this.write('action', '/actions', { tool, arguments: args, request_id: crypto.randomUUID(), expected_version: s.world.version }, labels[tool] || '操作');
  }
  sendTurn(role: RoleId, text: string) {
    return this.write('turn', '/turns', { role_id: role, text, request_id: crypto.randomUUID() }, '同事回复');
  }
  test(query: string) {
    const s = this.active(); if (!s) return;
    return this.write('test', '/tests', { query, config_version: s.world.config_version, request_id: crypto.randomUUID() }, '知识助手测试');
  }
  saveArtifact() { const s = this.active(); if (!s) return; return this.write('artifact', '/artifacts', { content: s.draft, request_id: crypto.randomUUID() }, '保存交付稿'); }
  submit() {
    const s = this.active(); if (!s?.artifact) return;
    if (s.artifact.config_version !== s.world.config_version || JSON.stringify(s.artifact.content) !== JSON.stringify(s.draft)) {
      this.emit({ error: '配置或交付文字已变化，请先保存新的交付稿。' }); return;
    }
    return this.write('submission', '/submissions', { artifact_id: s.artifact.id, config_version: s.world.config_version, request_id: crypto.randomUUID() }, '固定提交');
  }
  feedback() { const s = this.active(); if (!s) return; return this.write('feedback', '/feedback', { submission_id: this.submissionId(s) }, '生成反馈'); }
  relation(claim: string) { return this.write('relation', '/relation-checks', { claim, request_id: crypto.randomUUID() }, '辅助关系判断'); }
  approval(rule: string) { const s = this.active(); if (!s) return; return this.write('approval', '/approvals/resolve', { rule_id: rule, request_id: crypto.randomUUID(), expected_version: s.world.version }, '按场景规则审核申请'); }
  async execute(id = this.state.workspace.active) {
    const s = this.state.workspace.sessions.find(s => s.id === id);
    if (!s?.pending || this.state.busy) return;
    if (s.pending.jobId) { await this.poll(id); return; }
    this.emit({ busy: true, error: '', notice: '' });
    const op = s.pending;
    try {
      const result = await this.transport(sessionPath(s, op.path), op.body, s);
      if (op.kind === 'turn' || op.kind === 'feedback') {
        this.update(s.id, { pending: { ...op, jobId: result.job_id } });
        this.emit({ notice: '任务已入队，等待独立 worker。可以离开页面，返回后继续查询。' });
      } else {
        const latest = this.state.workspace.sessions.find(x => x.id === s.id)!;
        const patch: Partial<LocalSession> = { pending: undefined };
        if (op.kind === 'test') {
          patch.tests = [...latest.tests.filter(t => t.id !== result.id), result as TestRun];
          patch.testNotes = { ...latest.testNotes, [result.id]: { expected: op.localExpected || '', diagnosis: '' } };
        }
        if (op.kind === 'artifact') patch.artifact = result as Artifact;
        if (op.kind === 'submission') patch.submission = result as Submission;
        if (op.kind === 'relation') patch.relationResult = result;
        if (op.kind === 'action' && op.body.tool === 'update_pilot') patch.configDraft = undefined;
        this.update(s.id, patch);
        this.emit({ notice: op.label + '已由后端保存。' });
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
      this.emit({ error: unavailableStudy ? '服务器尚未配置冻结实验，辅助关系判断不可用；其他功能可继续使用。' : message(e) + (e instanceof ApiError && e.status === 409 ? ' 已刷新状态，请核对后重新操作；草稿仍保留。' : '') });
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
        this.emit({ error: '', notice: op.label + '已完成。' });
        await this.sync(s.id);
      } else if (job.status === 'failed') {
        this.update(s.id, { pending: undefined, failedTurn: op.kind === 'turn' ? { ...op, job } : undefined, ...(op.kind === 'feedback' ? { feedbackFailure: job } : {}) });
        this.emit({ error: '任务已失败（' + job.error + '）。后端已尝试 ' + job.attempt + ' 次。' + (op.kind === 'feedback' ? '现有接口不支持重新执行终态失败的反馈任务，重复申请只会返回原任务。' : '可保留原问题并重新发起一次新回合。') });
        await this.sync(s.id);
      } else { this.update(s.id, { pending: { ...op, job } }); }
    } catch (e) { this.emit({ error: '查询任务失败：' + message(e) }); }
    finally { this.polling = false; }
  }
}
export function message(e: unknown) { return e instanceof Error ? e.message : String(e); }

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
