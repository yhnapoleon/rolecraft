type Message = { role: string; traceId?: string | null };
/** The fallback ordinal counts colleague messages, never interleaved learner questions. */
export const messageKey = (message: Message, colleagueIndex: number) =>
  message.traceId || `legacy-${colleagueIndex}`;
export function messageRows<M extends Message>(messages: readonly M[]) {
  let colleagueIndex = 0;
  return messages.map((message) => ({
    message,
    key: message.role === 'user' ? '' : messageKey(message, colleagueIndex++),
  }));
}
export const noteKey = (key: string) => `note:${key}`;

/** Browser-local reading receipts; never sent to the conversation/model. */
export function unreadStore(storage?: Pick<Storage, 'getItem' | 'setItem'>) {
  const key = 'rolecraft.colleague-read.v1';
  let memory: Record<string, string[]> = {};
  const all = () => {
    try {
      const stored = JSON.parse(storage?.getItem(key) || '{}');
      return {
        ...memory,
        ...(stored && typeof stored === 'object' && !Array.isArray(stored) ? stored : {}),
      };
    } catch {
      return memory;
    }
  };
  const save = (value: Record<string, string[]>) => {
    memory = value;
    try {
      storage?.setItem(key, JSON.stringify(value));
    } catch {
      /* page-local fallback */
    }
  };
  const slot = (session: string, person: string) => `${session}:${person}`;
  return {
    seed(session: string, person: string, ids: string[]) {
      const value = all(),
        k = slot(session, person);
      if (!Array.isArray(value[k])) save({ ...value, [k]: ids });
    },
    count(session: string, person: string, ids: string[]) {
      const value = all()[slot(session, person)];
      const read = new Set(Array.isArray(value) ? value : []);
      return ids.filter((id) => !read.has(id)).length;
    },
    read(session: string, person: string, id: string) {
      const value = all(),
        k = slot(session, person);
      const ids = new Set<string>(Array.isArray(value[k]) ? value[k] : []);
      if (ids.has(id)) return false;
      ids.add(id);
      save({ ...value, [k]: [...ids] });
      return true;
    },
  };
}

/** Observe the actual painted message, including clipping by scroll ancestors. Hidden tabs,
 * collapsed drawers and modal overlays cannot acknowledge messages. */
export function watchMessages(
  root: HTMLElement,
  read: (id: string) => void,
  visible: () => boolean,
  selector = '[data-message-id], .rc-msg--them:not(.rc-typing)',
) {
  if (typeof IntersectionObserver === 'undefined') return () => {};
  const seen = new Map<Element, boolean>();
  const acknowledge = () => {
    if (document.hidden || !visible()) return;
    for (const [node, inView] of seen) {
      if (!inView || !node.isConnected) continue;
      const el = node as HTMLElement;
      if (el.closest('[inert], [hidden]')) continue;
      const id =
        el.dataset.noteMessageId ||
        el.dataset.messageId ||
        el.closest<HTMLElement>('[data-turn-id]')?.dataset.turnId;
      if (id) read(id);
    }
  };
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries)
      seen.set(
        entry.target,
        entry.isIntersecting &&
          entry.intersectionRect.height >= Math.min(32, entry.boundingClientRect.height),
      );
    acknowledge();
  });
  const scan = () => {
    for (const node of seen.keys())
      if (!node.isConnected) {
        observer.unobserve(node);
        seen.delete(node);
      }
    for (const node of root.querySelectorAll(selector)) {
      if (!seen.has(node)) {
        seen.set(node, false);
        observer.observe(node);
      }
    }
  };
  const changes = new MutationObserver(scan);
  changes.observe(root, { childList: true, subtree: true });
  document.addEventListener('visibilitychange', acknowledge);
  window.addEventListener('focus', acknowledge);
  document.addEventListener('close', acknowledge, true);
  document.addEventListener('rolecraft:greetings', acknowledge);
  scan();
  return () => {
    observer.disconnect();
    changes.disconnect();
    document.removeEventListener('visibilitychange', acknowledge);
    window.removeEventListener('focus', acknowledge);
    document.removeEventListener('close', acknowledge, true);
    document.removeEventListener('rolecraft:greetings', acknowledge);
  };
}
