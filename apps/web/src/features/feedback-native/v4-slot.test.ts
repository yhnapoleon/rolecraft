import { fixtureHost, type HostFixture } from '../../host-test-support';
import { describe, it, expect } from 'vitest';
import { createV4FeedbackAdapter, W05_V4_OPERATIONS as op } from './v4-slot';
import type { V4HostSnapshot, V4CommandResult, V4SlotId } from '../../v4-host';
import recorded from './model-advice.fixtures.json';

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
    getRead: () => read,
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
  const choice = { decision: 'launch' as const, products: [ref('product', 'p', 2)] };
  const must = <T>(value: T | undefined): T => {
    if (value === undefined) throw Error('The adapter lacks this method');
    return value;
  };
  /** A host that answers rule checks by echoing the input it was given. */
  function checking(f: ReturnType<typeof fixture>, change: Record<string, unknown> = {}) {
    f.setSnapshot({
      available: { ...f.host.snapshot().available, 'submissions.rule_check': true },
    });
    const original = f.getRead();
    const asked: unknown[] = [];
    f.setRead(async (operation, input) => {
      if (!operation.startsWith('submissions.rule_check')) return original(operation, input);
      asked.push({ operation, input });
      const sent = (input ?? {}) as Record<string, unknown>;
      return {
        basis: operation === 'submissions.rule_check' ? 'draft' : 'saved',
        session_id: 's',
        as_of: f.host.snapshot().asOf,
        decision: sent.decision ?? 'no_go',
        products: sent.products ?? [ref('product', 'p', 2)],
        config: sent.config ?? f.cfg,
        rule_items: [],
        ...(operation === 'submissions.rule_check'
          ? {}
          : { submission: ref('submission', String(sent.submission_id)) }),
        ...change,
      };
    });
    return asked;
  }
  it('checks before submitting with exactly the input it would submit, and only reads', async () => {
    const f = fixture();
    const asked = checking(f);
    const ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    await ctl.refresh();
    expect(ctl.adapter.canPreview).toBe(true);
    expect((await must(ctl.adapter.previewSubmission)(choice)).basis).toBe('draft');
    expect(f.calls).toEqual([]);
    await ctl.adapter.submit(choice);
    expect(asked).toEqual([{ operation: 'submissions.rule_check', input: f.calls[0].input }]);
    ctl.destroy();
  });
  it('refuses a check that answers for other inputs', async () => {
    const f = fixture();
    checking(f, { products: [ref('product', 'p', 1)] });
    const ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    await ctl.refresh();
    await expect(must(ctl.adapter.previewSubmission)(choice)).rejects.toThrow();
    ctl.destroy();
  });
  it('checks a saved submission again only for that submission', async () => {
    const f = fixture();
    const asked = checking(f);
    const ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    await ctl.refresh();
    const saved = await must(ctl.adapter.submissionRuleCheck)(ref('submission', 'sub'));
    expect(saved.submission).toEqual(ref('submission', 'sub'));
    expect(asked).toEqual([
      { operation: 'submissions.rule_check.read', input: { submission_id: 'sub' } },
    ]);
    ctl.destroy();
  });
  it('remembers the panel choice in this page only, per practice', () => {
    const f = fixture();
    const first = createV4FeedbackAdapter(fixtureHost(f.host));
    const picked = { decision: 'launch', products: [ref('product', 'p', 2)] };
    expect(first.adapter.rememberedChoice?.()).toBeUndefined();
    first.adapter.rememberChoice?.(picked);
    first.destroy();
    const reopened = createV4FeedbackAdapter(fixtureHost(f.host));
    expect(reopened.adapter.rememberedChoice?.()).toEqual(picked);
    const other = fixture();
    other.setSnapshot({
      session: {
        protocol: 2,
        sessionId: 'other',
        workLanguage: 'zh',
        scenarioHash: 'f'.repeat(64),
      },
    });
    expect(createV4FeedbackAdapter(fixtureHost(other.host)).adapter.rememberedChoice?.()).toBe(
      undefined,
    );
    reopened.adapter.rememberChoice?.(null);
    expect(reopened.adapter.rememberedChoice?.()).toBeUndefined();
    reopened.destroy();
  });
  it('offers no check where the host does not', async () => {
    const f = fixture();
    f.setSnapshot({
      available: { ...f.host.snapshot().available, 'submissions.rule_check': false },
    });
    const ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    await ctl.refresh();
    expect(ctl.adapter.canPreview).toBe(false);
    ctl.destroy();
  });
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

