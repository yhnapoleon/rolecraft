/** S1: each run shows its answer and answer chain; unmet cases are grouped by where they stopped. */
import { describe, expect, it, vi } from 'vitest';
import type { ObjectRef } from '../../aipm/types';
import type * as C from '../../contracts-v2';
import { answerChain, fromTestResult } from '../answer-chain/model';
import { createEvaluationDesk } from './index';
import type { BatchView, EvaluationCase } from './model';
import { type DeskState, preview, renderDesk, unmetByStage } from './view';

const ref = (kind: string, id: string): ObjectRef =>
  ({ session_id: 's', kind, object_id: id, version: 1 }) as ObjectRef;
const evalCase = (id: string, run: string | null): EvaluationCase =>
  ({
    id,
    need_ref: 'n',
    triage_row_id: 'r1',
    triage_row_revision: 1,
    request_id: `req-${id}`,
    status: run ? 'completed' : 'pending',
    case_revision: 1,
    route: 'retrieval_generation',
    coverage: 'assistant_answer',
    run_ref: run ? ref('test', run) : null,
  }) as EvaluationCase;
const config = { fallback: 'human', update_strategy: 'daily', freshness_guard: 'none' };
const test = (id: string, over: Partial<C.TestResultV2> & { recognition?: unknown } = {}) =>
  ({
    id,
    session_id: 's',
    query: id,
    answer: `Answer of ${id}`,
    status: 'answered',
    error_code: null,
    citations: [
      { kind: 'material', object_id: 'policy', version: 1, session_id: 's', observed_at_seq: 1 },
    ],
    execution: { source_versions: { policy: 1 }, indexed_versions: { policy: 1 } },
    config: { effective: config, requested: config },
    recognition: [],
    ...over,
  }) as unknown as C.TestResultV2;
const stale = test('t-stale', {
  execution: {
    source_versions: { policy: 2 },
    indexed_versions: { policy: 1 },
  } as unknown as C.TestExecutionMetadata,
});
const missed = test('t-miss', {
  status: 'fallback',
  error_code: 'no_retrieval_hit',
  citations: [],
});
const view = (assessments: BatchView['assessments']): BatchView =>
  ({
    batch: {
      id: 'batch',
      revision: 1,
      execution_mode: 'extractive',
      pause_reason: null,
      cases: [
        evalCase('a', 't-stale'),
        evalCase('b', 't-miss'),
        evalCase('c', 't-ok'),
        evalCase('d', null),
      ],
    },
    assessments,
    summary: { all: { total: 0, runnable: 0, completed: 0, assessed: 0, satisfied: 0 } },
  }) as unknown as BatchView;
const runs = Object.fromEntries(
  [stale, missed, test('t-ok', { answer: 'x'.repeat(200) })].map((t) => [
    t.id,
    { answer: t.answer, chain: fromTestResult(t, { 'policy:1': 'Travel lodging' }) },
  ]),
);
const desk = (over: Partial<DeskState> = {}): DeskState =>
  ({
    language: 'en',
    readOnly: false,
    tab: 'run',
    content: null,
    design: null,
    drafts: [],
    view: view([]),
    monitoring: [],
    running: false,
    busy: false,
    notice: null,
    judging: {},
    runs,
    ...over,
  }) as DeskState;
const caseHtml = (html: string, id: string) =>
  html.split('<li class="aipm-eval__case"').find((part) => part.includes(`data-run="${id}"`)) ?? '';

