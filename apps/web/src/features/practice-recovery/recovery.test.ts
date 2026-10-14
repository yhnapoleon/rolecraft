import { readFileSync } from 'node:fs';
import { runInThisContext } from 'node:vm';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, type Transport } from '../../api';
import { LiveWorkbench } from '../../workbench-live';
import { groupContinueCode } from './code';

type Engine = ConstructorParameters<typeof LiveWorkbench>[0];
const loaded = { exports: {} };
runInThisContext(
  '(function(module){' +
    readFileSync(new URL('../../../public/workbench-engine.js', import.meta.url), 'utf8') +
    '\n})',
)(loaded);
const engine = loaded.exports as Engine;

const CODE = '7K3QM9XRPD2WTHC6NJAF';
const binding = { protocol: 2, sessionId: 's1', workLanguage: 'en', scenarioHash: 'hash-1' };
const point = { business_seq: 3, workspace_revision: 2, storage_revision: 5 };

function opened(token = 'new-token', scenario = 'pm_pilot_urgent_v2') {
  return {
    schema_version: 2,
    result: {
      scenario,
      session: {
        schema_version: 2,
        session_id: 's1',
        token,
        state: { session_id: 's1', status: 'active', cycle_id: 'c', config_version: 1, ...point },
        binding,
      },
    },
  };
}

function memory() {
  const values = new Map<string, string>();
  return {
    values,
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
  };
}

/** The server as the browser sees it: one practice with a task, a work, a test and a reply. */
function server(fail = false): typeof fetch {
  const page = (items: unknown[]) => ({ items, next_cursor: null, as_of: point });
  const records = [
    {
      ref: { kind: 'test', object_id: 't1' },
      assistant: { mode: 'extractive', provider: null, model_revision: null },
      content: {
        query: 'Hotel limit?',
        answer: '400',
        status: 'answered',
        citations: [],
        as_of: point,
        config_ref: { config_version: 1 },
        execution: { source_versions: { policy: 2 }, indexed_versions: { policy: 2 } },
      },
    },
    {
      ref: { kind: 'role_turn', object_id: 'q1' },
      content: { input: { role_id: 'supervisor', text: 'Who first?' }, as_of: point },
    },
    {
      ref: { kind: 'role_reply', object_id: 'r1' },
      content: { request: { object_id: 'q1' }, text: 'Start small.', status: 'answered' },
    },
  ];
  const context = {
    as_of: point,
    session: binding,
    state: { status: 'active', config_version: 1 },
    read_only: false,
    available: {},
    semantic: { roles: 'model', assistant: 'model', feedback: 'model' },
    materials: { materials: [] },
    timeline: {
      events: [],
      objects: records,
      workspace: {
        resources: { capacity: 30, dev_days: 3, deadline_day: 5 },
        source_versions: { policy: 2 },
        indexed_versions: { policy: 2 },
        material_titles: {},
        config: {
          id: 'c',
          version: 1,
          config_version: 1,
          participants: 20,
          domains: ['faq'],
          launch_day: 5,
          update_strategy: 'daily',
          fallback: 'human',
          work_items: [],
        },
      },
    },
  };
  const task = {
    id: 'task-1',
    title: 'Scope',
    goal: 'Who first',
    priority: 0,
    status: 'active',
    revision: 1,
  };
  const work = {
    product_id: 'work-1',
    task: { object_id: 'task-1' },
    title: 'Pilot decision',
    purpose: 'commitment',
    content: 'Defer.',
    version: 1,
    kind: 'text',
    author: { kind: 'human' },
  };
  return vi.fn<typeof fetch>(async (input) => {
    const path = new URL(String(input), 'https://rolecraft.invalid').pathname;
    if (fail) throw new TypeError('offline');
    const result =
      path === '/api/sessions/s1/workbench'
        ? context
        : path === '/api/sessions/s1/work-items'
          ? page([task])
          : path === '/api/sessions/s1/work-products'
            ? page([work])
            : null;
    if (!result) return new Response(JSON.stringify({ code: 'not_found' }), { status: 404 });
    return new Response(
      JSON.stringify({ schema_version: 2, result: { schema_version: 2, result } }),
    );
  });
}

