import { afterEach, describe, expect, it, vi } from 'vitest';
import { setPreference } from './app/i18n';
import { V4LiveData } from './v4-live-data';
import { fromPilot, toPilot } from './workbench-live';
import type { WorkspaceStore } from './store';
import type { LocalSession, LocalTestRun, Pilot } from './types';

const point = { business_seq: 4, workspace_revision: 2, storage_revision: 6 };
const config = {
  id: 'pilot',
  version: 3,
  config_version: 2,
  participants: 20,
  domains: ['stable_faq', 'policy_travel'],
  launch_day: 7,
  update_strategy: 'daily',
  fallback: 'human',
  work_items: ['scope_filter'],
};
const savedTest = (id: string, mode: string, effective: object) => ({
  ref: { kind: 'test', object_id: id },
  assistant: {
    mode,
    provider: mode === 'extractive' ? null : 'openai',
    model_revision: mode === 'extractive' ? null : 'm1',
    config_version: 2,
  },
  content: {
    query: id,
    answer: `Saved answer ${id}`,
    status: 'answered',
    citations: [{ kind: 'material', object_id: 'policy', version: 1 }],
    as_of: point,
    config_ref: { config_version: 2 },
    config: { requested: effective, effective },
    execution: { source_versions: { policy: 1 }, indexed_versions: { policy: 1 } },
  },
});

function harness(assistant: 'model' | 'waiting_model', generator?: 'llm') {
  const session = {
    id: 's',
    protocol: 2,
    v2Binding: { protocol: 2, sessionId: 's', workLanguage: 'en', scenarioHash: 'fixed' },
    materials: [],
    tests: [],
    testNotes: {},
    testRunMeta: {},
  } as unknown as LocalSession;
  const report = vi.fn<(patch: { error?: string }) => void>();
  const store = {
    installV2: vi.fn(),
    getSnapshot: () => ({ workspace: { sessions: [session] } }),
    update: vi.fn((_id: string, patch: Partial<LocalSession>) => Object.assign(session, patch)),
    report,
  } as unknown as WorkspaceStore;
  const objects: object[] = [];
  const context = {
    as_of: point,
    state: { status: 'active', config_version: 2 },
    read_only: false,
    semantic: { roles: 'waiting_model', feedback: 'waiting_model', assistant },
    materials: { materials: [] },
    timeline: {
      events: [],
      workspace: { resources: {}, config: { ...config, ...(generator ? { generator } : {}) } },
      objects,
    },
  };
  const host = {
    ensureFeedbackPointer: async () => {},
    query: async (operation: string) => (operation === 'workbench.read' ? context : { items: [] }),
    command: vi.fn(),
    recover: vi.fn(),
    pendingRequests: vi.fn(() => []),
    keepDraft: vi.fn(),
    draft: vi.fn(),
  };
  const data = new V4LiveData(store, { getItem: () => null, setItem: () => {} });
  vi.spyOn(data, 'host').mockReturnValue(host as unknown as ReturnType<V4LiveData['host']>);
  return { session, report, host, data, objects };
}

const origin: LocalTestRun = {
  taskId: 'task-1',
  workId: 'plan',
  workRevision: 2,
  caseId: 'case-1',
  caseRevision: 1,
  sessionId: 's',
  requestId: 'local',
  query: 'What is the hotel limit?',
  expectation: 'Cites policy',
  config: null,
  createdAt: '2026-10-11T00:00:00Z',
};

afterEach(() => setPreference('zh'));

