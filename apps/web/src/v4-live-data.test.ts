import { describe, expect, it, vi } from 'vitest';
import { ApiError } from './api';
import { STORAGE_KEY, WorkspaceStore, emptyDraft } from './store';
import { V4LiveData } from './v4-live-data';
import type { LocalSession, LocalTestRun } from './types';
import type { V4DataHost } from './v4-data-host';

/** A saved v2 practice in a real store; the host stands in for the HTTP gateway. */
function polledPractice(extra: Partial<LocalSession> = {}) {
  const session = {
    id: 's',
    token: 'test-only-token',
    scenario: 'pm_pilot',
    created: '2026-10-14T00:00:00Z',
    protocol: 2,
    v2Binding: { protocol: 2, sessionId: 's', workLanguage: 'zh', scenarioHash: 'fixed' },
    world: {
      session_id: 's',
      status: 'active',
      version: 0,
      logical_time: 0,
      resources: {},
      configs: {},
      material_versions: {},
      indexed_versions: {},
      applied_rules: [],
      pending_requests: [],
      action_count: 0,
      config_version: 1,
    },
    materials: [],
    tests: [],
    testNotes: {},
    questions: {},
    timeline: { events: [], turns: [], mode: '' },
    draft: emptyDraft(),
    inputs: { question: '', expected: '', messages: {}, capacityReason: '', resourceReason: '' },
    ...extra,
  } as LocalSession;
  const values = new Map([
    [STORAGE_KEY, JSON.stringify({ schema: 1, active: 's', sessions: [session] })],
  ]);
  const storage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
  };
  const store = new WorkspaceStore(storage);
  const data = new V4LiveData(store, storage);
  let businessSeq = 9;
  const workbench = () => ({
    as_of: { business_seq: businessSeq, workspace_revision: 3, storage_revision: 12 },
    state: { status: 'active', config_version: 2 },
    read_only: false,
    semantic: { roles: 'waiting_model', assistant: 'waiting_model' },
    materials: { materials: [{ id: 'policy', version: 1, title: 'Travel policy' }] },
    timeline: {
      events: [],
      objects: [],
      workspace: {
        resources: { capacity: 30, dev_days: 3, deadline_day: 7 },
        source_versions: { policy: 1 },
        indexed_versions: { policy: 1 },
        material_titles: { 'policy:1': 'Travel policy' },
        config: {
          id: 'c',
          version: 1,
          config_version: 2,
          participants: 20,
          domains: ['policy_travel'],
          launch_day: 7,
          update_strategy: 'daily',
          fallback: 'human',
          work_items: [],
        },
      },
    },
  });
  const served = async (operation: string): Promise<unknown> =>
    operation === 'workbench.read' ? workbench() : { items: [] };
  let read = served;
  const host = {
    ensureFeedbackPointer: async () => {},
    query: (operation: string) => read(operation),
    pendingRequests: (): { requestId: string }[] => [],
    recover: vi.fn(),
  };
  vi.spyOn(data, 'host').mockReturnValue(host as unknown as ReturnType<V4LiveData['host']>);
  return {
    store,
    host,
    fail: (error: Error) => {
      read = async () => {
        throw error;
      };
    },
    serve: () => {
      read = served;
    },
    advance: () => {
      businessSeq++;
    },
  };
}
const dropped = () => new ApiError('The result is unconfirmed.', 0, 'response_unconfirmed');

