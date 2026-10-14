import { readFileSync } from 'node:fs';
import { setImmediate as settle } from 'node:timers/promises';
import { runInThisContext } from 'node:vm';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { LocalSession } from './types';
import type { V4DataHost } from './v4-data-host';
import { regionHost } from './v4-region-test-support';
import { LiveWorkbench } from './workbench-live';

const mod = { exports: {} as ConstructorParameters<typeof LiveWorkbench>[0] };
runInThisContext(
  '(function(module){' +
    readFileSync(new URL('../public/workbench-engine.js', import.meta.url), 'utf8') +
    '\n})',
)(mod);
const engine = mod.exports;

const failure = 'Duplicate v4 region: workspace';

/** A page whose workspace region can be owned twice; every render mounts the regions again. */
function page() {
  const values = new Map<string, string>();
  const live = new LiveWorkbench(engine, {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => {
      values.set(key, value);
    },
  });
  const session = {
    id: 's',
    protocol: 2,
    v2NativeWorkspace: true,
    v2Workspace: { tasks: [], products: [] },
  } as unknown as LocalSession;
  vi.spyOn(live, 'session').mockReturnValue(session);
  vi.spyOn(live, 'v4Host').mockReturnValue(
    Object.assign(regionHost(), {
      reflectSelection: vi.fn(async () => {}),
    }) as unknown as V4DataHost,
  );
  const root = { isConnected: true, closest: () => null, querySelector: () => null };
  const dom = {
    roots: [root, root],
    querySelectorAll: (selector: string) =>
      selector === '[data-v4-region="workspace"]' ? dom.roots : [],
  };
  Object.defineProperty(root, 'ownerDocument', { value: dom });
  vi.stubGlobal('document', dom);
  const errors: string[] = [];
  live.store.subscribe(() => errors.push(live.store.getSnapshot().error));
  const mount = () => live.mountV4({ id: 's' }, { taskId: null, productId: null });
  let renders = 0;
  // Like ui.js: every notification renders the page, and every render mounts the regions.
  live.attach(engine.newState(), () => {
    if (++renders < 20) mount();
  });
  return { dom, root, errors, mount };
}

describe('v4 region mounting', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('reports a failing mount once instead of rendering into the same failure again', async () => {
    const f = page();
    await settle();
    expect(f.errors).toEqual([failure]);
  });

  it('reports the same failure again once a mount has succeeded in between', async () => {
    const f = page();
    await settle();
    f.dom.roots = [f.root];
    f.mount();
    await settle();
    f.dom.roots = [f.root, f.root];
    f.mount();
    await settle();
    expect(f.errors).toEqual([failure, failure]);
  });
});
