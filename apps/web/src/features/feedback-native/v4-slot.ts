import { retryableRead } from '../../api';
import { readRegisteredAdvice } from './model-advice';
import type { V4Query, QueryInput, V4Command, CommandInput } from '../../v4-host-operations';
/** W05 native v4 slot: no transport, credentials, Command envelope or journal. */
import type {
  V4HostAdapter,
  V4HostSnapshot,
  V4SlotContext,
  V4SlotHandle,
  V4CommandResult,
} from '../../v4-host';
import type { SubmissionRuleCheck } from '../../contracts-v2';
import type { ObjectRef } from '../workspace/contract-types';
import { exactRefKey } from './exact-ref';
import { readCatalog } from '../../reference-catalog';
import {
  mountNativeFeedback,
  type FeedbackNativeAdapter,
  type FeedbackNativeState,
  type RememberedChoice,
  type Report,
  type ReviewRecord,
  type SubmitChoice,
} from './index';

type Row = Record<string, unknown>;
const object = (v: unknown): v is Row => typeof v === 'object' && v !== null && !Array.isArray(v);
function payload(value: unknown): Row {
  for (let depth = 0; depth < 4; depth++) {
    if (!object(value)) throw Error('Invalid feedback data');
    if (Array.isArray(value.items) || value.workspace || value.feedback || value.objects)
      return value;
    if (!object(value.result)) return value;
    value = value.result;
  }
  throw Error('Invalid feedback envelope');
}
function reference(value: unknown, sid: string): ObjectRef {
  if (
    !object(value) ||
    value.session_id !== sid ||
    typeof value.kind !== 'string' ||
    typeof value.object_id !== 'string' ||
    !Number.isInteger(value.version) ||
    Number(value.version) < 1
  )
    throw Error('Invalid feedback reference');
  return value as unknown as ObjectRef;
}
const signature = (s: Readonly<V4HostSnapshot>) =>
  JSON.stringify([s.session, s.asOf, s.state, s.available]);
const semantic = (s: Readonly<V4HostSnapshot>) =>
  s.semantic?.feedback === 'waiting_model'
    ? 'waiting_for_model'
    : s.semantic?.feedback === 'model'
      ? 'available'
      : s.semantic?.feedback === 'unavailable'
        ? 'pending'
        : undefined;
export const W05_V4_OPERATIONS = Object.freeze({
  products: 'work_products.list',
  submissions: 'submissions.list',
  feedback: 'feedback.read',
  responses: 'feedback.responses.list',
  timeline: 'timeline',
  reviews: 'reviews.read',
  review: 'reviews.create',
  submit: 'submissions.create',
  respond: 'feedback.responses.create',
  revise: 'revision_cycles',
  ruleCheck: 'submissions.rule_check',
  savedRuleCheck: 'submissions.rule_check.read',
});
const sameRef = (value: unknown, ref: ObjectRef | undefined) =>
  ref === undefined
    ? value === null || value === undefined
    : object(value) && exactRefKey(value as ObjectRef) === exactRefKey(ref);
/** A rule check answers for exactly the asked session, basis and inputs. */
function answers(
  value: unknown,
  sid: string,
  basis: 'draft' | 'saved',
  asked: {
    decision?: string;
    products?: readonly ObjectRef[];
    config?: ObjectRef;
    submission?: ObjectRef;
  },
): value is SubmissionRuleCheck {
  if (
    !object(value) ||
    value.session_id !== sid ||
    value.basis !== basis ||
    !Array.isArray(value.rule_items)
  )
    return false;
  if (asked.decision !== undefined && value.decision !== asked.decision) return false;
  const products = value.products;
  if (
    asked.products !== undefined &&
    !(
      Array.isArray(products) &&
      products.length === asked.products.length &&
      products.every((ref, i) => sameRef(ref, asked.products?.[i]))
    )
  )
    return false;
  if (basis === 'draft' && !sameRef(value.config, asked.config)) return false;
  return asked.submission === undefined || sameRef(value.submission, asked.submission);
}

