import { expect, it, vi } from 'vitest';
import { V4DataHost, type V4HostPorts } from '../../../v4-data-host';
import type { WorkspaceProductRead } from '../../../contracts-v2';
import { keepProductDraft, WorkspaceSlotController } from './slot-controller';

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
function fixture() {
  const memory = new Map<string, string>();
  const fetcher = vi.fn<typeof fetch>();
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
  return { ports, memory, fetcher, host: new V4DataHost(ports) };
}
it('restores pre-mount edits through the same product draft after a new host is created', async () => {
  const f = fixture();
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
  const f = fixture();
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
