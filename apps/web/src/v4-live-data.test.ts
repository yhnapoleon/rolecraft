import { describe, expect, it, vi } from 'vitest';
import { V4LiveData } from './v4-live-data';
import type { LocalSession } from './types';
import type { WorkspaceStore } from './store';
import type { V4DataHost } from './v4-data-host';

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
    expect(session.tests[0].source_versions).toEqual({ faq: 1, policy: 2 });
    expect(session.tests[1].citations).toEqual([{ material_id: 'policy', version: 1 }]);
    expect(session.tests.every((t) => t.mode === 'extractive')).toBe(true);
    expect(session.v2Assistant).toBe('waiting_model');
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
