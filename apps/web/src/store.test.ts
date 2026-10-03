import { describe, expect, it, vi } from 'vitest';
import { ApiError, type Transport } from './api';
import { STORAGE_KEY, WorkspaceStore } from './store';
import type { LocalSession, World } from './types';

function fixture() {
  const world: World = { session_id: 's1', version: 0, logical_time: 0, resources: { capacity: 30, dev_days: 3, deadline_day: 7 }, configs: {}, material_versions: { policy: 1 }, indexed_versions: { policy: 1 }, applied_rules: [], pending_requests: [], action_count: 0, config_version: 1, status: 'active' };
  const map = new Map<string, string>();
  const storage = { getItem: (key: string) => map.get(key) || null, setItem: (key: string, value: string) => { map.set(key, value); } };
  const transport = vi.fn<Transport>(async (path: string, body?: any) => {
    if (path === '/sessions') return { session_id: 's1', token: 'test-only-token', state: world };
    if (path.endsWith('/materials')) return [];
    if (path.endsWith('/timeline')) return { events: [], turns: [], mode: 'saved_replay_no_model_calls' };
    if (path === '/sessions/s1' && !body) return { state: world };
    throw new Error('Unexpected call: ' + path);
  });
  const store = new WorkspaceStore(storage, transport);
  return { world, storage, transport, store };
}

