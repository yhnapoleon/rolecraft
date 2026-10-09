import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { VerticalClient } from './vertical-client';

function memory(): Storage {
  const values = new Map<string, string>();
  return {
    getItem: (k) => values.get(k) ?? null,
    setItem: (k, v) => {
      values.set(k, v);
    },
    removeItem: (k) => {
      values.delete(k);
    },
    clear: () => values.clear(),
    key: (i) => [...values.keys()][i] ?? null,
    get length() {
      return values.size;
    },
  };
}
const state = {
  schema_version: 2,
  state: {
    business_seq: 0,
    workspace_revision: 0,
    storage_revision: 0,
    config_version: 0,
    session_id: 's',
    status: 'active',
  },
};
const json = (value: any, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
beforeEach(() => {
  vi.stubGlobal('navigator', {
    locks: { request: (_key: string, opts: any, body?: any) => (body ?? opts)() },
  });
});
afterEach(() => vi.unstubAllGlobals());

describe('Native v2 request recovery', () => {
  it('retains a committed result when the follow-up view refresh fails', async () => {
    let writes = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_path: string, init: any) => {
        if (init.method === 'POST') {
          writes++;
          return json({
            schema_version: 2,
            boundary: { request_id: 'saved' },
            result: {},
            state: state.state,
          });
        }
        if (writes) return json({ code: 'view_unavailable', error: 'refresh unavailable' }, 503);
        return json(state);
      }),
    );
    const storage = memory();
    const client = new VerticalClient(
      { sessionId: 's', token: 'private-test-token', createdAt: 'now', workLanguage: 'zh' },
      storage,
    );
    const result = await client.command('/actions', 'read_material', {}, 'saved');
    expect(result.boundary.request_id).toBe('saved');
    expect(JSON.parse(storage.getItem(client.requestKey('saved'))!).status).toBe('completed');
    expect(writes).toBe(1);
    expect(storage.getItem(client.requestKey('saved'))).not.toContain('private-test-token');
  });

  it('keeps an uncertain command and recovers without issuing a second write', async () => {
    let writes = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string, init: any) => {
        if (init.method === 'POST') {
          writes++;
          throw Error('connection closed');
        }
        if (path.includes('/requests/'))
          return json({ schema_version: 2, status: 'pending', request_id: 'original', jobs: [] });
        return json(state);
      }),
    );
    const storage = memory();
    const client = new VerticalClient(
      { sessionId: 's', token: 't', createdAt: 'now', workLanguage: 'zh' },
      storage,
    );
    await expect(
      client.command('/turns', 'turns.create', { text: '保留原问题' }, 'original'),
    ).rejects.toThrow();
    const saved = JSON.parse(storage.getItem(client.requestKey('original'))!);
    expect(saved.status).toBe('pending');
    expect(saved.command.payload.text).toBe('保留原问题');
    expect(
      (await client.command('/turns', 'turns.create', { text: 'different' }, 'original')).status,
    ).toBe('pending');
    expect(writes).toBe(1);
  });

  it('does not write to the server if it cannot preserve the request locally', async () => {
    const fetcher = vi.fn(async () => json(state));
    vi.stubGlobal('fetch', fetcher);
    const storage = memory();
    storage.setItem = () => {
      throw Error('quota');
    };
    const client = new VerticalClient(
      { sessionId: 's', token: 't', createdAt: 'now', workLanguage: 'zh' },
      storage,
    );
    await expect(
      client.command('/submissions', 'submissions.create', {}, 'submit'),
    ).rejects.toThrow('quota');
    expect(fetcher.mock.calls.length).toBe(1);
  });
});
