import { createGatewayTransport } from './gateway-transport';
import { request, sessionPath, type Transport } from './api';
import { T, locale } from './app/i18n';
import { V4LiveData } from './v4-live-data';
import { V4Mounts } from './v4-mounts';
import { projectNativeWorkspace } from './v4-workspace-projection';
import {
  keepProductDraft,
  WorkspaceSlotController,
} from './features/workspace/native-v4/slot-controller';
import type { ProductCreate, WorkspaceProductRead } from './contracts-v2';
import { workspaceActionMessage } from './features/workspace/native-v4/messages';
import { canonicalPurpose } from './features/workspace/native-v4/form-values';
import { blankPilot, WorkspaceStore } from './store';
import type {
  Deliverable,
  LocalSession,
  Material,
  Pilot,
  RoleId,
  Scenario,
  TestRunOrigin,
  TurnContext,
} from './types';

// The HTML workbench owns local notes; WorkspaceStore owns all server authority.
// No credential is copied into an attempt, task package, screenshot or export.
type Attempt = any;
type Engine = Record<string, (...args: any[]) => any> & Record<string, any>;
const scenarios: Record<string, Scenario> = {
  pilot: 'pm_pilot',
  urgent: 'pm_pilot_urgent',
  capacity: 'pm_pilot_capacity15',
};
export const roleIds: Record<string, RoleId> = {
  manager: 'supervisor',
  business: 'business_lead',
  technical: 'tech_lead',
};
const workIds: Record<string, string> = {
  scope: 'scope_filter',
  fallback: 'human_fallback',
  realtime: 'realtime_sync',
};
export const fromPilot = (p: Pilot) => ({
  participants: p.participants,
  domains: p.knowledge_domains.map((d) => (d === 'stable_faq' ? 'faq' : d)),
  update: p.update_strategy === 'manual_policy' ? 'manual' : p.update_strategy,
  fallback: p.fallback,
  workItems: p.work_items.map((w) => Object.keys(workIds).find((k) => workIds[k] === w) || w),
  launchDay: p.launch_day,
});
export function toPilot(c: any): Pilot {
  if (
    !['daily', 'realtime', 'manual'].includes(c.update) ||
    !['human', 'none'].includes(c.fallback)
  )
    throw new Error(T('这项设置没有对应的后端接口。', 'This setting has no server equivalent.'));
  if (
    c.domains.some(
      (d: string) =>
        !['faq', 'policy', 'onboarding', 'policy_travel', 'policy_meal', 'policy_leave'].includes(
          d,
        ),
    ) ||
    c.workItems.some((w: string) => !workIds[w])
  )
    throw new Error(T('未知知识范围或工作项。', 'Unknown knowledge area or work item.'));
  return {
    participants: c.participants,
    knowledge_domains: c.domains.map((d: string) => (d === 'faq' ? 'stable_faq' : d)),
    launch_day: c.launchDay,
    update_strategy: c.update === 'manual' ? 'manual_policy' : c.update,
    fallback: c.fallback,
    work_items: c.workItems.map((w: string) => workIds[w]),
  };
}

