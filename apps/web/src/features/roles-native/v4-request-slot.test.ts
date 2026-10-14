import { setImmediate as settle } from 'node:timers/promises';
import { afterEach, expect, it, vi } from 'vitest';
import { V4DataHost } from '../../v4-data-host';
import type { V4SlotHandle } from '../../v4-host';
import { rememberRequest } from './v4-data';
import { mount } from './v4-request-slot';

// Minimal DOM boundary; the production slot, host, journal and notifications stay real.
class Element extends EventTarget {
  children: Element[] = [];
  dataset: Record<string, string> = {};
  textContent = '';
  value = '';
  disabled = false;
  ownerDocument = dom;
  append(...children: Element[]) {
    this.children.push(...children);
  }
  replaceChildren(...children: Element[]) {
    this.children = children;
  }
  closest() {
    return null;
  }
  remove() {}
  focus() {}
  setAttribute(name: string, value: string) {
    this.dataset[`attr:${name}`] = value;
  }
  all(): Element[] {
    return [this, ...this.children.flatMap((child) => child.all())];
  }
}
const dom = {
  activeElement: null,
  createElement: () => new Element(),
  createDocumentFragment: () => new Element(),
};
class Form extends Element {
  reason = new Element();
  querySelector() {
    return this.reason;
  }
  querySelectorAll() {
    return [];
  }
}
const cleanup: (() => void)[] = [];
afterEach(() => {
  cleanup.splice(0).forEach((destroy) => {
    destroy();
  });
  vi.unstubAllGlobals();
});

type Options = {
  kind?: string;
  resources?: Record<string, number>;
  draft?: Record<string, unknown>;
  objects?: unknown[];
  titles?: Record<string, string>;
};
async function fixture(options: Options = {}) {
  const { kind = 'request_capacity', resources = { capacity: 30 } } = options;
  vi.stubGlobal('HTMLFormElement', Form);
  vi.stubGlobal('HTMLButtonElement', Element);
  vi.stubGlobal(
    'FormData',
    class {
      get() {
        return kind;
      }
    },
  );
  type Sent = { operation: string; payload: { tool?: string; terms?: Record<string, number> } };
  const sent: Sent[] = [];
  let revision = 1;
  let status = 'completed';
  const point = () => ({
    business_seq: 0,
    workspace_revision: revision,
    storage_revision: revision,
  });
  const state = () => ({ ...point(), session_id: 's', status: 'active' });
  const binding = {
    protocol: 2 as const,
    sessionId: 's',
    workLanguage: 'zh' as const,
    scenarioHash: 'fixed',
  };
  const records = new Map<string, string>();
  const storage = new Map<string, string>();
  const reads: string[] = [];
  let timelineReads = 0;
  let holdTimeline: Promise<void> | undefined;
  let holdRecovery: Promise<void> | undefined;
  const reply = (value: Record<string, unknown>) =>
    new Response(JSON.stringify({ schema_version: 2, ...value }), {
      headers: { 'Content-Type': 'application/json' },
    });
  const envelope = (value: unknown) => reply({ result: { result: value } });
  const fetcher: typeof fetch = async (input, init) => {
    const url = String(input);
    if (init?.body) {
      const command: Sent & { request_id: string } = JSON.parse(String(init.body));
      records.set(command.request_id, command.operation);
      sent.push(command);
      return reply({ boundary: { request_id: command.request_id }, state: state(), result: {} });
    }
    if (url.includes('/requests/')) {
      const id = url.split('/requests/')[1];
      reads.push(id);
      if (reads.length > 8) throw Error('Test transport guard: recovery did not converge');
      await holdRecovery;
      return reply({
        session_id: 's',
        request_id: id,
        operation: records.get(id),
        status,
        read_only: true,
      });
    }
    if (url.includes('/workbench'))
      return envelope({
        session: binding,
        state: state(),
        as_of: point(),
        available: { timeline: true, actions: true },
        semantic: { roles: 'unavailable', feedback: 'unavailable', assistant: 'unavailable' },
      });
    if (url.includes('/timeline')) {
      timelineReads++;
      await holdTimeline;
      return envelope({
        objects: options.objects ?? [],
        workspace: { resources, material_titles: options.titles ?? {} },
      });
    }
    return reply({ state: state() });
  };
  let queue = Promise.resolve();
  const announce = vi.fn();
  const host = new V4DataHost({
    binding,
    fetcher,
    credentials: () => ({ sessionId: 's', token: 'local-test-credential' }),
    storage: {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => {
        storage.set(key, value);
      },
    },
    uiLanguage: () => 'zh',
    announce,
    chooseEvidence: async () => [],
    openReference: async () => {},
    exclusive: <T>(_name: string, action: () => Promise<T>): Promise<T> => {
      const result = queue.then(action);
      queue = result.then(
        () => {},
        () => {},
      );
      return result;
    },
  });
  await host.query('workbench.read');
  const createRequest = () =>
    host.command('actions', {
      tool: 'request_business',
      terms: { capacity: 100 },
      reason: 'Bounded pilot',
    });
  const request = await createRequest();
  await rememberRequest(host, 'resource-requests', request);
  if (options.draft) await host.keepDraft('resource-requests', 'form', options.draft);
  const form = new Form();
  const submit = new Element();
  const results = new Element();
  let handle: V4SlotHandle | undefined;
  // Mirrors the surface update delivered by V4Mounts as well as the slot's own subscription.
  const unsubscribe = host.subscribe(() => handle?.update(host.snapshot()));
  cleanup.push(() => {
    handle?.destroy();
    unsubscribe();
  });
  return {
    host,
    reads,
    sent,
    form,
    announce,
    submit,
    results,
    request,
    createRequest,
    timelineReads: () => timelineReads,
    start() {
      handle = mount({
        host,
        nodes: {
          form: form as unknown as HTMLElement,
          submit: submit as unknown as HTMLElement,
          results: results as unknown as HTMLElement,
        },
      });
      return handle;
    },
    setStatus(value: string) {
      status = value;
    },
    holdRecovery(value: Promise<void>) {
      holdRecovery = value;
    },
    holdTimeline(value: Promise<void>) {
      holdTimeline = value;
    },
    async changeRevision() {
      revision++;
      await host.query('workbench.read');
    },
  };
}

