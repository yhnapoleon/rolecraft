import { describe, it, expect } from 'vitest';
import { workspaceGatewayTransport } from './gateway-adapter';
import { WorkspaceClient } from './client';
import { MemoryCoordinator } from './test-support';
const at = { business_seq: 0, workspace_revision: 1, storage_revision: 1 };
const page = { items: [], as_of: at, next_cursor: null };
const command = {
  schema_version: 2,
  request_id: 'request',
  expected_version: 0,
  expected_workspace_revision: 0,
  operation: 'work_products.versions.create',
  payload: {},
};
const removed = {
  product: { session_id: 's', kind: 'product', object_id: 'p', version: 2 },
  all_active_shares_revoked: true,
  visible_revocations: [],
  sharing_complete: false,
};
const wire = {
  schema_version: 2,
  transaction_id: 'tx',
  boundary: { request_id: 'request', transaction_id: 'tx' },
  state: { ...at, session_id: 's' },
  objects: [],
  events: [],
  replayed: false,
  result: { as_of: at, removals: [removed] },
};

describe('fixed c7 Gateway envelope adapter', () => {
  it('unwraps the registered read shape and preserves exact preview and removal results', async () => {
    const read = workspaceGatewayTransport(async () => ({
      schema_version: 2,
      result: { schema_version: 2, result: page },
    }));
    expect(await read('/sessions/s/work-products')).toEqual(page);
    const write = workspaceGatewayTransport(async () => wire);
    expect(await write('/sessions/s/work-products/p/versions', command, 'POST')).toEqual(
      wire.result,
    );
    const preview = {
      schema_version: 2,
      mode: 'preview',
      package_id: 'pkg',
      as_of: at,
      applied: false,
    };
    const query = workspaceGatewayTransport(async () => ({ schema_version: 2, result: preview }));
    expect(
      await query(
        '/sessions/s/workspace-imports',
        {
          ...command,
          operation: 'workspace_imports',
          payload: { mode: 'preview', package_id: 'pkg' },
        },
        'POST',
      ),
    ).toEqual(preview);
  });
  it('does not accept an unrelated request acknowledgement or guess a read shape', async () => {
    const wrong = workspaceGatewayTransport(async () => ({
      ...wire,
      boundary: { ...wire.boundary, request_id: 'another' },
    }));
    await expect(
      wrong('/sessions/s/work-products/p/versions', command, 'POST'),
    ).rejects.toMatchObject({ status: 0, code: 'response_unconfirmed' });
    const direct = workspaceGatewayTransport(async () => ({ schema_version: 2, result: page }));
    await expect(direct('/sessions/s/work-products')).rejects.toMatchObject({
      code: 'response_unconfirmed',
    });
  });
});

it('merges overlapping pages once and preserves unknown sharing on scoped reads', async () => {
  const product: any = {
    schema_version: 2,
    product_id: 'p',
    session_id: 's',
    version: 2,
    kind: 'text',
    purpose: 'exploration',
    title: 'p',
    content: 'new private version',
    visibility: null,
    content_hash: '0'.repeat(64),
    cycle: { session_id: 's', kind: 'cycle', object_id: 'c', version: 1 },
    author: { id: 'h', kind: 'human' },
    executor: { id: 'h', kind: 'human' },
    created_at: '2026-10-07T00:00:00Z',
  };
  const share: any = {
    schema_version: 2,
    id: 'share',
    session_id: 's',
    version: 1,
    product: { session_id: 's', kind: 'product', object_id: 'p', version: 1 },
    recipient_role: 'tech_lead',
    shared_at: at,
    revoked_at: null,
  };
  const transport = async (path: string) =>
    path.includes('work-items')
      ? page
      : {
          items: [product],
          shares: [share],
          sharing_complete: false,
          as_of: at,
          next_cursor: path.includes('cursor=0') ? 1 : null,
        };
  const data = new Map<string, string>();
  const storage = {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => {
      data.set(k, v);
    },
  };
  const client = new WorkspaceClient('s', storage, transport, () => crypto.randomUUID(), {
    coordinator: new MemoryCoordinator(),
  });
  await client.refresh();
  expect(client.snapshot().products).toHaveLength(1);
  expect(client.snapshot().shares.p).toEqual([share]);
  expect(client.snapshot().sharingComplete).toBe(false);
  expect(client.snapshot().products[0].visibility).toBeNull();
});

it('reads exact saved history without replacing the current head or local draft', async () => {
  const head: any = {
    session_id: 's',
    product_id: 'p',
    version: 2,
    title: 'current',
    content: 'private v2',
    visibility: 'private',
  };
  const old: any = {
    ...head,
    version: 1,
    title: 'old',
    content: 'shared v1',
    visibility: 'shared',
  };
  const data = new Map<string, string>();
  const storage = {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => {
      data.set(k, v);
    },
  };
  const client = new WorkspaceClient(
    's',
    storage,
    async (path) =>
      path.includes('/versions')
        ? { ...page, items: [old, head] }
        : path.includes('work-items')
          ? page
          : { ...page, items: [head] },
    undefined,
    { coordinator: new MemoryCoordinator() },
  );
  await client.refresh();
  await client.keepDraft('p', { title: 'unsent', content: 'keep my local text', kind: 'text' });
  expect((await client.loadVersions('p')).map((p) => [p.version, p.content, p.visibility])).toEqual(
    [
      [2, 'private v2', 'private'],
      [1, 'shared v1', 'shared'],
    ],
  );
  expect(client.snapshot().products[0]).toEqual(head);
  expect(client.snapshot().journal.drafts.p.content).toBe('keep my local text');
});

it('rejects an unrelated object in a history response', async () => {
  const data = new Map<string, string>();
  const storage = {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => {
      data.set(k, v);
    },
  };
  const client = new WorkspaceClient(
    's',
    storage,
    async () => ({ ...page, items: [{ session_id: 's', product_id: 'other', version: 1 }] }),
    undefined,
    { coordinator: new MemoryCoordinator() },
  );
  await expect(client.loadVersions('p')).rejects.toThrow('Invalid product history');
  expect(client.snapshot().products).toEqual([]);
});
