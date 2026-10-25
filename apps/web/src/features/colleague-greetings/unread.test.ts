import { afterEach, describe, expect, it, vi } from 'vitest';
import { messageRows, noteKey, unreadStore, watchMessages } from './unread';
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
it.each(['reply', 'note'])(
  'acknowledges a visible %s only in an open foreground surface and stops on disposal',
  (kind) => {
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
    const id = kind === 'note' ? noteKey('policy-changed') : 'polled-reply';
    const node = {
      isConnected: true,
      dataset: kind === 'note' ? { noteMessageId: id } : { messageId: id },
      closest: () => null,
    };
    const root = { querySelectorAll: () => [node] } as unknown as HTMLElement;
    let open = true;
    const read = vi.fn(),
      stop = watchMessages(
        root,
        read,
        () => open,
        kind === 'note' ? '[data-note-message-id]' : undefined,
      );
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
    expect(read).toHaveBeenCalledWith(id);
    stop();
    expect(disconnect).toHaveBeenCalled();
    expect(listeners.size).toBe(0);
  },
);

it('uses the same legacy colleague ordinal for counting and the rendered receipt across user messages', () => {
  const messages = [
    { role: 'user', text: 'Question one' },
    { role: 'colleague', text: 'A local note without a trace' },
    { role: 'user', text: 'Question two' },
    { role: 'colleague', traceId: 'server-reply', text: 'A traced reply' },
    { role: 'colleague', traceId: '', text: 'Another legacy reply' },
  ];
  const rows = messageRows(messages),
    ids = rows.filter((row) => row.key).map((row) => row.key);
  expect(ids).toEqual(['legacy-0', 'server-reply', 'legacy-2']);
  expect(rows.filter((row) => row.message.role === 'user').every((row) => row.key === '')).toBe(
    true,
  );
  const disk = memory(),
    receipts = unreadStore(disk);
  expect(receipts.count('s', 'manager', ids)).toBe(3);
  for (const row of rows) if (row.key) receipts.read('s', 'manager', row.key);
  expect(unreadStore(disk).count('s', 'manager', ids)).toBe(0);
});
it('keeps notes unread until their own reading receipt, separately from replies and other people', () => {
  const disk = memory(),
    receipts = unreadStore(disk),
    note = noteKey('policy-changed');
  const ids = ['reply', note];
  receipts.read('s', 'business', 'reply');
  expect(receipts.count('s', 'business', ids)).toBe(1);
  receipts.read('s', 'business', note);
  expect(unreadStore(disk).count('s', 'business', ids)).toBe(0);
  expect(receipts.count('s', 'technical', [note])).toBe(1);
  expect(receipts.count('s', 'business', [...ids, noteKey('new-note')])).toBe(1);
});