export class LiveWorkbench {
  readonly store: WorkspaceStore;
  readonly fromPilot = fromPilot;
  readonly engine: Engine;
  private state: any;
  private readonly v4: V4LiveData;
  private readonly mounts = new V4Mounts();
  private notify = (_changed: boolean) => {};
  private signature = '';
  private materialCache = new Map<string, Material>();
  constructor(
    readonly base: Engine,
    storage: Pick<Storage, 'getItem' | 'setItem'>,
    private transport: Transport = request,
    private options: { newSessionProtocol?: 2 } = {},
  ) {
    this.store = new WorkspaceStore(storage, transport);
    this.v4 = new V4LiveData(this.store, storage);
    this.engine = {
      ...base,
      scenarios: base.scenarios.map((s: any) => (s.id === 'urgent' ? { ...s, deadline: 5 } : s)),
      getMaterials: (a: Attempt) => a.backend?.materials || [],
      maybeTriggerEvents: () => false,
      checkCommitment: () => {},
      checkFocus: () => {},
      coach: () => ({ items: [] }),
      review: () => ({ observations: [] }),
      preparePackage: (a: Attempt, taskId: string | null, scope: any) =>
        this.package(a, taskId, scope),
      addEvidence: (a: Attempt, id: string, ev: any) => this.addEvidence(a, id, ev),
    };
    // Some local editing methods call simulation helpers internally. Strip those
    // synthetic colleague messages instead of displaying them beside real turns.
    for (const name of [
      'saveArtifact',
      'moveTask',
      'restoreOrder',
      'adoptArtifact',
      'updateTask',
    ]) {
      this.engine[name] = (...args: any[]) => {
        const result = base[name](...args);
        args[0].nudges = [];
        args[0].events = args[0].events.filter(
          (e: any) => !['colleague_note', 'colleague_nudged', 'nudge'].includes(e.type),
        );
        for (const role of Object.keys(roleIds))
          args[0].conversations[role] = args[0].conversations[role].filter(
            (m: any) => m.mode !== 'simulated',
          );
        return result;
      };
    }
    for (const name of [
      'runTest',
      'reply',
      'updateConfig',
      'refreshIndex',
      'requestResources',
      'resolveResources',
      'triggerPolicyUpdate',
      'submit',
      'revise',
      'suggestPriorities',
      'readMaterial',
    ]) {
      this.engine[name] = () => {
        throw new Error(
          T(
            '此操作必须由后端确认；没有切换为本地模拟。',
            'This must be confirmed by the server; nothing was simulated locally.',
          ),
        );
      };
    }
    for (const name of [
      'addTask',
      'updateTask',
      'splitTask',
      'moveTask',
      'restoreOrder',
      'createArtifact',
      'saveArtifact',
      'adoptArtifact',
      'removeArtifact',
      'restoreArtifact',
      'addTestCase',
      'updateTestCase',
      'removeTestCase',
      'moveInvestigationBlock',
      'addEvidence',
    ]) {
      const local = this.engine[name];
      this.engine[name] = (a: Attempt, ...args: any[]) => {
        if (this.session(a)?.v2NativeWorkspace)
          throw new Error(
            T(
              '此操作尚未保存，请保留输入并使用当前作品的保存控件。',
              'This action has not been saved. Keep your input and use the current work’s save control.',
            ),
          );
        return local(a, ...args);
      };
    }
    this.store.subscribe(() => this.changed());
  }
  attach(state: any, notify: (changed: boolean) => void) {
    this.state = state;
    this.notify = notify;
    const snap = this.store.getSnapshot();
    for (const s of snap.workspace.sessions) this.ensureAttempt(s);
    if (snap.workspace.active) state.activeId = snap.workspace.active;
    if (state.activeId && snap.workspace.sessions.some((s) => s.id === state.activeId))
      this.store.select(state.activeId);
    this.changed();
  }
  private ensureAttempt(s: LocalSession, opts?: any) {
    let a = this.state.attempts.find((x: Attempt) => x.id === s.id);
    if (!a) {
      const previous = this.state.activeId;
      a = this.base.createAttempt(
        this.state,
        Object.keys(scenarios).find((k) => scenarios[k] === s.scenario),
        opts,
      );
      a.id = s.id;
      a.createdAt = s.created;
      a.selectedTaskId = null;
      a.nudges = [];
      a.events = []; // Seed cards are local organization, not server actions.
      this.state.activeId = previous;
    }
    return a;
  }
  private changed() {
    if (!this.state) return;
    const snap = this.store.getSnapshot();
    for (const s of snap.workspace.sessions) this.project(this.ensureAttempt(s), s);
    const signature = JSON.stringify(
      snap.workspace.sessions.map((s) => [
        s.id,
        s.world,
        s.materials,
        s.timeline,
        s.tests,
        s.testNotes,
        s.testRunMeta,
        s.feedback,
        s.pending?.jobId,
        s.pending?.job?.status,
        !!s.pending,
        s.feedbackFailure,
        s.failedTurn,
        s.v2Workspace,
      ]),
    );
    const changed = signature !== this.signature;
    this.signature = signature;
    this.notify(changed);
  }
  project(a: Attempt, s: LocalSession) {
    const w = s.world;
    projectNativeWorkspace(a, s);
    a.world = {
      capacity: w.resources.capacity,
      devDays: w.resources.dev_days,
      deadline: w.resources.deadline_day,
      policyVersion: w.material_versions.policy,
      indexVersion: w.indexed_versions.policy,
    };
    a.config = fromPilot(w.configs.pilot || blankPilot());
    a.configVersion = w.config_version;
    a.configDraft = s.configDraft ? fromPilot(s.configDraft) : null;
    a.backend = {
      status: w.status,
      version: w.version,
      configured: !!w.configs.pilot,
      materials: s.materials.map((m) => ({ ...m, body: m.content })),
      pendingRequests: w.pending_requests,
      submissionId: this.store.submissionId(s),
    };
    a.nudges = [];
    a.tests = s.tests.map((t) => {
      const previous = a.tests.find((p: any) => p.id === t.id) || {};
      const saved = s.testRunMeta?.[t.id];
      const meta = saved || previous;
      return {
        id: t.id,
        question: t.query,
        rawAnswer: t.answer,
        answer:
          (s.protocol === 2 && t.mode === 'waiting_model'
            ? T(
                '等待模型接入（当前为原文检索结果）\n\n',
                'Waiting for model connection (source retrieval result)\n\n',
              )
            : '') + t.answer,
        citations: t.citations.map((c) => ({
          id: c.material_id,
          version: c.version,
          title:
            (s.protocol === 2
              ? s.v2MaterialTitles?.[c.material_id + ':' + c.version]
              : s.materials.find((m) => m.id === c.material_id)?.title) || c.material_id,
        })),
        expectation: s.testNotes[t.id]?.expected ?? saved?.expectation ?? '',
        diagnosis: s.testNotes[t.id]?.diagnosis || '',
        policyVersion: t.source_versions.policy,
        indexVersion: t.indexed_versions.policy,
        sourceVersions: { ...t.source_versions },
        indexedVersions: { ...t.indexed_versions },
        configVersion: t.config_version,
        config: saved ? (saved.config ? fromPilot(saved.config) : null) : previous.config || null,
        taskId: meta.taskId || null,
        createdAt: t.created_at || meta.createdAt || '',
        workId: meta.workId,
        workRevision: meta.workRevision,
        caseId: meta.caseId,
        caseRevision: meta.caseRevision,
        investigationId: meta.investigationId,
        investigationRevision: meta.investigationRevision,
        blockId: meta.blockId,
        blockRevision: meta.blockRevision,
        baselineRunId: meta.baselineRunId,
        requestId: meta.requestId,
        intent: meta.intent || '',
        refs: meta.refs || [],
        mode: t.mode,
        asOfSeq: t.as_of_seq,
        fallback: t.fallback,
        stale: t.stale,
      };
    });
    a.turnTask ||= {};
    for (const t of s.timeline.turns)
      if (t.context?.task_id !== undefined) a.turnTask[t.trace_id] = t.context.task_id;
    a.conversations = Object.fromEntries(
      Object.entries(roleIds).map(([role, id]) => [
        role,
        s.timeline.turns
          .filter((t) => t.role_id === id)
          .flatMap((t) => {
            const question = t.question ?? s.questions[t.trace_id];
            const common = {
              traceId: t.trace_id,
              createdAt: t.created_at || '',
              context: t.context,
            };
            return [
              ...(question ? [{ ...common, role: 'user', text: question }] : []),
              { ...common, role: 'colleague', text: t.text, model: t.model_revision },
            ];
          }),
      ]),
    );
    // Server events are projected separately from local editing events. Local ordering
    // (applySuggestion, moveTask) stays allowed: it never touches server authority.
    a.events = a.events.filter(
      (e: any) => !e.server && !['colleague_note', 'colleague_nudged', 'nudge'].includes(e.type),
    );
    for (const e of s.timeline.events)
      a.events.push({
        id: 'server-' + e.seq,
        server: true,
        type: e.event_type === 'read_material' ? 'material_read' : e.event_type,
        text: '后端 · ' + e.event_type + ' · #' + e.seq,
        createdAt: e.created_at || '',
        detail: { ...e.payload, materialId: e.payload.material_id },
        seq: e.seq,
      });
    a.approvalDenials = s.timeline.approval_denials || [];
    for (const d of a.approvalDenials)
      a.events.push({
        id: 'denial-' + d.id,
        server: true,
        type: 'approval_denied',
        seq: 'denial-' + d.id,
        createdAt: d.created_at || '',
        detail: d,
      });
    a.requests = w.pending_requests.map((id) => ({
      id,
      status: 'pending',
      reason: id === 'capacity_approved' ? '扩容申请' : '资源与延期申请',
    }));
    a.submissions = this.store.submissionId(s)
      ? [
          {
            id: this.store.submissionId(s),
            createdAt: s.submission?.created_at || '',
            artifacts: [],
          },
        ]
      : [];
    if (s.submission?.created_at) a.submittedAt = s.submission.created_at;
  }
  session(a?: Attempt) {
    return a
      ? this.store.getSnapshot().workspace.sessions.find((s) => s.id === a.id)
      : this.store.active();
  }
  gatewayTransport(a: Attempt, fetcher: typeof fetch = fetch) {
    const id = a.id;
    return createGatewayTransport(() => {
      const session = this.session({ id });
      if (!session)
        throw new Error(
          T(
            '找不到会话凭据，请保留原浏览器存档。',
            'Session credentials are missing. Keep the original browser data.',
          ),
        );
      return { sessionId: session.id, token: session.token };
    }, fetcher);
  }
  async createNativeInvestigation(a: Attempt, runId: string, taskId: string) {
    const s = this.session(a),
      task = s?.v2Workspace?.tasks.find((t) => t.id === taskId),
      run = s?.tests.find((t) => t.id === runId);
    if (!s || !task || !run)
      throw new Error(T('请选择真实测试和事项。', 'Choose an actual test and task.'));
    const host = this.v4.host(s),
      timeline: any = await host.query('timeline');
    const testRef = timeline.objects.find(
      (r: any) => r.ref.kind === 'test' && r.ref.object_id === runId,
    )?.ref;
    if (!testRef)
      throw new Error(T('测试原始版本暂不可读。', 'The original test version is unavailable.'));
    const blocks: any[] = [
      {
        id: crypto.randomUUID(),
        type: 'note',
        title: T('调查思路', 'Investigation notes'),
        text: '',
      },
    ];
    const citation = run.citations[0],
      material = citation && s.materials.find((m) => m.id === citation.material_id);
    if (material) {
      const source: any = await host.query('objects.read', {
        kind: 'material',
        object_id: material.id,
        version: material.version,
      });
      const ref = source.content.fragments[0]?.ref;
      if (ref)
        blocks.push({
          id: crypto.randomUUID(),
          type: 'source_check',
          test_ref: testRef,
          source_ref: ref,
        });
    }
    blocks.push({ id: crypto.randomUUID(), type: 'retest', test_ref: testRef });
    const result = await host.command('work_products.create', {
      task: { session_id: s.id, kind: 'task', object_id: task.id, version: task.revision },
      kind: 'investigation',
      purpose: 'exploration',
      title: T('核对回答与资料', 'Check the answer against its sources'),
      content: '',
      evidence_refs: [],
      structured_payload: { type: 'investigation', question: run.query, blocks },
    });
    if (result.status !== 'confirmed')
      throw new Error(
        T(
          '调查保存尚未确认，请保留原请求。',
          'The investigation is unconfirmed. Keep the original request.',
        ),
      );
    const body = result.result as any;
    await this.v4.sync(this.store.getSnapshot().workspace.sessions.find((x) => x.id === s.id)!);
    const objectId =
      body.ref?.kind === 'product' && body.ref.session_id === s.id ? body.ref.object_id : undefined;
    if (!objectId)
      throw new Error(
        T(
          '调查已保存，请在事项目录打开。',
          'The investigation is saved. Open it from the task contents.',
        ),
      );
    return objectId as string;
  }
  async createNativeTask(
    a: Attempt,
    input: { title: string; goal: string; priority: number },
  ): Promise<string> {
    const session = this.session(a);
    if (!session?.v2NativeWorkspace) {
      throw new Error(T('当前事项服务不可用。', 'The task service is unavailable.'));
    }
    const outcome = await this.v4.host(session).command('work_items.create', input);
    if (outcome.status !== 'confirmed') {
      throw new Error(
        T(
          '事项保存尚未确认，请核对原请求。',
          'Task saving is unconfirmed. Check the original request.',
        ),
      );
    }
    const payload = outcome.result;
    const ref = payload && typeof payload === 'object' && 'ref' in payload ? payload.ref : null;
    if (
      !ref ||
      typeof ref !== 'object' ||
      !('kind' in ref) ||
      ref.kind !== 'task' ||
      !('session_id' in ref) ||
      ref.session_id !== session.id ||
      !('object_id' in ref) ||
      typeof ref.object_id !== 'string'
    ) {
      throw new Error(T('事项引用尚未确认。', 'The task reference is unconfirmed.'));
    }
    const current = this.store
      .getSnapshot()
      .workspace.sessions.find((row) => row.id === session.id);
    if (current) await this.v4.sync(current);
    return ref.object_id;
  }
  async patchNativeTask(a: Attempt, id: string, patch: Record<string, unknown>) {
    const s = this.session(a);
    const task = s?.v2Workspace?.tasks.find((t) => t.id === id);
    if (!s || !task)
      throw new Error(T('找不到这件事的已保存版本。', 'The saved task version is unavailable.'));
    const result = await this.v4.host(s).command('work_items.update', {
      item_id: id,
      expected_revision: task.revision,
      ...patch,
      ...(patch.status === 'working' ? { status: 'active' } : {}),
    });
    if (result.status !== 'confirmed')
      throw new Error(
        T(
          '事项变更尚未确认，请保留原请求。',
          'The task change is not confirmed. Keep the original request.',
        ),
      );
    await this.v4.sync(this.store.getSnapshot().workspace.sessions.find((x) => x.id === s.id)!);
  }
  async moveNativeTask(a: Attempt, id: string, to: { priority: string; beforeId?: string | null }) {
    const s = this.session(a),
      task = s?.v2Workspace?.tasks.find((t) => t.id === id);
    if (!s || !task) throw new Error('Task unavailable');
    const priority = ['first', 'next', 'later'].indexOf(to.priority);
    if (priority < 0) throw new Error('Invalid task priority');
    const siblings = s
      .v2Workspace!.tasks.filter(
        (t) => t.id !== id && t.status !== 'removed' && t.priority === priority,
      )
      .sort((a, b) => (a.order ?? 0) - (b.order ?? 0) || a.id.localeCompare(b.id));
    const before = siblings.findIndex((t) => t.id === to.beforeId);
    siblings.splice(before < 0 ? siblings.length : before, 0, task);
    const updates = siblings.map((t, order) => ({
      item_id: t.id,
      expected_revision: t.revision,
      priority,
      order,
    }));
    const result = await this.v4.host(s).command('work_items.batch', { updates });
    if (result.status !== 'confirmed')
      throw new Error(
        T(
          '排序尚未确认，请核对原请求。',
          'The order change is unconfirmed. Check the original request.',
        ),
      );
    await this.v4.sync(this.store.getSnapshot().workspace.sessions.find((x) => x.id === s.id)!);
  }
  async keepNativeProductDraft(a: Attempt, id: string, patch: Partial<ProductCreate>) {
    const session = this.session(a);
    const product: WorkspaceProductRead | undefined = session?.v2Workspace?.products.find(
      (item: { product_id: string }) => item.product_id === id,
    );
    if (
      session?.protocol !== 2 ||
      !session.v2NativeWorkspace ||
      session.world.status !== 'active' ||
      !product
    )
      throw new Error(T('当前无法保存作品草稿。', 'The work draft cannot be saved right now.'));
    await keepProductDraft(this.v4.host(session), product, patch);
  }
  async restoreNativeProduct(a: Attempt, productId: string): Promise<void> {
    const session = this.session(a);
    const host = this.v4Host(a);
    if (!session?.v2NativeWorkspace || !host)
      throw new Error(T('当前无法恢复作品。', 'Work cannot be restored right now.'));
    const controller = new WorkspaceSlotController(host);
    try {
      await controller.refresh();
      const product = controller.state.products.find((item) => item.product_id === productId);
      if (!product) throw new Error('product_unavailable');
      if (!product.removed_at) return;
      const result = await controller.remove(false, productId);
      if (result.status !== 'confirmed') throw new Error(`restore_${result.status}`);
      const current = this.store
        .getSnapshot()
        .workspace.sessions.find((item) => item.id === session.id);
      if (current) await this.v4.sync(current);
      this.changed();
    } catch (error) {
      throw new Error(workspaceActionMessage(error instanceof Error ? error.message : '', T));
    } finally {
      controller.destroy();
    }
  }
  nativeWorkspace(a: Attempt) {
    return this.session(a)?.v2NativeWorkspace === true;
  }
  hasUnsavedV4() {
    return this.v4.hasUnpersistedDrafts();
  }
  mountV4(a: Attempt | null, selection: { taskId: string | null; productId: string | null }) {
    void this.mounts
      .sync(document, a ? this.session(a) : undefined, a ? this.v4Host(a) : null, selection)
      .catch((error) => this.store.report({ error: error.message }));
  }
  configDomains(a: Attempt) {
    const s = this.session(a);
    return s?.protocol === 2
      ? (s.v2Domains ?? []).map((d) => (d === 'stable_faq' ? 'faq' : d))
      : ['faq', 'policy'];
  }
  v4Host(a?: Attempt) {
    const s = this.session(a);
    return s?.protocol === 2 ? this.v4.host(s) : null;
  }
  async start(
    caseId: string,
    opts?: any,
    via?: { create: () => Promise<any>; workLanguage: 'zh' | 'en' },
  ) {
    if (!scenarios[caseId])
      throw new Error(T('后端不支持这个情境。', 'The server does not support this situation.'));
    const id = await this.store.create(
      scenarios[caseId],
      via?.workLanguage ?? (this.options.newSessionProtocol === 2 ? locale() : undefined),
      via?.create,
    );
    if (!id)
      throw new Error(
        this.store.getSnapshot().error || T('会话未创建。', 'The session was not created.'),
      );
    const a = this.ensureAttempt(this.store.active()!, opts);
    if (opts) Object.assign(a, opts);
    this.state.activeId = id;
    if (this.store.active()!.protocol === 2 && !this.store.active()!.v2NativeWorkspace) {
      const source =
        opts?.initialTasks ?? a.tasks.map((t: any) => ({ title: t.title, goal: t.note }));
      const result = await this.v4.host(this.store.active()!).command('work_items.batch', {
        creates: source.map((t: any, i: number) => ({
          title: t.title,
          goal: t.goal ?? '',
          order: i,
          priority: ['first', 'next', 'later'].indexOf(opts?.priorities?.[i] ?? 'next'),
        })),
      });
      if (result.status !== 'confirmed')
        throw new Error(
          T(
            '起始事项尚未确认，练习和原请求已保留，请恢复原请求。',
            'Initial tasks are unconfirmed. The practice and original request are retained.',
          ),
        );
      await this.v4.sync(this.store.active()!);
      this.store.update(id, { v2NativeWorkspace: true });
    }
    this.project(a, this.store.active()!);
    return a;
  }
  /** Optional reviewed practice for the latest submission's feedback. W05 rules run on the server on every read. */
  async practice(a: Attempt) {
    const s = this.session(a),
      host = this.v4Host(a);
    if (!s || !host || !this.nativeWorkspace(a)) return { state: 'unsupported' };
    const list: any = await host.query('submissions.list');
    const rows: any[] = Array.isArray(list) ? list : Array.isArray(list?.items) ? list.items : [];
    const last = rows[rows.length - 1];
    if (!last?.id) return { state: 'no_submission' };
    try {
      const body = await this.transport(
        sessionPath(s, '/practice?submission_id=' + encodeURIComponent(last.id)),
        undefined,
        s,
      );
      return { state: 'ready', submissionId: last.id, ...body.result };
    } catch (error: any) {
      if (error?.status === 404 && error?.code === 'feedback_not_ready')
        return { state: 'feedback_pending', submissionId: last.id };
      throw error;
    }
  }
  /**
   * An explicit choice on the shown suggestion. Choosing makes the server validate the plan, create the new
   * practice and record source feedback -> new practice in one request; the new session is then registered
   * here exactly like a normally created one. A replayed request never yields a second session.
   */
  async choosePractice(
    a: Attempt,
    shown: any,
    choice: 'choose' | 'choose_other' | 'decline' | 'continue_revision',
    optionId: string | null,
    requestId: string,
    opts: any = {},
  ) {
    const s = this.session(a);
    if (!s)
      throw new Error(T('找不到原练习的凭据。', 'The original practice credentials are missing.'));
    const { catalog: _listing, ...suggestion } = shown ?? {};
    const send = async () =>
      (
        await this.transport(
          sessionPath(s, '/practice/choices'),
          { shown: suggestion, choice, option_id: optionId, request_id: requestId },
          s,
        )
      ).result;
    if (choice !== 'choose' && choice !== 'choose_other')
      return { result: await send(), attempt: null };
    const target = (choice === 'choose' ? (shown.options ?? []) : (shown.catalog ?? [])).find(
      (o: any) => o.id === optionId,
    );
    const caseId = Object.keys(scenarios).find(
      (k) => scenarios[k] + '-' + shown.work_language === optionId,
    );
    if (!target || !caseId)
      throw new Error(
        T('这个补练情境不在已审核清单里。', 'This practice situation is not on the reviewed list.'),
      );
    let result: any = null;
    const attempt = await this.start(
      caseId,
      {
        ...opts,
        parentAttemptId: a.id,
        practiceOrigin: {
          sourceAttemptId: a.id,
          sourceSessionId: s.id,
          feedbackId: shown.source_feedback?.object_id,
          optionId,
          choice,
          title: target.title,
          reason: target.reason ?? null,
          criteria: (target.basis ?? []).map((b: any) => b.criterion),
          chosenAt: new Date().toISOString(),
        },
      },
      {
        workLanguage: shown.work_language,
        create: async () => {
          // A retry of the same choice returns the same practice and access; it never creates a second one.
          result = await send();
          if (!result.session)
            throw new Error(
              T(
                '补练结果未确认，原选择已保留，可再次确认。',
                'The practice was not confirmed. Your choice is kept; confirm it again.',
              ),
            );
          return result.session;
        },
      },
    );
    return { result, attempt };
  }
  select(a: Attempt) {
    if (!this.session(a))
      throw new Error(
        T(
          '找不到会话凭据，请保留原浏览器存档。',
          'Session credentials are missing. Keep the original browser data.',
        ),
      );
    this.store.select(a.id);
  }
  async perform(a: Attempt, fn: () => Promise<unknown> | undefined, allowSubmitted = false) {
    this.select(a);
    const s = this.session(a)!;
    const snap = this.store.getSnapshot();
    if (snap.busy || s.pending)
      throw new Error(
        T(
          '上一请求还未确认，请先等待或重试原请求。',
          'The previous request is not confirmed yet. Wait, or retry it.',
        ),
      );
    if (snap.storageError)
      throw new Error(
        T('存储不可用，已暂停服务端写入。', 'Storage is unavailable, so server writes are paused.'),
      );
    if (!allowSubmitted && s.world.status !== 'active')
      throw new Error(
        s.world.status === 'submitted'
          ? T(
              '这次交付已锁定。可以查看反馈，或新建练习。',
              'This submission is locked. Read the review or start a new practice.',
            )
          : T('练习已暂停，请先恢复。', 'The practice is paused. Resume it first.'),
      );
    await fn();
    this.changed();
    const after = this.store.getSnapshot();
    if (after.error) throw new Error(after.error);
  }
  async action(a: Attempt, tool: string, args: Record<string, unknown> = {}) {
    await this.perform(a, () => this.store.action(tool, args), tool === 'resume');
  }
  async read(a: Attempt, materialId: string) {
    if (!a.backend.materials.some((m: any) => m.id === materialId))
      throw new Error(
        T('当前会话不可读取这份资料。', 'This document is not available in this session.'),
      );
    if (this.session(a)!.world.status === 'active')
      await this.action(a, 'read_material', { material_id: materialId });
    else {
      await this.store.sync(a.id); // Read only; never invent a historical read receipt.
      const current = this.session(a)!,
        visible = current.materials.find((m) => m.id === materialId);
      if (current.protocol === 2 && visible) {
        const exact = await this.exactMaterial(
          a,
          materialId,
          visible.version,
          current.world.version,
        );
        if (exact)
          this.store.update(a.id, {
            materials: this.session(a)!.materials.map((m) =>
              m.id === materialId && m.version === exact.version ? exact : m,
            ),
          });
      }
    }
  }
  async config(a: Attempt, c: any) {
    const plan = toPilot(c);
    this.select(a);
    this.store.update(a.id, { configDraft: plan });
    await this.action(a, 'update_pilot', { plan });
  }
  async test(a: Attempt, input: any) {
    const s = this.session(a);
    if (!s?.world.configs.pilot)
      throw new Error(
        T(
          '先打开“试点设置”并应用一次配置，再测试助手。',
          'Save the pilot settings once before testing the assistant.',
        ),
      );
    if (
      typeof input.question !== 'string' ||
      !input.question.trim() ||
      Array.from(input.question).length > 4000 ||
      (input.expectation != null && typeof input.expectation !== 'string')
    )
      throw new Error(
        T(
          '测试问题需要 1–4000 个字符，预期表现需要是文字。',
          'The question needs 1–4,000 characters and its expectation must be text.',
        ),
      );
    const origin: TestRunOrigin & { expectation: string } = {
      taskId: input.taskId || null,
      expectation: input.expectation || '',
    };
    if (origin.taskId && !a.tasks.some((t: any) => t.id === origin.taskId))
      throw new Error(T('找不到测试所属的事项。', 'The task for this test was not found.'));
    const linked = ['workId', 'workRevision', 'caseId', 'caseRevision'].some(
      (k) => input[k] !== undefined,
    );
    const investigationLinked = [
      'investigationId',
      'investigationRevision',
      'blockId',
      'blockRevision',
      'baselineRunId',
    ].some((k) => input[k] !== undefined);
    if (linked && investigationLinked)
      throw new Error(
        T('一次测试只能关联一个作品入口。', 'A test can be linked to only one work entry.'),
      );
    if (linked) {
      const work = a.artifacts.find((w: any) => w.id === input.workId);
      if (work?.removedAt)
        throw new Error(
          T(
            '作品已移除，请恢复后再发起测试。',
            'This work has been removed. Restore it before starting a test.',
          ),
        );
      const row = work?.cases?.find((c: any) => c.id === input.caseId);
      if (
        !work?.adopted ||
        work.kind !== 'test_set' ||
        !row ||
        work.revision !== input.workRevision ||
        row.revision !== input.caseRevision ||
        !Number.isInteger(input.workRevision) ||
        input.workRevision < 1 ||
        !Number.isInteger(input.caseRevision) ||
        input.caseRevision < 1 ||
        (work.taskId || null) !== origin.taskId ||
        row.question !== input.question ||
        (row.expectation || '') !== origin.expectation
      ) {
        throw new Error(
          T(
            '测试行或作品已经变化，或尚未采用。请保存并核对当前行后再运行。',
            'The test row or work changed, or has not been adopted. Save and check the current row before running it.',
          ),
        );
      }
      Object.assign(origin, {
        workId: work.id,
        workRevision: work.revision,
        caseId: row.id,
        caseRevision: row.revision,
        intent: row.intent || '',
        refs: structuredClone(row.refs || []),
      });
    }
    if (investigationLinked) {
      const work = a.artifacts.find((w: any) => w.id === input.investigationId);
      const block = work?.blocks?.find((b: any) => b.id === input.blockId);
      const baseline = s.tests.find((t) => t.id === input.baselineRunId);
      if (
        !work?.adopted ||
        work.removedAt ||
        work.kind !== 'investigation' ||
        !block ||
        block.type !== 'retest' ||
        !baseline ||
        block.testId !== baseline.id ||
        baseline.query !== input.question ||
        (work.taskId || null) !== origin.taskId ||
        work.revision !== input.investigationRevision ||
        block.revision !== input.blockRevision ||
        !Number.isInteger(input.investigationRevision) ||
        input.investigationRevision < 1 ||
        !Number.isInteger(input.blockRevision) ||
        input.blockRevision < 1
      ) {
        throw new Error(
          T(
            '调查视图或重测入口已变化、未采用或不可用。请保存并核对当前入口后重测。',
            'The investigation or retest entry changed, has not been adopted, or is unavailable. Save and check it before retesting.',
          ),
        );
      }
      Object.assign(origin, {
        investigationId: work.id,
        investigationRevision: work.revision,
        blockId: block.id,
        blockRevision: block.revision,
        baselineRunId: baseline.id,
        intent: work.question || '',
      });
    }
    const before = new Set(s.tests.map((t) => t.id));
    await this.perform(a, () => this.store.test(input.question, origin));
    const t = this.session(a)!.tests.find((t) => !before.has(t.id));
    if (!t)
      throw new Error(
        T(
          '测试尚未获确认，请重试原请求。',
          'The test is not confirmed yet. Retry the same request.',
        ),
      );
    return a.tests.find((x: any) => x.id === t.id);
  }
  async turn(a: Attempt, role: string, text: string, context?: TurnContext) {
    if (!roleIds[role] || !text.trim() || text.length > 4000)
      throw new Error(T('消息需要 1–4000 个字符。', 'Messages need 1–4,000 characters.'));
    await this.perform(a, () => this.store.sendTurn(roleIds[role], text, context));
    const s = this.session(a)!;
    this.store.update(a.id, {
      inputs: { ...s.inputs, messages: { ...s.inputs.messages, [roleIds[role]]: '' } },
      turnContexts: { ...s.turnContexts, [roleIds[role]]: undefined },
    });
  }
  async save(a: Attempt, draft: Deliverable) {
    this.store.update(a.id, { draft });
    await this.perform(a, () => this.store.saveArtifact());
  }
  async submit(a: Attempt) {
    await this.perform(a, () => this.store.submit());
  }
  async feedback(a: Attempt, retry = false) {
    if (!this.store.submissionId(this.session(a)!))
      throw new Error(
        T('正式交付后才可生成后端反馈。', 'The review can only be generated after you submit.'),
      );
    await this.perform(a, () => this.store.feedback(retry), true);
  }
  async savedFeedback(a: Attempt) {
    const s = this.session(a)!;
    const id = this.store.submissionId(s);
    if (!id) throw new Error(T('尚无正式交付。', 'Nothing has been submitted yet.'));
    const feedback = await this.transport(
      sessionPath(s, '/feedback/' + encodeURIComponent(id)),
      undefined,
      s,
    );
    this.store.update(s.id, { feedback });
    return feedback;
  }
  async history(a: Attempt, seq?: number) {
    const s = this.session(a)!;
    return this.transport(
      sessionPath(s, '/materials' + (seq === undefined ? '' : '?as_of_seq=' + seq)),
      undefined,
      s,
    );
  }
  private visibleMaterial(a: Attempt, id: string, version?: number) {
    const s = this.session(a);
    const current = s?.materials.find((m) => m.id === id);
    if (
      !s ||
      !current ||
      (version !== undefined &&
        (!Number.isInteger(version) || version < 1 || version > current.version))
    ) {
      throw new Error(
        T(
          '当前会话不可读取这个材料版本。',
          'This material version is not readable in the current session.',
        ),
      );
    }
    return { s, current };
  }
  private cacheMaterial(sessionId: string, material: Material) {
    this.materialCache.set(
      JSON.stringify([sessionId, material.id, material.version]),
      structuredClone(material),
    );
    return structuredClone(material);
  }
  private async exactMaterial(
    a: Attempt,
    id: string,
    version: number,
    asOfSeq: number,
  ): Promise<Material | null> {
    const { s, current } = this.visibleMaterial(a, id, version);
    if (s.protocol === 2) {
      const value: any = await this.v4
        .host(s)
        .query('objects.read', { kind: 'material', object_id: id, version });
      const host = this.v4.host(s),
        known = host.draft<any[]>('workspace', 'evidence-cache') ?? [];
      await host.keepDraft('workspace', 'evidence-cache', [
        ...new Map(
          [...known, ...value.content.fragments.map((f: any) => f.ref)].map((ref) => [
            JSON.stringify(ref),
            ref,
          ]),
        ).values(),
      ]);
      return this.cacheMaterial(s.id, {
        id,
        version,
        title: value.content.title,
        content: value.content.fragments.map((f: any) => f.text).join('\n\n'),
      });
    }
    if (current.version === version) return this.cacheMaterial(s.id, current);
    const cached = this.materialCache.get(JSON.stringify([s.id, id, version]));
    if (cached) return structuredClone(cached);
    const activations = s.timeline.events
      .filter(
        (e) =>
          e.seq <= asOfSeq &&
          Array.isArray(e.payload.material_versions) &&
          e.payload.material_versions.some(
            (v: any) => v.material_id === id && v.version === version,
          ),
      )
      .map((e) => e.seq);
    const candidates = [...new Set([asOfSeq, ...activations.reverse(), 0])].filter(
      (seq) => Number.isInteger(seq) && seq >= 0,
    );
    for (const seq of candidates) {
      try {
        const materials = await this.history(a, seq);
        const exact =
          Array.isArray(materials) &&
          materials.find(
            (m: any) => m.id === id && m.version === version && typeof m.content === 'string',
          );
        if (exact) return this.cacheMaterial(s.id, exact);
      } catch {
        /* A missing snapshot or temporary failure must not substitute another version. */
      }
    }
    return null;
  }
  async citationSource(a: Attempt, runId: string, materialId: string) {
    const s = this.session(a);
    const run = s?.tests.find((t) => t.id === runId);
    const citation = run?.citations.find((c) => c.material_id === materialId);
    if (!s || !run || !citation)
      throw new Error(
        T(
          '该引用不属于当前会话的真实测试。',
          'This citation is not part of a real test in the current session.',
        ),
      );
    const material = await this.exactMaterial(a, materialId, citation.version, run.as_of_seq);
    return {
      material,
      requestedVersion: citation.version,
      ...(material
        ? {}
        : {
            reason: T(
              '该引用版本的原文暂未取得；没有用其他版本替代。',
              'The cited version could not be retrieved. No other version was substituted.',
            ),
          }),
    };
  }
  async materialVersion(a: Attempt, id: string, version: number): Promise<Material | null> {
    const { s } = this.visibleMaterial(a, id, version);
    return this.exactMaterial(a, id, version, s.world.version);
  }
  async evidence(a: Attempt, criterion: string, id: string) {
    const s = this.session(a)!;
    return this.transport(
      sessionPath(
        s,
        '/evidence/' +
          [this.store.submissionId(s), criterion, id].map(encodeURIComponent).join('/'),
      ),
      undefined,
      s,
    );
  }
  async relation(a: Attempt, claim: string) {
    await this.perform(a, () => this.store.relation(claim), true);
  }
  async retry(a: Attempt) {
    this.select(a);
    await this.store.execute(a.id);
  }
  async refresh(a?: Attempt) {
    await this.store.health();
    if (a) await this.store.sync(a.id);
  }
  draftFromWorks(a: Attempt) {
    const list = this.base.currentArtifacts(a);
    return list
      .map((x: any) => {
        const view = x.draft ? { ...x, ...x.draft } : x;
        return (
          '## ' +
          view.title +
          '（' +
          view.purpose +
          '，v' +
          x.revision +
          (x.draft ? ' 后的草稿' : '') +
          '）\n' +
          view.body +
          (x.evidence.length
            ? '\n依据：' +
              x.evidence.map((e: any) => e.title + ' [' + e.id + '@' + e.version + ']').join('；')
            : '')
        );
      })
      .join('\n\n');
  }
  private addEvidence(a: Attempt, artifactId: string, ev: any) {
    const target = a.artifacts.find((x: any) => x.id === artifactId);
    if (target?.removedAt)
      throw new Error(
        T(
          '作品已移除，请恢复后再添加依据。',
          'This work has been removed. Restore it before adding evidence.',
        ),
      );
    if (target?.kind === 'test_set') {
      if (this.session(a)?.world.status !== 'active')
        throw new Error(
          T(
            '这次练习只读，不能修改测试作品的依据。',
            'This practice is read-only; the test work evidence cannot be changed.',
          ),
        );
      if (!target.adopted)
        throw new Error(
          T('先采用测试作品，再添加依据。', 'Adopt the test work before adding evidence.'),
        );
      if (this.store.getSnapshot().storageError)
        throw new Error(
          T(
            '存储不可用，不能修改测试作品的依据。',
            'Storage is unavailable; the test work evidence cannot be changed.',
          ),
        );
    }
    const actual =
      ev.type === 'test'
        ? a.tests.find((x: any) => x.id === ev.id && x.configVersion === ev.version)
        : a.backend.materials.find((x: any) => x.id === ev.id && x.version === ev.version);
    if (!target || !actual)
      throw new Error(
        T(
          '只能引用当前会话实际返回的资料或测试。',
          'Only documents and tests returned in this session can be cited.',
        ),
      );
    const safe = {
      id: actual.id,
      title: ev.type === 'test' ? '测试：' + actual.question : actual.title,
      version: ev.version,
      body: ev.type === 'test' ? actual.answer : actual.body,
      type: ev.type,
    };
    return this.base.addEvidence(a, artifactId, safe);
  }
  package(a: Attempt, taskId: string | null, scope: any = {}) {
    const read = new Set([
      'brief',
      ...a.events
        .filter((e: any) => e.server && e.type === 'material_read')
        .map((e: any) => e.detail.materialId),
    ]);
    const artifacts = this.base
      .currentArtifacts(a)
      .filter(
        (x: any) =>
          (!taskId || x.taskId === taskId) &&
          (!scope.artifactIds || scope.artifactIds.includes(x.id)),
      );
    const historicalMaterials: Material[] = [];
    for (const work of artifacts.filter((x: any) => x.kind === 'investigation')) {
      for (const block of (work.blocks || []).filter((b: any) => b.type === 'source_check')) {
        const ref = block.material;
        const citedRun = this.session(a)?.tests.find((t) => t.id === block.testId);
        if (!citedRun?.citations.some((c) => c.material_id === ref?.id)) continue;
        const current = a.backend.materials.find((m: any) => m.id === ref?.id);
        if (
          !current ||
          !Number.isInteger(ref.version) ||
          ref.version < 1 ||
          ref.version > current.version ||
          (scope.materialIds && !scope.materialIds.includes(ref.id))
        )
          continue;
        if (current.version === ref.version) read.add(ref.id);
        else {
          const cached = this.materialCache.get(JSON.stringify([a.id, ref.id, ref.version]));
          if (
            cached &&
            !historicalMaterials.some((m) => m.id === cached.id && m.version === cached.version)
          )
            historicalMaterials.push(structuredClone(cached));
        }
      }
    }
    const requestId = scope.requestId || crypto.randomUUID();
    const inputVersions = artifacts.map((x: any) => ({ artifactId: x.id, revision: x.revision }));
    const materials = [
      ...a.backend.materials.filter(
        (m: any) => read.has(m.id) && (!scope.materialIds || scope.materialIds.includes(m.id)),
      ),
      ...historicalMaterials,
    ];
    const tests = a.tests.filter((t: any) => !scope.testIds || scope.testIds.includes(t.id));
    const inputSnapshot = this.base.captureInputSnapshot(a, { artifacts, materials, tests });
    const guide = this.base.buildReturnGuide(requestId);
    const result = structuredClone({
      schema: 'practice-task-package/v1',
      requestId,
      mode: 'backend-evidence-local-notes',
      exportedAt: new Date().toISOString(),
      scenario: { id: a.scenarioId, title: a.title },
      task: a.tasks.find((t: any) => t.id === taskId) || null,
      materials,
      artifacts,
      tests,
      inputVersions,
      inputSnapshot,
      ...guide,
      instructions:
        T(
          '仅用本包可见资料。作品回传是本地草稿，不批准资源、不执行动作；结论必须核查。',
          'Use only what this package contains. Returned work is a local draft: it approves nothing and runs nothing, and its claims must be checked.',
        ) +
        '\n' +
        guide.instructions,
    });
    if (scope.record) {
      a.exports ||= [];
      a.exports.push({
        requestId,
        taskId,
        inputVersions,
        inputSnapshot: structuredClone(inputSnapshot),
        createdAt: result.exportedAt,
      });
    }
    return result;
  }
  /** Exact-version task package: only versions the person actually read (plus the brief they
   * were given), each with its original text from the server. A version whose text cannot
   * be retrieved is listed as omitted instead of being sent with an empty body. */
  async preparePackageExact(a: Attempt, taskId: string | null, scope: any = {}) {
    const s = this.session(a);
    if (!s || s.protocol !== 2) return this.package(a, taskId, scope);
    const wanted = new Map<string, { id: string; version: number }>();
    const want = (id: string, version: number) => {
      if (!id || !Number.isInteger(version) || version < 1) return;
      if (scope.materialIds && !scope.materialIds.includes(id)) return;
      wanted.set(id + '@' + version, { id, version });
    };
    const brief = s.materials.find((m) => m.id === 'brief');
    if (brief) want('brief', brief.version);
    for (const e of a.events)
      if (e.server && e.type === 'material_read') want(e.detail?.materialId, e.detail?.version);
    const artifacts = this.base
      .currentArtifacts(a)
      .filter(
        (x: any) =>
          (!taskId || x.taskId === taskId) &&
          (!scope.artifactIds || scope.artifactIds.includes(x.id)),
      );
    for (const work of artifacts.filter((x: any) => x.kind === 'investigation'))
      for (const block of (work.blocks || []).filter((b: any) => b.type === 'source_check')) {
        const citedRun = s.tests.find((t) => t.id === block.testId);
        if (
          citedRun?.citations.some(
            (c) => c.material_id === block.material?.id && c.version === block.material?.version,
          )
        )
          want(block.material.id, block.material.version);
      }
    const materials: any[] = [],
      omittedMaterials: any[] = [];
    for (const { id, version } of wanted.values()) {
      let exact: Material | null = null;
      try {
        exact = await this.exactMaterial(a, id, version, s.world.version);
      } catch {
        exact = null;
      }
      const title =
        exact?.title ||
        s.v2MaterialTitles?.[id + ':' + version] ||
        s.materials.find((m) => m.id === id)?.title ||
        id;
      if (exact && exact.content.trim())
        materials.push({ id, version, title, content: exact.content, body: exact.content });
      else
        omittedMaterials.push({
          id,
          version,
          title,
          reason: T(
            '这个版本的原文暂时取不到，没有放入任务包。',
            'The text of this version could not be retrieved, so it was left out.',
          ),
        });
    }
    const requestId = scope.requestId || crypto.randomUUID();
    const inputVersions = artifacts.map((x: any) => ({ artifactId: x.id, revision: x.revision }));
    const tests = a.tests.filter((t: any) => !scope.testIds || scope.testIds.includes(t.id));
    const inputSnapshot = this.base.captureInputSnapshot(a, { artifacts, materials, tests });
    const guide = this.base.buildReturnGuide(requestId);
    const result = structuredClone({
      schema: 'practice-task-package/v1',
      requestId,
      mode: 'backend-evidence-exact-versions',
      exportedAt: new Date().toISOString(),
      scenario: { id: a.scenarioId, title: a.title },
      task: a.tasks.find((t: any) => t.id === taskId) || null,
      materials,
      ...(omittedMaterials.length ? { omittedMaterials } : {}),
      artifacts,
      tests,
      inputVersions,
      inputSnapshot,
      ...guide,
      instructions:
        T(
          '仅用本包可见资料，每份资料都是你读过的确切版本。带回的作品先作为“待检查”，不批准资源、不执行动作；结论必须核查。',
          'Use only what this package contains; each document is the exact version you read. Returned work arrives as “to check”: it approves nothing and runs nothing, and its claims must be checked.',
        ) +
        '\n' +
        guide.instructions,
    });
    if (scope.record) {
      a.exports ||= [];
      a.exports.push({
        requestId,
        taskId,
        inputVersions,
        inputSnapshot: structuredClone(inputSnapshot),
        createdAt: result.exportedAt,
      });
    }
    return result;
  }
  /** Agent return into a v4 practice: saved on the server as work "to check", linked to its
   * task and return id. Nothing is adopted, shared or run by importing. */
  async importNativeReturn(a: Attempt, text: string, taskId: string | null) {
    const s = this.session(a);
    if (!s || s.protocol !== 2 || !s.v2NativeWorkspace)
      throw new Error(
        T('这个练习不支持服务端回传。', 'This practice cannot save returns on the server.'),
      );
    if (s.world.status !== 'active')
      throw new Error(
        T(
          '这次练习只读，不能导入新作品。',
          'This practice is read-only. New work cannot be imported.',
        ),
      );
    const data = this.base.validateImported(text);
    const exp = data.requestId
      ? (a.exports || []).find((x: any) => x.requestId === data.requestId)
      : null;
    if (data.requestId && !exp && data.returnId)
      throw new Error(
        T(
          '找不到对应的任务包；请核对 requestId，或去掉该字段后作为未关联回传导入。',
          'No matching task package. Check the requestId, or remove it to import as an unlinked return.',
        ),
      );
    if (exp?.taskId && taskId && exp.taskId !== taskId)
      throw new Error(
        T(
          '回传所属事项与任务包不一致，请在原事项导入。',
          'This return belongs to a different task. Import it from that task.',
        ),
      );
    const digestText = async (value: string) =>
      Array.from(
        new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))),
      )
        .map((b) => b.toString(16).padStart(2, '0'))
        .join('');
    const returnKey = data.returnId
      ? String(data.returnId)
      : 'paste-' + (await digestText((data.requestId || '') + '\n' + text.trim())).slice(0, 40);
    const products = s.v2Workspace?.products || [];
    const existing = products.find((p: any) => p.source_return_id === returnKey);
    if (existing)
      return {
        duplicate: true,
        removed: !!existing.removed_at,
        productId: existing.product_id as string,
        taskId: existing.task?.object_id ?? null,
      };
    const tasks = (s.v2Workspace?.tasks || []).filter((t: any) => t.status !== 'removed');
    const task = tasks.find((t: any) => t.id === (taskId || exp?.taskId)) || tasks[0];
    if (!task)
      throw new Error(
        T('请先建立一件事项，再导入回传。', 'Create a task before importing a return.'),
      );
    const host = this.v4.host(s);
    let timeline: any = null;
    const testRef = async (id: string) => {
      timeline ??= await host.query('timeline');
      const ref = timeline.objects.find(
        (r: any) => r.ref.kind === 'test' && r.ref.object_id === id,
      )?.ref;
      if (!ref)
        throw new Error(
          T(
            '回传引用了本练习里不存在的测试：',
            'The return cites a test that is not in this practice: ',
          ) + id,
        );
      return ref;
    };
    const materialRef = async (m: { id: string; version: number }, wholeVersion: boolean) => {
      const value: any = await host.query('objects.read', {
        kind: 'material',
        object_id: m.id,
        version: m.version,
      });
      const ref = value?.content?.fragments?.[0]?.ref;
      if (!ref)
        throw new Error(
          T('回传引用的资料版本不可读：', 'The cited document version is not readable: ') +
            m.id +
            ' v' +
            m.version,
        );
      if (!wholeVersion) return ref;
      const { quote: _q, span_start: _s, span_end: _e, ...rest } = ref;
      return rest; // A version-level citation; the agent did not quote a specific passage.
    };
    const purposeKey = (label: string) => canonicalPurpose(label || '自由作品');
    const base = {
      source_return_id: returnKey,
      task: { session_id: s.id, kind: 'task', object_id: task.id, version: task.revision },
      title: data.title,
      evidence_refs: [] as any[],
    };
    let payload: any;
    if (data.kind === 'test_set') {
      const cases = [];
      for (const [i, c] of data.cases.entries())
        cases.push({
          id: 'case-' + (i + 1),
          query: c.question,
          intent: c.intent || '',
          declared_expected: c.expectation || null,
          refs: await Promise.all((c.refs || []).map((r: any) => materialRef(r, true))),
        });
      payload = {
        ...base,
        kind: 'test_plan',
        purpose: 'test_plan',
        content: data.agentSummary ?? data.body ?? '',
        structured_payload: { type: 'test_plan', cases },
      };
    } else if (data.kind === 'investigation') {
      const blocks = [];
      for (const [i, b] of data.blocks.entries()) {
        const id = 'block-' + (i + 1);
        if (b.type === 'note')
          blocks.push({ id, type: 'note', title: b.title || '', text: b.text });
        else if (b.type === 'retest')
          blocks.push({
            id,
            type: 'retest',
            title: b.label || '',
            test_ref: await testRef(b.testId),
          });
        else if (b.type === 'test_compare')
          blocks.push({
            id,
            type: 'test_compare',
            test_refs: await Promise.all(b.testIds.map(testRef)),
          });
        else if (b.type === 'source_check')
          blocks.push({
            id,
            type: 'source_check',
            test_ref: await testRef(b.testId),
            source_ref: await materialRef(b.material, false),
          });
      }
      payload = {
        ...base,
        kind: 'investigation',
        purpose: 'exploration',
        content: data.body || '',
        structured_payload: { type: 'investigation', question: data.question, blocks },
      };
    } else {
      payload = { ...base, kind: 'text', purpose: purposeKey(data.purpose), content: data.body };
    }
    const result = await host.command('work_products.create', payload);
    if (result.status !== 'confirmed')
      throw new Error(
        T(
          '回传尚未保存确认，原文仍在输入框里，请重试。',
          'The return is not confirmed yet. The original text is still in the box; try again.',
        ),
      );
    await this.v4.sync(this.store.getSnapshot().workspace.sessions.find((x) => x.id === s.id)!);
    const body = result.result as any;
    const productId =
      body?.ref?.kind === 'product'
        ? (body.ref.object_id as string)
        : (this.session(a)?.v2Workspace?.products || []).find(
            (p: any) => p.source_return_id === returnKey,
          )?.product_id;
    if (!productId)
      throw new Error(
        T('回传已保存，请在事项目录打开。', 'The return is saved. Open it from the task contents.'),
      );
    if (data.requestId && exp) {
      a.returnLinks ||= {};
      a.returnLinks[productId] = { requestId: data.requestId };
    }
    this.changed();
    return { duplicate: false, removed: false, productId, taskId: task.id };
  }
  /** Adoption is a separate human decision on the exact saved version. */
  async adoptNative(a: Attempt, productId: string) {
    const s = this.session(a);
    const p = s?.v2Workspace?.products.find((x: any) => x.product_id === productId);
    if (!s || !p)
      throw new Error(
        T('找不到这份作品的已保存版本。', 'The saved version of this work is unavailable.'),
      );
    if (s.world.status !== 'active')
      throw new Error(T('这次练习只读。', 'This practice is read-only.'));
    const result = await this.v4.host(s).command('work_products.adopt', {
      product_id: p.product_id,
      product_version: p.version,
      expected_head: p.version,
      status: 'adopted',
    });
    if (result.status !== 'confirmed')
      throw new Error(T('采用尚未确认，请重试。', 'Adoption is not confirmed yet. Try again.'));
    await this.v4.sync(this.store.getSnapshot().workspace.sessions.find((x) => x.id === s.id)!);
    this.changed();
  }
}
