import { afterEach, describe, expect, it, vi } from 'vitest';
import { unreadStore, watchMessages } from './unread';
const memory = () => {
  const values = new Map<string, string>();
  return {
    getItem: (k: string) => values.get(k) ?? null,
    setItem: (k: string, v: string) => {
      values.set(k, v);
    },
  };
};
describe('local colleague reading receipts', () => {
  it('keeps background replies unread and only acknowledges the visible message for that person', () => {
    const book = unreadStore(memory());
    book.seed('s', 'manager', []);
    expect(book.count('s', 'manager', ['preset-opening', 'reply-1'])).toBe(2);
    book.read('s', 'manager', 'preset-opening');
    expect(book.count('s', 'manager', ['preset-opening', 'reply-1'])).toBe(1);
    expect(book.count('s', 'technical', ['preset-opening'])).toBe(1);
    book.read('s', 'manager', 'reply-1');
    expect(book.count('s', 'manager', ['preset-opening', 'reply-1', 'poll-reply'])).toBe(1);
  });
  it('preserves read messages across reload, reordering and further history synchronisation', () => {
    const storage = memory(),
      first = unreadStore(storage);
    first.seed('s', 'business', ['old']);
    first.read('s', 'business', 'reply');
    const restored = unreadStore(storage);
    restored.seed('s', 'business', ['old', 'reply', 'new']);
    expect(restored.count('s', 'business', ['new', 'reply', 'old'])).toBe(1);
    expect(restored.count('other-session', 'business', ['reply'])).toBe(1);
  });
  it('migrates only legacy read turns and keeps imported history separate from new replies', () => {
    const book = unreadStore(memory());
    book.seed('old-session', 'manager', ['old-read']);
    expect(book.count('old-session', 'manager', ['old-read', 'old-unread'])).toBe(1);
    book.seed('recovered', 'manager', ['imported']);
    expect(book.count('recovered', 'manager', ['imported', 'later'])).toBe(1);
  });
  it('retains receipts in memory when storage is blocked', () => {
    const book = unreadStore({
      getItem() {
        throw Error();
      },
      setItem() {
        throw Error();
      },
    });
    expect(book.read('s', 'manager', 'reply')).toBe(true);
    expect(book.read('s', 'manager', 'reply')).toBe(false);
    expect(book.count('s', 'manager', ['reply'])).toBe(0);
  });
});

afterEach(() => vi.unstubAllGlobals());
it('acknowledges visible replies only in an open foreground conversation and stops on disposal', () => {
  let deliver: (entries: unknown[]) => void = () => {};
  const disconnect = vi.fn(),
    observed = vi.fn();
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      constructor(callback: typeof deliver) {
        deliver = callback;
      }
      observe = observed;
      unobserve() {}
      disconnect = disconnect;
    },
  );
  vi.stubGlobal(
    'MutationObserver',
    class {
      observe() {}
      disconnect() {}
    },
  );
  const listeners = new Map<string, () => void>();
  const doc = {
    hidden: true,
    addEventListener: (k: string, f: () => void) => listeners.set(k, f),
    removeEventListener: (k: string) => listeners.delete(k),
  };
  vi.stubGlobal('document', doc);
  vi.stubGlobal('window', { addEventListener() {}, removeEventListener() {} });
  const node = { isConnected: true, dataset: { messageId: 'polled-reply' }, closest: () => null };
  const root = { querySelectorAll: () => [node] } as unknown as HTMLElement;
  let open = true;
  const read = vi.fn(),
    stop = watchMessages(root, read, () => open);
  const entry = {
    target: node,
    isIntersecting: true,
    intersectionRect: { height: 60 },
    boundingClientRect: { height: 200 },
  };
  deliver([entry]);
  expect(read).not.toHaveBeenCalled();
  doc.hidden = false;
  open = false;
  listeners.get('visibilitychange')?.();
  expect(read).not.toHaveBeenCalled();
  open = true;
  deliver([{ ...entry, isIntersecting: false }]);
  expect(read).not.toHaveBeenCalled();
  deliver([entry]);
  expect(read).toHaveBeenCalledWith('polled-reply');
  stop();
  expect(disconnect).toHaveBeenCalled();
  expect(listeners.size).toBe(0);
});
