import { describe, expect, it, vi } from 'vitest';
import { V4DataHost, type V4HostPorts } from './v4-data-host';

const point = { business_seq: 8, workspace_revision: 3, storage_revision: 11 };
const state = { ...point, session_id: 's', status: 'active' };
const reply = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const response = (command: any) => ({ schema_version: 2, boundary: { request_id: command.request_id }, state, result: { saved: true } });
function setup() {
  const map = new Map<string, string>();
  const storage = { getItem: vi.fn((key: string) => map.get(key) ?? null), setItem: vi.fn((key: string, value: string) => { map.set(key, value); }) };
  const fetcher = vi.fn<typeof fetch>(async (url, init) => {
    if (!init?.body) return reply({ schema_version: 2, state });
    return reply(response(JSON.parse(String(init.body))));
  });
  let queue = Promise.resolve();
  const ports: V4HostPorts = {
    binding: { protocol: 2, sessionId: 's', workLanguage: 'en', scenarioHash: 'fixed-hash' },
    credentials: () => ({ sessionId: 's', token: 'private-credential' }), storage, uiLanguage: () => 'zh',
    openReference: vi.fn(async () => {}), chooseEvidence: vi.fn(async () => []), announce: vi.fn(), fetcher,
    exclusive: <T>(_name: string, action: () => Promise<T>): Promise<T> => {
      const result = queue.then(action); queue = result.then(() => {}, () => {}); return result;
    },
  };
  return { map, storage, fetcher, ports, host: new V4DataHost(ports) };
}
const posts = (fetcher: ReturnType<typeof setup>['fetcher']) => fetcher.mock.calls.filter(c => c[1]?.body);

