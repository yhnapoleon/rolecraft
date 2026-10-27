import { describe, expect, it, vi } from 'vitest';
import { RECOVER_TIMEOUT_MS, V4DataHost, type V4HostPorts } from './v4-data-host';

const point = { business_seq: 8, workspace_revision: 3, storage_revision: 11 };
const state = { ...point, session_id: 's', status: 'active' };
const reply = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const response = (command: any) => ({
  schema_version: 2,
  boundary: { request_id: command.request_id },
  state,
  result: { saved: true },
});
function setup() {
  const map = new Map<string, string>();
  const storage = {
    getItem: vi.fn((key: string) => map.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      map.set(key, value);
    }),
  };
  const fetcher = vi.fn<typeof fetch>(async (url, init) => {
    if (!init?.body) return reply({ schema_version: 2, state });
    return reply(response(JSON.parse(String(init.body))));
  });
  let queue = Promise.resolve();
  const ports: V4HostPorts = {
    binding: { protocol: 2, sessionId: 's', workLanguage: 'en', scenarioHash: 'fixed-hash' },
    credentials: () => ({ sessionId: 's', token: 'private-credential' }),
    storage,
    uiLanguage: () => 'zh',
    openReference: vi.fn(async () => {}),
    chooseEvidence: vi.fn(async () => []),
    announce: vi.fn(),
    fetcher,
    exclusive: <T>(_name: string, action: () => Promise<T>): Promise<T> => {
      const result = queue.then(action);
      queue = result.then(
        () => {},
        () => {},
      );
      return result;
    },
  };
  return { map, storage, fetcher, ports, host: new V4DataHost(ports) };
}
const posts = (fetcher: ReturnType<typeof setup>['fetcher']) =>
  fetcher.mock.calls.filter((c) => c[1]?.body);