/** The submission panel's last choice per practice, for this page only; never stored. */
const rememberedChoices = new Map<string, RememberedChoice>();

/** A dropped read is asked again after these delays (ms) before it is shown as a failure. */
const READ_AGAIN_MS = [1500, 3000, 6000];
/** While feedback is written, its request is read again this often for the stage it is in. */
const JOB_WATCH_MS = 2500;
/** When this page first saw each feedback request waiting, for the seconds shown; page memory. */
const waitSeen = new Map<string, number>();

/** The stage the server reports for a waiting request's job, if it reports one. */
export function jobPhase(result: unknown): 'queued' | 'running' | undefined {
  if (!object(result)) return undefined;
  const jobs = Array.isArray(result.jobs) ? result.jobs : [];
  const statuses = jobs.map((job) => (object(job) ? job.status : undefined));
  if (statuses.includes('running')) return 'running';
  if (statuses.includes('queued')) return 'queued';
  if (result.feedback_status === 'queued' || result.status === 'queued') return 'queued';
  return undefined;
}
/** Server time of each delivery, from the timeline's submitted events. */
export function deliveryTimes(timeline: unknown): Record<string, string> {
  const times: Record<string, string> = {};
  const events = object(timeline) && Array.isArray(timeline.events) ? timeline.events : [];
  for (const event of events) {
    if (!object(event)) continue;
    const type = event.type ?? event.event_type;
    const at = event.created_at ?? event.at;
    if (type !== 'submitted' || typeof at !== 'string') continue;
    const refs = Array.isArray(event.refs) ? event.refs : [];
    const submission = refs.find((ref) => object(ref) && ref.kind === 'submission');
    if (object(submission) && typeof submission.object_id === 'string')
      times[submission.object_id] ??= at;
  }
  return times;
}