describe('v4 single host persistence and recovery', () => {
  it('uses the exact server boundary, persists before POST and never stores/exposes credentials', async () => {
    const { host, fetcher, map } = setup();
    fetcher.mockImplementation(async (_url, init) => {
      if (!init?.body) return reply({ schema_version: 2, state });
      const command = JSON.parse(String(init.body));
      expect(JSON.parse([...map.values()][0]).requests[command.request_id].command).toEqual(command);
      expect(command).toMatchObject({ expected_version: 8, expected_workspace_revision: 3 });
      return reply(response(command));
    });
    const result = await host.command('work_items.create', { title: 'Investigate' });
    expect(result.status).toBe('confirmed');
    expect([...map.values()].join('')).not.toContain('private-credential');
    expect(host.snapshot().session).toMatchObject({ workLanguage: 'en' });
    expect(host.snapshot().uiLanguage).toBe('zh');
    expect(JSON.stringify(host.snapshot())).not.toContain('private-credential');
  });
  it('does not send a command when writing its journal fails', async () => {
    const { host, fetcher, storage } = setup();
    storage.setItem.mockImplementation(() => { throw Error('quota'); });
    await expect(host.command('work_items.create', { title: 'Unsaved' })).rejects.toMatchObject({ code: 'storage_unavailable' });
    expect(posts(fetcher)).toHaveLength(0);
    expect(host.snapshot().storageError).toBe(true);
  });
  it('preserves an ambiguous original command across reload and only GETs during recovery', async () => {
    const { host, ports, fetcher, map } = setup();
    let original: any;
    fetcher.mockImplementation(async (_url, init) => {
      if (!init?.body) return reply({ schema_version: 2, state });
      original = JSON.parse(String(init.body)); throw Error('disconnected after commit');
    });
    const pending = await host.command('turns.create', { role_id: 'supervisor', text: 'Question' });
    expect(pending.status).toBe('unconfirmed');
    const saved = [...map.values()][0];
    const restored = new V4DataHost(ports);
    await expect(restored.command('work_items.create', { title: 'Other action' })).rejects.toMatchObject({ code: 'request_unconfirmed' });
    fetcher.mockImplementation(async () => reply({ schema_version: 2, session_id: 's', request_id: original.request_id,
      operation: 'turns.create', status: 'pending', read_only: true, response: response(original), jobs: [{ job_id: 'j', status: 'running' }] }));
    expect((await restored.recover(pending.requestId)).status).toBe('pending');
    expect(posts(fetcher)).toHaveLength(1);
    expect(JSON.parse(saved).requests[pending.requestId].command).toEqual(JSON.parse([...map.values()][0]).requests[pending.requestId].command);
  });
  it('does not silently convert a server 500 into a definitive rejection', async () => {
    const { host, fetcher } = setup();
    fetcher.mockImplementation(async (_url, init) => init?.body ? reply({ code: 'backend_failure' }, 500) : reply({ schema_version: 2, state }));
    expect((await host.command('work_items.create', { title: 'Keep me' })).status).toBe('unconfirmed');
    expect(posts(fetcher)).toHaveLength(1);
  });
  it('only an explicit retry creates one fresh job-refresh command, retaining the old attempt', async () => {
    const { host, fetcher, map } = setup();
    const original = await host.command('turns.create', { role_id: 'supervisor', text: 'Question' });
    fetcher.mockImplementation(async (url, init) => {
      if (String(url).includes('/requests/')) return reply({ schema_version: 2, session_id: 's', request_id: original.requestId,
        operation: 'turns.create', status: 'failed', read_only: true, jobs: [{ job_id: 'j', status: 'failed' }] });
      if (!init?.body) return reply({ schema_version: 2, state });
      return reply(response(JSON.parse(String(init.body))));
    });
    await host.recover(original.requestId);
    expect(posts(fetcher)).toHaveLength(1);
    const retried = await host.retry(original.requestId);
    expect(posts(fetcher)).toHaveLength(2);
    expect(retried.requestId).not.toBe(original.requestId);
    expect(JSON.parse(String(posts(fetcher)[1][1]?.body))).toMatchObject({ operation: 'jobs.refresh', payload: { job_id: 'j' } });
    const entries = JSON.parse([...map.values()][0]).requests;
    expect(entries[retried.requestId].previousRequestId).toBe(original.requestId);
    expect(entries[original.requestId].command.payload.text).toBe('Question');
  });
  it('never retries a still-running job', async () => {
    const { host, fetcher } = setup();
    const original = await host.command('turns.create', { text: 'Question' });
    fetcher.mockImplementation(async () => reply({ schema_version: 2, session_id: 's', request_id: original.requestId,
      operation: 'turns.create', status: 'pending', read_only: true, jobs: [{ job_id: 'j', status: 'running' }] }));
    await expect(host.retry(original.requestId)).rejects.toMatchObject({ code: 'retry_not_available' });
    expect(posts(fetcher)).toHaveLength(1);
  });
  it('preserves interleaved drafts from two native slots/host instances and leaves legacy storage unchanged', async () => {
    const { host, ports, map } = setup();
    map.set('rolecraft.live.workspace.v1', 'legacy-bytes');
    const second = new V4DataHost(ports);
    await Promise.all([host.keepDraft('workspace', 'work', { body: 'private draft' }), second.keepDraft('roles', 'supervisor', 'unsent question')]);
    await host.flushDrafts();
    expect(host.draft('workspace', 'work')).toEqual({ body: 'private draft' });
    expect(host.draft('roles', 'supervisor')).toBe('unsent question');
    expect(map.get('rolecraft.live.workspace.v1')).toBe('legacy-bytes');
  });
  it('cannot dispatch secret-bearing delegation services before the control-plane adapter exists', async () => {
    const { host, fetcher } = setup();
    expect(host.snapshot().available['delegations.create']).toBe(false);
    await expect(host.command('delegations.create', { agent_label: 'test' })).rejects.toMatchObject({ code: 'delegation_host_not_ready' });
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('previews an import through the existing read-only handler without a write journal', async () => {
    const { host, fetcher, map } = setup();
    fetcher.mockImplementation(async (_url, init) => {
      if (!init?.body) return reply({ schema_version: 2, state });
      const sent = JSON.parse(String(init.body));
      expect(sent.operation).toBe('workspace_imports');
      expect(sent.payload.mode).toBe('preview');
      return reply({ schema_version: 2, result: { package_id: 'p', mode: 'preview', applied: false, as_of: point } });
    });
    expect(await host.query('workspace_imports', { package_id: 'p', mode: 'preview' })).toMatchObject({ applied: false });
    expect(map.size).toBe(0);
    await expect(host.query('workspace_imports', { package_id: 'p', mode: 'apply' })).rejects.toMatchObject({ code: 'invalid_read' });
    expect(posts(fetcher)).toHaveLength(1);
  });
  it('retains unsaved text in memory after a quota failure and flushes it when storage recovers', async () => {
    const { host, storage, ports } = setup();
    await host.keepDraft('workspace', 'work', 'old');
    storage.setItem.mockImplementationOnce(() => { throw Error('quota'); });
    await expect(host.keepDraft('workspace', 'work', 'new unsaved text')).rejects.toMatchObject({ code: 'storage_unavailable' });
    expect(host.draft('workspace', 'work')).toBe('new unsaved text');
    await host.flushDrafts();
    expect(new V4DataHost(ports).draft('workspace', 'work')).toBe('new unsaved text');
  });
  it('rejects a corrupt journal without replacing it, and blocks cross-session references and envelopes', async () => {
    const { ports, map, fetcher } = setup();
    map.set('rolecraft.v4.session.s', '{broken');
    const host = new V4DataHost(ports);
    await expect(host.command('work_items.create', { title: 'x' })).rejects.toMatchObject({ code: 'storage_unavailable' });
    expect(map.get('rolecraft.v4.session.s')).toBe('{broken');
    expect(fetcher).not.toHaveBeenCalled();
    expect(() => host.openReference({ session_id: 'other', kind: 'product', object_id: 'p', version: 1 })).toThrow();
  });
  it('keeps model status independent and requires the exact fixed session binding', async () => {
    const { host, fetcher } = setup();
    const context = { as_of: point, state, session: host.snapshot().session, available: { 'turns.create': true },
      semantic: { roles: 'model', feedback: 'waiting_model', assistant: 'waiting_model' } };
    fetcher.mockResolvedValue(reply({ schema_version: 2, result: { result: context } }));
    await host.query('workbench.read');
    expect(host.snapshot().semantic).toEqual(context.semantic);
    fetcher.mockResolvedValue(reply({ schema_version: 2, result: { result: { ...context, session: { ...context.session, workLanguage: 'zh' } } } }));
    await expect(host.query('workbench.read')).rejects.toMatchObject({ code: 'response_unconfirmed' });
    expect(host.snapshot().session?.workLanguage).toBe('en');
  });
});