describe('v4 single host persistence and recovery', () => {
  it('returns the declared task page through the existing gateway envelope', async () => {
    const { host, fetcher } = setup();
    const task = {
      id: 'task',
      session_id: 's',
      revision: 1,
      title: 'Known task',
      created_at: '2026-10-09T00:00:00Z',
      updated_at: '2026-10-09T00:00:00Z',
    };
    fetcher.mockImplementation(async () =>
      reply({
        schema_version: 2,
        result: { schema_version: 2, result: { items: [task], as_of: point, next_cursor: null } },
      }),
    );
    const page = await host.query('work_items.list', { cursor: 0, limit: 20 });
    expect(page.items[0].title).toBe('Known task');
    expect(page.as_of).toEqual(point);
    expect(fetcher).toHaveBeenCalledWith(
      '/api/sessions/s/work-items?cursor=0&limit=20',
      expect.objectContaining({ method: 'GET' }),
    );
    expect(posts(fetcher)).toHaveLength(0);
  });
  it('uses the exact server boundary, persists before POST and never stores/exposes credentials', async () => {
    const { host, fetcher, map } = setup();
    fetcher.mockImplementation(async (_url, init) => {
      if (!init?.body) return reply({ schema_version: 2, state });
      const command = JSON.parse(String(init.body));
      expect(JSON.parse([...map.values()][0]).requests[command.request_id].command).toEqual(
        command,
      );
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
    storage.setItem.mockImplementation(() => {
      throw Error('quota');
    });
    await expect(host.command('work_items.create', { title: 'Unsaved' })).rejects.toMatchObject({
      code: 'storage_unavailable',
    });
    expect(posts(fetcher)).toHaveLength(0);
    expect(host.snapshot().storageError).toBe(true);
  });
  it('treats a recovery read with no answer after 15 seconds as unconfirmed and frees the lock', async () => {
    const { host, fetcher } = setup();
    fetcher.mockImplementation(async (_url, init) => {
      if (!init?.body) return reply({ schema_version: 2, state });
      throw Error('disconnected after commit');
    });
    const pending = await host.command('turns.create', { role_id: 'supervisor', text: 'Question' });
    vi.useFakeTimers();
    try {
      fetcher.mockImplementation(() => new Promise<Response>(() => {}));
      const waiting = host.recover(pending.requestId);
      const settled = expect(waiting).rejects.toMatchObject({ code: 'response_unconfirmed' });
      await vi.advanceTimersByTimeAsync(RECOVER_TIMEOUT_MS);
      await settled;
      fetcher.mockImplementation(async () =>
        reply({
          schema_version: 2,
          session_id: 's',
          request_id: pending.requestId,
          operation: 'turns.create',
          status: 'pending',
          read_only: true,
        }),
      );
      expect((await host.recover(pending.requestId)).status).toBe('pending');
    } finally {
      vi.useRealTimers();
    }
  });
  it('preserves an ambiguous original command across reload and only GETs during recovery', async () => {
    const { host, ports, fetcher, map } = setup();
    let original: any;
    fetcher.mockImplementation(async (_url, init) => {
      if (!init?.body) return reply({ schema_version: 2, state });
      original = JSON.parse(String(init.body));
      throw Error('disconnected after commit');
    });
    const pending = await host.command('turns.create', { role_id: 'supervisor', text: 'Question' });
    expect(pending.status).toBe('unconfirmed');
    const saved = [...map.values()][0];
    const restored = new V4DataHost(ports);
    await expect(
      restored.command('work_items.create', { title: 'Other action' }),
    ).rejects.toMatchObject({ code: 'request_unconfirmed' });
    fetcher.mockImplementation(async () =>
      reply({
        schema_version: 2,
        session_id: 's',
        request_id: original.request_id,
        operation: 'turns.create',
        status: 'pending',
        read_only: true,
        response: response(original),
        jobs: [{ job_id: 'j', status: 'running' }],
      }),
    );
    expect((await restored.recover(pending.requestId)).status).toBe('pending');
    expect(posts(fetcher)).toHaveLength(1);
    expect(JSON.parse(saved).requests[pending.requestId].command).toEqual(
      JSON.parse([...map.values()][0]).requests[pending.requestId].command,
    );
  });
  it('rebuilds a command once, quietly, when a background job moved the version point', async () => {
    const { host, fetcher, ports } = setup();
    let sent = 0;
    fetcher.mockImplementation(async (_url, init) => {
      if (!init?.body) return reply({ schema_version: 2, state });
      sent += 1;
      return sent === 1
        ? reply({ code: 'version_conflict', detail: 'moved' }, 409)
        : reply(response(JSON.parse(String(init.body))));
    });
    const result = await host.command('work_items.create', { title: 'Investigate' });
    expect(result.status).toBe('confirmed');
    const ids = posts(fetcher).map((c) => JSON.parse(String(c[1]?.body)).request_id);
    expect(ids).toHaveLength(2);
    expect(ids[0]).not.toBe(ids[1]);
    expect(ports.announce).not.toHaveBeenCalled();
  });
  it('reports a second version conflict and never retries a content conflict', async () => {
    const twice = setup();
    twice.fetcher.mockImplementation(async (_url, init) =>
      init?.body
        ? reply({ code: 'version_conflict', detail: 'moved' }, 409)
        : reply({ schema_version: 2, state }),
    );
    expect((await twice.host.command('work_items.create', { title: 'A' })).status).toBe('failed');
    expect(posts(twice.fetcher)).toHaveLength(2);
    expect(twice.ports.announce).toHaveBeenCalledTimes(1);
    const content = setup();
    content.fetcher.mockImplementation(async (_url, init) =>
      init?.body
        ? reply({ code: 'object_version_conflict', detail: 'edited' }, 409)
        : reply({ schema_version: 2, state }),
    );
    expect((await content.host.command('work_items.create', { title: 'B' })).status).toBe('failed');
    expect(posts(content.fetcher)).toHaveLength(1);
  });
  it('does not silently convert a server 500 into a definitive rejection', async () => {
    const { host, fetcher } = setup();
    fetcher.mockImplementation(async (_url, init) =>
      init?.body ? reply({ code: 'backend_failure' }, 500) : reply({ schema_version: 2, state }),
    );
    expect((await host.command('work_items.create', { title: 'Keep me' })).status).toBe(
      'unconfirmed',
    );
    expect(posts(fetcher)).toHaveLength(1);
  });
  it('only an explicit retry creates one fresh job-refresh command, retaining the old attempt', async () => {
    const { host, fetcher, map } = setup();
    const original = await host.command('turns.create', {
      role_id: 'supervisor',
      text: 'Question',
    });
    fetcher.mockImplementation(async (url, init) => {
      if (String(url).includes('/requests/'))
        return reply({
          schema_version: 2,
          session_id: 's',
          request_id: original.requestId,
          operation: 'turns.create',
          status: 'failed',
          read_only: true,
          jobs: [{ job_id: 'j', status: 'failed' }],
        });
      if (!init?.body) return reply({ schema_version: 2, state });
      return reply(response(JSON.parse(String(init.body))));
    });
    await host.recover(original.requestId);
    expect(posts(fetcher)).toHaveLength(1);
    const retried = await host.retry(original.requestId);
    expect(posts(fetcher)).toHaveLength(2);
    expect(retried.requestId).not.toBe(original.requestId);
    expect(JSON.parse(String(posts(fetcher)[1][1]?.body))).toMatchObject({
      operation: 'jobs.refresh',
      payload: { job_id: 'j' },
    });
    const entries = JSON.parse([...map.values()][0]).requests;
    expect(entries[retried.requestId].previousRequestId).toBe(original.requestId);
    expect(entries[original.requestId].command.payload.text).toBe('Question');
  });
  it('never retries a still-running job', async () => {
    const { host, fetcher } = setup();
    const original = await host.command('turns.create', {
      role_id: 'supervisor',
      text: 'Question',
    });
    fetcher.mockImplementation(async () =>
      reply({
        schema_version: 2,
        session_id: 's',
        request_id: original.requestId,
        operation: 'turns.create',
        status: 'pending',
        read_only: true,
        jobs: [{ job_id: 'j', status: 'running' }],
      }),
    );
    await expect(host.retry(original.requestId)).rejects.toMatchObject({
      code: 'retry_not_available',
    });
    expect(posts(fetcher)).toHaveLength(1);
  });
  it('preserves interleaved drafts from two native slots/host instances and leaves legacy storage unchanged', async () => {
    const { host, ports, map } = setup();
    map.set('rolecraft.live.workspace.v1', 'legacy-bytes');
    const second = new V4DataHost(ports);
    await Promise.all([
      host.keepDraft('workspace', 'work', { body: 'private draft' }),
      second.keepDraft('roles', 'supervisor', 'unsent question'),
    ]);
    await host.flushDrafts();
    expect(host.draft('workspace', 'work')).toEqual({ body: 'private draft' });
    expect(host.draft('roles', 'supervisor')).toBe('unsent question');
    expect(map.get('rolecraft.live.workspace.v1')).toBe('legacy-bytes');
  });
  it('cannot dispatch secret-bearing delegation services before the control-plane adapter exists', async () => {
    const { host, fetcher } = setup();
    expect(host.snapshot().available['delegations.create']).toBe(false);
    await expect(
      host.command('delegations.create', {
        agent_label: 'test',
        expires_at: new Date(Date.now() + 1800000).toISOString(),
      }),
    ).rejects.toMatchObject({ code: 'delegation_host_not_ready' });
    expect(fetcher).not.toHaveBeenCalled();
  });
  /** A host whose control plane issues grant d1 with the token 'agent-secret'. */
  async function issuingHost(listed: () => unknown[] = () => []) {
    const setupResult = setup();
    const { host, fetcher } = setupResult;
    const context = {
      as_of: point,
      state,
      session: host.snapshot().session,
      available: { 'delegations.create': true, 'delegations.revoke': true },
      semantic: { roles: 'model', feedback: 'model', assistant: 'model' },
    };
    fetcher.mockImplementation(async (url, init) => {
      if (!init?.body && String(url).includes('/delegations?'))
        return reply({
          schema_version: 2,
          result: { schema_version: 2, result: { items: listed(), next_cursor: null } },
        });
      if (!init?.body)
        return String(url).endsWith('/workbench')
          ? reply({ schema_version: 2, result: { result: context } })
          : reply({ schema_version: 2, state });
      const sent = JSON.parse(String(init.body));
      return reply({
        schema_version: 2,
        result: {
          schema_version: 2,
          result:
            sent.operation === 'delegations.revoke'
              ? { delegation_id: 'd1', revoked: true }
              : { delegation: { id: 'd1' }, token: 'agent-secret' },
        },
      });
    });
    await host.query('workbench.read');
    return setupResult;
  }
  const grant = (status: 'active' | 'expired' | 'revoked') => ({
    id: 'd1',
    session_id: 's',
    executor: { id: 'external:d1', kind: 'external_agent', delegation_id: 'd1' },
    capabilities: ['read', 'act'],
    allowed_actions: null,
    allowed_objects: null,
    create_under_tasks: [],
    expires_at: new Date(Date.now() + 1800000).toISOString(),
    revoked: status === 'revoked',
    effective_status: status,
  });
  const config = { api_url: 'http://127.0.0.1:1/api', session_id: 's', token: 'agent-secret' };
  // One offering: the card hands the secret out while it is open; once the person finishes it is
  // gone for good. The secret never reaches results, storage or the snapshot.
  it('keeps an issued agent secret only in memory and hands the connection config out once', async () => {
    const { host, map, storage } = await issuingHost();
    expect(host.snapshot().available).toMatchObject({
      'delegations.create': true,
      'delegations.list': true,
    });
    const expiresAt = new Date(Date.now() + 1800000).toISOString();
    const issued = await host.command('delegations.create', {
      agent_label: 'Helper',
      expires_at: expiresAt,
    });
    expect(issued.status).toBe('confirmed');
    expect(JSON.stringify(issued)).not.toContain('agent-secret');
    expect([...map.values()].join('')).not.toContain('agent-secret');
    expect(JSON.stringify(storage.setItem.mock.calls)).not.toContain('agent-secret');
    expect(JSON.stringify(host.snapshot())).not.toContain('agent-secret');
    expect(host.issuedDelegation()).toEqual({
      delegationId: 'd1',
      label: 'Helper',
      issuedAt: expect.any(String),
      expiresAt,
    });
    expect(JSON.stringify(host.issuedDelegation())).not.toContain('agent-secret');
    expect(host.connectionConfig('http://127.0.0.1:1/api')).toEqual(config);
    const issuedStates: ReturnType<typeof host.issuedDelegation>[] = [];
    const unsubscribe = host.subscribe(() => issuedStates.push(host.issuedDelegation()));
    host.dismissConnection();
    expect(issuedStates).toEqual([null]);
    unsubscribe();
    expect(host.issuedDelegation()).toBeNull();
    expect(host.connectionSecret()).toBeNull();
    expect(host.connectionConfig('http://127.0.0.1:1/api')).toBeNull();
    await host.command('delegations.create', {
      agent_label: 'Second',
      expires_at: new Date(Date.now() + 1800000).toISOString(),
    });
    await host.command('delegations.revoke', { delegation_id: 'd1' });
    expect(host.issuedDelegation()).toBeNull();
    expect([...map.values()].join('')).not.toContain('agent-secret');
  });
  it('stops offering a grant the server lists as revoked, expired or missing', async () => {
    for (const elsewhere of [[grant('revoked')], [grant('expired')], []]) {
      let listed: unknown[] = [grant('active')];
      const { host } = await issuingHost(() => listed);
      await host.command('delegations.create', {
        agent_label: 'Helper',
        expires_at: new Date(Date.now() + 1800000).toISOString(),
      });
      await host.query('delegations.list', { cursor: 0, limit: 50 });
      expect(host.connectionSecret()?.token).toBe('agent-secret');
      // Revoked in another tab, expired by the server clock, or gone: the card stops offering it.
      listed = elsewhere;
      const states: ReturnType<typeof host.issuedDelegation>[] = [];
      const unsubscribe = host.subscribe(() => states.push(host.issuedDelegation()));
      await host.query('delegations.list', { cursor: 0, limit: 50 });
      unsubscribe();
      expect(host.connectionSecret()).toBeNull();
      expect(host.issuedDelegation()).toBeNull();
      expect(states).toContain(null);
    }
  });
  it('offers the secret for every copy until the person finishes, the grant expires or it is revoked', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    const logged = (['log', 'info', 'warn', 'error', 'debug'] as const).map((name) =>
      vi.spyOn(console, name).mockImplementation(() => {}),
    );
    try {
      const { host, map } = await issuingHost();
      await host.command('delegations.create', {
        agent_label: 'Helper',
        expires_at: new Date(Date.now() + 1800000).toISOString(),
      });
      // A blocked clipboard or a second client: each request the person makes gets the token.
      expect(host.connectionSecret()).toEqual({ sessionId: 's', token: 'agent-secret' });
      expect(host.connectionSecret()).toEqual({ sessionId: 's', token: 'agent-secret' });
      expect(host.connectionConfig('http://127.0.0.1:1/api')).toEqual(config);
      expect(host.connectionConfig('http://127.0.0.1:1/api')).toEqual(config);
      host.dismissConnection();
      expect(host.connectionSecret()).toBeNull();
      // Expiry clears it on its own, and emits so the card goes away.
      await host.command('delegations.create', {
        agent_label: 'Second',
        expires_at: new Date(Date.now() + 60000).toISOString(),
      });
      expect(host.connectionSecret()?.token).toBe('agent-secret');
      const expiredStates: ReturnType<typeof host.issuedDelegation>[] = [];
      const unsubscribe = host.subscribe(() => expiredStates.push(host.issuedDelegation()));
      vi.advanceTimersByTime(60001);
      unsubscribe();
      expect(expiredStates).toEqual([null]);
      expect(host.connectionSecret()).toBeNull();
      // Revoking the grant clears it as well.
      await host.command('delegations.create', {
        agent_label: 'Third',
        expires_at: new Date(Date.now() + 1800000).toISOString(),
      });
      expect(host.connectionSecret()?.token).toBe('agent-secret');
      await host.command('delegations.revoke', { delegation_id: 'd1' });
      expect(host.connectionSecret()).toBeNull();
      expect([...map.values()].join('')).not.toContain('agent-secret');
      for (const spy of logged)
        expect(JSON.stringify(spy.mock.calls)).not.toContain('agent-secret');
    } finally {
      for (const spy of logged) spy.mockRestore();
      vi.useRealTimers();
    }
  });
  it('recovers a lost grant after a new page host, persists confirmation, and permits the next business write', async () => {
    const { host, ports, fetcher, map } = setup();
    const context = {
      as_of: point,
      state,
      session: host.snapshot().session,
      available: { 'delegations.create': true, 'delegations.revoke': true },
      semantic: { roles: 'waiting_model', feedback: 'waiting_model', assistant: 'waiting_model' },
    };
    const grantCommands: unknown[] = [];
    const grants = new Map<string, string>();
    let drop = true;
    fetcher.mockImplementation(async (url, init) => {
      if (!init?.body)
        return String(url).endsWith('/workbench')
          ? reply({ schema_version: 2, result: { result: context } })
          : reply({ schema_version: 2, state });
      const sent = JSON.parse(String(init.body));
      if (sent.operation !== 'delegations.create') return reply(response(sent));
      grantCommands.push(sent);
      if (!grants.has(sent.request_id)) grants.set(sent.request_id, 'd1');
      if (drop) {
        drop = false;
        throw Error('connection lost after commit');
      }
      return reply({
        schema_version: 2,
        result: {
          schema_version: 2,
          result: { delegation: { id: grants.get(sent.request_id) }, token: 'agent-secret' },
        },
      });
    });
    await host.query('workbench.read');
    const lost = await host.command('delegations.create', {
      agent_label: 'Helper',
      expires_at: new Date(Date.now() + 1800000).toISOString(),
    });
    expect(lost.status).toBe('unconfirmed');
    expect([...map.values()].join('')).toContain(lost.requestId);
    await expect(
      host.command('work_items.create', { title: 'Blocked until recovered' }),
    ).rejects.toMatchObject({ code: 'request_unconfirmed' });
    const restored = new V4DataHost(ports);
    await restored.query('workbench.read');
    expect(restored.pendingRequests({ readOnly: true })).toEqual([]);
    expect(restored.pendingRequests()).toEqual([lost]);
    expect(grantCommands).toHaveLength(1); // Remount/read and passive polling must not replay issuance.
    const recovered = await restored.recover(lost.requestId);
    expect(recovered.status).toBe('confirmed');
    expect(grantCommands).toHaveLength(2);
    expect(grantCommands[1]).toEqual(grantCommands[0]);
    expect(grants.size).toBe(1);
    expect(restored.pendingRequests()).toEqual([]);
    const journal = JSON.parse(map.get('rolecraft.v4.session.s')!);
    expect(journal.requests[lost.requestId].outcome.status).toBe('confirmed');
    expect(new V4DataHost(ports).pendingRequests()).toEqual([]);
    expect(
      await restored.command('work_items.create', { title: 'Continue working' }),
    ).toMatchObject({ status: 'confirmed', result: { saved: true } });
    expect([...map.values()].join('')).not.toContain('agent-secret');
    expect(
      JSON.stringify([
        recovered,
        restored.snapshot(),
        restored.issuedDelegation(),
        vi.mocked(ports.announce).mock.calls,
      ]),
    ).not.toContain('agent-secret');
    expect(restored.issuedDelegation()).toMatchObject({ delegationId: 'd1' });
  });
  it('reports an agent grant that could not be sent as not sent, without a journal entry', async () => {
    const { host, fetcher, map } = setup();
    const context = {
      as_of: point,
      state,
      session: host.snapshot().session,
      available: { 'delegations.create': true },
      semantic: { roles: 'model', feedback: 'model', assistant: 'model' },
    };
    fetcher.mockImplementation(async (url) =>
      String(url).endsWith('/workbench')
        ? reply({ schema_version: 2, result: { result: context } })
        : reply({ detail: 'down' }, 502),
    );
    await host.query('workbench.read');
    const result = await host.command('delegations.create', {
      agent_label: 'Helper',
      expires_at: new Date(Date.now() + 1800000).toISOString(),
    });
    expect(result).toMatchObject({
      status: 'failed',
      result: { code: 'not_sent', definitive: true },
    });
    expect(posts(fetcher)).toHaveLength(0);
    expect([...map.values()].join('')).not.toContain(result.requestId);
  });
  it('previews an import through the existing read-only handler without a write journal', async () => {
    const { host, fetcher, map } = setup();
    fetcher.mockImplementation(async (_url, init) => {
      if (!init?.body) return reply({ schema_version: 2, state });
      const sent = JSON.parse(String(init.body));
      expect(sent.operation).toBe('workspace_imports');
      expect(sent.payload.mode).toBe('preview');
      return reply({
        schema_version: 2,
        result: { package_id: 'p', mode: 'preview', applied: false, as_of: point },
      });
    });
    expect(
      await host.query('workspace_imports', {
        package_id: 'p',
        mode: 'preview',
        source_schema: 'practice.v4',
        source_session_id: 'legacy',
        package_hash: '0'.repeat(64),
        items: [],
      }),
    ).toMatchObject({ applied: false });
    expect(map.size).toBe(0);
    await expect(
      // @ts-expect-error Deliberate invalid input still exercises the real runtime read guard.
      host.query('workspace_imports', { package_id: 'p', mode: 'apply' }),
    ).rejects.toMatchObject({ code: 'invalid_read' });
    expect(posts(fetcher)).toHaveLength(1);
  });
  describe('submission rule check', () => {
    const work = { session_id: 's', kind: 'product', object_id: 'p', version: 2 };
    const input = { decision: 'launch' as const, products: [work] };
    const checked = (basis: 'draft' | 'saved') => ({
      schema_version: 2,
      basis,
      mode: 'rules_only',
      session_id: 's',
      as_of: point,
      decision: 'launch',
      products: [work],
      evaluation: { path: 'runtime/evaluation.json', sha256: '0'.repeat(64) },
      work_language: 'en',
      rule_items: [],
      ...(basis === 'saved'
        ? { submission: { session_id: 's', kind: 'submission', object_id: 'sub', version: 1 } }
        : {}),
    });
    it('checks the command the submit control would send, read-only and unjournaled', async () => {
      const { host, fetcher, map } = setup();
      fetcher.mockImplementation(async (url, init) => {
        if (!init?.body) return reply({ schema_version: 2, state });
        expect(String(url)).toBe('/api/sessions/s/submission-rule-check');
        expect(JSON.parse(String(init.body))).toMatchObject({
          schema_version: 2,
          operation: 'submissions.rule_check',
          expected_version: point.business_seq,
          expected_workspace_revision: point.workspace_revision,
          payload: input,
        });
        return reply({ schema_version: 2, result: checked('draft') });
      });
      expect(await host.query('submissions.rule_check', input)).toEqual(checked('draft'));
      expect(posts(fetcher)).toHaveLength(1);
      expect(map.size).toBe(0);
    });
    it('asks for the sentence step of the same command on its own route', async () => {
      const { host, fetcher, map } = setup();
      const sentences = { session_id: 's', enabled: true, recognition: { units: [] } };
      fetcher.mockImplementation(async (url, init) => {
        if (!init?.body) return reply({ schema_version: 2, state });
        expect(String(url)).toBe('/api/sessions/s/submission-rule-check/recognition');
        expect(JSON.parse(String(init.body))).toMatchObject({
          operation: 'submissions.rule_check',
          expected_version: point.business_seq,
          payload: input,
        });
        return reply({ schema_version: 2, result: sentences });
      });
      expect(await host.query('submissions.rule_check.recognition', input)).toEqual(sentences);
      expect(map.size).toBe(0);
      fetcher.mockImplementation(async (_url, init) =>
        init?.body
          ? reply({ schema_version: 2, result: { ...sentences, session_id: 'other' } })
          : reply({ schema_version: 2, state }),
      );
      await expect(host.query('submissions.rule_check.recognition', input)).rejects.toMatchObject({
        code: 'response_unconfirmed',
      });
    });
    it('reads a saved submission again by GET', async () => {
      const { host, fetcher } = setup();
      fetcher.mockImplementation(async () =>
        reply({ schema_version: 2, result: checked('saved') }),
      );
      expect(await host.query('submissions.rule_check.read', { submission_id: 'sub' })).toEqual(
        checked('saved'),
      );
      expect(fetcher).toHaveBeenCalledWith(
        '/api/sessions/s/submission-rule-check?submission_id=sub',
        expect.objectContaining({ method: 'GET' }),
      );
      expect(posts(fetcher)).toHaveLength(0);
    });
    it('refuses an answer for another session or basis', async () => {
      const { host, fetcher } = setup();
      fetcher.mockImplementation(async (_url, init) =>
        init?.body
          ? reply({ schema_version: 2, result: { ...checked('draft'), session_id: 'other' } })
          : reply({ schema_version: 2, state }),
      );
      await expect(host.query('submissions.rule_check', input)).rejects.toMatchObject({
        code: 'response_unconfirmed',
      });
      fetcher.mockImplementation(async () =>
        reply({ schema_version: 2, result: checked('draft') }),
      );
      await expect(
        host.query('submissions.rule_check.read', { submission_id: 'sub' }),
      ).rejects.toMatchObject({ code: 'response_unconfirmed' });
    });
    it('is offered exactly where submitting is, and never in a read-only practice', async () => {
      const { host, fetcher } = setup();
      const context = {
        as_of: point,
        state,
        session: host.snapshot().session,
        available: { 'submissions.create': true },
        semantic: { roles: 'model', feedback: 'model', assistant: 'model' },
        read_only: false,
      };
      fetcher.mockResolvedValue(reply({ schema_version: 2, result: { result: context } }));
      await host.query('workbench.read');
      expect(host.snapshot().available['submissions.rule_check']).toBe(true);
      fetcher.mockResolvedValue(
        reply({ schema_version: 2, result: { result: { ...context, read_only: true } } }),
      );
      await host.query('workbench.read');
      expect(host.snapshot().available['submissions.rule_check']).toBe(false);
    });
  });
  it('retains unsaved text in memory after a quota failure and flushes it when storage recovers', async () => {
    const { host, storage, ports } = setup();
    await host.keepDraft('workspace', 'work', 'old');
    storage.setItem.mockImplementationOnce(() => {
      throw Error('quota');
    });
    await expect(host.keepDraft('workspace', 'work', 'new unsaved text')).rejects.toMatchObject({
      code: 'storage_unavailable',
    });
    expect(host.draft('workspace', 'work')).toBe('new unsaved text');
    await host.flushDrafts();
    expect(new V4DataHost(ports).draft('workspace', 'work')).toBe('new unsaved text');
  });
  it('rejects a corrupt journal without replacing it, and blocks cross-session references and envelopes', async () => {
    const { ports, map, fetcher } = setup();
    map.set('rolecraft.v4.session.s', '{broken');
    const host = new V4DataHost(ports);
    await expect(host.command('work_items.create', { title: 'x' })).rejects.toMatchObject({
      code: 'storage_unavailable',
    });
    expect(map.get('rolecraft.v4.session.s')).toBe('{broken');
    expect(fetcher).not.toHaveBeenCalled();
    expect(() =>
      host.openReference({ session_id: 'other', kind: 'product', object_id: 'p', version: 1 }),
    ).toThrow();
  });
  it('keeps model status independent and requires the exact fixed session binding', async () => {
    const { host, fetcher } = setup();
    const context = {
      as_of: point,
      state,
      session: host.snapshot().session,
      available: { 'turns.create': true },
      semantic: { roles: 'model', feedback: 'waiting_model', assistant: 'waiting_model' },
    };
    fetcher.mockResolvedValue(reply({ schema_version: 2, result: { result: context } }));
    await host.query('workbench.read');
    expect(host.snapshot().semantic).toEqual(context.semantic);
    fetcher.mockResolvedValue(
      reply({
        schema_version: 2,
        result: { result: { ...context, session: { ...context.session, workLanguage: 'zh' } } },
      }),
    );
    await expect(host.query('workbench.read')).rejects.toMatchObject({
      code: 'response_unconfirmed',
    });
    expect(host.snapshot().session?.workLanguage).toBe('en');
  });
});
