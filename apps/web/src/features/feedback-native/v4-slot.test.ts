import { fixtureHost, type HostFixture } from '../../host-test-support';
import { describe, it, expect } from 'vitest';
import { createV4FeedbackAdapter, W05_V4_OPERATIONS as op } from './v4-slot';
import type { V4HostSnapshot, V4CommandResult, V4SlotId } from '../../v4-host';

const ref = (kind: string, id: string, version = 1) => ({
  session_id: 's',
  kind,
  object_id: id,
  version,
});
function fixture() {
  let snapshot: V4HostSnapshot = {
    session: { protocol: 2, sessionId: 's', workLanguage: 'zh', scenarioHash: 'f'.repeat(64) },
    uiLanguage: 'en',
    semantic: { roles: 'model', feedback: 'waiting_model', assistant: 'waiting_model' },
    state: 'active',
    asOf: { business_seq: 3, workspace_revision: 2, storage_revision: 2 },
    currentTask: null,
    currentProduct: null,
    busy: false,
    storageError: false,
    available: Object.fromEntries(Object.values(op).map((k) => [k, true])),
  };
  const listeners = new Set<() => void>();
  const calls: { operation: string; input: unknown }[] = [];
  const queries: string[] = [];
  const drafts = new Map<string, unknown>();
  const recovery: string[] = [];
  let result: V4CommandResult = { requestId: 'host-request', status: 'confirmed', result: {} };
  const product = {
    session_id: 's',
    product_id: 'p',
    version: 2,
    title: '用户原文',
    author: { id: 'h', kind: 'human' },
    removed_at: null,
  };
  const submission = {
    id: 'sub',
    session_id: 's',
    version: 1,
    products: [ref('product', 'p', 2)],
    decision: 'no_go',
  };
  const report = {
    id: 'f',
    session_id: 's',
    version: 1,
    subject: ref('submission', 'sub'),
    semantic_status: 'waiting_for_model',
    items: [],
    rule_items: [],
    business_response: '原反馈不翻译',
    next_options: [],
  };
  const cfg = { ...ref('config', 'cfg', 3), config_version: 2 };
  let read: (operation: string, input?: Readonly<Record<string, unknown>>) => Promise<unknown> =
    async (operation) => {
      if (operation === 'workbench.read')
        return {
          as_of: snapshot.asOf,
          state: { status: snapshot.state },
          available: snapshot.available,
          semantic: snapshot.semantic,
          session: snapshot.session,
        };
      if (operation === op.products)
        return { result: { result: { items: [product], next_cursor: null } } };
      if (operation === op.submissions)
        return { result: { items: [submission], next_cursor: null } };
      if (operation === op.feedback) return { items: [report] };
      if (operation === op.reviews) return { items: [], next_cursor: null };
      if (operation === op.responses) return { items: [], next_cursor: null };
      if (operation === op.timeline)
        return {
          role_mode: 'model',
          objects: [{ ref: cfg, content: {} }],
          workspace: { config: { id: 'cfg', version: 3, config_version: 2 } },
        };
      throw Error('unexpected operation');
    };
  const host: HostFixture = {
    snapshot: () => snapshot,
    subscribe: (fn) => {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
    query: (name, input) => {
      queries.push(name);
      return read(name, input);
    },
    command: async (name, input) => {
      calls.push({ operation: name, input });
      return result;
    },
    recover: async (id) => {
      recovery.push(id);
      return result;
    },
    retry: async () => {
      throw Error('must not retry automatically');
    },
    draft: <T>(_slot: V4SlotId, key: string) => drafts.get(key) as T | undefined,
    keepDraft: async (_slot, key, value) => {
      drafts.set(key, value);
    },
    flushDrafts: async () => {},
    openReference: async () => {},
    chooseEvidence: async () => [],
    selectTask: () => {},
    selectProduct: () => {},
    announce: () => {},
  };
  return {
    host,
    calls,
    queries,
    drafts,
    recovery,
    product,
    report,
    cfg,
    setRead: (value: typeof read) => {
      read = value;
    },
    setResult: (value: V4CommandResult) => {
      result = value;
    },
    setSnapshot: (value: Partial<V4HostSnapshot>) => {
      snapshot = { ...snapshot, ...value };
      for (const fn of listeners) fn();
    },
    listeners,
  };
}

describe('W05 v4 host adapter', () => {
  it('reads exact records and submits domain input with authoritative config only', async () => {
    const f = fixture();
    const ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    await ctl.refresh();
    expect(ctl.adapter.snapshot().status).toBe('active');
    expect(ctl.adapter.snapshot().uiLanguage).toBe('en');
    expect(ctl.adapter.snapshot().workLanguage).toBe('zh');
    expect(ctl.adapter.snapshot().reports[0].business_response).toBe('原反馈不翻译');
    expect(ctl.adapter.snapshot().semanticStatus).toBe('waiting_for_model');
    await ctl.adapter.submit({ decision: 'no_go', products: [ref('product', 'p', 2)] });
    expect(f.calls).toEqual([
      {
        operation: op.submit,
        input: { decision: 'no_go', products: [ref('product', 'p', 2)], config: f.cfg },
      },
    ]);
    expect(JSON.stringify(f.calls)).not.toMatch(/expected_version|request_id|token/);
    ctl.destroy();
  });
  it('pending commands retain drafts and recover only on the explicit control', async () => {
    const f = fixture();
    const ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    await ctl.refresh();
    f.setResult({ requestId: 'original-key', status: 'unconfirmed', result: {} });
    await ctl.adapter.keepDraft('f:general', { text: 'Keep my wording', evidence: [] });
    await expect(
      ctl.adapter.respond({
        feedback_id: 'f',
        feedback_version: 1,
        kind: 'objection',
        section: 'general',
        text: 'Keep my wording',
        evidence: [],
      }),
    ).rejects.toThrow();
    expect(f.calls).toHaveLength(1);
    expect(f.recovery).toEqual([]);
    expect(ctl.adapter.snapshot().pending).toBe(true);
    await expect(
      ctl.adapter.respond({
        feedback_id: 'f',
        feedback_version: 1,
        kind: 'supplement',
        section: 'general',
        text: 'second',
        evidence: [],
      }),
    ).rejects.toThrow();
    expect(f.calls).toHaveLength(1);
    expect(f.drafts.get('f:general')).toEqual({ text: 'Keep my wording', evidence: [] });
    f.setResult({ requestId: 'original-key', status: 'confirmed', result: {} });
    await ctl.adapter.recover!();
    expect(f.recovery).toEqual(['original-key']);
    expect(ctl.adapter.snapshot().pending).toBe(false);
    ctl.destroy();
  });
  it('a saved submission with a pending feedback job is not a failed write', async () => {
    const f = fixture();
    const ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    await ctl.refresh();
    f.setResult({
      requestId: 'feedback-job',
      status: 'pending',
      result: { submission: ref('submission', 'sub'), feedback_status: 'queued' },
    });
    await ctl.adapter.submit({ decision: 'no_go', products: [ref('product', 'p', 2)] });
    expect(ctl.adapter.snapshot().pending).toBe(false);
    expect(ctl.adapter.snapshot().awaitingFeedback).toBe(true);
    expect(f.recovery).toEqual(['feedback-job']);
    expect(f.calls).toHaveLength(1);
    f.setResult({ requestId: 'feedback-job', status: 'confirmed', result: {} });
    await ctl.adapter.recover!();
    expect(ctl.adapter.snapshot().awaitingFeedback).toBe(false);
    expect(f.recovery).toEqual(['feedback-job', 'feedback-job']);
    ctl.destroy();
  });
  it('does not treat colleague model mode as feedback readiness', async () => {
    const f = fixture();
    const ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    await ctl.refresh();
    expect(ctl.adapter.snapshot().reports[0].semantic_status).toBe('waiting_for_model');
    expect(ctl.adapter.snapshot().modelMode).toBeUndefined();
    ctl.destroy();
  });
  it('legacy sessions make no v2 queries or commands', async () => {
    const f = fixture();
    f.setSnapshot({ session: { protocol: 1, sessionId: 'old', workLanguage: null } });
    const ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    await ctl.refresh();
    expect(f.queries).toEqual([]);
    expect(() => ctl.adapter.submit({ decision: 'no_go', products: [] })).toThrow();
    expect(f.calls).toEqual([]);
    ctl.destroy();
  });
  it('a changed session cannot receive the old asynchronous response or draft', async () => {
    const f = fixture();
    let release!: (value: unknown) => void;
    f.setRead((operation) =>
      operation === op.products
        ? new Promise((resolve) => {
            release = resolve;
          })
        : Promise.resolve({ items: [], next_cursor: null }),
    );
    const ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    const running = ctl.refresh();
    f.setSnapshot({
      session: {
        protocol: 2,
        sessionId: 'other',
        workLanguage: 'en',
        scenarioHash: 'a'.repeat(64),
      },
    });
    release({ items: [f.product], next_cursor: null });
    await running;
    expect(ctl.adapter.snapshot().products).toEqual([]);
    expect(f.calls).toEqual([]);
    await expect(
      ctl.adapter.keepDraft('revision', { text: 'old-session draft', evidence: [] }),
    ).rejects.toThrow();
    expect(f.drafts.size).toBe(0);
    ctl.destroy();
  });
  it('failed authorized reads remove server records while keeping user drafts', async () => {
    const f = fixture();
    const ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    await ctl.refresh();
    await ctl.adapter.keepDraft('revision', { text: 'keep', evidence: [] });
    f.setRead(async () => {
      throw Error('forbidden');
    });
    await ctl.refresh();
    expect(ctl.adapter.snapshot().reports).toEqual([]);
    expect(ctl.adapter.snapshot().products).toEqual([]);
    expect(ctl.adapter.snapshot().error).toBeTruthy();
    expect(f.drafts.get('revision')).toEqual({ text: 'keep', evidence: [] });
    ctl.destroy();
  });
  it('busy-only host notices do not start another query loop', async () => {
    const f = fixture();
    const ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    await ctl.refresh();
    const count = f.queries.length;
    f.setSnapshot({ busy: true });
    f.setSnapshot({ busy: false });
    expect(f.queries.length).toBe(count);
    ctl.destroy();
    expect(f.listeners.size).toBe(0);
  });
  it('changing UI language preserves fixed work language and stored feedback', async () => {
    const f = fixture();
    const ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    await ctl.refresh();
    const count = f.queries.length;
    f.setSnapshot({ uiLanguage: 'zh' });
    expect(ctl.adapter.snapshot().workLanguage).toBe('zh');
    expect(ctl.adapter.snapshot().reports[0].business_response).toBe('原反馈不翻译');
    expect(f.queries.length).toBe(count);
    ctl.destroy();
  });
});

describe('W05 non-terminal review via public host', () => {
  const review = {
    id: 'review-1',
    session_id: 's',
    version: 1,
    subjects: [ref('product', 'p', 2)],
    purpose: 'test plan',
    question: 'Check the assumptions',
    decision: null,
    scope: [],
    followup_of: [],
  };
  it('records exact selected versions and optional unknown decision without submitting the session', async () => {
    const f = fixture(),
      ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    await ctl.refresh();
    await ctl.adapter.review!({
      subjects: review.subjects,
      purpose: 'test plan',
      question: review.question,
      decision: null,
      scope: [],
      followup_of: [],
    });
    expect(f.calls).toEqual([
      {
        operation: op.review,
        input: {
          subjects: review.subjects,
          purpose: 'test plan',
          question: review.question,
          decision: null,
          scope: [],
          followup_of: [],
        },
      },
    ]);
    expect(ctl.adapter.snapshot().status).toBe('active');
    expect(f.recovery).toEqual([]);
    ctl.destroy();
  });
  it('discovers immutable reviews and their feedback from public paged reads', async () => {
    const f = fixture();
    const seen: unknown[] = [];
    f.setRead(async (operation, input) => {
      seen.push({ operation, input });
      if (operation === op.products) return { items: [f.product] };
      if (operation === op.submissions) return { items: [] };
      if (operation === op.timeline) return { objects: [] };
      if (operation === op.reviews)
        return input?.cursor === 0
          ? { items: [review], next_cursor: 1 }
          : { items: [], next_cursor: null };
      if (operation === op.feedback)
        return { items: [{ ...f.report, subject: ref('review', review.id) }] };
      if (operation === op.responses)
        return {
          items: [
            {
              id: 'resp',
              session_id: 's',
              version: 1,
              feedback: ref('feedback', 'f'),
              kind: 'supplement',
              text: 'User-supplied; not verified',
            },
          ],
        };
      throw Error('unexpected operation');
    });
    const ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    await ctl.refresh();
    expect(ctl.adapter.snapshot().reviews).toEqual([review]);
    expect(ctl.adapter.snapshot().reviewHistoryAvailable).toBe(true);
    expect(ctl.adapter.snapshot().reports[0].subject).toEqual(ref('review', review.id));
    expect(ctl.adapter.snapshot().responses![0].text).toBe('User-supplied; not verified');
    expect(seen).toContainEqual({ operation: op.feedback, input: { submission_id: 'review-1' } });
    expect(f.calls).toEqual([]);
    ctl.destroy();
  });
  it('keeps usable submission feedback when an older host lacks the collection route', async () => {
    const f = fixture(),
      ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    await ctl.refresh();
    f.setSnapshot({ available: { ...f.host.snapshot().available, [op.reviews]: false } });
    await ctl.refresh();
    expect(ctl.adapter.snapshot().reviewHistoryAvailable).toBe(false);
    expect(ctl.adapter.canReview).toBe(false);
    expect(ctl.adapter.snapshot().reports).toHaveLength(1);
    expect(ctl.adapter.snapshot().error).toBeUndefined();
    ctl.destroy();
  });
  it('does not borrow another feedback response or cross-session review subject', async () => {
    const f = fixture(),
      ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    await ctl.refresh();
    expect(() =>
      ctl.adapter.review!({
        subjects: [{ ...ref('product', 'p'), session_id: 'other' }],
        purpose: '',
        question: '',
        decision: null,
        scope: [],
        followup_of: [],
      }),
    ).toThrow();
    expect(() =>
      ctl.adapter.review!({
        subjects: review.subjects,
        purpose: '',
        question: '',
        decision: null,
        scope: [],
        followup_of: [ref('feedback', 'f')],
      }),
    ).toThrow();
    expect(f.calls).toEqual([]);
    ctl.destroy();
  });
  it('a pending review job does not prevent recording a later, explicit user response', async () => {
    const f = fixture(),
      ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    await ctl.refresh();
    f.setResult({
      requestId: 'review-job',
      status: 'pending',
      result: { review: ref('review', 'r'), feedback_status: 'queued' },
    });
    await ctl.adapter.review!({
      subjects: review.subjects,
      purpose: 'test plan',
      question: '',
      decision: null,
      scope: [],
      followup_of: [],
    });
    f.setResult({ requestId: 'response', status: 'confirmed', result: {} });
    await ctl.adapter.respond({
      feedback_id: 'f',
      feedback_version: 1,
      kind: 'objection',
      section: 'general',
      text: 'An explicit user action',
      evidence: [],
    });
    expect(f.calls).toHaveLength(2);
    expect(f.recovery).toEqual(['review-job']);
    ctl.destroy();
  });
});

it('restores a failed feedback pointer without retry and requires an explicit new attempt', async () => {
  const f = fixture();
  f.drafts.set('last-request', { requestId: 'original', status: 'pending' });
  f.setResult({ requestId: 'original', status: 'failed', result: {} });
  f.setSnapshot({ available: { ...f.host.snapshot().available, 'jobs.refresh': true } });
  const ctl = createV4FeedbackAdapter(fixtureHost(f.host));
  await ctl.refresh();
  expect(ctl.adapter.snapshot().failedFeedback).toBe(true);
  expect(f.calls).toEqual([]);
  expect(f.recovery).toEqual(['original']);
  const retries: string[] = [];
  f.host.retry = async (id) => {
    retries.push(id);
    const result: V4CommandResult = { requestId: 'explicit-new', status: 'pending', result: {} };
    f.setResult(result);
    return result;
  };
  await ctl.adapter.retry!();
  expect(retries).toEqual(['original']);
  expect(f.drafts.get('last-request')).toEqual({ requestId: 'explicit-new', status: 'pending' });
  expect(ctl.adapter.snapshot().awaitingFeedback).toBe(true);
  ctl.destroy();
});
