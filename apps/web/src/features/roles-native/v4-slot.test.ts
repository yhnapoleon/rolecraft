import { beforeEach, expect, it, vi } from 'vitest';
import type { RolesNativeAdapter } from './index';
import type { V4HostAdapter, V4HostSnapshot, V4SlotHandle } from '../../v4-host';
const capture = vi.hoisted(() => ({ adapter: undefined as RolesNativeAdapter | undefined }));
vi.mock('./index', () => ({
  mountConversation: (_node: unknown, adapter: RolesNativeAdapter) => {
    capture.adapter = adapter;
    return { refresh: () => adapter.read().then(() => undefined), destroy() {} };
  },
}));
vi.mock('../../app/i18n', () => ({ T: (zh: string) => zh }));
import { mount } from './v4-slot';
import { regionHost } from '../../v4-region-test-support';
class Form {
  input = Object.assign(new EventTarget(), { value: '', defaultValue: '' });
  querySelector() {
    return this.input;
  }
  querySelectorAll() {
    return [];
  }
  addEventListener() {}
  removeEventListener() {}
}
beforeEach(() => vi.stubGlobal('HTMLFormElement', Form));
function setup(changeDuringRead: boolean) {
  let calls = 0,
    handle: V4SlotHandle;
  let snapshot: V4HostSnapshot = {
    session: { protocol: 2, sessionId: 's', workLanguage: 'zh', scenarioHash: 'hash' },
    uiLanguage: 'zh',
    state: 'active',
    asOf: { business_seq: 0, workspace_revision: 1, storage_revision: 1 },
    currentTask: null,
    currentProduct: null,
    busy: false,
    storageError: false,
    available: { timeline: true, 'turns.create': true },
  };
  const reference = (kind: string, id: string) => ({
    session_id: 's',
    kind,
    object_id: id,
    version: 1,
  });
  const turn = {
    ref: reference('role_turn', 't'),
    content: { session_id: 's', input: { role_id: 'supervisor', text: 'question' } },
  };
  const reply = {
    ref: reference('role_reply', 'r'),
    content: {
      session_id: 's',
      role_id: 'supervisor',
      question: 'question',
      text: 'reply',
      request: turn.ref,
    },
  };
  const host = {
    snapshot: () => snapshot,
    subscribe: () => () => {},
    query: async () => ({
      objects: changeDuringRead && calls === 0 ? [turn] : [turn, reply],
      role_mode: 'local_reference',
    }),
    recover: async () => {
      calls++;
      if (calls > 10) throw Error('test guard: repeated identical recovery notifications');
      if (changeDuringRead && calls === 1)
        snapshot = {
          ...snapshot,
          asOf: { business_seq: 0, workspace_revision: 2, storage_revision: 2 },
        };
      // Production recovery emits through V4Mounts even when the snapshot is unchanged.
      handle.update(snapshot);
      return {
        requestId: 'request',
        status: 'confirmed',
        result: { turn: turn.ref, question: 'question', role_id: 'supervisor' },
      };
    },
    draft: (_slot: string, key: string) => (key === 'requestRefs' ? ['request'] : undefined),
    keepDraft: async () => {},
    announce() {},
  } as unknown as V4HostAdapter;
  const thread = { dataset: { roleId: 'supervisor' }, replaceChildren() {} };
  handle = mount({
    host,
    nodes: {
      thread: thread as unknown as HTMLElement,
      composer: new Form() as unknown as HTMLElement,
    },
  });
  return {
    read: () => capture.adapter!.read(),
    calls: () => calls,
    destroy: () => handle.destroy(),
  };
}
it('finishes a role read when recovery echoes an unchanged host snapshot', async () => {
  const test = setup(false);
  try {
    const view = await test.read();
    expect(test.calls()).toBe(1);
    expect(view.turns[0].reply).toBe('reply');
  } finally {
    test.destroy();
  }
});
it('rereads once when a new reply revision arrives during recovery', async () => {
  const test = setup(true);
  try {
    const view = await test.read();
    expect(test.calls()).toBe(2);
    expect(view.turns[0].reply).toBe('reply');
  } finally {
    test.destroy();
  }
});

for (const language of ['zh', 'en'] as const) {
  it(`restores each saved colleague draft into a focused empty composer (${language})`, () => {
    const host = regionHost();
    const snapshot = host.snapshot();
    if (!snapshot.session) throw Error('Expected active session');
    const session = snapshot.session;
    host.snapshot = () => ({
      ...snapshot,
      uiLanguage: language,
      session: { ...session, workLanguage: language },
    });
    const saved = new Map([
      [
        'question:supervisor',
        language === 'zh' ? '经理问题草稿，尚未发送。' : 'Manager draft, not sent.',
      ],
      [
        'question:tech_lead',
        language === 'zh' ? '技术问题草稿，尚未发送。' : 'Technical draft, not sent.',
      ],
    ]);
    host.draft = <T>(_slot: string, key: string) => saved.get(key) as T | undefined;
    for (const roleId of ['supervisor', 'tech_lead']) {
      const form = new Form();
      vi.stubGlobal('document', { activeElement: form.input });
      const handle = mount({
        host,
        nodes: {
          thread: { dataset: { roleId }, replaceChildren() {} } as unknown as HTMLElement,
          composer: form as unknown as HTMLElement,
        },
      });
      try {
        expect(form.input.value).toBe(saved.get(`question:${roleId}`));
        expect(host.keepDraft).not.toHaveBeenCalled();
      } finally {
        handle.destroy();
      }
    }
  });
}

it.each([
  ['new text before mounting', 'New question', ''],
  ['cleared restored text before mounting', '', 'Saved question'],
])('preserves %s', (_name, value, defaultValue) => {
  const host = regionHost();
  host.draft = <T>(_slot: string, key: string) =>
    (key === 'question:supervisor' ? 'Saved question' : undefined) as T | undefined;
  const form = new Form();
  form.input.value = value;
  form.input.defaultValue = defaultValue;
  vi.stubGlobal('document', { activeElement: form.input });
  const handle = mount({
    host,
    nodes: {
      thread: { dataset: { roleId: 'supervisor' }, replaceChildren() {} } as unknown as HTMLElement,
      composer: form as unknown as HTMLElement,
    },
  });
  try {
    expect(form.input.value).toBe(value);
    expect(host.command).not.toHaveBeenCalled();
    expect(host.keepDraft).not.toHaveBeenCalled();
  } finally {
    handle.destroy();
  }
});

it('retains new input and deliberate clearing across later host updates', async () => {
  const host = regionHost();
  host.draft = <T>(_slot: string, key: string) =>
    (key === 'question:supervisor' ? 'Saved question' : undefined) as T | undefined;
  const form = new Form();
  const handle = mount({
    host,
    nodes: {
      thread: { dataset: { roleId: 'supervisor' }, replaceChildren() {} } as unknown as HTMLElement,
      composer: form as unknown as HTMLElement,
    },
  });
  try {
    for (const value of ['New question', '']) {
      form.input.value = value;
      form.input.dispatchEvent(new Event('input'));
      await Promise.resolve();
      handle.update(host.snapshot());
      expect(form.input.value).toBe(value);
      expect(host.keepDraft).toHaveBeenLastCalledWith('roles', 'question:supervisor', value);
    }
    expect(host.command).not.toHaveBeenCalled();
  } finally {
    handle.destroy();
  }
});
