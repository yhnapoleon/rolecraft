// React islands inside the native page. ui.js redraws whole regions with innerHTML, so an
// island never lives in the redrawn markup itself: it renders into its own container element,
// and after each redraw the container is moved into the new placeholder. Moving a node keeps
// its React tree, so state (a toggle's thumb, a sheet's open state) survives redraws.
import { type ComponentType, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import './tw.css';
import './bridge.css';

export type Island<P> = { update(p: P): void; destroy(): void };

/** Mounts C into host once. The caller owns the host's lifetime (use keepIsland under ui.js). */
export function mountIsland<P>(
  host: HTMLElement,
  C: React.ComponentType<P>,
  props: P,
): { update(p: P): void; destroy(): void } {
  const container = document.createElement('div');
  container.className = 'rc-island';
  host.appendChild(container);
  const root = createRoot(container);
  const draw = (p: P) =>
    root.render(createElement(C as ComponentType<P & object>, p as P & object));
  draw(props);
  return {
    update: draw,
    destroy() {
      root.unmount();
      container.remove();
    },
  };
}

/* ---------- islands that survive ui.js redraws ---------- */

type Kept = {
  container: HTMLElement;
  root: Root;
  component: ComponentType<never>;
  persist: boolean;
  focus: HTMLElement | null;
};
const kept = new Map<string, Kept>();

/**
 * The placeholder an island is adopted into. Put it in the template string; after the redraw,
 * call keepIsland with the same key. `tag` lets the placeholder sit inline (span) where needed.
 */
export function islandSlot(key: string, cls = '', tag: 'div' | 'span' = 'div'): string {
  const k = key.replace(/"/g, '');
  return `<${tag} class="rc-island-slot ${cls}" data-island="${k}"></${tag}>`;
}

/**
 * Finds the placeholder for key and puts the island there, creating it on first use and
 * updating its props on every later call. Returns false when this render has no placeholder.
 * persist: keep the island alive (but hidden) while its placeholder is absent, instead of
 * unmounting it on the next sweep.
 */
export function keepIsland<P>(
  key: string,
  C: ComponentType<P>,
  props: P,
  opts: { persist?: boolean; root?: ParentNode } = {},
): boolean {
  const slot = (opts.root ?? document).querySelector<HTMLElement>(
    `[data-island="${CSS.escape(key)}"]`,
  );
  let k = kept.get(key);
  if (k && k.component !== (C as ComponentType<never>)) {
    k.root.unmount();
    k.container.remove();
    kept.delete(key);
    k = undefined;
  }
  if (!k) {
    if (!slot) return false;
    const container = document.createElement(slot.tagName === 'SPAN' ? 'span' : 'div');
    container.className = 'rc-island';
    const entry: Kept = {
      container,
      root: createRoot(container),
      component: C as ComponentType<never>,
      persist: !!opts.persist,
      focus: null,
    };
    // Remember focus inside the island: the redraw detaches the container and drops it.
    container.addEventListener('focusin', (e) => {
      entry.focus = e.target as HTMLElement;
    });
    container.addEventListener('focusout', (e) => {
      if (!container.contains((e as FocusEvent).relatedTarget as Node | null)) {
        // A detach also fires focusout; keep the record only when the container left the page.
        if (container.isConnected) entry.focus = null;
      }
    });
    kept.set(key, entry);
    k = entry;
  }
  k.persist = !!opts.persist;
  if (slot && k.container.parentElement !== slot) {
    slot.replaceChildren(k.container);
    const f = k.focus;
    if (f && k.container.contains(f) && document.activeElement === document.body)
      f.focus({ preventScroll: true });
  }
  k.root.render(createElement(C as ComponentType<P & object>, props as P & object));
  return !!slot;
}

/** Unmounts a kept island now. */
export function dropIsland(key: string): void {
  const k = kept.get(key);
  if (!k) return;
  k.root.unmount();
  k.container.remove();
  kept.delete(key);
}

/**
 * Called by the shell after every render: islands whose placeholder did not come back are
 * unmounted, unless they asked to persist. Deferred one frame so a route's async mount can
 * still adopt its island first.
 */
export function sweepIslands(): void {
  requestAnimationFrame(() => {
    for (const [key, k] of kept) if (!k.persist && !k.container.isConnected) dropIsland(key);
  });
}

/** For tests and diagnostics: which kept islands exist right now. */
export const keptIslands = () => [...kept.keys()];