function workbench(first: unknown = opened()) {
  let response = first;
  const calls: unknown[][] = [];
  const transport: Transport = async (path, body, session) => {
    calls.push([path, body, session]);
    if (path === '/continue-codes/exchange') return structuredClone(response);
    throw new ApiError('Not found', 404, 'not_found');
  };
  const storage = memory();
  const live = new LiveWorkbench(engine, storage, transport, { newSessionProtocol: 2 });
  const state = engine.newState();
  live.attach(state, () => {});
  const answer = (next: unknown) => {
    response = next;
  };
  return { live, state, storage, calls, answer };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('a practice opened on this browser with its continue code', () => {
  it('joins this browser’s list and is read from the server, with no code kept', async () => {
    vi.stubGlobal('fetch', server());
    const { live, storage, calls } = workbench();

    const attempt = await live.recover(CODE, 'r1');

    expect(calls).toEqual([
      ['/continue-codes/exchange', { code: CODE, request_id: 'r1' }, undefined],
    ]);
    const snapshot = live.store.getSnapshot();
    expect(snapshot.workspace.active).toBe('s1');
    expect(snapshot.workspace.sessions).toHaveLength(1);
    expect(snapshot.workspace.sessions[0]).toMatchObject({
      id: 's1',
      token: 'new-token',
      scenario: 'pm_pilot_urgent',
      protocol: 2,
      v2Binding: binding,
      v2NativeWorkspace: true,
    });
    expect(snapshot.workspace.sessions[0].recovered).toEqual(expect.any(String));
    expect(attempt.id).toBe('s1');
    expect(attempt.scenarioId).toBe('urgent');
    expect(attempt.tasks.map((t: { title: string }) => t.title)).toEqual(['Scope']);
    expect(attempt.artifacts.map((x: { title: string }) => x.title)).toEqual(['Pilot decision']);
    expect(attempt.tests.map((t: { question: string }) => t.question)).toEqual(['Hotel limit?']);
    expect(attempt.conversations.manager.map((m: { text: string }) => m.text)).toEqual([
      'Who first?',
      'Start small.',
    ]);
    const stored = [...storage.values.values()].join('\n');
    for (const form of [CODE, groupContinueCode(CODE), CODE.toLowerCase()])
      expect(stored).not.toContain(form);
  });

  it('gives a copy this browser already holds the new access, without a second entry', async () => {
    vi.stubGlobal('fetch', server());
    const { live, answer } = workbench();
    await live.recover(CODE, 'r1');
    answer(opened('another-token'));

    await live.recover(CODE, 'r2');

    const sessions = live.store.getSnapshot().workspace.sessions;
    expect(sessions.map((s) => [s.id, s.token])).toEqual([['s1', 'another-token']]);
  });

  it('adds nothing for a situation this browser cannot show', async () => {
    vi.stubGlobal('fetch', server());
    const { live, storage } = workbench(opened('new-token', 'pm_pilot_later_v2'));

    await expect(live.recover(CODE, 'r1')).rejects.toMatchObject({
      code: 'continue_code_scenario_unavailable',
    });

    expect(live.store.getSnapshot().workspace.sessions).toEqual([]);
    expect([...storage.values.values()].join('')).not.toContain('new-token');
  });

  it('shows an empty board, never starter tasks, when the first read fails', async () => {
    vi.stubGlobal('fetch', server(true));
    const { live, state } = workbench();

    await expect(live.recover(CODE, 'r1')).rejects.toBeTruthy();

    expect(live.store.getSnapshot().workspace.sessions.map((s) => s.id)).toEqual(['s1']);
    const attempt = state.attempts.find((a: { id: string }) => a.id === 's1');
    expect(attempt.tasks).toEqual([]);
    expect(attempt.artifacts).toEqual([]);
  });
});