const registeredAdvice = {
  criterion: 'R2.support',
  status: 'completed',
  registration: {
    id: 'candidate',
    model_revision: 'fixed',
    scope: 'external_candidate',
    quality_validated: false,
  },
  label: 'SUPPORTED',
  evidence_ids: ['source'],
  citations: [ref('product', 'p', 2)],
  mode: 'advisory',
  affects_score: false,
  error_code: null,
  request_id: 'private-request',
  input_hash: 'private-input',
  job_id: 'private-job',
};

describe('registered advice through the feedback host', () => {
  it('MODEL-04: malformed advice stays local to the suggestion and preserves readable rules', async () => {
    const f = fixture();
    Object.assign(f.report, {
      model_advice: [
        { ...registeredAdvice, citations: [{ ...ref('product', 'p'), session_id: 'other' }] },
      ],
    });
    const ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    try {
      await ctl.refresh();
      const state = ctl.adapter.snapshot();
      expect(state.error).toBeUndefined();
      expect(state.reports[0].business_response).toBe('原反馈不翻译');
      expect(state.reports[0].model_advice?.[0]).toMatchObject({
        status: 'unavailable',
        error_code: 'model_prediction_invalid',
        label: null,
        citations: [],
      });
      expect(f.calls).toEqual([]);
    } finally {
      ctl.destroy();
    }
  });
});

it('MODEL-03/05: refresh reads the persisted result and public fields without inference or private identity', async () => {
  const f = fixture();
  Object.assign(f.report, { model_advice: [registeredAdvice] });
  const ctl = createV4FeedbackAdapter(fixtureHost(f.host));
  try {
    await ctl.refresh();
    const original = ctl.adapter.snapshot().reports[0];
    expect(original.model_advice?.[0]).toMatchObject({
      status: 'completed',
      label: 'SUPPORTED',
      registration: { id: 'candidate', model_revision: 'fixed' },
    });
    expect(JSON.stringify(original.model_advice)).not.toMatch(
      /private-request|private-input|private-job/,
    );
    f.setSnapshot({
      semantic: { roles: 'waiting_model', feedback: 'model', assistant: 'waiting_model' },
    });
    await ctl.refresh();
    expect(ctl.adapter.snapshot().reports[0]).toEqual(original);
    Object.assign(f.report, {
      model_advice: [
        {
          ...registeredAdvice,
          status: 'unavailable',
          label: null,
          evidence_ids: [],
          citations: [],
          error_code: 'evidence_unavailable',
        },
        registeredAdvice,
      ],
    });
    await ctl.refresh();
    expect(ctl.adapter.snapshot().reports[0].model_advice?.map((entry) => entry.status)).toEqual([
      'unavailable',
      'completed',
    ]);
    expect(f.calls).toEqual([]);
    expect(f.recovery).toEqual([]);
  } finally {
    ctl.destroy();
  }
});

const invalidCases: [string, unknown][] = [
  ['scoring', { ...registeredAdvice, affects_score: true }],
  ['task domain', { ...registeredAdvice, criterion: 'R3.capacity' }],
  ['relation label', { ...registeredAdvice, label: 'MET' }],
  [
    'synthetic conclusion',
    {
      ...registeredAdvice,
      registration: { ...registeredAdvice.registration, scope: 'synthetic_fixture' },
    },
  ],
  [
    'quality claim',
    {
      ...registeredAdvice,
      registration: { ...registeredAdvice.registration, quality_validated: true },
    },
  ],
  ['missing reference', { ...registeredAdvice, citations: [] }],
  ['stale failed result', { ...registeredAdvice, status: 'failed', error_code: 'model_timeout' }],
  ['unknown status', { ...registeredAdvice, status: 'ready' }],
];
it.each(invalidCases)(
  'MODEL-01/02/04: rejects %s within one public suggestion',
  async (_name, invalid) => {
    const f = fixture();
    Object.assign(f.report, { model_advice: [invalid, registeredAdvice] });
    const ctl = createV4FeedbackAdapter(fixtureHost(f.host));
    try {
      await ctl.refresh();
      const report = ctl.adapter.snapshot().reports[0];
      expect(report.business_response).toBe('原反馈不翻译');
      expect(report.model_advice?.[0]).toEqual({
        criterion: 'R2.support',
        status: 'unavailable',
        registration: null,
        label: null,
        evidence_ids: [],
        citations: [],
        error_code: 'model_prediction_invalid',
        mode: 'advisory',
        affects_score: false,
      });
      expect(report.model_advice?.[1].label).toBe('SUPPORTED');
      expect(f.calls).toEqual([]);
    } finally {
      ctl.destroy();
    }
  },
);

