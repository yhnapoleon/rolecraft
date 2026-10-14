import { afterEach, describe, expect, it } from 'vitest';
import type { ObjectRef } from '../contracts-v2';
import { setPreference } from './i18n';
import { nativeCiteAction, type NativeCiteHost } from './native-cite';

type Practice = { id: string; native: boolean };
type Work = { id: string };

function fakeHost(
  options: {
    open?: Work | null;
    newest?: Work | null;
    cite?: (focus?: ObjectRef) => Promise<boolean>;
    view?: () => Promise<unknown>;
  } = {},
) {
  const calls: unknown[][] = [];
  const host: NativeCiteHost<Practice, Work> = {
    native: (a) => a.native,
    open: () => (options.open === undefined ? { id: 'w-open' } : options.open),
    newest: () => (options.newest === undefined ? { id: 'w-newest' } : options.newest),
    cite: async (_a, work, focus) => {
      calls.push(['cite', work.id, focus]);
      return options.cite ? options.cite(focus) : true;
    },
    view: async (_a, work, key) => {
      calls.push(['view', work.id, key]);
      return options.view?.();
    },
    materialVersion: (_a, id) => (id === 'brief' ? 3 : undefined),
    show: (work) => {
      calls.push(['show', work.id]);
    },
    notify: (text) => {
      calls.push(['notify', text]);
    },
    errorText: (error) => `failed: ${error instanceof Error ? error.message : String(error)}`,
  };
  return { host, calls };
}

const server: Practice = { id: 's1', native: true };
const local: Practice = { id: 'local', native: false };
const added = '依据已加入草稿，保存这版后生效。';
const run = { session_id: 's1', kind: 'test', object_id: 't1', version: 1 };

afterEach(() => setPreference('zh'));

describe('evidence actions on server work', () => {
  it('leaves local practice and other actions to the local paths', async () => {
    const { host, calls } = fakeHost();
    expect(await nativeCiteAction(host, local, 'cite-run', { id: 't1' })).toBe(false);
    expect(await nativeCiteAction(host, server, 'save-work', { id: 'w-open' })).toBe(false);
    expect(await nativeCiteAction(host, null, 'cite-pick', {})).toBe(false);
    expect(calls).toEqual([]);
  });

  it('opens the picker on the open work, focused on the test run that was clicked', async () => {
    for (const action of ['cite-run', 'test-cite', 'investigation-cite']) {
      const { host, calls } = fakeHost();
      expect(await nativeCiteAction(host, server, action, { id: 't1' })).toBe(true);
      expect(calls).toEqual([
        ['cite', 'w-open', run],
        ['notify', added],
        ['show', 'w-open'],
      ]);
    }
  });

  it('focuses a document at its current version, and opens a plain picker from the toolbar', async () => {
    const material = fakeHost();
    await nativeCiteAction(material.host, server, 'cite-material', { id: 'brief' });
    expect(material.calls[0]).toEqual([
      'cite',
      'w-open',
      { session_id: 's1', kind: 'material', object_id: 'brief', version: 3 },
    ]);
    const unlisted = fakeHost();
    await nativeCiteAction(unlisted.host, server, 'cite-material', { id: 'gone' });
    expect(unlisted.calls[0]).toEqual(['cite', 'w-open', undefined]);
    const toolbar = fakeHost();
    await nativeCiteAction(toolbar.host, server, 'cite-pick', {});
    expect(toolbar.calls[0]).toEqual(['cite', 'w-open', undefined]);
  });

  it('cites into the newest work of the task when no work is open', async () => {
    const { host, calls } = fakeHost({ open: null });
    await nativeCiteAction(host, server, 'cite-run', { id: 't1' });
    expect(calls[0]).toEqual(['cite', 'w-newest', run]);
    expect(calls.at(-1)).toEqual(['show', 'w-newest']);
  });

  it('asks for a piece of work first when the task has none', async () => {
    setPreference('en');
    const { host, calls } = fakeHost({ open: null, newest: null });
    expect(await nativeCiteAction(host, server, 'investigation-cite', { id: 't1' })).toBe(true);
    expect(calls).toEqual([
      ['notify', 'Write a piece of work for this task first, then cite evidence.'],
    ]);
  });

  it('changes nothing when the picker is closed, and reports a failure in the person’s words', async () => {
    const closed = fakeHost({ cite: async () => false });
    await nativeCiteAction(closed.host, server, 'cite-run', { id: 't1' });
    expect(closed.calls).toEqual([['cite', 'w-open', run]]);
    const failed = fakeHost({
      cite: async () => {
        throw new Error('locked');
      },
    });
    await nativeCiteAction(failed.host, server, 'investigation-cite', { id: 't1' });
    expect(failed.calls.at(-1)).toEqual(['notify', 'failed: locked']);
  });

  it('opens the exact original behind an evidence chip of the open work', async () => {
    const { host, calls } = fakeHost();
    expect(await nativeCiteAction(host, server, 'view-evidence', { key: 'k1' })).toBe(true);
    expect(calls).toEqual([['view', 'w-open', 'k1']]);
    const gone = fakeHost({
      view: async () => {
        throw new Error('removed');
      },
    });
    await nativeCiteAction(gone.host, server, 'view-evidence', { key: 'k1' });
    expect(gone.calls.at(-1)).toEqual(['notify', 'failed: removed']);
    const closedWork = fakeHost({ open: null });
    expect(await nativeCiteAction(closedWork.host, server, 'view-evidence', { key: 'k1' })).toBe(
      true,
    );
    expect(closedWork.calls).toEqual([]);
  });
});
