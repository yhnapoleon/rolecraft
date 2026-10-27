/** `installAipmEvaluation(host)`: the evaluation desk registered into L1's AIPM host.
 * Writes go through explicit host commands; the server owns batches, results and counts.
 * Running uses the host's `sendPreparedTest`, which sends the saved original command verbatim. */
import type { AipmDesign, MonitoringPlan, ObjectRef } from '../../aipm/types';
import type * as C from '../../contracts-v2';
import { fromTestResult } from '../answer-chain/model';
import {
  blockSummary,
  type BatchView,
  type CaseDraft,
  draftReady,
  emptyMonitoring,
  type EvaluationBatch,
  type EvaluationContent,
  type Language,
  planPayload,
  regressionDraft,
  selections,
  starterDraft,
  text,
} from './model';
import {
  type EvaluationRunnerPort,
  type RunnerBatch,
  SerialEvaluationRunner,
  type TestCommand,
} from './runner';
import {
  type DeskState,
  monitoringComplete,
  monitoringLine,
  readyLine,
  renderDesk,
  type Tab,
} from './view';
import './evaluation.css';

type Feature = { render(): string; mount?(root: HTMLElement): undefined | (() => void) };
type Context = { sessionId: string; workLanguage: Language; readOnly: boolean };

/** The subset of L4's AipmClient this desk reads. */
export interface EvaluationClient {
  readBatch<T>(id: string): Promise<T>;
  readDesign<T>(id: string): Promise<T>;
}
/** Structural subset of L1's `AipmHost`, so this feature compiles without importing its file. */
export interface EvaluationHost {
  getSessionContext(): Context | null;
  getClient(): unknown;
  readProgress(): Promise<unknown>;
  command(operation: string, payload: Record<string, unknown>): Promise<unknown>;
  createWorkVersion(input: never): Promise<unknown>;
  registerFeature(id: 'evaluation', feature: Feature): () => void;
  getDataHost?(): {
    openReference(ref: ObjectRef): Promise<void>;
    /** Saved test results and material titles, for each case's answer and answer chain. */
    query?(operation: 'tests.list' | 'workbench.read'): Promise<unknown>;
  } | null;
  /** Sends a stored `tests.create` Command unchanged: same request_id, no journal, no retry. */
  sendPreparedTest(command: Record<string, unknown>): Promise<unknown>;
  /** The bound package's `public/evaluation.<work language>.json`. */
  readContent(id: 'evaluation'): Promise<unknown>;
}
export type InstallOptions = { content?: Partial<Record<Language, EvaluationContent>> };

type Loose = Record<string, unknown>;
/** Responses are wrapped differently by journal, gateway and read routes; take the first match. */
function dig<T>(value: unknown, pick: (v: Loose) => T | undefined, depth = 5): T | undefined {
  if (!value || typeof value !== 'object' || depth < 0) return undefined;
  const found = pick(value as Loose);
  if (found !== undefined) return found;
  for (const key of ['result', 'response', 'output', 'data', 'design', 'product']) {
    const inner = dig((value as Loose)[key], pick, depth - 1);
    if (inner !== undefined) return inner;
  }
  return undefined;
}
/** A saved work product answers `{ object: version, ref }`, possibly inside a command envelope. */
export function savedPlanOf(response: unknown) {
  return dig(response, (v) => {
    const version = [v.object, v.content, v].find(
      (x): x is Loose => !!x && typeof x === 'object' && !!(x as Loose).structured_payload,
    );
    const payload = version?.structured_payload as { cases?: { id: string }[] } | undefined;
    const ref = (v.ref ?? v.product_ref) as ObjectRef | undefined;
    return payload?.cases && ref?.object_id
      ? { ref, ids: payload.cases.map((c) => c.id) }
      : undefined;
  });
}
const failure = (value: unknown) =>
  dig(
    value,
    (v) => (v.status === 'failed' || v.status === 'needs_context' ? String(v.status) : undefined),
    1,
  );

/** Accept only this desk's content in the practice's work language; never the other language. */
function asContent(value: unknown, language: Language): EvaluationContent {
  const content = value as EvaluationContent | null;
  if (
    content?.schema_version !== 1 ||
    content.language !== language ||
    !Array.isArray(content.routes)
  )
    throw new Error('evaluation_content_unavailable');
  return content;
}