describe('evaluation desk: answers and answer chains', () => {
  it('renders the answer and the compact chain of a case that ran', () => {
    const html = renderDesk(desk());
    const a = caseHtml(html, 't-stale');
    expect(a).toContain('<p class="aipm-eval__answer-short">Answer of t-stale</p>');
    expect(a).toContain('data-answer-chain');
    expect(a).toContain('data-compact');
    expect(a).toContain(
      'Answered from an outdated source: Travel lodging is now v2, but the answer cites v1.',
    );
    expect(a).toContain('data-action="engineer-handover"');
    expect(a).not.toContain('chain-steps');
  });

  it('keeps long answers to 140 characters with the rest on request', () => {
    const c = caseHtml(renderDesk(desk()), 't-ok');
    expect(c).toContain(`${'x'.repeat(140)}…`);
    expect(c).toContain('<summary>Show the full answer</summary>');
  });

  it('cuts a long English answer on a word, and Chinese at 140 characters', () => {
    const english = `${'Keep the receipt. '.repeat(7)}Obtain written manager approval before booking a hotel.`;
    expect([...english].length).toBeGreaterThan(140);
    expect(preview(english)).toMatch(/ [A-Za-z]+…$/);
    expect(english.startsWith(preview(english).slice(0, -1))).toBe(true);
    expect(english.charAt(preview(english).length - 1)).toBe(' ');
    expect(preview('出'.repeat(200))).toBe(`${'出'.repeat(140)}…`);
  });

  it('renders nothing extra for a case without a run, or before results are read', () => {
    const html = renderDesk(desk());
    expect(html.match(/data-answer-chain/g)).toHaveLength(3);
    expect(renderDesk(desk({ runs: {} }))).not.toContain('data-answer-chain');
  });

  it('shows each case its own saved question, not the first draft of its request', () => {
    const html = renderDesk(
      desk({
        queries: { a: 'Hotel cap after the change?', b: 'Weather on Mars?' },
        drafts: [{ key: 'k', rowId: 'r1', query: 'First draft' } as never],
      }),
    );
    expect(html).toContain('<span class="aipm-eval__q">Hotel cap after the change?</span>');
    expect(html).toContain('<span class="aipm-eval__q">Weather on Mars?</span>');
    expect(html).not.toContain('First draft</span>');
  });

  it('hides "Hand to Daniel" on a read-only practice', () => {
    expect(renderDesk(desk({ readOnly: true }))).not.toContain('engineer-handover');
  });

  it('groups only cases judged "does not meet" by where they stopped', () => {
    const judged = view([
      { case_id: 'a', result: 'not_satisfied', reason: 'old amount', assessed_by: 'learner' },
      { case_id: 'b', result: 'not_satisfied', reason: 'no answer', assessed_by: 'learner' },
      { case_id: 'c', result: 'satisfied', reason: 'ok', assessed_by: 'learner' },
      { case_id: 'd', result: 'not_satisfied', reason: 'not run', assessed_by: 'learner' },
    ]);
    const state = desk({ view: judged });
    expect(unmetByStage(state, judged)).toEqual([
      ['fresh', 1],
      ['found', 1],
    ]);
    expect(renderDesk(state)).toContain('Where the unmet cases stopped');
    expect(renderDesk(state)).toContain('Up to date? 1 · Found 1');
    expect(renderDesk(desk())).not.toContain('Where the unmet cases stopped');
  });
});

describe('evaluation desk: reading the saved results', () => {
  const host = (query?: (op: string) => Promise<unknown>) => ({
    getSessionContext: () => ({ sessionId: 's', workLanguage: 'en' as const, readOnly: false }),
    getClient: () => null,
    readProgress: async () => ({}),
    command: async () => ({}),
    createWorkVersion: async () => ({}),
    sendPreparedTest: async () => ({}),
    readContent: async () => ({}),
    getDataHost: () => ({ openReference: async () => {}, query }),
  });

  it('reads tests and titles once and keeps each run by test id', async () => {
    const query = vi.fn(async (op: string) =>
      op === 'tests.list'
        ? { tests: [stale, missed] }
        : { timeline: { workspace: { material_titles: { 'policy:1': 'Travel lodging' } } } },
    );
    const d = createEvaluationDesk(host(query));
    d.state.view = view([]);
    await d.readRuns();
    expect(query.mock.calls.map(([op]) => op).sort()).toEqual(['tests.list', 'workbench.read']);
    expect(Object.keys(d.state.runs).sort()).toEqual(['t-miss', 't-stale']);
    expect(d.state.runs['t-stale'].chain.citations[0].title).toBe('Travel lodging');
  });

  it('says "current" only against today’s versions, and never without them', async () => {
    const before = test('t-before');
    const read = (workspace: Record<string, unknown>) =>
      vi.fn(async (op: string) =>
        op === 'tests.list' ? { tests: [before] } : { timeline: { workspace } },
      );
    const titles = { material_titles: { 'policy:1': 'Travel lodging' } };
    const changed = createEvaluationDesk(host(read({ ...titles, source_versions: { policy: 2 } })));
    changed.state.view = view([]);
    await changed.readRuns();
    const chain = (d: typeof changed) => d.state.runs['t-before'].chain;
    expect(answerChain(chain(changed), 'en').reason).toBe(
      'Answered from Travel lodging v1, the current version at the time.',
    );
    const same = createEvaluationDesk(host(read({ ...titles, source_versions: { policy: 1 } })));
    same.state.view = view([]);
    await same.readRuns();
    expect(answerChain(chain(same), 'en').reason).toBe(
      'Answered from Travel lodging v1, the current version.',
    );
    const unread = createEvaluationDesk(
      host(async (op: string) => {
        if (op === 'workbench.read') throw new Error('offline');
        return { tests: [before] };
      }),
    );
    unread.state.view = view([]);
    await unread.readRuns();
    expect(answerChain(chain(unread), 'en').reason).toContain('was not checked');
  });

  it('leaves the desk as it was when results cannot be read', async () => {
    const d = createEvaluationDesk(
      host(async () => {
        throw new Error('offline');
      }),
    );
    d.state.view = view([]);
    await expect(d.readRuns()).resolves.toBeUndefined();
    expect(d.state.runs).toEqual({});
    const none = createEvaluationDesk(host());
    await none.readRuns();
    expect(none.state.runs).toEqual({});
  });
});
