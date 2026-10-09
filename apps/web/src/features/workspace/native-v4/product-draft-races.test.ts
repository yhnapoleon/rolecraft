import { expect, it, vi } from 'vitest';
import { V4DataHost, type V4HostPorts } from '../../../v4-data-host';
import { surfaceHost } from '../../../v4-surface-host';
import type { ProductEdit, WorkspaceProductRead } from '../../../contracts-v2';
import { keepProductDraft, productRef, WorkspaceSlotController } from './slot-controller';

const saved: WorkspaceProductRead = {
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
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
async function fixture() {
  const memory = new Map<string, string>();
  let head = structuredClone(saved);
  const point = () => ({
    business_seq: 0,
    workspace_revision: head.version,
    storage_revision: head.version,
  });
  const state = () => ({ ...point(), session_id: 's', status: 'active' });
  const binding = {
    protocol: 2 as const,
    sessionId: 's',
    workLanguage: 'en' as const,
    scenarioHash: 'fixed',
  };
  const saveStarted = deferred<void>();
  let saveGate: Promise<void> | undefined;
  const response = (value: Record<string, unknown>) =>
    new Response(JSON.stringify({ schema_version: 2, ...value }));
  const envelope = (value: unknown) => response({ result: { schema_version: 2, result: value } });
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const url = String(input);
    if (init?.body) {
      const command: { request_id: string; payload: ProductEdit } = JSON.parse(String(init.body));
      saveStarted.resolve();
      await saveGate;
      head = { ...head, ...command.payload, version: head.version + 1 };
      return response({
        boundary: { request_id: command.request_id },
        state: state(),
        result: { object: head, as_of: point() },
      });
    }
    if (url.includes('/workbench'))
      return envelope({
        session: binding,
        state: state(),
        as_of: point(),
        available: {
          'work_products.versions.create': true,
          'work_products.list': true,
          'work_items.list': true,
        },
        semantic: { roles: 'unavailable', feedback: 'unavailable', assistant: 'unavailable' },
      });
    if (url.includes('/work-products'))
      return envelope({
        items: [head],
        as_of: point(),
        next_cursor: null,
        shares: [],
        sharing_complete: true,
      });
    if (url.includes('/work-items'))
      return envelope({ items: [], as_of: point(), next_cursor: null });
    return response({ state: state() });
  });
  let queue = Promise.resolve();
  const exclusive = <T>(_name: string, action: () => Promise<T>): Promise<T> => {
    const result = queue.then(action);
    queue = result.then(
      () => {},
      () => {},
    );
    return result;
  };
  const ports: V4HostPorts = {
    binding,
    fetcher,
    exclusive,
    credentials: () => ({ sessionId: 's', token: 'private-test-credential' }),
    storage: {
      getItem: (key) => memory.get(key) ?? null,
      setItem: (key, value) => {
        memory.set(key, value);
      },
    },
    uiLanguage: () => 'en',
    announce() {},
    openReference: async () => {},
    chooseEvidence: async () => [],
  };
  const host = new V4DataHost(ports);
  await host.query('workbench.read');
  host.selectProduct(productRef(saved));
  await host.flushDrafts();
  // Real mounted slots receive a surface facade, while pre-mount input uses the canonical host.
  const controller = new WorkspaceSlotController(surfaceHost(host, () => true));
  await controller.refresh();
  fetcher.mockClear();
  return {
    host,
    controller,
    ports,
    fetcher,
    saveStarted,
    delaySave: (gate: Promise<void>) => {
      saveGate = gate;
    },
    async holdLock() {
      const entered = deferred<void>();
      const release = deferred<void>();
      const held = exclusive('test-lock', async () => {
        entered.resolve();
        await release.promise;
      });
      await entered.promise;
      return { release: () => release.resolve(), held };
    },
  };
}

it.each(['text', 'test_plan', 'investigation'] as const)(
  'preserves existing %s draft when pre-mount input appends to the rendered value',
  async (kind) => {
    const f = await fixture();
    const product = { ...saved, kind };
    await keepProductDraft(f.host, product, {
      title: 'Unsaved title',
      content: 'Long unsaved paragraph',
    });
    const view = f.controller.value(product);
    await keepProductDraft(f.host, product, {
      title: `${view.title}x`,
      content: `${view.content}x`,
    });
    const restored = new WorkspaceSlotController(new V4DataHost(f.ports));
    expect(restored.draft(product)).toMatchObject({
      status: 'dirty',
      baseVersion: 3,
      value: { title: 'Unsaved titlex', content: 'Long unsaved paragraphx' },
    });
    expect(f.fetcher).not.toHaveBeenCalled();
  },
);

it('does not let a destroyed slot acknowledgement clear newer pre-mount input', async () => {
  const f = await fixture();
  await f.controller.edit({ content: 'Sent paragraph' });
  const gate = deferred<void>();
  f.delaySave(gate.promise);
  const saving = f.controller.save();
  await f.saveStarted.promise;
  f.controller.destroy();
  const latest = keepProductDraft(f.host, saved, { content: 'New paragraph after remount' });
  const token = new WorkspaceSlotController(f.host).draft(saved)?.token;
  gate.resolve();
  await Promise.all([saving, latest]);
  const restored = new WorkspaceSlotController(new V4DataHost(f.ports));
  expect(restored.draft(saved)).toMatchObject({
    token,
    status: 'dirty',
    baseVersion: 3,
    value: { content: 'New paragraph after remount' },
  });
});

it('does not let an old queued slot write overwrite newer pre-mount input after the host lock releases', async () => {
  const f = await fixture();
  await f.controller.edit({ content: 'Original unsaved paragraph' });
  const lock = await f.holdLock();
  const older = f.controller.edit({ content: 'Earlier queued paragraph' });
  f.controller.destroy();
  const newer = keepProductDraft(f.host, saved, {
    title: 'Newest title',
    content: 'Newest paragraph',
  });
  lock.release();
  await Promise.all([lock.held, older, newer]);
  const restored = new WorkspaceSlotController(new V4DataHost(f.ports));
  expect(restored.draft(saved)).toMatchObject({
    status: 'dirty',
    baseVersion: 3,
    value: { title: 'Newest title', content: 'Newest paragraph' },
  });
  expect(f.fetcher).not.toHaveBeenCalled();
});