describe('background polling of a v2 practice', () => {
  it('settles a completed original test request even when its original response says queued', async () => {
    const queued: LocalTestRun = { taskId: 'task-1', sessionId: 's', requestId: 'r-1', query: 'Hotel limit?', expectation: 'Cite policy', config: null, createdAt: '2026-10-27T00:00:00Z' };
    const practice = polledPractice({ queuedTestRuns: { 'r-1': queued } });
    practice.host.recover.mockResolvedValue({ requestId: 'r-1', status: 'confirmed', result: { status: 'completed', response: { result: { status: 'queued' } }, jobs: [{status: 'completed', effect: {result: {test: {id: 'answer-1'}}}}] } });
    const settled = vi.fn();
    vi.stubGlobal('dispatchEvent', settled);
    try {
      await practice.store.poll();
    } finally {
      vi.unstubAllGlobals();
    }
    expect(practice.store.active()?.queuedTestRuns).toEqual({});
    expect(practice.store.active()?.testRunMeta?.['answer-1']?.requestId).toBe('r-1');
    expect(practice.host.recover).toHaveBeenCalledTimes(1);
    expect(settled).toHaveBeenCalledTimes(1);
    const event = settled.mock.calls[0][0] as CustomEvent;
    expect(event.type).toBe('v4-test-settled');
    expect(event.detail).toEqual({ caseId: null, testId: 'answer-1' });
  });
  it('a dropped read resolves and shows the connection as lost, without an error message', async () => {
    const practice = polledPractice();
    await practice.store.poll();
    practice.fail(dropped());
    await expect(practice.store.poll()).resolves.toBeUndefined();
    expect(practice.store.getSnapshot()).toMatchObject({ connected: false, error: '' });
    practice.serve();
    await practice.store.poll();
    expect(practice.store.getSnapshot()).toMatchObject({ connected: true, error: '' });
  });
  it('a refused read is shown as an error and still resolves', async () => {
    const practice = polledPractice();
    practice.fail(new ApiError('Session credentials are no longer valid.', 401, 'token_invalid'));
    await expect(practice.store.poll()).resolves.toBeUndefined();
    expect(practice.store.getSnapshot()).toMatchObject({
      connected: false,
      error: 'Session credentials are no longer valid.',
    });
  });
  it('a queued test keeps waiting when reading its request is dropped', async () => {
    const queued: LocalTestRun = {
      taskId: 'task-1',
      sessionId: 's',
      requestId: 'r-1',
      query: 'What is the hotel limit?',
      expectation: '',
      config: null,
      createdAt: '2026-10-14T00:00:00Z',
    };
    const practice = polledPractice({ queuedTestRuns: { 'r-1': queued } });
    practice.host.recover.mockRejectedValueOnce(dropped());
    await practice.store.poll();
    expect(Object.keys(practice.store.active()?.queuedTestRuns ?? {})).toEqual(['r-1']);
    expect(practice.store.getSnapshot().error).toBe('');
  });
  it('waits, so a hidden page keeps polling, only while a reply or a queued test is unsettled', () => {
    const practice = polledPractice();
    expect(practice.store.awaiting()).toBe(false);
    let pending = [{ requestId: 'turn-1' }];
    practice.host.pendingRequests = () => pending;
    expect(practice.store.awaiting()).toBe(true);
    pending = [];
    expect(practice.store.awaiting()).toBe(false);
    const queued = { requestId: 'r-1' } as LocalTestRun;
    expect(polledPractice({ queuedTestRuns: { 'r-1': queued } }).store.awaiting()).toBe(true);
  });
  it('an idle poll that reads unchanged data does not notify the workbench', async () => {
    const practice = polledPractice();
    await practice.store.poll();
    const changed = vi.fn();
    practice.store.subscribe(changed);
    await practice.store.poll();
    await practice.store.poll();
    expect(changed).not.toHaveBeenCalled();
    practice.advance();
    await practice.store.poll();
    expect(changed).toHaveBeenCalled();
    expect(practice.store.active()?.world.version).toBe(10);
  });
});

describe('v2 test results shown in the workbench', () => {
  it('flags an old cited policy, but not a stable FAQ, a current real-time citation, or an uncited fallback', async () => {
    const session = {
      id: 's',
      protocol: 2,
      v2Binding: { protocol: 2, sessionId: 's', workLanguage: 'en', scenarioHash: 'fixed' },
      materials: [],
    } as unknown as LocalSession;
    const store: any = {
      installV2: vi.fn(),
      getSnapshot: () => ({ workspace: { sessions: [session] } }),
      update: vi.fn((_id, patch) => Object.assign(session, patch)),
      report: vi.fn(),
    };
    const data = new V4LiveData(store, { getItem: () => null, setItem: () => {} });
    const point = { business_seq: 9, workspace_revision: 3, storage_revision: 12 };
    const test = (id: string, citations: object[], status = 'answered') => ({
      ref: { kind: 'test', object_id: id },
      assistant: { mode: 'extractive', provider: null, model_revision: null, config_version: 2 },
      content: {
        query: id,
        answer: id,
        status,
        citations,
        as_of: point,
        config_ref: { config_version: 2 },
        execution: {
          source_versions: { faq: 1, policy: 2 },
          indexed_versions: { faq: 1, policy: 1 },
        },
      },
    });
    const context = {
      as_of: point,
      state: { status: 'active', config_version: 2 },
      read_only: false,
      semantic: { roles: 'waiting_model', assistant: 'waiting_model' },
      materials: { materials: [] },
      timeline: {
        events: [],
        workspace: {
          resources: {},
          config: {
            id: 'c',
            version: 1,
            config_version: 2,
            participants: 20,
            domains: ['faq', 'policy_travel'],
            launch_day: 7,
            update_strategy: 'daily',
            fallback: 'human',
            work_items: [],
          },
        },
        objects: [
          test('stable-faq', [{ kind: 'material', object_id: 'faq', version: 1 }]),
          test('old-policy', [{ kind: 'material', object_id: 'policy', version: 1 }]),
          test('current-policy', [{ kind: 'material', object_id: 'policy', version: 2 }]),
          test('no-answer', [], 'fallback'),
        ],
      },
    };
    vi.spyOn(data, 'host').mockReturnValue({
      ensureFeedbackPointer: async () => {},
      query: async (op: string) => (op === 'workbench.read' ? context : { items: [] }),
    } as any);
    await data.sync(session);
    expect(session.tests.map((t) => [t.id, t.stale])).toEqual([
      ['stable-faq', false],
      ['old-policy', true],
      ['current-policy', false],
      ['no-answer', false],
    ]);
    expect(session.tests.map((t) => (t as { status?: string }).status)).toEqual([
      'answered',
      'answered',
      'answered',
      'fallback',
    ]);
    expect(session.tests[0].source_versions).toEqual({ faq: 1, policy: 2 });
    expect(session.tests[1].citations).toEqual([{ material_id: 'policy', version: 1 }]);
    expect(session.tests.every((t) => t.mode === 'extractive')).toBe(true);
    expect(session.v2Assistant).toBe('waiting_model');
  });

  it('keeps the configuration the next test uses beside the saved one', async () => {
    const session = {
      id: 's',
      protocol: 2,
      v2Binding: { protocol: 2, sessionId: 's', workLanguage: 'zh', scenarioHash: 'fixed' },
      materials: [],
    } as unknown as LocalSession;
    const store = {
      installV2: vi.fn(),
      getSnapshot: () => ({ workspace: { sessions: [session] } }),
      update: vi.fn((_id: string, patch: object) => Object.assign(session, patch)),
      report: vi.fn(),
    };
    const data = new V4LiveData(store as never, { getItem: () => null, setItem: () => {} });
    const config = {
      id: 'c',
      session_id: 's',
      version: 2,
      config_version: 1,
      participants: 20,
      domains: ['faq'],
      launch_day: 7,
      update_strategy: 'realtime',
      fallback: 'human',
      work_items: ['human_fallback', 'realtime_sync'],
    };
    const effective = {
      requested: config,
      effective: { ...config, update_strategy: 'daily', work_items: ['human_fallback'] },
      differences: { update_strategy: 'realtime_sync_not_provisioned' },
    };
    const point = { business_seq: 4, workspace_revision: 2, storage_revision: 5 };
    const context = {
      as_of: point,
      state: { status: 'active', config_version: 1 },
      read_only: false,
      semantic: { roles: 'waiting_model', assistant: 'waiting_model' },
      materials: { materials: [] },
      timeline: {
        events: [],
        objects: [],
        workspace: { resources: { dev_days: 3 }, config, effective_config: effective },
      },
    };
    vi.spyOn(data, 'host').mockReturnValue({
      ensureFeedbackPointer: async () => {},
      query: async (op: string) => (op === 'workbench.read' ? context : { items: [] }),
    } as never);
    await data.sync(session);
    expect(session.v2EffectiveConfig).toEqual(effective);
  });
});

