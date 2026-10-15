import { afterEach, describe, expect, it, vi } from 'vitest';
import { STORAGE_KEY, emptyDraft } from './store';
import type { LocalSession } from './types';
import { LiveWorkbench } from './workbench-live';
import { engine, memory } from './workbench-live-test-support';

/** A v2 practice saved in this browser, as found when the page loads. */
function savedPractice(): LocalSession {
  return {
    id: 's',
    token: 'test-only-token',
    scenario: 'pm_pilot',
    created: '2026-10-14T00:00:00Z',
    protocol: 2,
    v2NativeWorkspace: true,
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
  };
}

describe('page load of a saved v2 practice', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('a dropped first read resolves and shows the connection as lost, without an error', async () => {
    const storage = memory();
    storage.setItem(
      STORAGE_KEY,
      JSON.stringify({ schema: 1, active: 's', sessions: [savedPractice()] }),
    );
    // The API answers its health check, but the practice read never arrives.
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (String(url).endsWith('/health'))
          return new Response(JSON.stringify({ status: 'ok', model: '' }));
        throw new TypeError('Failed to fetch');
      }),
    );
    const live = new LiveWorkbench(engine, storage);
    const state = engine.newState();
    live.attach(state, () => {});
    const attempt = state.attempts.find((a: { id: string }) => a.id === 's');
    await expect(live.load(attempt)).resolves.toBe(false);
    expect(live.store.getSnapshot()).toMatchObject({ connected: false, error: '' });
  });
});