/** Recorded HTTP advice (148 normal serve+worker), moved into this fixture's session. */
function inSession<T>(value: T, sessionId = 's'): T {
  return JSON.parse(
    JSON.stringify(value).replaceAll('"session_id":"fixture"', `"session_id":"${sessionId}"`),
  );
}
async function readThroughHost(advice: unknown[]) {
  const f = fixture();
  Object.assign(f.report, { model_advice: advice });
  const ctl = createV4FeedbackAdapter(fixtureHost(f.host));
  try {
    await ctl.refresh();
    return { f, report: ctl.adapter.snapshot().reports[0] };
  } finally {
    ctl.destroy();
  }
}

describe('149 sentence advice through the feedback host', () => {
  const quotes = {
    zh: '试点先只开放给已完成人工复核的团队，审批要求有据可查。',
    en: 'Open the pilot only to teams with completed human review, as corroborated by the approval rules.',
  };
  it.each(['zh', 'en'] as const)(
    'UI-01: %s synthetic sentence advice keeps its labels, sentences and counts',
    async (language) => {
      const { f, report } = await readThroughHost([inSession(recorded.advice[language])]);
      const advice = report.model_advice?.[0];
      expect(advice).toMatchObject({
        status: 'synthetic_mechanism_only',
        label: 'CONTRADICTED',
        registration: { scope: 'synthetic_fixture', quality_validated: false },
        affects_score: false,
      });
      expect(advice?.evidence_ids).toHaveLength(4);
      expect(advice?.units?.map((unit) => unit.label)).toEqual([
        'SUPPORTED',
        'INSUFFICIENT',
        'CONTRADICTED',
        'INSUFFICIENT',
        'INSUFFICIENT',
        'INSUFFICIENT',
      ]);
      expect(advice?.units?.[0]).toMatchObject({
        index: 0,
        status: 'completed',
        quote: quotes[language],
      });
      expect(advice?.units?.[0].citations.map((ref) => ref.object_id)).toEqual([
        'pilot',
        'policy',
        'brief',
        'technical',
      ]);
      expect(advice?.aggregation).toEqual({
        policy: 'r2-support-units-v1',
        counts: {
          supported: 1,
          contradicted: 1,
          insufficient: 4,
          abstained: 0,
          failed: 0,
          skipped_short: 0,
          over_budget: 0,
        },
      });
      expect(JSON.stringify(report.model_advice)).not.toMatch(
        /request_id|job_id|input_hash|unit_hash/,
      );
      expect(f.calls).toEqual([]);
      expect(f.recovery).toEqual([]);
    },
  );
});