describe('v2 timeline events kept for the activity tab', () => {
  it('keeps the object each event is about and who did it', async () => {
    const session = {
      id: 's',
      protocol: 2,
      v2Binding: { protocol: 2, sessionId: 's', workLanguage: 'zh', scenarioHash: 'fixed' },
      materials: [],
    } as unknown as LocalSession;
    const store = {
      installV2: vi.fn(),
      getSnapshot: () => ({ workspace: { sessions: [session] } }),
      update: vi.fn((_id: string, patch: Partial<LocalSession>) => Object.assign(session, patch)),
      report: vi.fn(),
    } as unknown as WorkspaceStore;
    const data = new V4LiveData(store, { getItem: () => null, setItem: () => {} });
    const point = { business_seq: 2, workspace_revision: 1, storage_revision: 3 };
    const test = { session_id: 's', kind: 'test', object_id: 't1', version: 1 };
    const context = {
      as_of: point,
      state: { status: 'active', config_version: 1 },
      read_only: false,
      semantic: { roles: 'waiting_model', assistant: 'waiting_model' },
      materials: { materials: [] },
      timeline: {
        events: [
          {
            seq: 1,
            type: 'material_read',
            executor: { kind: 'human', id: 'human:s' },
            data: { material_id: 'brief', version: 1 },
          },
          {
            seq: 2,
            type: 'test_assistant',
            executor: { kind: 'external_agent', id: 'agent:d1', delegation_id: 'd1' },
            refs: [test],
            data: {},
          },
        ],
        workspace: {
          resources: {},
          material_titles: {},
          config: {
            id: 'c',
            version: 1,
            config_version: 1,
            participants: 20,
            domains: ['faq'],
            launch_day: 7,
            update_strategy: 'daily',
            fallback: 'human',
            work_items: [],
          },
        },
        objects: [],
      },
    };
    vi.spyOn(data, 'host').mockReturnValue({
      ensureFeedbackPointer: async () => {},
      query: async (op: string) => (op === 'workbench.read' ? context : { items: [] }),
    } as unknown as V4DataHost);
    await data.sync(session);
    expect(session.timeline.events).toEqual([
      {
        seq: 1,
        event_type: 'read_material',
        actor_id: 'human:s',
        executor_kind: 'human',
        refs: [],
        payload: { material_id: 'brief', version: 1 },
      },
      {
        seq: 2,
        event_type: 'test_assistant',
        actor_id: 'agent:d1',
        executor_kind: 'external_agent',
        refs: [test],
        payload: {},
      },
    ]);
  });
});