describe('live workspace request and recovery boundaries', () => {
  it('uses a separate storage key and restores the session token without putting it in the URL', async () => {
    const { store, storage, transport } = fixture();
    await store.create('pm_pilot');
    const restored = new WorkspaceStore(storage, transport);
    expect(restored.active()?.token).toBe('test-only-token');
    expect(storage.getItem('isy5002_proto_v1')).toBeNull();
    expect(storage.getItem(STORAGE_KEY)).toBeTruthy();
  });

  it('journals an uncertain write before sending and retries exactly the same body and id', async () => {
    const { store, transport, storage } = fixture();
    await store.create('pm_pilot');
    transport.mockImplementationOnce(async () => { throw new ApiError('timeout'); });
    await store.action('refresh_index', {});
    const pending = structuredClone(store.active()!.pending!);
    expect(pending.body.expected_version).toBe(0);
    const restored = new WorkspaceStore(storage, transport);
    transport.mockImplementationOnce(async (_path, body) => { expect(body).toEqual(pending.body); return {}; });
    await restored.execute();
    expect(restored.active()?.pending).toBeUndefined();
  });

  it('refreshes a 409 rejection while keeping the user draft; it never silently rebases a mutation', async () => {
    const { store, transport, world } = fixture();
    await store.create('pm_pilot');
    store.update('s1', { draft: { ...store.active()!.draft, goal: 'User judgement' } });
    world.version = 4;
    transport.mockImplementationOnce(async () => { throw new ApiError('expected 0; current 4', 409); });
    await store.action('refresh_index', {});
    expect(store.active()?.pending).toBeUndefined();
    expect(store.active()?.draft.goal).toBe('User judgement');
    expect(store.active()?.world.version).toBe(4);
    expect(transport.mock.calls.filter(([path]) => path.endsWith('/actions'))).toHaveLength(1);
    expect(store.getSnapshot().error).toContain('重新操作');
  });

  it('restores a queued role job after reload and polls it without sending another turn', async () => {
    const { store, storage, transport } = fixture();
    await store.create('pm_pilot');
    transport.mockImplementationOnce(async () => ({ job_id: 'j1' }));
    await store.sendTurn('tech_lead', 'Can you clarify the index?');
    expect(store.canWrite()).toBe(false);
    const restored = new WorkspaceStore(storage, transport);
    transport.mockImplementationOnce(async () => ({ id: 'j1', status: 'completed', attempt: 1, error: null, result: { trace_id: 'trace', role_id: 'tech_lead', text: 'Actual service response', status: 'completed', model_revision: 'local-extractive-v1', as_of_seq: 0 } }));
    await restored.poll();
    expect(restored.active()?.questions.trace).toBe('Can you clarify the index?');
    expect(restored.active()?.pending).toBeUndefined();
    expect(transport.mock.calls.filter(([path]) => path.endsWith('/turns'))).toHaveLength(1);
  });

  it('does not claim that terminal failed feedback can be retried', async () => {
    const { store, transport } = fixture();
    await store.create('pm_pilot');
    store.update('s1', { submission: { id: 'sub', artifact_id: 'a', config_version: 1, as_of_seq: 0 } });
    transport.mockImplementationOnce(async () => ({ job_id: 'feedback-job' }));
    await store.feedback();
    transport.mockImplementationOnce(async () => ({ id: 'feedback-job', status: 'failed', attempt: 3, result: null, error: 'RuntimeError' }));
    await store.poll();
    expect(store.active()?.feedback).toBeUndefined();
    expect(store.getSnapshot().error).toContain('不支持重新执行');
  });

  it('retains a terminal failed role question for a deliberate new attempt', async () => {
    const { store, transport } = fixture();
    await store.create('pm_pilot');
    transport.mockImplementationOnce(async () => ({ job_id: 'j' }));
    await store.sendTurn('business_lead', 'What should I investigate?');
    transport.mockImplementationOnce(async () => ({ id: 'j', status: 'failed', attempt: 3, result: null, error: 'RuntimeError' }));
    await store.poll();
    expect(store.active()?.failedTurn?.body.text).toBe('What should I investigate?');
    expect(store.active()?.pending).toBeUndefined();
  });

  it('refuses stale artifact submission after configuration changes', async () => {
    const { store, transport } = fixture();
    await store.create('pm_pilot');
    const s = store.active()!;
    store.update('s1', { artifact: { id: 'a', content: s.draft, version: 1, config_version: 0 } });
    await store.submit();
    expect(transport.mock.calls.filter(([path]) => path.endsWith('/submissions'))).toHaveLength(0);
    expect(store.getSnapshot().error).toContain('先保存');
  });

  it('keeps submitted sessions read-only for turns, tests and artifacts', async () => {
    const { store, transport, world } = fixture();
    await store.create('pm_pilot');
    world.status = 'submitted';
    store.update('s1', { world });
    await store.sendTurn('supervisor', 'More');
    await store.test('Question');
    await store.saveArtifact();
    expect(store.canWrite()).toBe(false);
    expect(transport.mock.calls.some(([p]) => /\/(turns|tests|artifacts)$/.test(p))).toBe(false);
  });

  it('stops a mutation if its recovery journal cannot be saved', async () => {
    const { store, storage, transport } = fixture();
    await store.create('pm_pilot');
    storage.setItem = () => { throw new Error('quota'); };
    await store.action('refresh_index', {});
    expect(transport.mock.calls.some(([p]) => p.endsWith('/actions'))).toBe(false);
    expect(store.getSnapshot().storageError).toBe(true);
  });

  it('does not automatically retry non-idempotent session creation', async () => {
    const { store, transport } = fixture();
    transport.mockImplementationOnce(async () => { throw new ApiError('timeout'); });
    await store.create('pm_pilot');
    expect(transport).toHaveBeenCalledTimes(1);
    expect(store.active()).toBeUndefined();
  });

  it('recovers the saved submission reference from the read-only timeline', async () => {
    const { store, transport, world } = fixture();
    await store.create('pm_pilot');
    world.status = 'submitted';
    const original = transport.getMockImplementation()!;
    transport.mockImplementation(async (path, body) => path.endsWith('/timeline') ? { events: [{ seq: 5, event_type: 'submit_plan', actor_id: 'learner', payload: { object_id: 'server-sub' } }], turns: [], mode: 'saved_replay_no_model_calls' } : path.endsWith('/feedback/server-sub') ? { submission_id: 'server-sub', items: [], summary: {}, sources: {}, practice: [] } : original(path, body));
    await store.sync();
    expect(store.submissionId(store.active() as LocalSession)).toBe('server-sub');
    expect(store.active()?.feedback?.submission_id).toBe('server-sub');
  });
});