describe('assistant generator in the v4 data host', () => {
  it('projects each saved mode, the deployment state and the saved generator', async () => {
    const { session, data, objects } = harness('model', 'llm');
    objects.push(
      savedTest('extract', 'extractive', { generator: 'extractive' }),
      savedTest('generated', 'llm', { generator: 'llm' }),
    );
    await data.sync(session);
    expect(session.v2Assistant).toBe('model');
    expect(session.world.configs.pilot?.generator).toBe('llm');
    expect(session.tests.map((t) => [t.id, t.mode, t.answer])).toEqual([
      ['extract', 'extractive', 'Saved answer extract'],
      ['generated', 'llm', 'Saved answer generated'],
    ]);
    expect(session.tests[1].generation).toEqual({ provider: 'openai', model_revision: 'm1' });
    expect(session.tests[1].effective_config).toEqual({ generator: 'llm' });
  });

  it('defaults an omitted generator to extractive and sends the visible choice with settings', async () => {
    const { session, host, data } = harness('waiting_model');
    await data.sync(session);
    const pilot = session.world.configs.pilot as Pilot;
    expect(pilot.generator).toBe('extractive');
    expect(fromPilot(pilot).generator).toBe('extractive');
    host.command.mockResolvedValue({ requestId: 'c', status: 'confirmed', result: {} });
    const plan = toPilot({ ...fromPilot(pilot), participants: 25 });
    await data.write(session, 'action', { tool: 'update_pilot', arguments: { plan } });
    const [operation, input] = host.command.mock.calls[0];
    expect(operation).toBe('configuration.apply');
    expect(input.settings).toMatchObject({ participants: 25, generator: 'extractive' });
    expect(input.base).toEqual({
      session_id: 's',
      kind: 'config',
      object_id: 'pilot',
      version: 3,
      config_version: 2,
    });
  });

  it('keeps a queued generation linked to its test-plan row until the worker saves it', async () => {
    const { session, host, data, objects, report } = harness('model', 'llm');
    host.command.mockResolvedValue({
      requestId: 'r-1',
      status: 'pending',
      result: { status: 'queued' },
    });
    const outcome = await data.write(
      session,
      'test',
      { query: origin.query, config_version: 2 },
      origin,
    );
    expect(outcome).toEqual({ queued: 'r-1' });
    expect(session.queuedTestRuns?.['r-1']).toMatchObject({ caseId: 'case-1', requestId: 'r-1' });
    expect(session.testRunMeta).toEqual({});
    // Still running: polling reads the original request and keeps waiting.
    host.recover.mockResolvedValueOnce({ requestId: 'r-1', status: 'pending', result: {} });
    await data.poll(session);
    expect(Object.keys(session.queuedTestRuns ?? {})).toEqual(['r-1']);
    objects.push(savedTest('generated', 'llm', { generator: 'llm' }));
    host.recover.mockResolvedValueOnce({
      requestId: 'r-1',
      status: 'confirmed',
      result: {
        jobs: [{ status: 'completed', effect: { result: { test: { id: 'generated' } } } }],
      },
    });
    await data.poll(session);
    expect(host.recover).toHaveBeenCalledWith('r-1');
    expect(session.queuedTestRuns).toEqual({});
    expect(session.testRunMeta?.generated).toMatchObject({
      workId: 'plan',
      caseId: 'case-1',
      requestId: 'r-1',
    });
    expect(session.testNotes.generated).toEqual({ expected: 'Cites policy', diagnosis: '' });
    expect(session.tests.map((t) => t.mode)).toEqual(['llm']);
    expect(report.mock.calls.every(([patch]) => !patch.error)).toBe(true);
    expect(host.command).toHaveBeenCalledTimes(1);
  });

  it('stops waiting with a visible message when the queued request failed', async () => {
    setPreference('en');
    const { session, host, data, report } = harness('model', 'llm');
    host.command.mockResolvedValue({
      requestId: 'r-2',
      status: 'pending',
      result: { status: 'queued' },
    });
    await data.write(session, 'test', { query: origin.query, config_version: 2 }, origin);
    host.recover.mockResolvedValueOnce({
      requestId: 'r-2',
      status: 'failed',
      result: { jobs: [] },
    });
    await data.poll(session);
    expect(session.queuedTestRuns).toEqual({});
    expect(session.testRunMeta).toEqual({});
    expect(report).toHaveBeenCalledWith({
      error: 'This test did not produce a result. The question is kept; run it again when ready.',
    });
    // Recovery never starts another model call.
    expect(host.command).toHaveBeenCalledTimes(1);
  });
});
