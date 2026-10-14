/** Evidence actions on server work go through this one entry: "Cite evidence", "Use as
 * evidence" on a document or test run, "Cite result" in an investigation, and the evidence
 * chips of the open work. Citing opens the shared picker on the work's draft, focused on what
 * was clicked; the evidence takes effect when the person saves that version. Local practice
 * keeps its own paths in ui.js. */
import type { ObjectRef } from '../contracts-v2';
import { T } from './i18n';

type Work = { id: string };

export type NativeCiteHost<A extends { id: string }, W extends Work> = {
  /** Whether this practice keeps its work on the server. */
  native(a: A): boolean;
  /** The work open on the stage, if any. */
  open(): W | null;
  /** The newest work of the open task, cited into when no work is open. */
  newest(a: A): W | null;
  /** Opens the picker on the work's draft; false when the person closes it. */
  cite(a: A, work: W, focus?: ObjectRef): Promise<boolean>;
  /** Opens the exact original behind one of the work's evidence chips. */
  view(a: A, work: W, key: string): Promise<unknown>;
  /** The current version of a listed document. */
  materialVersion(a: A, id: string): number | undefined;
  /** Shows the work whose draft now holds the evidence. */
  show(work: W): void;
  notify(text: string): void;
  errorText(error: unknown): string;
};

const TEST_ACTIONS = new Set(['cite-run', 'test-cite', 'investigation-cite']);
const ACTIONS = new Set([...TEST_ACTIONS, 'cite-pick', 'cite-material', 'view-evidence']);

/** What the picker opens on: the clicked test run or document, or nothing in particular. */
function focusOf(
  sessionId: string,
  action: string,
  id: string | undefined,
  materialVersion: (id: string) => number | undefined,
): ObjectRef | undefined {
  if (!id) return undefined;
  // A test run is a single, unchanging version of its object.
  if (TEST_ACTIONS.has(action))
    return { session_id: sessionId, kind: 'test', object_id: id, version: 1 };
  if (action !== 'cite-material') return undefined;
  const version = materialVersion(id);
  return version === undefined
    ? undefined
    : { session_id: sessionId, kind: 'material', object_id: id, version };
}

/** Handles an evidence action on server work; false leaves it to the local practice. */
export async function nativeCiteAction<A extends { id: string }, W extends Work>(
  host: NativeCiteHost<A, W>,
  a: A | null | undefined,
  action: string | undefined,
  data: { id?: string; key?: string },
): Promise<boolean> {
  if (!a || !action || !ACTIONS.has(action) || !host.native(a)) return false;
  try {
    if (action === 'view-evidence') {
      const work = host.open();
      if (work && data.key) await host.view(a, work, data.key);
      return true;
    }
    const work = host.open() ?? host.newest(a);
    if (!work) {
      host.notify(
        T(
          '先在这件事里写一份作品，再引用依据。',
          'Write a piece of work for this task first, then cite evidence.',
        ),
      );
      return true;
    }
    const focus = focusOf(a.id, action, data.id, (id) => host.materialVersion(a, id));
    if (!(await host.cite(a, work, focus))) return true;
    host.notify(
      T(
        '依据已加入草稿，保存这版后生效。',
        'Evidence added to your draft. Save this version to keep it.',
      ),
    );
    host.show(work);
  } catch (error) {
    host.notify(host.errorText(error));
  }
  return true;
}
