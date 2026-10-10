import { expect, it, vi } from 'vitest';
import { V4DataHost, type V4HostPorts } from '../../../v4-data-host';
import type { WorkspaceProductRead } from '../../../contracts-v2';
import { keepProductDraft, readProduct, WorkspaceSlotController } from './slot-controller';
import { workspaceActionMessage } from './messages';

const product: WorkspaceProductRead = {
  session_id: 's',
  product_id: 'work',
  version: 3,
  kind: 'text',
  title: 'Saved title',
  content: 'Saved body',
  purpose: 'exploration',
  content_hash: 'fixed',
  cycle: { session_id: 's', kind: 'cycle', object_id: 'c', version: 1 },
  author: { kind: 'human', id: 'owner' },
  executor: { kind: 'human', id: 'owner' },
  created_at: '2026-10-09T00:00:00Z',
};
async function fixture(editable = true) {
  const memory = new Map<string, string>();
  const fetcher = vi.fn<typeof fetch>(
    async () =>
      new Response(
        JSON.stringify({
          schema_version: 2,
          result: {
            result: {
              session: { protocol: 2, sessionId: 's', workLanguage: 'en', scenarioHash: 'fixed' },
              state: { status: 'active' },
              as_of: { business_seq: 0, workspace_revision: 3, storage_revision: 3 },
              available: { 'work_products.versions.create': editable },
              semantic: { roles: 'unavailable', feedback: 'unavailable', assistant: 'unavailable' },
            },
          },
        }),
      ),
  );

  let queue = Promise.resolve();
  const ports: V4HostPorts = {
    binding: { protocol: 2, sessionId: 's', workLanguage: 'en', scenarioHash: 'fixed' },
    credentials: () => ({ sessionId: 's', token: 'private-credential' }),
    storage: {
      getItem: (key) => memory.get(key) ?? null,
      setItem: (key, value) => {
        memory.set(key, value);
      },
    },
    uiLanguage: () => 'en',
    announce: () => {},
    openReference: async () => {},
    chooseEvidence: async () => [],
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
  const host = new V4DataHost(ports);
  await host.query('workbench.read');
  fetcher.mockClear();
  return { ports, memory, fetcher, host };
}
it('restores pre-mount edits through the same product draft after a new host is created', async () => {
  const f = await fixture();
  const first = keepProductDraft(f.host, product, { content: 'New body' });
  const second = keepProductDraft(f.host, product, { title: 'New title' });
  await Promise.all([first, second]);
  const restored = new WorkspaceSlotController(new V4DataHost(f.ports));
  expect(restored.draft(product)).toMatchObject({
    sessionId: 's',
    productId: 'work',
    baseVersion: 3,
    value: { title: 'New title', content: 'New body' },
    status: 'dirty',
  });
  expect(restored.draft({ ...product, product_id: 'other' })).toBeUndefined();
  expect([...f.memory.values()].join('')).not.toContain('private-credential');
  expect(f.fetcher).not.toHaveBeenCalled();
});
it('keeps deliberate clearing and the original version without crossing session or product identities', async () => {
  const f = await fixture();
  await keepProductDraft(f.host, product, { content: 'Before clearing' });
  await keepProductDraft(f.host, { ...product, version: 4 }, { content: '' });
  const restored = new WorkspaceSlotController(new V4DataHost(f.ports));
  expect(restored.draft(product)).toMatchObject({ baseVersion: 3, value: { content: '' } });
  const other = new V4DataHost({
    ...f.ports,
    binding: { ...f.ports.binding, sessionId: 'other' },
    credentials: () => ({ sessionId: 'other', token: 'another-private-credential' }),
  });
  expect(new WorkspaceSlotController(other).draft(product)).toBeUndefined();
  const before = [...f.memory.entries()];
  await expect(keepProductDraft(other, product, { content: 'wrong session' })).rejects.toThrow(
    'session_changed',
  );
  await expect(
    keepProductDraft(f.host, { ...product, removed_at: 'removed' }, { content: 'restore' }),
  ).rejects.toThrow('editing_unavailable');
  expect([...f.memory.entries()]).toEqual(before);
  expect(f.fetcher).not.toHaveBeenCalled();
});

it('uses the same editing permission before and after mounting', async () => {
  const f = await fixture(false);
  await expect(keepProductDraft(f.host, product, { content: 'Blocked' })).rejects.toThrow(
    'editing_unavailable',
  );
  expect(new WorkspaceSlotController(f.host).draft(product)).toBeUndefined();
  expect(f.fetcher).not.toHaveBeenCalled();
});

it.each(['zh', 'en'] as const)(
  'localizes a pre-mount storage failure and retains the current text (%s)',
  async (language) => {
    const f = await fixture();
    f.ports.storage.setItem = () => {
      throw Error('Browser storage is unavailable: internal detail');
    };
    const editing = keepProductDraft(f.host, product, { content: 'Retain this input' });
    await expect(editing).rejects.toThrow('draft_storage_failed');
    const message = await editing.catch((error: Error) =>
      workspaceActionMessage(error.message, (zh, en) => (language === 'zh' ? zh : en)),
    );
    expect(message).toBe(
      language === 'zh'
        ? '本机保存失败，请保留本页文字。'
        : 'Local saving failed. Keep your text on this page.',
    );
    expect(new WorkspaceSlotController(f.host).draft(product)?.value.content).toBe(
      'Retain this input',
    );
    expect(f.fetcher).not.toHaveBeenCalled();
  },
);

it.each([
  [{ title: 9 }, 'invalid_product'],
  [{ content: null }, 'invalid_product'],
  [{ version: 0 }, 'invalid_product'],
  [{ session_id: 'foreign' }, 'invalid_workspace_identity'],
] as const)(
  'rejects an invalid projected product before using it as a draft source: %j',
  (patch, code) => {
    expect(() => readProduct({ ...product, ...patch }, 's')).toThrow(code);
  },
);