it('does not recover again when subscribe and update echo identical resource inputs', async () => {
  const f = await fixture();
  const handle = f.start();
  await settle();
  handle.update(f.host.snapshot());
  await settle();
  expect(f.reads).toEqual([f.request.requestId]);
  expect(f.timelineReads()).toBe(1);
  expect(f.submit.disabled).toBe(false);
});

it('refreshes a new request identity even when the host snapshot is unchanged', async () => {
  const f = await fixture();
  const next = await f.createRequest();
  const handle = f.start();
  await settle();
  const before = f.host.snapshot();
  await rememberRequest(f.host, 'resource-requests', next);
  expect(f.host.snapshot()).toEqual(before);
  handle.update(f.host.snapshot());
  await settle();
  expect(f.reads).toEqual([f.request.requestId, f.request.requestId, next.requestId]);
});

it('refreshes once for a real host revision change', async () => {
  const f = await fixture();
  f.start();
  await settle();
  await f.changeRevision();
  await settle();
  expect(f.reads).toEqual([f.request.requestId, f.request.requestId]);
  expect(f.timelineReads()).toBe(2);
});

it('retains the pending gate until the original request is explicitly recovered', async () => {
  const f = await fixture();
  f.setStatus('pending');
  const handle = f.start();
  await settle();
  handle.update(f.host.snapshot());
  await settle();
  expect(f.reads).toEqual([f.request.requestId]);
  expect(f.submit.disabled).toBe(true);
  const button = f.results.all().find((node) => node.textContent === '恢复原请求');
  expect(button).toBeDefined();
  f.setStatus('completed');
  if (!button) throw Error('Expected original-request recovery control');
  button.dispatchEvent(new Event('click'));
  await settle();
  expect(f.reads).toEqual([f.request.requestId, f.request.requestId, f.request.requestId]);
  expect(f.submit.disabled).toBe(false);
});

