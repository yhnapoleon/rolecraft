/** FIXTURE ONLY: the design, batch and host below are fake data for component tests.
 * They are not evidence that the normal entry or L1/L4 wiring works. */
import { describe, expect, it, vi } from 'vitest';
import en from '../../../../../scenarios/pm_pilot/aipm-phase1/public/evaluation.en.json';
import zh from '../../../../../scenarios/pm_pilot/aipm-phase1/public/evaluation.zh.json';
import type { AipmDesign, ObjectRef } from '../../aipm/types';
import { type EvaluationHost, installAipmEvaluation } from './index';
import {
  type BatchView,
  blockSummary,
  buckets,
  coverageOf,
  type EvaluationContent,
  type EvaluationCase,
  planPayload,
  ratio,
  regressionDraft,
  selections,
  starterDraft,
  summaryLines,
} from './model';
import { type DeskState, renderDesk } from './view';

const content = { zh: zh as EvaluationContent, en: en as EvaluationContent };
const ref = (kind: string, id: string, version = 1): ObjectRef => ({
  session_id: 's',
  kind,
  object_id: id,
  version,
});
const row = (
  id: string,
  route: AipmDesign['rows'] extends (infer R)[] | undefined
    ? R extends { route: infer X }
      ? X
      : never
    : never,
) => ({
  id,
  revision: 1,
  need_ref: `need-${id}`,
  user_request: `FIXTURE request ${id}`,
  target_action: 'explain' as const,
  route,
  rationale: '',
  final_authority: 'named_human_role' as const,
});
const design: AipmDesign = {
  id: 'design',
  session_id: 's',
  revision: 2,
  rows: [
    row('r1', 'retrieval_generation'),
    row('r2', 'deterministic'),
    row('r3', 'agent_confirmation'),
    row('r4', 'human'),
  ],
};
const rows = design.rows ?? [];
const evalCase = (
  id: string,
  route: EvaluationCase['route'],
  status: EvaluationCase['status'],
): EvaluationCase => ({
  id,
  need_ref: 'n',
  triage_row_id: 'r1',
  triage_row_revision: 1,
  request_id: `req-${id}`,
  test_case_ref: ref('product', 'plan'),
  expected_ref: ref('product', 'plan'),
  status,
  case_revision: 1,
  route,
  coverage: status === 'unsupported' ? 'plan_only' : 'assistant_answer',
  run_ref: status === 'completed' ? ref('test', `t-${id}`) : null,
});
const count = (over: Partial<BatchView['summary']['all']> = {}) => ({
  total: 0,
  runnable: 0,
  completed: 0,
  assessed: 0,
  satisfied: 0,
  unknown: 0,
  unsupported: 0,
  execution_failed: 0,
  completion_rate: null,
  assessment_rate: null,
  satisfaction_rate: null,
  judge: 'learner_assessment' as const,
  ...over,
});
const view: BatchView = {
  batch: {
    id: 'batch',
    session_id: 's',
    revision: 4,
    design_ref: ref('aipm_design', 'design', 2),
    plan_ref: ref('product', 'plan'),
    config_ref: ref('config', 'c'),
    execution_mode: 'extractive',
    pause_reason: null,
    cases: [
      evalCase('a', 'retrieval_generation', 'completed'),
      evalCase('b', 'retrieval_generation', 'completed'),
      evalCase('c', 'deterministic', 'unsupported'),
      evalCase('d', 'retrieval_generation', 'pending'),
    ],
  },
  assessments: [{ case_id: 'a', result: 'satisfied', reason: 'FIXTURE', assessed_by: 'learner' }],
  summary: {
    all: count({
      total: 4,
      runnable: 3,
      completed: 2,
      assessed: 1,
      satisfied: 1,
      unknown: 1,
      unsupported: 1,
    }),
    deterministic: count({ total: 1, unsupported: 1 }),
    retrieval_generation: count({
      total: 3,
      runnable: 3,
      completed: 2,
      assessed: 1,
      satisfied: 1,
      unknown: 1,
    }),
    agent_confirmation: count(),
    human: count(),
  },
};
const desk = (over: Partial<DeskState> = {}): DeskState => ({
  language: 'zh',
  readOnly: false,
  tab: 'cases',
  content: content.zh,
  design,
  drafts: [],
  view: null,
  monitoring: [],
  running: false,
  busy: false,
  notice: null,
  judging: {},
  ...over,
});

