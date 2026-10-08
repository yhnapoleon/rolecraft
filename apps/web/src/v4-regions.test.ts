import { describe, expect, it, vi } from 'vitest';
import type { V4HostAdapter } from './v4-host';
import { NamedRegions } from './v4-regions';
import { regionHost as host } from './v4-region-test-support';
import { WorkspaceRegions } from './features/workspace/native-v4/regions';

describe('named workspace ownership', () => {
  it('retains the renderer and draft owner while its own contents change', async () => {
    const root = {
      isConnected: true,
      closest: () => null,
      firstElementChild: {},
    } as unknown as HTMLElement;
    const document = {
      querySelectorAll: (selector: string) =>
        selector === '[data-v4-region="workspace"]' ? [root] : [],
    } as unknown as Document;
    const data = host();
    const update = vi.fn();
    const destroy = vi.fn();
    let owner: V4HostAdapter | undefined;
    const render = vi.fn((_name: string, _root: HTMLElement, surface: V4HostAdapter) => {
      owner = surface;
      return { update, destroy };
    });
    const regions = new NamedRegions(['workspace', 'workspace-form'], render);
    regions.sync(document, data);
    Object.defineProperty(root, 'firstElementChild', { value: { replacement: true } });
    regions.sync(document, data);
    if (!owner) throw new Error('Workspace was not mounted');
    await owner.keepDraft('workspace', 's:p', { text: 'Keep these words' });
    expect(render).toHaveBeenCalledOnce();
    expect(update).toHaveBeenCalledOnce();
    expect(destroy).not.toHaveBeenCalled();
    expect(data.keepDraft).toHaveBeenCalledWith('workspace', 's:p', { text: 'Keep these words' });
  });
});

it('leaves document and test-bench routes free of workspace editor controls', () => {
  const root = {
    isConnected: true,
    closest: () => null,
    querySelector: () => null,
  } as unknown as HTMLElement;
  const document = {
    querySelectorAll: (selector: string) =>
      selector === '[data-v4-region="workspace"]' ? [root] : [],
  } as unknown as Document;
  Object.defineProperty(root, 'ownerDocument', { value: document });
  const regions = new WorkspaceRegions();
  expect(() => regions.sync(document, host())).not.toThrow();
  regions.destroy();
});
