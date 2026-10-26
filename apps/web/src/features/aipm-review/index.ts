/** `installAipmReview(host)`: the section review screen, opened by L1's `host.openReview(step)`.
 * It reads the saved review (never recomputes it), the reviewed PRD version's text and, when
 * the recognition layer is on, the sentence marks through the existing read-only check. */
import type { ObjectRef } from '../../aipm/types';
import type { Colleague } from '../../screens/result/colleagues';
import type { PreviewRecognition } from '../recognition-native/chain';
import { type Language, reviewSummaryForColleague, sheetName, sheetOfCriterion } from './model';
import type { Decision, SectionReview, StepId } from './types';
import { renderReview, type Sentences } from './view';

export { reviewSummaryForColleague } from './model';
export { renderReview } from './view';
export type { SectionReview } from './types';

type Feature = { render(): string; mount?(root: HTMLElement): undefined | (() => void) };
type Context = { sessionId: string; workLanguage: Language; readOnly: boolean };
type Loose = Record<string, unknown>;
type DataHost = {
  query(operation: never, input: never): Promise<unknown>;
  snapshot(): { state: string };
};

/** The read this screen needs from L4's client (spec §9.4 `GET /section-reviews?step_id=`). */
export interface ReviewClient {
  readSectionReviews<T>(stepId: StepId): Promise<T>;
}
/** Structural subset of L1's `AipmHost` plus the v2 methods (spec §10 L1). */
export interface ReviewHost {
  getSessionContext(): Context | null;
  getClient(): unknown;
  getDataHost(): unknown;
  readProgress(): Promise<unknown>;
  registerFeature(id: 'review', feature: Feature): () => void;
  /** v2: the colleague rail with a prefilled, editable message and the PRD version attached. */
  askColleague?(input: {
    colleague: Colleague;
    prefill: string;
    attachPrd: ObjectRef | null;
  }): Promise<void>;
  openColleague(role: Colleague, question?: string): Promise<void>;
  /** v2: back to the sheet; older hosts open the design feature. */
  openWorksheet?(step: StepId): Promise<void> | void;
  openFeature(id: 'design'): void;
}
export type ReviewOptions = {
  /** The launch decision the sentence check is asked with. Until L4 confirms the sentence marks
   * do not depend on it (spec §6.6), the learner's proposed decision is preferred. */
  decision?: () => Decision | null;
};

function dig<T>(value: unknown, pick: (v: Loose) => T | undefined, depth = 5): T | undefined {
  if (!value || typeof value !== 'object' || depth < 0) return undefined;
  const found = pick(value as Loose);
  if (found !== undefined) return found;
  for (const key of ['result', 'response', 'review', 'data']) {
    const inner = dig((value as Loose)[key], pick, depth - 1);
    if (inner !== undefined) return inner;
  }
  return undefined;
}
const isReview = (v: Loose) =>
  v.schema_version === 1 && v.step_id && v.prd_ref ? (v as unknown as SectionReview) : undefined;
/** The newest review in a page of reviews, or the single review returned. */
export function latestReview(response: unknown): SectionReview | null {
  const list = dig(response, (v) => (Array.isArray(v.items) ? (v.items as Loose[]) : undefined));
  if (list) {
    const reviews = list.map((item) => isReview(item)).filter((r): r is SectionReview => !!r);
    return reviews.sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null;
  }
  return dig(response, isReview) ?? null;
}

const errorCode = (error: unknown) =>
  (error as { code?: string } | null)?.code ?? (error instanceof Error ? error.message : '');

