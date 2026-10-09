import { describe, expect, it, vi } from 'vitest';
import { V4Mounts } from './v4-mounts';
import { WorkspaceRegions } from './features/workspace/native-v4/regions';
import { regionHost } from './v4-region-test-support';
import type { V4DataHost } from './v4-data-host';
import type { V4HostAdapter, V4SlotContext } from './v4-host';
import type { LocalSession } from './types';

function fixture() {
  const dialog = { open: true };
  const lane = {} as HTMLElement;
  const root = {
    isConnected: true,
    closest: () => dialog,
    querySelector: (selector: string) => (selector === '.col-first .cards' ? lane : null),
  } as unknown as HTMLElement;
  const roots = new Map<string, HTMLElement[]>([['workspace', [root]]]);
  const doc = {
    querySelector: () => null,
    querySelectorAll: (selector: string) => {
      const name = selector.match(/data-v4-region="([^"]+)"/)?.[1];
      return roots.get(name ?? '') ?? [];
    },
  } as unknown as Document;
  Object.defineProperty(root, 'ownerDocument', { value: doc });
  const data = Object.assign(regionHost(), { reflectSelection: vi.fn(async () => {}) });
  const surfaces: V4HostAdapter[] = [];
  const destroy = vi.fn();
  const workspace = new WorkspaceRegions((context: V4SlotContext) => {
    surfaces.push(context.host);
    return { update() {}, destroy };
  });
  const mounts = new V4Mounts(workspace);
  const session = {
    id: 's',
    protocol: 2,
    v2NativeWorkspace: true,
    v2Workspace: { tasks: [], products: [] },
  } as unknown as LocalSession;
  const sync = () =>
    mounts.sync(doc, session, data as unknown as V4DataHost, { taskId: null, productId: null });
  return { dialog, roots, data, surfaces, destroy, sync };
}

describe('workspace lifetime across host persistence', () => {
  it.each(['route replaced', 'dialog closed'])(
    'releases the departed surface before a blocked host operation: %s',
    async (change) => {
      const f = fixture();
      await f.sync();
      const surface = f.surfaces[0];
      if (change === 'route replaced') f.roots.clear();
      else f.dialog.open = false;
      let release = () => {};
      f.data.reflectSelection.mockImplementation(
        () =>
          new Promise<void>((resolve) => {
            release = resolve;
          }),
      );
      const pending = f.sync();
      try {
        surface.selectProduct({ session_id: 's', kind: 'product', object_id: 'p', version: 1 });
        surface.announce('A late completion');
        await surface.recover('original-request');
        expect(f.data.selectProduct).not.toHaveBeenCalled();
        expect(f.data.announce).not.toHaveBeenCalled();
        expect(f.destroy).toHaveBeenCalledOnce();
        expect(f.data.recover).toHaveBeenCalledWith('original-request');
      } finally {
        release();
        await pending;
      }
    },
  );

  it('does not retain a departed surface when selection persistence rejects', async () => {
    const f = fixture();
    await f.sync();
    f.roots.clear();
    f.data.reflectSelection.mockRejectedValue(new Error('Storage unavailable'));
    await expect(f.sync()).rejects.toThrow('Storage unavailable');
    f.surfaces[0].announce('A late completion');
    expect(f.data.announce).not.toHaveBeenCalled();
    expect(f.destroy).toHaveBeenCalledOnce();
  });
});