export function createV4FeedbackAdapter(host: V4HostAdapter) {
  const first = host.snapshot();
  const sid = first.session?.protocol === 2 ? first.session.sessionId : null;
  let closed = false;
  let epoch = 0;
  let seen = signature(first);
  let loading = false;
  let refreshAgain = false;
  let loadDone: Promise<void> = Promise.resolve();
  let finishLoad: (() => void) | undefined;
  let readsAgain = 0;
  let readAgainTimer: ReturnType<typeof setTimeout> | undefined;
  const pointer = host.draft<{ requestId: string; status: V4CommandResult['status'] }>(
    'feedback',
    'last-request',
  );
  let pending: V4CommandResult | null = pointer?.requestId ? { ...pointer, result: null } : null;
  let config: ObjectRef | undefined;
  let loadedPoint: string | null = null;
  const listeners = new Set<() => void>();
  let state: FeedbackNativeState = {
    submissions: [],
    reviews: [],
    products: [],
    reports: [],
    responses: [],
    status:
      first.state === 'active' ? 'active' : first.state === 'submitted' ? 'submitted' : 'paused',
    busy: true,
    workLanguage: first.session?.workLanguage ?? first.uiLanguage,
    uiLanguage: first.uiLanguage,
    semanticStatus: semantic(first),
    readOnly: first.readOnly === true,
  };
  const text = (zh: string, en: string) => (host.snapshot().uiLanguage === 'en' ? en : zh);
  function valid() {
    const s = host.snapshot();
    if (closed || !sid || s.session?.protocol !== 2 || s.session.sessionId !== sid)
      throw Error(
        text('练习已切换，请核对后继续。', 'The practice changed. Check it before continuing.'),
      );
    return s;
  }
  function emit() {
    for (const fn of listeners) fn();
  }
  let jobTimer: ReturnType<typeof setTimeout> | undefined;
  /** The waiting fields: whether feedback is awaited, its reported stage and since when. */
  function waiting(): Pick<
    FeedbackNativeState,
    'pending' | 'awaitingFeedback' | 'failedFeedback' | 'feedbackPhase' | 'feedbackSince'
  > {
    const awaiting = pending?.status === 'pending';
    let since: number | undefined;
    if (awaiting && pending) {
      const at = state.submission ? state.submittedAt?.[state.submission.ref.object_id] : undefined;
      const server = at ? Date.parse(at) : Number.NaN;
      // Server time when it is plausible for this wait; otherwise when this page first saw it.
      if (Number.isFinite(server) && Date.now() - server < 30 * 60_000 && server <= Date.now() + 60_000)
        since = server;
      else {
        if (!waitSeen.has(pending.requestId)) waitSeen.set(pending.requestId, Date.now());
        since = waitSeen.get(pending.requestId);
      }
    }
    return {
      pending: pending !== null && ['unconfirmed', 'needs_context'].includes(pending.status),
      awaitingFeedback: awaiting,
      failedFeedback: pending?.status === 'failed',
      feedbackPhase: awaiting ? jobPhase(pending?.result) : undefined,
      feedbackSince: since,
    };
  }
  /** While feedback is written, read its request again for the stage the server reports; once
   * it completes, read the records so the feedback shows where the wait was. */
  function watchJob() {
    clearTimeout(jobTimer);
    jobTimer = undefined;
    if (closed || pending?.status !== 'pending') return;
    jobTimer = setTimeout(async () => {
      jobTimer = undefined;
      const watched = pending;
      if (closed || watched?.status !== 'pending') return;
      if (loading || host.snapshot().busy) {
        watchJob();
        return;
      }
      try {
        const recovered = await host.recover(watched.requestId);
        if (closed || pending !== watched) return;
        pending = recovered.status === 'confirmed' ? null : recovered;
        await host.keepDraft(
          'feedback',
          'last-request',
          pending ? { requestId: pending.requestId, status: pending.status } : null,
        );
        state = { ...state, ...waiting() };
        emit();
        if (!pending) {
          await readEffect();
          return;
        }
      } catch {
        // A dropped read keeps what is shown; the next tick asks again.
      }
      watchJob();
    }, JOB_WATCH_MS);
  }
  function sync(s: Readonly<V4HostSnapshot>) {
    if (s.session?.protocol !== 2 || s.session.sessionId !== sid) {
      epoch++;
      stopReadingAgain();
      state = {
        ...state,
        products: [],
        references: undefined,
        reports: [],
        responses: [],
        reviews: [],
        submissions: [],
        reviewHistoryAvailable: false,
        submission: null,
        busy: false,
        status: 'paused',
      };
      config = undefined;
      loadedPoint = null;
      emit();
      return;
    }
    state = {
      ...state,
      status: s.state === 'submitted' ? 'submitted' : s.state === 'active' ? 'active' : 'paused',
      busy: s.busy || loading,
      ...waiting(),
      workLanguage: s.session.workLanguage,
      uiLanguage: s.uiLanguage,
      semanticStatus: semantic(s),
      readOnly: s.readOnly === true,
    };
    emit();
    const next = signature(s);
    if (next !== seen) {
      seen = next;
      void refresh();
    }
  }
  async function page(operation: V4Query, input: QueryInput<V4Query> = {}) {
    if (valid().available[operation] !== true)
      throw Error(text('这部分反馈服务尚未就绪。', 'This feedback service is not ready.'));
    return payload(await host.query(operation, input));
  }
  async function pages(operation: V4Query, input: QueryInput<V4Query> = {}) {
    const rows: unknown[] = [];
    const cursors = new Set<number>();
    let cursor = 0;
    for (let n = 0; n < 100; n++) {
      if (cursors.has(cursor)) throw Error('Repeated feedback cursor');
      cursors.add(cursor);
      const data = await page(operation, { ...input, cursor, limit: 100 });
      if (!Array.isArray(data.items)) throw Error('Missing feedback items');
      rows.push(...data.items);
      if (data.next_cursor === null || data.next_cursor === undefined) return rows;
      if (!Number.isInteger(data.next_cursor) || Number(data.next_cursor) < 0)
        throw Error('Invalid feedback cursor');
      cursor = Number(data.next_cursor);
    }
    throw Error(
      text(
        '记录较多，请缩小范围后重试。',
        'There are too many records; narrow the scope before retrying.',
      ),
    );
  }
  function stopReadingAgain() {
    clearTimeout(readAgainTimer);
    readAgainTimer = undefined;
  }
  /** A dropped read keeps what is shown and reads again shortly. A refusal or an invalid record
   * removes the server records; it and a dropped read that keeps failing are shown as errors. */
  function readFailed(error: unknown) {
    const retryable = retryableRead(error);
    if (retryable && readsAgain < READ_AGAIN_MS.length) {
      stopReadingAgain();
      readAgainTimer = setTimeout(() => {
        readAgainTimer = undefined;
        if (!closed && host.snapshot().session?.sessionId === sid) void refresh();
      }, READ_AGAIN_MS[readsAgain++]);
      return;
    }
    if (!retryable) {
      config = undefined;
      loadedPoint = null;
      state = {
        ...state,
        products: [],
        references: undefined,
        reports: [],
        responses: [],
        reviews: [],
        submissions: [],
        reviewHistoryAvailable: false,
        submission: null,
      };
    }
    state = {
      ...state,
      error: text(
        '反馈记录暂时无法确认，请刷新或恢复原请求；草稿仍保留。',
        'Feedback records are unconfirmed. Refresh or recover the original request; drafts are retained.',
      ),
    };
    host.announce(state.error!, 'error');
  }
  async function refresh() {
    if (closed || !sid) return;
    if (loading) {
      refreshAgain = true;
      return loadDone;
    }
    const current = valid();
    if (current.state === 'unavailable') {
      state = {
        ...state,
        products: [],
        references: undefined,
        reports: [],
        responses: [],
        reviews: [],
        submissions: [],
        reviewHistoryAvailable: false,
        submission: null,
        status: 'paused',
        busy: false,
        error: text(
          '当前记录无法读取，草稿仍由工作台保留。',
          'Records are unavailable; the workbench retains your drafts.',
        ),
      };
      emit();
      return;
    }
    loading = true;
    loadDone = new Promise((resolve) => {
      finishLoad = resolve;
    });
    const started = ++epoch;
    state = { ...state, busy: true };
    emit();
    try {
      if (pending) {
        const recovered = await host.recover(pending.requestId);
        pending = recovered.status === 'confirmed' ? null : recovered;
        await host.keepDraft(
          'feedback',
          'last-request',
          pending ? { requestId: pending.requestId, status: pending.status } : null,
        );
      }
      const [products, submissions, timeline] = await Promise.all([
        pages(W05_V4_OPERATIONS.products),
        pages(W05_V4_OPERATIONS.submissions),
        current.available.timeline === true
          ? page(W05_V4_OPERATIONS.timeline)
          : Promise.resolve({} as Row),
      ]);
      valid();
      const reports: Report[] = [];
      const responses: NonNullable<FeedbackNativeState['responses']> = [];
      const selected = products.map((row) => {
        if (
          !object(row) ||
          row.session_id !== sid ||
          typeof row.product_id !== 'string' ||
          !Number.isInteger(row.version) ||
          Number(row.version) < 1 ||
          !object(row.author)
        )
          throw Error('Invalid work version');
        return row as unknown as FeedbackNativeState['products'][number];
      });
      const saved = submissions.map((row) => {
        if (
          !object(row) ||
          row.session_id !== sid ||
          typeof row.id !== 'string' ||
          !Number.isInteger(row.version) ||
          Number(row.version) < 1 ||
          !Array.isArray(row.products) ||
          typeof row.decision !== 'string'
        )
          throw Error('Invalid submission');
        for (const ref of row.products) reference(ref, sid);
        return row;
      });
      // Shared public collection; older hosts may not yet expose this route.
      const reviews: ReviewRecord[] = [];
      let reviewHistoryAvailable = false;
      if (current.available[W05_V4_OPERATIONS.reviews]) {
        try {
          const rows = await pages(W05_V4_OPERATIONS.reviews);
          for (const row of rows) {
            if (
              !object(row) ||
              row.session_id !== sid ||
              typeof row.id !== 'string' ||
              !Number.isInteger(row.version) ||
              Number(row.version) < 1 ||
              !Array.isArray(row.subjects) ||
              typeof row.purpose !== 'string' ||
              typeof row.question !== 'string' ||
              !Array.isArray(row.followup_of)
            )
              throw Error('Invalid saved review');
            for (const subject of row.subjects)
              if (reference(subject, sid).kind !== 'product') throw Error('Invalid review subject');
            for (const response of row.followup_of)
              if (reference(response, sid).kind !== 'feedback_response')
                throw Error('Invalid review followup');
            if (!reviews.some((old) => old.id === row.id))
              reviews.push(row as unknown as ReviewRecord);
          }
          reviewHistoryAvailable = true;
        } catch {
          reviews.length = 0;
        }
      }
      for (const submission of [
        ...saved.map((row) => ({
          id: String(row.id),
          version: Number(row.version),
          kind: 'submission',
        })),
        ...reviews.map((row) => ({ id: row.id, version: row.version, kind: 'review' })),
      ]) {
        const data = await page(W05_V4_OPERATIONS.feedback, { submission_id: submission.id });
        if (!Array.isArray(data.items)) throw Error('Invalid feedback collection');
        for (const row of data.items) {
          if (
            !object(row) ||
            row.session_id !== sid ||
            typeof row.id !== 'string' ||
            !Number.isInteger(row.version) ||
            Number(row.version) < 1 ||
            !Array.isArray(row.items) ||
            !Array.isArray(row.next_options) ||
            typeof row.business_response !== 'string'
          )
            throw Error('Invalid feedback record');
          const subject = reference(row.subject, sid);
          if (
            subject.kind !== submission.kind ||
            subject.object_id !== submission.id ||
            subject.version !== submission.version
          )
            throw Error('Feedback subject mismatch');
          if (!reports.some((old) => old.id === row.id)) {
            const modelAdvice = readRegisteredAdvice(row.model_advice, sid);
            reports.push({ ...row, model_advice: modelAdvice } as unknown as Report);
          }
          if (current.available[W05_V4_OPERATIONS.responses])
            for (const response of await pages(W05_V4_OPERATIONS.responses, {
              feedback_id: row.id,
            })) {
              if (
                !object(response) ||
                response.session_id !== sid ||
                typeof response.id !== 'string' ||
                typeof response.text !== 'string' ||
                response.version !== 1 ||
                !object(response.feedback) ||
                !['objection', 'supplement'].includes(String(response.kind))
              )
                throw Error('Invalid feedback response');
              const feedbackRef = reference(response.feedback, sid);
              if (
                feedbackRef.kind !== 'feedback' ||
                feedbackRef.object_id !== row.id ||
                feedbackRef.version !== row.version
              )
                throw Error('Response feedback mismatch');
              responses.push(
                response as unknown as NonNullable<FeedbackNativeState['responses']>[number],
              );
            }
        }
      }
      let chosen: ObjectRef | undefined;
      if (
        object(timeline.workspace) &&
        object(timeline.workspace.config) &&
        Array.isArray(timeline.objects)
      ) {
        const cfg = timeline.workspace.config;
        for (const row of timeline.objects)
          if (
            object(row) &&
            object(row.ref) &&
            row.ref.kind === 'config' &&
            row.ref.object_id === cfg.id &&
            row.ref.version === cfg.version &&
            row.ref.config_version === cfg.config_version
          )
            chosen = reference(row.ref, sid);
      }
      if (started !== epoch || closed || host.snapshot().session?.sessionId !== sid) return;
      if (JSON.stringify(host.snapshot().asOf) !== JSON.stringify(current.asOf)) {
        refreshAgain = true;
        return;
      }
      config = chosen;
      const last = saved.at(-1);
      loadedPoint = JSON.stringify(current.asOf);
      state = {
        ...state,
        point: loadedPoint,
        products: selected,
        references: readCatalog(timeline, selected),
        submittedAt: {
          ...Object.fromEntries(
            saved.flatMap((row) => {
              const at = host.draft<string>('feedback', `delivered-at:${String(row.id)}`);
              return typeof at === 'string' ? [[String(row.id), at]] : [];
            }),
          ),
          ...deliveryTimes(timeline),
        },
        reports,
        responses,
        reviews,
        reviewHistoryAvailable,
        submissions: saved.map((row) => ({
          ref: {
            session_id: sid,
            kind: 'submission',
            object_id: String(row.id),
            version: Number(row.version),
          },
          products: row.products as ObjectRef[],
          decision: String(row.decision),
        })),
        submission: last
          ? {
              ref: {
                session_id: sid,
                kind: 'submission',
                object_id: String(last.id),
                version: Number(last.version),
              },
              products: last.products as ObjectRef[],
              decision: String(last.decision),
            }
          : null,
        error: undefined,
      };
      readsAgain = 0;
      stopReadingAgain();
      // Never derive feedback readiness from timeline.role_mode.
    } catch (error) {
      if (started === epoch && !closed) readFailed(error);
    } finally {
      loading = false;
      finishLoad?.();
      finishLoad = undefined;
      if (!closed) {
        state = {
          ...state,
          busy: host.snapshot().busy,
          ...waiting(),
        };
        emit();
        watchJob();
      }
      if (refreshAgain) {
        refreshAgain = false;
        if (!closed && host.snapshot().session?.sessionId === sid) void refresh();
      }
    }
  }
  async function finish(result: V4CommandResult) {
    valid();
    if (result.status === 'pending') {
      pending = result;
      state = { ...state, ...waiting() };
      emit();
      await readEffect();
      return;
    }
    if (result.status !== 'confirmed') {
      pending = ['pending', 'unconfirmed', 'needs_context', 'failed'].includes(result.status)
        ? result
        : null;
      state = { ...state, ...waiting() };
      emit();
      throw Error(
        text(
          '操作尚未确认，请通过工作台恢复原请求。',
          'The action is not confirmed. Recover the original request through the workbench.',
        ),
      );
    }
    pending = null;
    await readEffect();
  }
  /** The command is saved; a dropped follow-up read is left to the next poll and the panel's own
   * reads, so it is never reported as a failed write. */
  async function readEffect() {
    try {
      await host.query('workbench.read');
    } catch (error) {
      if (!retryableRead(error)) throw error;
    }
    await refresh();
  }
  async function command<K extends V4Command>(operation: K, input: CommandInput<K>) {
    const s = valid();
    if (s.available[operation] !== true)
      throw Error(text('当前操作尚未就绪。', 'This action is not ready.'));
    if (operation === W05_V4_OPERATIONS.review && !state.reviewHistoryAvailable)
      throw Error(
        text(
          '评审历史入口尚未就绪，请稍后再评审。',
          'Review history is not ready. Try the review later.',
        ),
      );
    if (pending && ['unconfirmed', 'needs_context'].includes(pending.status))
      throw Error(text('先恢复尚未确认的原请求。', 'Recover the outstanding request first.'));
    if (
      (operation === W05_V4_OPERATIONS.submit || operation === W05_V4_OPERATIONS.review) &&
      loadedPoint !== JSON.stringify(s.asOf)
    ) {
      await refresh();
      throw Error(
        text(
          '记录已变化，请核对确切版本后再交付。',
          'Records changed. Check the exact versions before submitting.',
        ),
      );
    }
    await host.flushDrafts();
    const afterFlush = valid();
    if (
      (operation === W05_V4_OPERATIONS.submit || operation === W05_V4_OPERATIONS.review) &&
      loadedPoint !== JSON.stringify(afterFlush.asOf)
    )
      throw Error(
        text(
          '记录已变化，请核对确切版本后再交付。',
          'Records changed. Check exact versions before submitting.',
        ),
      );
    const result = await host.command(operation, input);
    await host.keepDraft('feedback', 'last-request', {
      requestId: result.requestId,
      status: result.status,
    });
    await finish(result);
  }
  /** Exactly what the submit control sends: the choice plus the current settings. */
  const submitInput = (input: SubmitChoice) => ({ ...input, ...(config ? { config } : {}) });
  /** The bound session, where the host offers rule checks. */
  function checkable(): string {
    const s = valid();
    if (!sid || s.available[W05_V4_OPERATIONS.ruleCheck] !== true) throw Error(unavailable());
    return sid;
  }
  const unavailable = () =>
    text(
      '交付前预演暂时算不出来，不影响交付。',
      'The preview is unavailable right now; you can still submit.',
    );
  const adapter: FeedbackNativeAdapter = {
    snapshot: () => state,
    subscribe: (fn) => {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
    refresh,
    review: (input) => {
      valid();
      if (!input.subjects.length)
        throw Error(text('请选择评审作品版本。', 'Select artifact versions for review.'));
      for (const ref of input.subjects)
        if (reference(ref, sid!).kind !== 'product') throw Error('Invalid review subject');
      for (const ref of input.followup_of)
        if (reference(ref, sid!).kind !== 'feedback_response')
          throw Error('Invalid review followup');
      return command(W05_V4_OPERATIONS.review, input);
    },
    submit: (input) => {
      valid();
      for (const ref of input.products) reference(ref, sid!);
      const at = new Date().toISOString();
      return command(W05_V4_OPERATIONS.submit, submitInput(input)).then(async () => {
        // The records do not carry a delivery time; this browser keeps the moment it delivered,
        // for the stamp and the seconds of the feedback wait. Another device shows no time.
        const id = state.submission?.ref.object_id;
        if (!id || host.draft('feedback', `delivered-at:${id}`)) return;
        await host.keepDraft('feedback', `delivered-at:${id}`, at).catch(() => undefined);
        state = { ...state, submittedAt: { ...state.submittedAt, [id]: at } };
        state = { ...state, ...waiting() };
        emit();
      });
    },
    previewSubmission: async (input) => {
      const id = checkable();
      for (const ref of input.products) reference(ref, id);
      const sent = submitInput(input);
      const checked = await host.query(W05_V4_OPERATIONS.ruleCheck, sent);
      valid();
      if (!answers(checked, id, 'draft', sent)) throw Error(unavailable());
      return checked;
    },
    submissionRuleCheck: async (submission) => {
      const id = checkable();
      if (reference(submission, id).kind !== 'submission') throw Error('Invalid submission');
      const checked = await host.query(W05_V4_OPERATIONS.savedRuleCheck, {
        submission_id: submission.object_id,
      });
      valid();
      if (!answers(checked, id, 'saved', { submission })) throw Error(unavailable());
      return checked;
    },
    respond: (input) => command(W05_V4_OPERATIONS.respond, input),
    beginRevision: (input) => {
      reference(input.parent_submission, valid().session!.sessionId);
      return command(W05_V4_OPERATIONS.revise, input);
    },
    recover: async () => {
      valid();
      if (pending) await finish(await host.recover(pending.requestId));
    },
    retry: async () => {
      valid();
      if (!pending || pending.status !== 'failed') return;
      const result = await host.retry(pending.requestId);
      await host.keepDraft('feedback', 'last-request', {
        requestId: result.requestId,
        status: result.status,
      });
      await finish(result);
    },
    openReference: (ref) => {
      valid();
      reference(ref, sid!);
      void host.openReference(ref);
    },
    chooseEvidence: async (pick) => {
      valid();
      const refs = await host.chooseEvidence(pick);
      valid();
      for (const ref of refs) reference(ref, sid!);
      return [...refs];
    },
    rememberChoice: (picked) => {
      if (!sid) return;
      if (picked) rememberedChoices.set(sid, structuredClone(picked));
      else rememberedChoices.delete(sid);
    },
    rememberedChoice: () => {
      const picked = sid ? rememberedChoices.get(sid) : undefined;
      return picked && structuredClone(picked);
    },
    readDraft: (key) => {
      valid();
      return host.draft('feedback', key);
    },
    keepDraft: async (key, value) => {
      valid();
      await host.keepDraft('feedback', key, value);
    },
  };
  Object.defineProperties(adapter, {
    canRetry: { get: () => host.snapshot().available['jobs.refresh'] === true },
    canReview: {
      get: () =>
        !state.error &&
        state.reviewHistoryAvailable === true &&
        !!host.snapshot().available[W05_V4_OPERATIONS.review],
    },
    canSubmit: { get: () => !state.error && !!host.snapshot().available[W05_V4_OPERATIONS.submit] },
    canPreview: {
      get: () => !state.error && host.snapshot().available[W05_V4_OPERATIONS.ruleCheck] === true,
    },
    canRespond: {
      get: () => !state.error && !!host.snapshot().available[W05_V4_OPERATIONS.respond],
    },
  });
  const unsubscribe = host.subscribe(() => sync(host.snapshot()));
  return {
    adapter,
    refresh,
    update: sync,
    destroy: () => {
      closed = true;
      epoch++;
      clearTimeout(jobTimer);
      stopReadingAgain();
      unsubscribe();
      listeners.clear();
    },
    sessionId: sid,
  };
}

/** Keys: content, or submission/reviewMain for the respective surface.
 * Reference navigation stays in host.openReference into existing review-side. */
export function mountV4Feedback(context: V4SlotContext): V4SlotHandle {
  const { host, nodes } = context;
  const surface = context.surface ?? 'feedback';
  const content = nodes.content ?? (surface === 'submission' ? nodes.submission : nodes.reviewMain);
  if (!content) throw Error('W05 v4 content node required');
  const controller = createV4FeedbackAdapter(host);
  let mounted: ReturnType<typeof mountNativeFeedback> | undefined;
  let locale = host.snapshot().uiLanguage;
  let closed = false;
  const blockLegacySubmit = (event: Event) => {
    event.preventDefault();
    event.stopPropagation();
  };
  if (content.tagName === 'FORM' && host.snapshot().session?.protocol === 2)
    content.addEventListener('submit', blockLegacySubmit);
  function render(s: Readonly<V4HostSnapshot>) {
    if (closed) return;
    if (s.session?.protocol !== 2 || s.session.sessionId !== controller.sessionId) {
      mounted?.destroy();
      mounted = undefined;
      content.removeEventListener('submit', blockLegacySubmit);
      return;
    }
    if (
      locale !== s.uiLanguage &&
      content.contains(content.ownerDocument.activeElement) &&
      content.ownerDocument.activeElement?.matches('input,textarea,select,[contenteditable="true"]')
    )
      return;
    if (!mounted || locale !== s.uiLanguage) {
      mounted?.destroy();
      locale = s.uiLanguage;
      mounted = mountNativeFeedback(content, controller.adapter, { surface });
    }
  }
  const onBlur = () => render(host.snapshot());
  content.addEventListener('focusout', onBlur);
  const stop = controller.adapter.subscribe(() => render(host.snapshot()));
  render(host.snapshot());
  void controller.refresh();
  return {
    update: (s) => {
      controller.update(s);
      render(s);
    },
    destroy: () => {
      closed = true;
      stop();
      controller.destroy();
      mounted?.destroy();
      content.removeEventListener('focusout', onBlur);
      content.removeEventListener('submit', blockLegacySubmit);
    },
  };
}
export { mountV4Feedback as mount };
