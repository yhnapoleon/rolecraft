import { setImmediate as settle } from 'node:timers/promises';
import { afterEach, expect, it, vi } from 'vitest';
import type { EvidenceRefV2 } from '../../contracts-v2';
import { V4DataHost, type V4HostPorts } from '../../v4-data-host';
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
  choose?: V4HostPorts['chooseEvidence'];
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
    chooseEvidence: options.choose ?? (async () => []),
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

it('offers passages, test runs and work with the current choice and summarises it', async () => {
  const cited = (kind: string, id: string, version: number): EvidenceRefV2 => ({
    session_id: 's',
    kind,
    object_id: id,
    version,
    observed_at_seq: 3,
    valid_from_seq: 0,
  });
  const chosen = [cited('test', 't1', 1), cited('product', 'p1', 2)];
  const picks: unknown[] = [];
  const f = await fixture({
    choose: async (pick) => {
      picks.push(structuredClone(pick));
      return chosen;
    },
  });
  f.start();
  await settle();
  const button = f.form.all().find((node) => node.textContent === '选择依据');
  if (!button) throw Error('Expected the evidence control');
  const summary = () => f.form.all().find((node) => node.textContent.startsWith('已选依据'));
  expect(f.form.all().some((node) => node.textContent === '还没有选择依据')).toBe(true);
  button.dispatchEvent(new Event('click'));
  await settle();
  expect(summary()?.textContent).toBe('已选依据：1 次测试 · 1 份作品');
  button.dispatchEvent(new Event('click'));
  await settle();
  expect(picks).toEqual([
    { kinds: ['material', 'test', 'product'], selected: [] },
    { kinds: ['material', 'test', 'product'], selected: chosen },
  ]);
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

const quote = '可审批上限：容量60人，开发资源6人日，期限第10天。';
const decided = (assessment?: Record<string, unknown>) => [
  {
    ref: { session_id: 's', kind: 'business_request', object_id: 'r1', version: 2 },
    content: {
      session_id: 's',
      requested: { dev_days: 7 },
      reason: '实时同步需要更多开发人日',
      status: 'rejected',
      basis: { config: { update_strategy: 'realtime' } },
    },
  },
  {
    ref: { session_id: 's', kind: 'business_decision', object_id: 'd1', version: 1 },
    content: {
      session_id: 's',
      status: 'rejected',
      request: { session_id: 's', kind: 'business_request', object_id: 'r1', version: 1 },
      reason_code: 'request_over_limit',
      reason: '请求超过当前可审批上限，或试图降低既有资源；请对照审批规则调整条款。',
      ...(assessment ? { assessment } : {}),
    },
  },
];
const texts = (f: Awaited<ReturnType<typeof fixture>>) => f.results.all().map((n) => n.textContent);

it('shows the decision card for a rejection and refills at the ceiling without sending', async () => {
  const f = await fixture({
    kind: 'request_resources',
    resources,
    titles: { 'approvals:1': '经理发布：资源审批规则' },
    objects: decided({
      terms: [
        {
          resource: 'dev_days',
          current: 3,
          requested: 7,
          limit: 6,
          needed: 6,
          issues: ['over_limit'],
        },
      ],
      clauses: [
        {
          session_id: 's',
          kind: 'material',
          object_id: 'approvals',
          version: 1,
          span_start: 89,
          span_end: 116,
          quote,
          observed_at_seq: 3,
        },
      ],
    }),
  });
  f.start();
  await settle();
  expect(texts(f)).toContain(quote);
  expect(texts(f)).toContain('开发人日：申请 7，超出上限 6；方案需要 6（缺口 3）');
  expect(texts(f)).not.toContain(
    '请求超过当前可审批上限，或试图降低既有资源；请对照审批规则调整条款。',
  );
  const before = f.sent.length;
  const refill = f.results.all().find((n) => n.textContent === '按上限改申请');
  if (!refill) throw Error('Expected the ceiling re-application control');
  refill.dispatchEvent(new Event('click'));
  await settle();
  expect([field(f, 'dev_days').value, field(f, 'deadline_day').value]).toEqual(['6', '7']);
  expect(f.sent.length).toBe(before);
});

it('keeps the recorded reason for a decision saved before the card existed', async () => {
  const f = await fixture({ kind: 'request_resources', resources, objects: decided() });
  f.start();
  await settle();
  expect(texts(f)).toContain(
    '请求超过当前可审批上限，或试图降低既有资源；请对照审批规则调整条款。',
  );
});

it('drops the ceiling re-application from an old rejection once resources reach it', async () => {
  const f = await fixture({
    kind: 'request_resources',
    resources: { ...resources, dev_days: 6 },
    titles: { 'approvals:1': '经理发布：资源审批规则' },
    objects: decided({
      terms: [
        {
          resource: 'dev_days',
          current: 3,
          requested: 7,
          limit: 6,
          needed: 6,
          issues: ['over_limit'],
        },
      ],
      clauses: [],
    }),
  });
  f.start();
  await settle();
  expect(texts(f)).toContain('开发人日：申请 7，超出上限 6；方案需要 6（缺口 3）');
  expect(texts(f)).not.toContain('按上限改申请');
});