/** The recorded sentences as an external candidate's completed advice (145 linear identity). */
const external = (language: 'zh' | 'en') => {
  const advice = inSession(recorded.advice[language]);
  return {
    ...advice,
    status: 'completed',
    error_code: null,
    registration: { ...recorded.identities.linear, scope: 'external_candidate' },
  };
};
type Raw = ReturnType<typeof external>;
const withUnit = (advice: Raw, index: number, change: Record<string, unknown>) => ({
  ...advice,
  units: advice.units.map((entry, i) => (i === index ? { ...entry, ...change } : entry)),
});
const counts = (advice: Raw, change: Record<string, number>) => ({
  ...advice,
  aggregation: { ...advice.aggregation, counts: { ...advice.aggregation.counts, ...change } },
});
const fusionIdentity = recorded.identities.fusion;
const invalidSentenceCases: [string, (advice: Raw) => unknown][] = [
  [
    'a stale sentence label on failed advice',
    (advice) => ({
      ...advice,
      status: 'failed',
      error_code: 'model_timeout',
      label: null,
      evidence_ids: [],
      citations: [],
    }),
  ],
  ['counts that disagree with the sentences', (advice) => counts(advice, { supported: 2 })],
  ['sentences without their aggregation', (advice) => ({ ...advice, aggregation: null })],
  [
    // Counts stay consistent: a second copy of an insufficient sentence replaces another one.
    'a duplicated sentence',
    (advice) => ({
      ...advice,
      units: advice.units.map((entry, i) => (i === 1 ? advice.units[3] : entry)),
    }),
  ],
  ['an aggregation without its sentences', (advice) => ({ ...advice, units: undefined })],

  [
    'a sentence cited from another session',
    (advice) =>
      withUnit(advice, 0, {
        citations: advice.units[0].citations.map((ref) => ({ ...ref, session_id: 'other' })),
      }),
  ],
  [
    'a label on an abstained sentence',
    (advice) =>
      counts(withUnit(advice, 1, { status: 'abstained' }), { abstained: 1, insufficient: 4 }),
  ],
  [
    'a sentence without its text',
    (advice) => withUnit(advice, 0, { subject: { ...advice.units[0].subject, quote: null } }),
  ],
  [
    'mechanism labels on an external registration',
    (advice) => ({
      ...advice,
      status: 'synthetic_mechanism_only',
      error_code: 'synthetic_mechanism_only',
    }),
  ],
  [
    'swapped fusion components',
    (advice) => ({
      ...advice,
      registration: {
        ...fusionIdentity,
        scope: 'external_candidate',
        components: [...fusionIdentity.components].reverse(),
      },
    }),
  ],
  [
    'a component weight that is not its share of alpha',
    (advice) => ({
      ...advice,
      registration: {
        ...fusionIdentity,
        scope: 'external_candidate',
        fusion: { ...fusionIdentity.fusion, alpha: 0.25 },
      },
    }),
  ],
  [
    'an alpha outside [0, 1]',
    (advice) => ({
      ...advice,
      registration: {
        ...fusionIdentity,
        scope: 'external_candidate',
        fusion: { ...fusionIdentity.fusion, alpha: 1.5 },
        components: undefined,
      },
    }),
  ],
  [
    'non-text label tiers',
    (advice) => ({
      ...advice,
      registration: {
        ...advice.registration,
        dataset: { ...advice.registration.dataset, label_tiers: [2] },
      },
    }),
  ],
  [
    'a criterion task on the registration',
    (advice) => ({ ...advice, registration: { ...advice.registration, task_type: 'criterion' } }),
  ],
  [
    'criteria on a relation registration',
    (advice) => ({ ...advice, registration: { ...advice.registration, criteria: ['R1.target'] } }),
  ],
];
it.each(invalidSentenceCases)(
  'UI-01: rejects %s within one suggestion and keeps the rest',
  async (_name, broken) => {
    const { f, report } = await readThroughHost([broken(external('zh')), external('en')]);
    expect(report.model_advice?.[0]).toEqual({
      criterion: 'R2.support',
      status: 'unavailable',
      registration: null,
      label: null,
      evidence_ids: [],
      citations: [],
      error_code: 'model_prediction_invalid',
      mode: 'advisory',
      affects_score: false,
    });
    expect(report.model_advice?.[1]).toMatchObject({ status: 'completed', label: 'CONTRADICTED' });
    expect(report.model_advice?.[1].units).toHaveLength(6);
    expect(report.business_response).toBe('原反馈不翻译');
    expect(f.calls).toEqual([]);
  },
);
// 149 review P3-4: a contract-valid criterion entry is not relation advice. It is skipped, so it
// can never turn the relation block into a failure; criterion display is §8 follow-up work.
describe('criterion entries next to relation advice', () => {
  const criterionEntry = (language: 'zh' | 'en') => {
    const { units: _units, aggregation: _aggregation, ...rest } = external(language);
    return { ...rest, task_type: 'criterion', criterion: 'R3.capacity', label: 'MET' };
  };
  it('skips them and keeps the relation advice', async () => {
    const { f, report } = await readThroughHost([criterionEntry('zh'), external('en')]);
    expect(report.model_advice).toHaveLength(1);
    expect(report.model_advice?.[0]).toMatchObject({ status: 'completed', label: 'CONTRADICTED' });
    expect(report.model_advice?.[0].units).toHaveLength(6);
    expect(f.calls).toEqual([]);
  });
  it('reads a list of criterion entries only as no relation advice', async () => {
    const { report } = await readThroughHost([criterionEntry('zh')]);
    expect(report.model_advice).toBeUndefined();
  });
  it('still rejects relation advice for another criterion', async () => {
    const { report } = await readThroughHost([{ ...external('zh'), criterion: 'R3.capacity' }]);
    expect(report.model_advice?.[0]).toMatchObject({
      status: 'unavailable',
      error_code: 'model_prediction_invalid',
    });
  });
});
it('UI-01: reads the fusion members, their weights and the observed fusion gain', async () => {
  const quarter = {
    ...fusionIdentity,
    scope: 'external_candidate',
    fusion: { ...fusionIdentity.fusion, alpha: 0.25, fusion_gain_observed: false },
    components: [
      { ...fusionIdentity.components[0], alpha: 0.75 },
      { ...fusionIdentity.components[1], alpha: 0.25 },
    ],
  };
  const { report } = await readThroughHost([{ ...external('en'), registration: quarter }]);
  expect(report.model_advice?.[0].registration).toEqual({
    id: fusionIdentity.id,
    model_revision: fusionIdentity.model_revision,
    scope: 'external_candidate',
    quality_validated: false,
    kind: 'probability_fusion',
    dataset: fusionIdentity.dataset,
    fusion: { alpha: 0.25, evidence_threshold: 0.5, fusion_gain_observed: false },
    components: [
      { ...fusionIdentity.components[0], alpha: 0.75 },
      { ...fusionIdentity.components[1], alpha: 0.25 },
    ],
  });
});
it('UI-01: reads the encoder kind, training data and weights stage', async () => {
  const { report } = await readThroughHost([
    { ...inSession(recorded.advice.zh), registration: recorded.identities.encoder },
  ]);
  expect(report.model_advice?.[0].registration).toEqual({
    ...recorded.identities.encoder,
    dataset: { ...recorded.identities.encoder.dataset, label_tiers: [] },
  });
  expect(report.model_advice?.[0].registration?.weights_stage).toBe('supervised_finetuned');
});