describe('evaluation content', () => {
  it('keeps both languages structurally identical and separate', () => {
    const shape = (c: EvaluationContent) => [
      c.routes.map((r) => [r.id, r.case_types.map((t) => t.id)]),
      c.monitoring.fields.map((f) => f.id),
      c.regression.id,
    ];
    expect(shape(content.en)).toEqual(shape(content.zh));
    expect(JSON.stringify(en)).not.toMatch(/[一-鿿]/);
    expect(content.zh.regression.expected_hint).toMatch(/500.*400/);
  });
});

describe('cases and expectations', () => {
  it('starts each case empty: a suggestion, never a filled-in expectation', () => {
    const draft = starterDraft(rows[0], content.zh, 'k');
    expect(draft.query).toBe('');
    expect(draft.expected).toBe('');
    expect(regressionDraft(design, content.zh, 'k2')?.expected).toBe('');
  });

  it('runs only answer coverage and never deterministic rows', () => {
    const base = starterDraft(rows[0], content.zh, 'k');
    expect(coverageOf(base)).toBe('assistant_answer');
    expect(coverageOf({ ...base, route: 'deterministic', answerOnly: true })).toBe('plan_only');
    expect(coverageOf(starterDraft(rows[2], content.zh, 'k'))).toBe('plan_only');
  });

  it('saves only cases with an expectation and maps saved ids in order', () => {
    const drafts = [
      { ...starterDraft(rows[0], content.zh, 'a'), query: 'q1', expected: 'e1' },
      { ...starterDraft(rows[1], content.zh, 'b'), query: 'q2', expected: '' },
      { ...starterDraft(rows[3], content.zh, 'c'), query: 'q3', expected: 'e3' },
    ];
    expect(planPayload(drafts).cases.map((c) => c.query)).toEqual(['q1', 'q3']);
    expect(selections(drafts, ['s1', 's3'])).toEqual([
      { case_id: 's1', triage_row_id: 'r1', coverage: 'assistant_answer' },
      { case_id: 's3', triage_row_id: 'r4', coverage: 'assistant_answer' },
    ]);
    expect(() => selections(drafts, ['s1'])).toThrow('evaluation_plan_mismatch');
  });
});

