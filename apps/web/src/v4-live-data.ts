/** v2 data projection into the existing v4 view model. No UI or second journal. */
import { V4DataHost } from './v4-data-host';
import { locale, T } from './app/i18n';
import { ApiError } from './api';
import type { WorkspaceStore } from './store';
import type { LocalSession, LocalTestRun, Operation, Pilot, Material } from './types';
import type { V4HostAdapter } from './v4-host';
import type { ObjectRef, EvidenceRefV2 } from './contracts-v2';

export class V4LiveData {
  private configRefs = new Map<string, ObjectRef>();
  private hosts = new Map<string, V4DataHost>();
  constructor(
    private store: WorkspaceStore,
    private storage: Pick<Storage, 'getItem' | 'setItem'>,
  ) {
    store.installV2({
      sync: (s) => this.sync(s),
      write: (s, kind, body, origin) => this.write(s, kind, body, origin),
      poll: (s) => this.poll(s),
    });
  }
  hasUnpersistedDrafts() {
    return [...this.hosts.values()].some((host) => host.hasUnpersistedDrafts());
  }
  private current(id: string) {
    const s = this.store.getSnapshot().workspace.sessions.find((s) => s.id === id);
    if (!s || s.protocol !== 2 || !s.v2Binding) throw new Error('V2 session unavailable');
    return s;
  }
  host(s: LocalSession): V4DataHost {
    if (!s.v2Binding || s.protocol !== 2) throw new Error('V2 host requires a v2 session');
    let host = this.hosts.get(s.id);
    if (!host) {
      host = new V4DataHost({
        binding: s.v2Binding,
        storage: this.storage,
        credentials: () => {
          const current = this.current(s.id);
          return { sessionId: current.id, token: current.token };
        },
        uiLanguage: locale,
        didRead: (operation, value, input) => this.cacheWorkspace(s.id, operation, value, input),
        didSelect: (kind, ref) => {
          window.dispatchEvent(new CustomEvent('v4-selection', { detail: { kind, ref } }));
        },
        openReference: (ref) => this.dispatch('v4-open-reference', { ref }),
        chooseEvidence: () => this.dispatch('v4-choose-evidence', { sessionId: s.id }),
        announce: (message, kind) =>
          this.store.report(kind === 'error' ? { error: message } : { notice: message }),
      });
      host.subscribe(() => this.store.report({ busy: host!.snapshot().busy }));
      this.hosts.set(s.id, host);
    }
    return host;
  }
  private cacheWorkspace(
    id: string,
    operation: string,
    value: any,
    input: Readonly<Record<string, unknown>>,
  ) {
    if (
      !['work_items.list', 'work_products.list'].includes(operation) ||
      !Array.isArray(value.items)
    )
      return;
    const s = this.current(id),
      previous = s.v2Workspace ?? { tasks: [], products: [] },
      key = operation === 'work_items.list' ? 'tasks' : 'products';
    const rows = Number(input.cursor ?? 0) === 0 ? value.items : [...previous[key], ...value.items];
    const map = new Map(rows.map((row: any) => [row.id ?? row.product_id, row]));
    const next = { ...previous, [key]: [...map.values()] };
    if (JSON.stringify(previous) !== JSON.stringify(next))
      this.store.update(id, { v2Workspace: next });
  }
  private dispatch<T>(name: string, data: Record<string, unknown>): Promise<T> {
    return new Promise((resolve, reject) => {
      const detail = { ...data, resolve, reject, handled: false };
      window.dispatchEvent(new CustomEvent(name, { detail }));
      if (!detail.handled)
        reject(
          new Error(
            T(
              '当前引用入口尚未接通，原记录已保留。',
              'This reference view is not connected yet. The original record is retained.',
            ),
          ),
        );
    });
  }
  async sync(session: LocalSession) {
    try {
      const host = this.host(session);
      await host.ensureFeedbackPointer();
      const context: any = await host.query('workbench.read');
      const s = this.current(session.id),
        timeline = context.timeline,
        w = timeline.workspace,
        config = w.config;
      const pilot: Pilot = {
        participants: config.participants,
        knowledge_domains: config.domains,
        launch_day: config.launch_day,
        update_strategy: config.update_strategy,
        fallback: config.fallback,
        work_items: config.work_items,
      };
      this.configRefs.set(s.id, {
        session_id: s.id,
        kind: 'config',
        object_id: config.id,
        version: config.version,
        config_version: config.config_version,
      });
      const rows: any[] = timeline.objects;
      const materials: Material[] = context.materials.materials.map((m: any) => {
        const previous = s.materials.find((p) => p.id === m.id && p.version === m.version);
        return { id: m.id, version: m.version, title: m.title, content: previous?.content ?? '' };
      });
      const turns = rows
        .filter((r) => r.ref.kind === 'role_turn')
        .flatMap((r) => {
          const reply = rows.find(
            (p) => p.ref.kind === 'role_reply' && p.content.request.object_id === r.ref.object_id,
          );
          if (!reply) return [];
          return [
            {
              trace_id: r.ref.object_id,
              role_id: r.content.input.role_id,
              question: r.content.input.text,
              text:
                (context.semantic.roles === 'waiting_model'
                  ? T('等待模型接入\n', 'Waiting for model connection\n')
                  : '') + reply.content.text,
              status: reply.content.status,
              model_revision: reply.content.model_revision ?? '',
              as_of_seq: r.content.as_of.business_seq,
            },
          ];
        });
      const tests = rows
        .filter((r) => r.ref.kind === 'test')
        .map((r) => {
          const t = r.content;
          return {
            id: r.ref.object_id,
            query: t.query,
            answer: t.answer,
            fallback: t.status === 'fallback',
            stale: (t.citations ?? []).some(
              (c: any) =>
                c.kind === 'material' && c.version < t.execution.source_versions[c.object_id],
            ),
            mode: context.semantic.assistant === 'waiting_model' ? 'waiting_model' : 'model',
            citations: (t.citations ?? []).map((c: any) => ({
              material_id: c.object_id,
              version: c.version,
            })),
            source_versions: t.execution.source_versions,
            indexed_versions: t.execution.indexed_versions,
            config_version: t.config_ref.config_version,
            as_of_seq: t.as_of.business_seq,
          };
        });
      this.store.update(s.id, {
        v2MaterialTitles: w.material_titles,
        v2ReadOnly: context.read_only === true,
        v2Domains: context.configuration_domains ?? s.v2Domains ?? config.domains,
        world: {
          session_id: s.id,
          status:
            context.read_only && context.state.status !== 'submitted'
              ? 'paused'
              : context.state.status,
          version: context.as_of.business_seq,
          logical_time: context.as_of.business_seq,
          resources: w.resources,
          configs: { pilot },
          material_versions: w.source_versions,
          indexed_versions: w.indexed_versions,
          applied_rules: [],
          pending_requests: [],
          action_count: context.as_of.business_seq,
          config_version: context.state.config_version,
        },
        materials,
        tests,
        timeline: {
          mode: context.semantic.roles,
          turns,
          events: (timeline.events ?? []).map((e: any) => ({
            seq: e.seq,
            event_type: e.type === 'material_read' ? 'read_material' : e.type,
            actor_id: e.executor.id,
            payload: e.data,
          })),
        },
      });
      await Promise.all([
        host.query('work_items.list', { limit: 100 }),
        host.query('work_products.list', { limit: 100 }),
      ]);
      this.store.report({ connected: true });
    } catch (error) {
      this.store.report({
        connected: false,
        error: error instanceof Error ? error.message : 'Refresh failed',
      });
      throw error;
    }
  }
  async write(
    session: LocalSession,
    kind: Operation['kind'],
    body: Record<string, unknown>,
    origin?: LocalTestRun,
  ) {
    const host = this.host(session);
    this.store.report({ error: '', notice: '' });
    let operation: string, input: Record<string, unknown>;
    if (kind === 'test') {
      operation = 'tests.create';
      input = { query: body.query, config_version: body.config_version };
    } else if (kind === 'turn') {
      operation = 'turns.create';
      input = { role_id: body.role_id, text: body.text, shares: [] };
    } else if (kind === 'action') {
      operation = 'actions';
      const args = (body.arguments ?? {}) as Record<string, any>;
      if (body.tool === 'read_material') {
        const m = this.current(session.id).materials.find((m) => m.id === args.material_id);
        if (!m) throw new Error('Material unavailable');
        input = {
          tool: 'read_material',
          material: {
            session_id: session.id,
            kind: 'material',
            object_id: m.id,
            version: m.version,
          },
        };
      } else if (body.tool === 'update_pilot') {
        const plan = args.plan as Pilot,
          base = this.configRefs.get(session.id);
        if (!base) throw new Error('Refresh the current settings first');
        operation = 'configuration.apply';
        input = {
          base,
          settings: {
            participants: plan.participants,
            domains: plan.knowledge_domains,
            launch_day: plan.launch_day,
            update_strategy: plan.update_strategy,
            fallback: plan.fallback,
            work_items: plan.work_items,
          },
        };
      } else if (['pause', 'resume', 'refresh_index'].includes(String(body.tool)))
        input = { tool: body.tool };
      else
        throw new ApiError(
          T(
            '请使用对应的 v4 原生部件完成此操作。',
            'Use the corresponding native v4 control for this action.',
          ),
          409,
          'native_slot_required',
        );
    } else
      throw new ApiError(
        T(
          '此操作正在接入原生部件，输入已保留。',
          'This action is being connected to the native control; your input is kept.',
        ),
        409,
        'native_slot_required',
      );
    const result = await host.command(operation, input);
    if (result.status === 'unconfirmed' || result.status === 'failed')
      throw new ApiError(
        T('请求尚未成功确认，输入已保留。', 'The request is not confirmed; your input is kept.'),
        409,
        'request_unconfirmed',
      );
    const value = result.result as any;
    if (kind === 'action' && input.tool === 'read_material') {
      const ref = input.material as ObjectRef,
        fragments = value.fragments ?? [];
      const s = this.current(session.id);
      this.store.update(s.id, {
        materials: s.materials.map((m) =>
          m.id === ref.object_id && m.version === ref.version
            ? { ...m, content: fragments.map((f: any) => f.text).join('\n\n') }
            : m,
        ),
      });
      const refs = host.draft<EvidenceRefV2[]>('workspace', 'evidence-cache') ?? [];
      await host.keepDraft('workspace', 'evidence-cache', [
        ...new Map(
          [...refs, ...fragments.map((f: any) => f.ref)].map((r) => [JSON.stringify(r), r]),
        ).values(),
      ]);
    }
    if (kind === 'test' && value.test && origin) {
      const s = this.current(session.id),
        testId = value.test.id;
      this.store.update(s.id, {
        testRunMeta: { ...s.testRunMeta, [testId]: { ...origin, requestId: result.requestId } },
        testNotes: { ...s.testNotes, [testId]: { expected: origin.expectation, diagnosis: '' } },
      });
    }
    if (kind === 'action' && body.tool === 'update_pilot')
      this.store.update(session.id, { configDraft: undefined });
    await this.sync(this.current(session.id));
  }
  async poll(session: LocalSession) {
    const host = this.host(session);
    // Recovery remains GET-only; a failed model job is never restarted here.
    for (const pending of host.pendingRequests({ readOnly: true }))
      await host
        .recover(pending.requestId)
        .catch((error) => this.store.report({ error: error.message }));
    await this.sync(this.current(session.id));
  }
}
