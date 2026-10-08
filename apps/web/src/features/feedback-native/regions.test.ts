import { describe, expect, it, vi } from 'vitest';
import type { V4HostAdapter, V4HostSnapshot, V4SlotContext } from '../../v4-host';
import { FeedbackRegions } from './regions';

function host(): V4HostAdapter {
  const snapshot: V4HostSnapshot = {
    session: { protocol: 2, sessionId: 's', workLanguage: 'en', scenarioHash: 'fixed' },
    uiLanguage: 'en',
    state: 'active',
    asOf: null,
    currentTask: null,
    currentProduct: null,
    busy: false,
    storageError: false,
    available: {},
  };
  return {
    snapshot: () => snapshot,
    subscribe: () => () => {},
    query: vi.fn(async () => ({})),
    command: vi.fn(async () => ({
      requestId: 'original',
      status: 'confirmed' as const,
      result: {},
    })),
    recover: vi.fn(async () => ({
      requestId: 'original',
      status: 'confirmed' as const,
      result: {},
    })),
    retry: vi.fn(async () => ({ requestId: 'retry', status: 'pending' as const, result: {} })),
    draft: () => undefined,
    keepDraft: vi.fn(async () => {}),
    flushDrafts: vi.fn(async () => {}),
    openReference: vi.fn(async () => {}),
    chooseEvidence: vi.fn(async () => []),
    selectTask: vi.fn(),
    selectProduct: vi.fn(),
    announce: vi.fn(),
  };
}

function fixture() {
  const roots = new Map<string, HTMLElement[]>();
  const document = {
    querySelectorAll: (selector: string) => roots.get(selector) ?? [],
  } as unknown as Document;
  const root = {
    isConnected: true,
    dataset: {},
    closest: () => null,
    querySelector: () => null,
  } as unknown as HTMLElement;
  roots.set('[data-v4-region="feedback"]', [root]);
  const mounts: V4SlotContext[] = [];
  const handles: { update: ReturnType<typeof vi.fn>; destroy: ReturnType<typeof vi.fn> }[] = [];
  const regions = new FeedbackRegions((context) => {
    mounts.push(context);
    const handle = { update: vi.fn(), destroy: vi.fn() };
    handles.push(handle);
    return handle;
  });
  return { roots, document, root, mounts, handles, regions };
}

describe('named feedback ownership', () => {
  it('keeps one renderer when the host polls or the module replaces its own children', () => {
    const f = fixture();
    const data = host();
    f.regions.sync(f.document, data);
    Object.defineProperty(f.root, 'firstElementChild', { value: {} });
    f.regions.sync(f.document, data);
    expect(f.mounts).toHaveLength(1);
    expect(f.mounts[0].nodes).toEqual({ content: f.root });
    expect(f.mounts[0].surface).toBe('feedback');
    expect(f.handles[0].update).toHaveBeenCalledOnce();
    expect(f.handles[0].destroy).not.toHaveBeenCalled();
  });

  it('disposes old ownership on root replacement, disconnection and session-host change', () => {
    const f = fixture();
    const data = host();
    f.regions.sync(f.document, data);
    const replacement = { ...f.root } as HTMLElement;
    f.roots.set('[data-v4-region="feedback"]', [replacement]);
    f.regions.sync(f.document, data);
    expect(f.handles[0].destroy).toHaveBeenCalledOnce();
    f.regions.sync(f.document, host());
    expect(f.handles[1].destroy).toHaveBeenCalledOnce();
    f.roots.clear();
    f.regions.sync(f.document, data);
    expect(f.handles[2].destroy).toHaveBeenCalledOnce();
  });

  it('uses the original data and draft owner but ignores late navigation after disposal', async () => {
    const f = fixture();
    const data = host();
    f.regions.sync(f.document, data);
    const adapter = f.mounts[0].host;
    const reference = { session_id: 's', kind: 'product', object_id: 'p', version: 1 };
    await adapter.keepDraft('feedback', 'revision', { text: 'Keep my words' });
    expect(data.keepDraft).toHaveBeenCalledWith('feedback', 'revision', { text: 'Keep my words' });
    adapter.selectProduct(reference);
    expect(data.selectProduct).toHaveBeenCalledOnce();
    f.regions.destroy();
    adapter.selectProduct(reference);
    adapter.announce('late');
    expect(data.selectProduct).toHaveBeenCalledOnce();
    expect(data.announce).not.toHaveBeenCalled();
    await adapter.recover('original');
    expect(data.recover).toHaveBeenCalledWith('original');
    expect(data.command).not.toHaveBeenCalled();
  });

  it('releases a closed submission dialog without touching the feedback region', () => {
    const f = fixture();
    const data = host();
    const dialog = { open: false };
    const submission = { ...f.root, closest: () => dialog } as unknown as HTMLElement;
    f.roots.set('[data-v4-region="submission"]', [submission]);
    f.regions.sync(f.document, data);
    expect(f.mounts).toHaveLength(1);
    dialog.open = true;
    f.regions.sync(f.document, data);
    expect(f.mounts[1].surface).toBe('submission');
    dialog.open = false;
    f.regions.sync(f.document, data);
    expect(f.handles[1].destroy).toHaveBeenCalledOnce();
    expect(f.handles[0].destroy).not.toHaveBeenCalled();
  });

  it('never mounts v2 feedback for a legacy session and rejects duplicate region owners', () => {
    const f = fixture();
    const data = host();
    data.snapshot = () => ({
      ...host().snapshot(),
      session: { protocol: 1, sessionId: 'old', workLanguage: null },
    });
    f.regions.sync(f.document, data);
    expect(f.mounts).toEqual([]);
    f.roots.set('[data-v4-region="feedback"]', [f.root, f.root]);
    expect(() => f.regions.sync(f.document, host())).toThrow('Duplicate v4 region');
    expect(f.mounts).toEqual([]);
  });
});