const invalidRead = {
  criterion: 'R2.support',
  status: 'unavailable',
  registration: null,
  label: null,
  evidence_ids: [],
  citations: [],
  error_code: 'model_prediction_invalid',
  mode: 'advisory',
  affects_score: false,
};
/** Every recorded sentence judged SUPPORTED with the first sentence's evidence. */
function allSupported(language: 'zh' | 'en', overBudget = 0) {
  const advice = external(language);
  const [first] = advice.units;
  return {
    ...advice,
    label: 'SUPPORTED',
    evidence_ids: first.evidence_ids,
    citations: first.citations,
    units: advice.units.map((entry) => ({
      ...entry,
      status: 'completed',
      label: 'SUPPORTED',
      evidence_ids: first.evidence_ids,
      citations: first.citations,
      reason_code: null,
    })),
    aggregation: {
      ...advice.aggregation,
      counts: {
        ...advice.aggregation.counts,
        supported: advice.units.length,
        contradicted: 0,
        insufficient: 0,
        over_budget: overBudget,
      },
    },
  };
}
it.each(['zh', 'en'] as const)(
  'UI-01: %s rejects a work-level conclusion its sentences do not give (148 conservative rule)',
  async (language) => {
    const { f, report } = await readThroughHost([
      { ...external(language), label: 'SUPPORTED' },
      { ...external(language), label: 'INSUFFICIENT' },
      { ...inSession(recorded.advice[language]), label: 'SUPPORTED' },
      allSupported(language),
      { ...allSupported(language, 2) },
      { ...allSupported(language, 2), label: 'INSUFFICIENT' },
      external(language),
    ]);
    const read = report.model_advice ?? [];
    // A contradicted sentence decides the work; over-budget sentences keep it insufficient.
    expect(read.slice(0, 3)).toEqual([invalidRead, invalidRead, invalidRead]);
    expect(read[3]).toMatchObject({ status: 'completed', label: 'SUPPORTED' });
    expect(read[4]).toEqual(invalidRead);
    expect(read[5]).toMatchObject({ status: 'completed', label: 'INSUFFICIENT' });
    expect(read[6]).toMatchObject({ status: 'completed', label: 'CONTRADICTED' });
    expect(f.calls).toEqual([]);
  },
);
it.each(['zh', 'en'] as const)(
  'UI-01: %s checks member weights when the fusion record is absent',
  async (language) => {
    const { fusion: _mix, ...members } = { ...fusionIdentity, scope: 'external_candidate' };
    const weighted = (left: number, right: number) => ({
      ...external(language),
      registration: {
        ...members,
        components: [
          { ...fusionIdentity.components[0], alpha: left },
          { ...fusionIdentity.components[1], alpha: right },
        ],
      },
    });
    const { report } = await readThroughHost([weighted(0.9, 0.9), weighted(0.25, 0.75)]);
    expect(report.model_advice?.[0]).toEqual(invalidRead);
    expect(report.model_advice?.[1].registration?.components?.map((m) => m.alpha)).toEqual([
      0.25, 0.75,
    ]);
    expect(report.model_advice?.[1].registration?.fusion).toBeUndefined();
  },
);