export function installAipmReview(host: ReviewHost, options: ReviewOptions = {}) {
  const context = host.getSessionContext();
  const language: Language = context?.workLanguage ?? 'zh';
  const t = (zh: string, en: string) => (language === 'zh' ? zh : en);
  const state: {
    step: StepId | null;
    review: SectionReview | null;
    sections: Partial<Record<StepId, string>>;
    sentences: Sentences;
    currentPrdVersion: number | null;
    error: string | null;
    loading: boolean;
  } = {
    step: null,
    review: null,
    sections: {},
    sentences: { kind: 'off' },
    currentPrdVersion: null,
    error: null,
    loading: false,
  };
  let root: HTMLElement | null = null;
  let token = 0;
  const data = () => host.getDataHost() as DataHost | null;
  const query = (operation: string, input: unknown) => {
    const d = data();
    if (!d) throw new Error('data_host_unavailable');
    return d.query(operation as never, input as never);
  };

  function paint() {
    if (!root) return;
    if (state.review) {
      root.replaceChildren(
        renderReview(root.ownerDocument, {
          review: state.review,
          language,
          sections: state.sections,
          sentences: state.sentences,
          currentPrdVersion: state.currentPrdVersion,
          hasDecision: !!options.decision?.(),
          onAsk: (who) => void ask(who),
          onBack: () => void back(),
        }),
      );
      return;
    }
    const note = root.ownerDocument.createElement('p');
    note.className = 'aipm-review__muted';
    note.textContent = state.loading
      ? t('正在读取批改…', 'Reading the review…')
      : (state.error ??
        t(
          '这一节还没有批改。在工作纸上点「交给批改」。',
          'No review for this section yet. Press “Send for review” on the sheet.',
        ));
    root.replaceChildren(note);
  }

  async function readSections(ref: ObjectRef) {
    const page = await query('work_products.versions.list', { product_id: ref.object_id });
    const items =
      dig(page, (v) => (Array.isArray(v.items) ? (v.items as Loose[]) : undefined)) ?? [];
    const version = items.find((item) => item.version === ref.version);
    const payload = version?.structured_payload as
      | { sections?: Record<string, string> }
      | undefined;
    return (payload?.sections ?? {}) as Partial<Record<StepId, string>>;
  }

  async function readSentences(ref: ObjectRef): Promise<Sentences> {
    if (data()?.snapshot().state === 'submitted') return { kind: 'submitted' };
    const decision = options.decision?.() ?? null;
    if (!decision) return { kind: 'no_decision' };
    try {
      const found = (await query('submissions.rule_check.recognition', {
        decision,
        products: [ref],
      })) as {
        enabled?: boolean;
        recognition?: PreviewRecognition | null;
      };
      const body =
        dig(found, (v) => (typeof v.enabled === 'boolean' ? (v as typeof found) : undefined)) ??
        found;
      if (!body.enabled) return { kind: 'off' };
      return body.recognition?.units?.length
        ? { kind: 'ready', preview: body.recognition }
        : { kind: 'failed' };
    } catch (error) {
      return errorCode(error).includes('session_submitted')
        ? { kind: 'submitted' }
        : { kind: 'failed' };
    }
  }

  /** Shows the latest review of a sheet; the same version reads its saved result, never a rerun. */
  async function open(step: StepId) {
    const mine = ++token;
    Object.assign(state, {
      step,
      review: null,
      error: null,
      loading: true,
      sentences: { kind: 'off' },
    });
    paint();
    try {
      const client = host.getClient() as ReviewClient | null;
      if (!client?.readSectionReviews) throw new Error('review_client_unavailable');
      const review = latestReview(await client.readSectionReviews(step));
      const progress = await host.readProgress().catch(() => null);
      const prd = dig(progress, (v) =>
        v.prd_ref && typeof v.prd_ref === 'object' ? (v.prd_ref as ObjectRef) : undefined,
      );
      if (mine !== token) return;
      state.review = review;
      state.currentPrdVersion = prd?.version ?? null;
      if (review) {
        state.sections = await readSections(review.prd_ref).catch(() => ({}));
        state.sentences = { kind: 'running' };
        paint();
        const sentences = await readSentences(review.prd_ref);
        if (mine !== token) return;
        state.sentences = sentences;
      }
    } catch {
      if (mine === token)
        state.error = t(
          '批改暂时读不到，稍后再打开。',
          'The review could not be read. Open it again later.',
        );
    } finally {
      if (mine === token) {
        state.loading = false;
        paint();
      }
    }
  }

  async function ask(who: Colleague) {
    const review = state.review;
    if (!review) return;
    const prefill = reviewSummaryForColleague(review, who, { language });
    if (host.askColleague)
      await host.askColleague({ colleague: who, prefill, attachPrd: review.prd_ref });
    else await host.openColleague(who, prefill);
  }

  async function back() {
    if (!state.step) return;
    if (host.openWorksheet) await host.openWorksheet(state.step);
    else host.openFeature('design');
  }

  const feature: Feature = {
    render: () => '',
    mount(element) {
      root = element;
      paint();
      return () => {
        root = null;
      };
    },
  };
  const unregister = host.registerFeature('review', feature);
  return { feature, state, open, ask, unregister };
}

/** For the result page's `backToSheet` option: "Back to ③ Validate the need" under a criterion,
 * or nothing for one no sheet reviews. */
export function backToSheet(
  doc: Document,
  criterion: string,
  language: Language,
  open: (step: StepId) => void,
): HTMLElement | null {
  const step = sheetOfCriterion(criterion);
  if (!step) return null;
  const button = doc.createElement('button');
  button.type = 'button';
  button.className = 'btn quiet small aipm-back-to-sheet';
  button.dataset.aipmSheet = step;
  button.textContent =
    language === 'zh'
      ? `回到 ${sheetName(step, language)}`
      : `Back to ${sheetName(step, language)}`;
  button.addEventListener('click', () => open(step));
  return button;
}