describe('run, judgement and plan-only cases stay apart', () => {
  it('separates a finished run from a judged case', () => {
    const b = buckets(view);
    expect(b.judged.map((c) => c.id)).toEqual(['a']);
    expect(b.awaitingJudgement.map((c) => c.id)).toEqual(['b']);
    expect(b.unsupported.map((c) => c.id)).toEqual(['c']);
    expect(b.waiting.map((c) => c.id)).toEqual(['d']);
  });

  it('writes every rate with its denominator and the judge', () => {
    expect(ratio('zh', 0, 0)).toBe('暂无可计算的分母');
    const lines = summaryLines('zh', view.summary.all);
    expect(lines.map((l) => l.value)).toEqual(['2 / 3（67%）', '1 / 2（50%）', '1 / 1（100%）']);
    expect(lines[0].note).toContain('1 道计划用例不计入');
    expect(lines[2].note).toContain('判定人：你本人');
  });

  it('offers the run while cases wait, and not when none remain or read-only', () => {
    expect(renderDesk(desk({ tab: 'run', view }))).not.toMatch(/data-eval-action="run" disabled/);
    expect(renderDesk(desk({ tab: 'run', view, readOnly: true }))).toMatch(
      /data-eval-action="run" disabled/,
    );
    const done = { ...view, batch: { ...view.batch, cases: view.batch.cases.slice(0, 3) } };
    expect(renderDesk(desk({ tab: 'run', view: done }))).toMatch(/data-eval-action="run" disabled/);
  });

  it('offers Send again or Prepare again only as the server read allows', () => {
    const prepared = {
      ...evalCase('p', 'retrieval_generation', 'pending'),
      original_command: { request_id: 'req-p' },
      abandoned: [{ request_id: 'old' }],
    };
    const at = (recovery?: 'send_again' | 'reprepare' | 'in_progress') =>
      renderDesk(
        desk({
          tab: 'run',
          view: {
            ...view,
            batch: { ...view.batch, cases: [prepared] },
            recovery: recovery ? { p: recovery } : {},
          },
        }),
      );
    expect(at('send_again')).toContain('data-eval-action="send-again"');
    expect(at('send_again')).toContain('服务端没有收到这道题');
    expect(at('reprepare')).toContain('data-eval-action="reprepare"');
    expect(at('reprepare')).toContain('条件已变，需重新准备');
    for (const html of [at('in_progress'), at()]) {
      expect(html).not.toMatch(/data-eval-action="(send-again|reprepare)"/);
      expect(html).toContain('结果待确认');
    }
    expect(at('send_again')).toContain('已放弃 1 条旧请求，不计入统计');
  });

  it('renders each language without the other', () => {
    for (const tab of ['cases', 'run', 'monitoring'] as const) {
      const english = renderDesk(
        desk({ tab, view, language: 'en', content: content.en, monitoring: [] }),
      );
      expect(english.replace(/FIXTURE[^<"]*/g, '')).not.toMatch(/[一-鿿]/);
      expect(renderDesk(desk({ tab, view }))).not.toMatch(/Run the remaining|Judged by|Plan only/);
    }
  });

  it('folds the block on a sheet into one line', () => {
    expect(blockSummary(null, 'zh')).toBe('还没有评测批次');
    expect(blockSummary(view, 'zh')).toBe('4 题 · 运行 2/3 · 已判定 1 · 观察计划 0 条');
    expect(blockSummary(view, 'en')).toBe('4 cases · ran 2/3 · judged 1 · 0 observation plans');
  });

  it('marks monitoring as a plan, not deployed', () => {
    const html = renderDesk(desk({ tab: 'monitoring', view }));
    expect(html).toContain('不代表监控已经部署');
    expect(html).toMatch(/data-eval-action="save-monitoring"[^>]*disabled/);
  });
});

describe('installAipmEvaluation', () => {
  it('registers the evaluation feature and loads the saved design and batch', async () => {
    const register = vi.fn(() => () => undefined);
    const host: EvaluationHost = {
      getSessionContext: () => ({ sessionId: 's', workLanguage: 'en', readOnly: false }),
      getClient: () => ({
        readDesign: async () => ({ result: { design } }),
        readBatch: async () => ({ result: { result: view } }),
      }),
      readProgress: async () => ({
        steps: [
          { evidence_refs: [ref('aipm_design', 'design', 1), ref('aipm_design', 'design', 2)] },
          { evidence_refs: [ref('aipm_batch', 'batch', 4)] },
        ],
      }),
      command: vi.fn(),
      createWorkVersion: vi.fn(),
      registerFeature: register,
      sendPreparedTest: vi.fn(),
      readContent: async () => content.en,
    };
    const installed = installAipmEvaluation(host);
    expect(register).toHaveBeenCalledWith('evaluation', installed.feature);
    await installed.load();
    expect(installed.state.design?.revision).toBe(2);
    expect(installed.state.view?.batch.id).toBe('batch');
    expect(installed.feature.render()).toContain('Evaluation, monitoring and rollback');
  });

  it('refuses content in the other language', async () => {
    const host = fakeHost({ readContent: async () => content.zh });
    const installed = installAipmEvaluation(host);
    await installed.load();
    expect(installed.state.content).toBeNull();
    expect(installed.state.notice?.kind).toBe('error');
  });

  it('runs through the host: the saved original command is sent once, verbatim', async () => {
    let batch = structuredClone(view.batch);
    batch.cases = [evalCase('x', 'retrieval_generation', 'pending')];
    const original = {
      schema_version: 2,
      request_id: 'req-x',
      operation: 'tests.create',
      expected_version: 3,
      expected_workspace_revision: 9,
      payload: { query: 'FIXTURE q', config_version: 1 },
    };
    const sent: unknown[] = [];
    const host = fakeHost({
      getClient: () => ({
        readDesign: async () => ({ design }),
        readBatch: async () => ({ result: { result: { ...view, batch } } }),
      }),
      readProgress: async () => ({ steps: [{ evidence_refs: [ref('aipm_batch', 'batch', 4)] }] }),
      command: async (operation: string, payload: Record<string, unknown>) => {
        expect(operation).toBe('aipm.batch.update');
        expect(payload.expected_revision).toBe(batch.revision);
        const row = batch.cases[0];
        if (payload.action === 'prepare') row.original_command = structuredClone(original);
        if (payload.action === 'reconcile') row.status = 'completed';
        batch = { ...batch, revision: batch.revision + 1 };
        return {
          status: 'confirmed',
          result: {
            result: { batch, ...(payload.action === 'prepare' ? { command: original } : {}) },
          },
        };
      },
      sendPreparedTest: async (command: Record<string, unknown>) => {
        sent.push(command);
        throw new Error('FIXTURE response lost');
      },
    });
    const installed = installAipmEvaluation(host);
    await installed.load();
    await installed.run();
    expect(sent).toEqual([original]);
    expect(installed.state.view?.batch.cases[0].status).toBe('completed');
    await installed.run();
    expect(sent).toHaveLength(1);
  });
  it('sends the same original again only when a fresh read still allows it', async () => {
    const original = { schema_version: 2, request_id: 'req-y', operation: 'tests.create' };
    let recovery: 'send_again' | 'reprepare' = 'reprepare';
    let batch = structuredClone(view.batch);
    batch.cases = [
      { ...evalCase('y', 'retrieval_generation', 'pending'), original_command: original },
    ];
    const sent: unknown[] = [];
    const actions: unknown[] = [];
    const host = fakeHost({
      getClient: () => ({
        readDesign: async () => ({ design }),
        readBatch: async () => ({
          result: { result: { ...view, batch, recovery: { y: recovery } } },
        }),
      }),
      readProgress: async () => ({ steps: [{ evidence_refs: [ref('aipm_batch', 'batch', 4)] }] }),
      command: async (_operation: string, payload: Record<string, unknown>) => {
        actions.push(payload.action);
        batch = { ...batch, cases: [{ ...batch.cases[0], status: 'completed' }] };
        return { status: 'confirmed', result: { result: { batch } } };
      },
      sendPreparedTest: async (command: Record<string, unknown>) => {
        sent.push(command);
      },
    });
    const installed = installAipmEvaluation(host);
    await installed.load();
    installed.sendAgain('y');
    await vi.waitFor(() => expect(installed.state.busy).toBe(false));
    expect(sent).toEqual([]);
    recovery = 'send_again';
    installed.sendAgain('y');
    await vi.waitFor(() => expect(installed.state.busy).toBe(false));
    expect(sent).toEqual([original]);
    expect(actions).toEqual(['reconcile']);
  });
});

function fakeHost(over: Partial<EvaluationHost> = {}): EvaluationHost {
  return {
    getSessionContext: () => ({ sessionId: 's', workLanguage: 'en', readOnly: false }),
    getClient: () => null,
    readProgress: async () => ({ steps: [] }),
    command: vi.fn(),
    createWorkVersion: vi.fn(),
    registerFeature: () => () => undefined,
    sendPreparedTest: vi.fn(),
    readContent: async () => content.en,
    ...over,
  };
}