it('starts no request recovery after destruction while a timeline read is in flight', async () => {
  const f = await fixture();
  let release!: () => void;
  f.holdTimeline(
    new Promise<void>((resolve) => {
      release = resolve;
    }),
  );
  const handle = f.start();
  handle.destroy();
  release();
  await settle();
  handle.update(f.host.snapshot());
  await f.changeRevision();
  await settle();
  expect(f.reads).toEqual([]);
  expect(f.timelineReads()).toBe(1);
});

it('does not recover another request after destruction during recovery', async () => {
  const f = await fixture();
  const next = await f.createRequest();
  await rememberRequest(f.host, 'resource-requests', next);
  let release!: () => void;
  f.holdRecovery(
    new Promise<void>((resolve) => {
      release = resolve;
    }),
  );
  const handle = f.start();
  await settle();
  expect(f.reads).toEqual([f.request.requestId]);
  handle.destroy();
  release();
  await settle();
  expect(f.reads).toEqual([f.request.requestId]);
});

it('does not refresh after an explicit recovery finishes on a destroyed slot', async () => {
  const f = await fixture();
  f.setStatus('pending');
  const handle = f.start();
  await settle();
  const button = f.results.all().find((node) => node.textContent === '恢复原请求');
  if (!button) throw Error('Expected original-request recovery control');
  let release!: () => void;
  f.holdRecovery(
    new Promise<void>((resolve) => {
      release = resolve;
    }),
  );
  f.setStatus('completed');
  button.dispatchEvent(new Event('click'));
  await settle();
  handle.destroy();
  release();
  await settle();
  expect(f.timelineReads()).toBe(1);
  expect(f.reads).toEqual([f.request.requestId, f.request.requestId]);
});

const resources = { capacity: 30, dev_days: 3, deadline_day: 7 };
const field = (f: Awaited<ReturnType<typeof fixture>>, key: string) => {
  const input = f.form.all().find((node) => node.dataset.resource === key);
  if (!input) throw Error(`Missing resource input ${key}`);
  return input;
};
const lastTerms = (f: Awaited<ReturnType<typeof fixture>>) =>
  f.sent.filter((c) => c.payload.tool === 'request_business').at(-1)?.payload.terms;

it('prefills current totals and sends only the term the learner changed', async () => {
  const f = await fixture({ kind: 'request_resources', resources });
  f.start();
  await settle();
  expect([field(f, 'dev_days').value, field(f, 'deadline_day').value]).toEqual(['3', '7']);
  field(f, 'dev_days').value = '7';
  f.form.reason.value = '实时同步需要更多开发人日';
  f.form.dispatchEvent(new Event('submit'));
  await settle();
  expect(lastTerms(f)).toEqual({ dev_days: 7 });
});

it('does not resend a restored draft term that equals the allocation in effect', async () => {
  const f = await fixture({
    kind: 'request_resources',
    resources,
    draft: {
      kind: 'request_resources',
      reason: '实时同步需要更多开发人日',
      terms: { dev_days: '7', deadline_day: '7' },
      evidence: [],
    },
  });
  f.start();
  await settle();
  f.form.dispatchEvent(new Event('submit'));
  await settle();
  expect(lastTerms(f)).toEqual({ dev_days: 7 });
});

it('sends nothing when no total differs from the allocation in effect', async () => {
  const f = await fixture({ kind: 'request_resources', resources });
  f.start();
  await settle();
  f.form.reason.value = '再看看';
  const before = f.sent.length;
  f.form.dispatchEvent(new Event('submit'));
  await settle();
  expect(f.sent.length).toBe(before);
  expect(f.announce).toHaveBeenLastCalledWith('请至少改一项申请数量。', 'error');
});
