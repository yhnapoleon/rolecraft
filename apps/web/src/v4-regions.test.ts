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

/** The roots a workspace region mounts on a page that answers these selectors truthfully. */
function mountedRoots(page: Record<string, unknown[]>): string[] {
  const document = {
    querySelectorAll: (selector: string) => page[selector] ?? [],
  } as unknown as Document;
  const render = vi.fn((_name: string, _root: HTMLElement, _host: V4HostAdapter) => ({
    update() {},
    destroy() {},
  }));
  new NamedRegions(['workspace'], render).sync(document, host());
  return render.mock.calls.map(([, root]) => root.id);
}
const region = (id: string) => ({ id, isConnected: true, closest: () => null });
const container = (...inside: unknown[]) => ({
  contains: (node: unknown) => inside.includes(node),
});

it('ignores a copy inside the document flight layer rather than failing on a second owner', () => {
  const live = region('live'),
    copy = region('copy'),
    flight = container(copy);
  const page = {
    '[data-v4-region="workspace"]': [live, copy],
    '.document-flight': [flight],
    '[inert][aria-hidden="true"]': [flight],
  };
  expect(mountedRoots(page)).toEqual(['live']);
});

it('still mounts a live region inside an ordinary inert, hidden container', () => {
  const live = region('live'),
    backdrop = container(live);
  const page = {
    '[data-v4-region="workspace"]': [live],
    '[inert][aria-hidden="true"]': [backdrop],
  };
  expect(mountedRoots(page)).toEqual(['live']);
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
