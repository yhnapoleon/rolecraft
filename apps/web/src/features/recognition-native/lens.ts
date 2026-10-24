/** Recognition lens: a per-viewer switch that shows the recognition process in place. Off by
 * default. The saved preference lives in this browser only; reading or writing it may fail
 * (private window, blocked storage) and then the lens is simply off. For recordings, `?lens=1`
 * in the address opens the lens for this tab and `?lens=0` forces it closed; neither changes the
 * saved preference. A toggle from the "⋯" menu applies at once and is saved. */
const KEY = 'rolecraft.lens';
type Store = Pick<Storage, 'getItem' | 'setItem'>;

export function createLensState(env: { search?: string; storage?: Store | null }) {
  const listeners = new Set<(on: boolean) => void>();
  const flag = new URLSearchParams(env.search ?? '').get('lens');
  let value: boolean;
  if (flag === '1' || flag === '0') value = flag === '1';
  else {
    try {
      value = env.storage?.getItem(KEY) === '1';
    } catch {
      value = false;
    }
  }
  return {
    on: () => value,
    set(next: boolean) {
      try {
        env.storage?.setItem(KEY, next ? '1' : '0');
      } catch {
        // Not saved; it still applies to this tab.
      }
      if (next === value) return;
      value = next;
      for (const listener of [...listeners]) listener(value);
    },
    subscribe(listener: (on: boolean) => void) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
  };
}

function browserStore(): Store | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

const shared = createLensState({
  search: typeof location === 'undefined' ? '' : location.search,
  storage: browserStore(),
});

function mark(on: boolean) {
  if (typeof document !== 'undefined') document.documentElement.dataset.lens = on ? 'on' : 'off';
}
mark(shared.on());
shared.subscribe(mark);

/** Whether the recognition lens is open in this tab. */
export const lensOn = () => shared.on();
/** Open or close the lens; pages redraw their recognition parts in place. */
export const setLens = (on: boolean) => shared.set(on);
/** Called with the new state on every change; returns the unsubscribe function. */
export const onLensChange = (listener: (on: boolean) => void) => shared.subscribe(listener);