function latestRef(progress: unknown, kind: string): ObjectRef | null {
  const steps =
    dig(progress, (v) => (Array.isArray(v.steps) ? (v.steps as Loose[]) : undefined)) ?? [];
  const refs = steps.flatMap((s) =>
    Array.isArray(s.evidence_refs) ? (s.evidence_refs as ObjectRef[]) : [],
  );
  return refs.filter((r) => r.kind === kind).sort((a, b) => b.version - a.version)[0] ?? null;
}

/** The desk without registering it, so a sheet can embed its own copy (`mountEvaluationBlock`). */
export function createEvaluationDesk(
  host: Omit<EvaluationHost, 'registerFeature'>,
  options: InstallOptions = {},
) {
  const context = host.getSessionContext();
  const language: Language = context?.workLanguage ?? 'zh';
  const state: DeskState = {
    language,
    readOnly: context?.readOnly ?? true,
    tab: 'cases',
    content: options.content?.[language] ?? null,
    design: null,
    drafts: [],
    view: null,
    monitoring: [],
    running: false,
    busy: false,
    notice: null,
    judging: {},
    runs: {},
  };
  const t = (zh: string, en: string) => text(language, zh, en);
  const requireBoundPractice = () => {
    const now = host.getSessionContext();
    if (!context || now?.sessionId !== context.sessionId || now.workLanguage !== language)
      throw new Error('evaluation_practice_changed');
  };
  let root: HTMLElement | null = null;
  let sequence = 0;
  const key = () => `draft-${Date.now().toString(36)}-${++sequence}`;
  const client = () => host.getClient() as EvaluationClient | null;
  const paint = () => {
    if (root) root.innerHTML = renderDesk(state);
  };
  /** Repaint, then give focus back to the same control. */
  const repaintKeeping = (input: HTMLElement) => {
    const { evalDraft, field } = input.dataset;
    paint();
    if (evalDraft && field)
      root
        ?.querySelector<HTMLElement>(
          `[data-eval-draft="${CSS.escape(evalDraft)}"][data-field="${CSS.escape(field)}"]`,
        )
        ?.focus();
  };
  const syncDrafts = () => {
    if (!root) return;
    for (const item of root.querySelectorAll<HTMLElement>('.aipm-eval__draft[data-draft]')) {
      const draft = state.drafts.find((d) => d.key === item.dataset.draft);
      if (draft) item.dataset.ready = String(draftReady(draft));
    }
    const count = root.querySelector('[data-eval-ready]');
    if (count) count.textContent = readyLine(state);
    const save = root.querySelector<HTMLButtonElement>('[data-eval-action="save-plan"]');
    if (save) save.disabled = state.readOnly || state.busy || !state.drafts.some(draftReady);
  };
  const syncMonitoring = () => {
    const line = root?.querySelector('[data-eval-complete]');
    if (line) line.textContent = monitoringLine(state);
    const save = root?.querySelector<HTMLButtonElement>('[data-eval-action="save-monitoring"]');
    if (save)
      save.disabled = state.readOnly || !state.view || state.busy || !monitoringComplete(state);
  };
  const say = (kind: 'status' | 'error', message: string) => {
    state.notice = { kind, message };
    paint();
  };

  async function readView(id: string) {
    requireBoundPractice();
    const c = client();
    if (!c) throw new Error('aipm_client_unavailable');
    const response = await c.readBatch<unknown>(id);
    requireBoundPractice();
    const view = dig(response, (v) =>
      v.batch && v.summary ? (v as unknown as BatchView) : undefined,
    );
    if (!view) throw new Error('aipm_batch_unreadable');
    state.view = view;
    state.monitoring = view.batch.monitoring?.map((m) => ({ ...m })) ?? state.monitoring;
    return view;
  }

  async function load() {
    state.busy = true;
    paint();
    try {
      requireBoundPractice();
      if (!state.content) {
        const content = await host.readContent('evaluation');
        requireBoundPractice();
        state.content = asContent(content, language);
      }
      const progress = await host.readProgress();
      requireBoundPractice();
      const designRef = latestRef(progress, 'aipm_design');
      const c = client();
      if (designRef && c) {
        const response = await c.readDesign<unknown>(designRef.object_id);
        requireBoundPractice();
        state.design =
          dig(response, (v) =>
            Array.isArray(v.rows) ? (v as unknown as AipmDesign) : undefined,
          ) ?? null;
      }
      const batchRef = latestRef(progress, 'aipm_batch');
      if (batchRef) await readView(batchRef.object_id);
      state.notice = null;
      if (state.tab === 'run') void readRuns();
    } catch {
      state.notice = {
        kind: 'error',
        message: t(
          '评测内容暂时读不到，稍后再打开。',
          'Evaluation could not be read. Open it again later.',
        ),
      };
    } finally {
      state.busy = false;
      paint();
    }
  }

  async function write(operation: string, payload: Record<string, unknown>) {
    requireBoundPractice();
    const response = await host.command(operation, payload);
    requireBoundPractice();
    if (failure(response)) throw new Error(failure(response));
    return response;
  }
  const updateBatch = (
    batch: RunnerBatch | EvaluationBatch,
    action: string,
    extra: Record<string, unknown> = {},
  ) =>
    write('aipm.batch.update', {
      batch_id: batch.id,
      expected_revision: batch.revision,
      action,
      ...extra,
    });
  const batchOf = (response: unknown) =>
    dig(response, (v) =>
      v.batch && typeof v.batch === 'object' ? (v.batch as EvaluationBatch) : undefined,
    );
  const live = (batch: RunnerBatch | undefined) => {
    if (batch && state.view) state.view = { ...state.view, batch: batch as EvaluationBatch };
    paint();
    // A case that just finished has a run this desk has not read yet.
    if (unreadRuns()) void readRuns();
    return batch;
  };

  // Each run's answer and answer chain, from the saved test results. Read when the run tab
  // opens and when a case finishes; never polled. Without the reads the desk shows states only.
  const asked = new Set<string>();
  const unreadRuns = () =>
    (state.view?.batch.cases ?? []).some(
      (row) =>
        row.run_ref && !state.runs[row.run_ref.object_id] && !asked.has(row.run_ref.object_id),
    );
  let reading: Promise<void> | null = null;
  function readRuns() {
    reading ??= (async () => {
      try {
        const data = host.getDataHost?.();
        if (!data?.query) return;
        for (const row of state.view?.batch.cases ?? [])
          if (row.run_ref) asked.add(row.run_ref.object_id);
        const [listed, context] = await Promise.all([
          data.query('tests.list'),
          data.query('workbench.read').catch(() => null),
        ]);
        requireBoundPractice();
        const workspace = (context as { timeline?: { workspace?: Loose } } | null)?.timeline
          ?.workspace;
        const titles = (workspace?.material_titles ?? {}) as Record<string, string>;
        // Today's document versions, so a chain says "current" only when it still is.
        const current = workspace?.source_versions as Record<string, number> | undefined;
        const tests = (listed as { tests?: C.TestResultV2[] } | null)?.tests ?? [];
        const runs = { ...state.runs };
        for (const test of tests)
          runs[test.id] = {
            answer: test.answer ?? '',
            chain: { ...fromTestResult(test, titles), currentVersions: current },
          };
        state.runs = runs;
        paint();
      } catch {
        // Unreadable results leave the case states as they are.
      } finally {
        reading = null;
      }
    })();
    return reading;
  }

  const port: EvaluationRunnerPort = {
    read: async (id) => (await readView(id)).batch as RunnerBatch,
    prepare: async (id, revision, caseId) => {
      const response = await write('aipm.batch.update', {
        batch_id: id,
        expected_revision: revision,
        action: 'prepare',
        case_id: caseId,
      });
      const batch = live(batchOf(response) as RunnerBatch | undefined);
      const command = dig(response, (v) =>
        v.command && typeof v.command === 'object' ? (v.command as TestCommand) : undefined,
      );
      if (!batch) throw new Error('evaluation_command_unconfirmed');
      // A paused prepare returns no command; the runner stops on pause_reason first.
      return { batch, command: command ?? (null as unknown as TestCommand) };
    },
    submit: (command) => {
      return host.sendPreparedTest(command);
    },
    reconcile: async (id, revision, caseId) => {
      const response = await write('aipm.batch.update', {
        batch_id: id,
        expected_revision: revision,
        action: 'reconcile',
        case_id: caseId,
      });
      const batch = live(batchOf(response) as RunnerBatch | undefined);
      if (!batch) throw new Error('evaluation_reconcile_unconfirmed');
      return batch;
    },
  };
  const runner = new SerialEvaluationRunner(port);

  async function run() {
    if (!state.view) return;
    state.running = true;
    state.notice = null;
    paint();
    try {
      const stop = await runner.continue(state.view.batch.id);
      await readView(stop.batch.id);
      if (stop.reason === 'pending')
        state.notice = {
          kind: 'status',
          message: t(
            '这一题的结果还没确认。不会重发；稍后再点继续会只读取原请求。',
            'This case’s outcome is not confirmed. It will not be resent; continuing later only reads the original request.',
          ),
        };
      if (stop.reason === 'complete')
        state.notice = {
          kind: 'status',
          message: t(
            '可运行的题都跑完了。下面逐题判定。',
            'All runnable cases are done. Judge them below.',
          ),
        };
    } catch {
      state.notice = {
        kind: 'error',
        message: t(
          '运行中断。已保存的请求不会重发，重新打开后可继续。',
          'The run stopped. Saved requests will not be resent; you can continue after reopening.',
        ),
      };
    } finally {
      state.running = false;
      paint();
    }
  }

  let savedPlan: { drafted: string; ref: ObjectRef; ids: string[] } | null = null;
  async function savePlan() {
    const design = state.design;
    if (!design) return;
    state.busy = true;
    paint();
    try {
      const payload = planPayload(state.drafts);
      const drafted = JSON.stringify(payload);
      // A retry of the same cases reuses the plan already saved, so a failed batch never leaves
      // a second copy of the plan behind.
      if (savedPlan?.drafted !== drafted) {
        const product = await host.createWorkVersion({
          kind: 'test_plan',
          title: t('评测计划', 'Evaluation plan'),
          structured_payload: payload,
        } as never);
        if (failure(product)) throw new Error('plan_not_saved');
        const found = savedPlanOf(product);
        if (!found) throw new Error('plan_ref_unavailable');
        savedPlan = { drafted, ...found };
      }
      const saved = savedPlan;
      const designRef: ObjectRef = {
        session_id: design.session_id,
        kind: 'aipm_design',
        object_id: design.id,
        version: design.revision,
      };
      const created = await write('aipm.batch.create', {
        design_ref: designRef,
        plan_ref: saved.ref,
        selections: selections(state.drafts, saved.ids),
      });
      const batch = batchOf(created);
      if (!batch) throw new Error('batch_unconfirmed');
      savedPlan = null;
      await readView(batch.id);
      state.tab = 'run';
      state.notice = {
        kind: 'status',
        message: t('预期已保存，批次已建立。', 'Expectations saved and batch created.'),
      };
    } catch {
      state.notice = {
        kind: 'error',
        message: t(
          '没能保存。已写的题还在，稍后再试。',
          'Could not save. Your cases are still here; try again later.',
        ),
      };
    } finally {
      state.busy = false;
      paint();
    }
  }

  async function guarded(action: () => Promise<unknown>, done: string) {
    state.busy = true;
    paint();
    try {
      await action();
      state.notice = { kind: 'status', message: done };
    } catch {
      state.notice = {
        kind: 'error',
        message: t('没能保存，稍后再试。', 'Could not save. Try again later.'),
      };
    } finally {
      state.busy = false;
      paint();
    }
  }

  /** One explicit send of the same saved original, only if a fresh read still allows it. */
  function sendAgain(caseId: string) {
    const id = state.view?.batch.id;
    if (!id) return;
    void guarded(
      async () => {
        const view = await readView(id);
        const row = view.batch.cases.find((c) => c.id === caseId);
        if (view.recovery?.[caseId] !== 'send_again' || !row?.original_command) {
          throw new Error('evaluation_resend_not_allowed');
        }
        try {
          await host.sendPreparedTest(row.original_command);
        } catch {
          // An unknown outcome stays unknown; the next read decides, never another send.
        }
        await updateBatch(view.batch, 'reconcile', { case_id: caseId });
        await readView(id);
      },
      t('已用原请求重新发送一次。', 'Sent once more with the original request.'),
    );
  }

  function judge(caseId: string, result: string) {
    const view = state.view;
    const reason = state.judging[caseId]?.trim();
    if (!view || !reason) return;
    const batchRef: ObjectRef = {
      session_id: view.batch.session_id,
      kind: 'aipm_batch',
      object_id: view.batch.id,
      version: view.batch.revision,
    };
    void guarded(
      async () => {
        await write('aipm.assessment.record', {
          batch_ref: batchRef,
          case_id: caseId,
          result,
          reason,
        });
        delete state.judging[caseId];
        await readView(view.batch.id);
      },
      t('判定已记录。', 'Judgement recorded.'),
    );
  }

  function onClick(event: Event) {
    const target = (event.target as HTMLElement).closest<HTMLElement>(
      '[data-eval-action],[data-eval-tab]',
    );
    if (!target || (target as HTMLButtonElement).disabled) return;
    const tab = target.dataset.evalTab as Tab | undefined;
    if (tab) {
      state.tab = tab;
      state.notice = null;
      paint();
      if (tab === 'run') void readRuns();
      return;
    }
    const content = state.content;
    switch (target.dataset.evalAction) {
      case 'add-draft': {
        const row = state.design?.rows?.find((r) => r.id === target.dataset.row);
        if (row && content) state.drafts.push(starterDraft(row, content, key()));
        return paint();
      }
      case 'add-regression': {
        const draft = content && regressionDraft(state.design, content, key());
        if (draft) state.drafts.push(draft);
        else
          say(
            'status',
            t(
              '还没有「检索与回答」类需求，回归题需要挂在这类需求下。',
              'Add a retrieval-and-answer need first; the regression case belongs to one.',
            ),
          );
        return paint();
      }
      case 'remove-draft':
        state.drafts = state.drafts.filter((d) => d.key !== target.dataset.key);
        return paint();
      case 'save-plan':
        return void savePlan();
      case 'run':
        return void run();
      case 'stop':
        runner.stop();
        return say(
          'status',
          t('当前这题结束后不再发起新题。', 'No new case starts after the current one.'),
        );
      case 'resume':
        if (state.view) {
          const view = state.view;
          void guarded(
            async () => {
              await updateBatch(view.batch, 'resume');
              await readView(view.batch.id);
            },
            t(
              '已核对。条件仍有变化时会继续暂停。',
              'Checked. It stays paused if conditions still differ.',
            ),
          );
        }
        return;
      case 'send-again':
        return sendAgain(target.dataset.case ?? '');
      case 'reprepare':
        if (state.view) {
          const view = state.view;
          void guarded(
            async () => {
              await updateBatch(view.batch, 'reprepare', { case_id: target.dataset.case });
              await readView(view.batch.id);
            },
            t(
              '旧请求已放弃并保留在记录里。点运行会用新请求重做这一题。',
              'The old request is set aside on record. Run to redo this case with a new request.',
            ),
          );
        }
        return;
      case 'judge':
        return judge(target.dataset.case ?? '', target.dataset.result ?? 'unknown');
      case 'open-run': {
        const row = state.view?.batch.cases.find((c) => c.id === target.dataset.case);
        if (row?.run_ref) void host.getDataHost?.()?.openReference(row.run_ref);
        return;
      }
      case 'add-monitor': {
        const starter = content?.monitoring.starter_metrics[Number(target.dataset.starter)];
        state.monitoring.push(
          emptyMonitoring(starter?.metric ?? '', starter?.definition_hint ?? ''),
        );
        return paint();
      }
      case 'remove-monitor':
        state.monitoring.splice(Number(target.dataset.index), 1);
        return paint();
      case 'save-monitoring':
        if (state.view) {
          const view = state.view;
          void guarded(
            async () => {
              await updateBatch(view.batch, 'monitoring', { monitoring: state.monitoring });
              await readView(view.batch.id);
            },
            t(
              '观察计划已保存。它是计划，不代表已上线监控。',
              'Plan saved. It is a plan, not deployed monitoring.',
            ),
          );
        }
        return;
    }
  }

  /** Typing updates drafts without repainting, so focus and caret stay put. */
  function onInput(event: Event) {
    const input = event.target as HTMLInputElement;
    const field = input.dataset.field;
    if (input.dataset.evalDraft && field) {
      const draft = state.drafts.find((d) => d.key === input.dataset.evalDraft);
      if (!draft) return;
      if (field === 'answerOnly') draft.answerOnly = input.checked;
      else (draft as Record<string, unknown>)[field as keyof CaseDraft] = input.value;
      // Text fields update the ready count and Save in place: a repaint while the field loses
      // focus would replace the button being clicked and throw inside the blur.
      if (input.type === 'checkbox' || input.tagName === 'SELECT') {
        if (event.type === 'change') repaintKeeping(input);
      } else syncDrafts();
    } else if (input.dataset.evalJudge) {
      const before = !!state.judging[input.dataset.evalJudge]?.trim();
      state.judging[input.dataset.evalJudge] = input.value;
      if (before !== !!input.value.trim()) {
        for (const button of root?.querySelectorAll<HTMLButtonElement>(
          `[data-eval-action="judge"][data-case="${CSS.escape(input.dataset.evalJudge)}"]`,
        ) ?? [])
          button.disabled = state.readOnly || state.busy || !input.value.trim();
      }
    } else if (input.dataset.evalMonitor && field) {
      const plan = state.monitoring[Number(input.dataset.evalMonitor)];
      if (plan) plan[field as keyof MonitoringPlan] = input.value;
      syncMonitoring();
    }
  }

  const feature: Feature = {
    render: () => renderDesk(state),
    mount(element) {
      root = element;
      element.addEventListener('click', onClick);
      element.addEventListener('input', onInput);
      element.addEventListener('change', onInput);
      // Closing the page stops new cases; reopening asks the person to continue.
      const stop = () => runner.stop();
      window.addEventListener('pagehide', stop);
      void load();
      return () => {
        runner.stop();
        window.removeEventListener('pagehide', stop);
        element.removeEventListener('click', onClick);
        element.removeEventListener('input', onInput);
        element.removeEventListener('change', onInput);
        root = null;
      };
    },
  };
  return { feature, state, load, run, sendAgain, readRuns, savePlan };
}

export function installAipmEvaluation(host: EvaluationHost, options: InstallOptions = {}) {
  const desks = new Map<string, ReturnType<typeof createEvaluationDesk>>();
  const current = () => {
    const context = host.getSessionContext();
    const key = `${context?.sessionId ?? ''}:${context?.workLanguage ?? ''}`;
    let desk = desks.get(key);
    if (!desk) {
      desk = createEvaluationDesk(host, options);
      desks.set(key, desk);
    }
    return desk;
  };
  const feature: Feature = {
    render: () => current().feature.render(),
    mount: (root) => current().feature.mount?.(root),
  };
  const unregister = host.registerFeature('evaluation', feature);
  return {
    feature,
    unregister,
    get state() {
      return current().state;
    },
    load: () => current().load(),
    run: () => current().run(),
    sendAgain: (caseId: string) => current().sendAgain(caseId),
  };
}

/** ⑥'s structure block on the sheet (v2 spec §5.1): one summary line, folded by default; opening
 * it mounts the same desk in place. It reads only; every write stays an explicit desk action. */
export function mountEvaluationBlock(
  host: Omit<EvaluationHost, 'registerFeature'>,
  root: HTMLElement,
  options: InstallOptions = {},
) {
  const desk = createEvaluationDesk(host, options);
  const doc = root.ownerDocument;
  const t = (zh: string, en: string) => text(desk.state.language, zh, en);
  const box = doc.createElement('section');
  box.className = 'aipm-eval-block';
  const head = doc.createElement('button');
  head.type = 'button';
  head.className = 'aipm-eval-block__head';
  head.setAttribute('aria-expanded', 'false');
  const body = doc.createElement('div');
  body.className = 'aipm-eval-block__body';
  body.hidden = true;
  box.append(head, body);
  root.replaceChildren(box);
  let dispose: (() => void) | undefined;
  const label = () => {
    head.replaceChildren();
    const name = doc.createElement('span');
    name.className = 'aipm-eval-block__name';
    name.textContent = t('评测、监控与回退', 'Evaluation, monitoring and rollback');
    const line = doc.createElement('span');
    line.className = 'aipm-eval-block__line';
    line.textContent = blockSummary(desk.state.view, desk.state.language);
    const toggle = doc.createElement('span');
    toggle.className = 'aipm-eval-block__toggle';
    toggle.textContent = body.hidden ? t('展开编辑', 'Open to edit') : t('收起', 'Fold');
    head.append(name, line, toggle);
  };
  head.addEventListener('click', () => {
    const opening = body.hidden;
    body.hidden = !opening;
    head.setAttribute('aria-expanded', String(opening));
    if (opening) dispose = desk.feature.mount?.(body) ?? undefined;
    else {
      dispose?.();
      dispose = undefined;
      void desk.load().then(label);
    }
    label();
  });
  label();
  void desk.load().then(label);
  return {
    element: box,
    destroy() {
      dispose?.();
      box.remove();
    },
  };
}
