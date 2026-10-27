/** `installAipmReview(host)`: the section review screen. L1 remounts it for each review target
 * and says which through `host.currentScreen()`. It reads the saved review (never recomputes
 * it), the reviewed PRD version's text and, when the recognition layer is on, the sentence
 * marks through the existing read-only check. */
import type { ObjectRef } from '../../aipm/types';
import type { Colleague } from '../../screens/result/colleagues';
import type { PreviewRecognition } from '../recognition-native/chain';
import {
  type Language,
  modelPart,
  shownDelta,
  shownStatus,
  reviewDetailForColleague,
  reviewSummaryForColleague,
  sheetName,
  sheetOfCriterion,
} from './model';
import type { Decision, SectionReview, SectionReviewPage, StepId } from './types';
import { renderReview, type Sentences } from './view';

export { reviewDetailForColleague, reviewSummaryForColleague } from './model';
export { renderReview } from './view';
export type { SectionReview } from './types';

type Feature = { render(): string; mount?(root: HTMLElement): undefined | (() => void) };
type Context = { sessionId: string; workLanguage: Language; readOnly: boolean };
type Loose = Record<string, unknown>;
type DataHost = {
  query(operation: never, input: never): Promise<unknown>;
  snapshot(): { state: string };
};

/** The read this screen needs from L4's client (`GET /section-reviews?step_id=`). */
export interface ReviewClient {
  sectionReviews(stepId?: StepId): Promise<SectionReviewPage>;
}
/** Structural subset of L1's v2 `AipmHost`. */
export interface ReviewHost {
  getSessionContext(): Context | null;
  getClient(): unknown;
  getDataHost(): unknown;
  readProgress(): Promise<unknown>;
  registerFeature(id: 'review', feature: Feature): () => void;
  currentScreen(): { kind: string; step?: StepId; reviewRef?: ObjectRef };
  openWorksheet(sheet: StepId): void;
  openMaterialSplit(materialId: string): void;
  /** Prefills only; attachPrd defaults to "this colleague has not seen the latest PRD". */
  askColleague(input: {
    colleague: Colleague;
    prefill: string;
    attachPrd?: boolean;
    /** The review's own words, offered as "Attach the review summary" (never inserted for you). */
    detail?: string;
  }): Promise<void>;
}
export type ReviewOptions = {
  /** The learner's proposed decision on ⑦; ⑤⑥'s capacity and resource lines need one. */
  decision?: () => Decision | null;
};
/** Sentence marks are the same under all four decisions (L4's test, spec §6.6), so the sentence
 * check is asked with this fixed placeholder and never waits for a choice on ⑦. */
const SENTENCE_DECISION: Decision = 'defer_with_conditions';
/** How often, and for how long (about 60 s), a running model look is reread. */
const FOLLOW_MS = 2000;
const FOLLOW_TRIES = 30;

function dig<T>(value: unknown, pick: (v: Loose) => T | undefined, depth = 5): T | undefined {
  if (!value || typeof value !== 'object' || depth < 0) return undefined;
  const found = pick(value as Loose);
  if (found !== undefined) return found;
  for (const key of ['result', 'response', 'data']) {
    const inner = dig((value as Loose)[key], pick, depth - 1);
    if (inner !== undefined) return inner;
  }
  return undefined;
}
const sameRef = (a: ObjectRef, b: ObjectRef) =>
  a.object_id === b.object_id && a.version === b.version;

/** The asked-for review in a page (newest first), or the newest one. */
export function pickReview(
  page: SectionReviewPage | null | undefined,
  ref?: ObjectRef,
): SectionReview | null {
  const items = page?.items ?? [];
  return (ref ? items.find((item) => sameRef(item.ref, ref)) : items[0])?.review ?? null;
}

const errorCode = (error: unknown) =>
  (error as { code?: string } | null)?.code ?? (error instanceof Error ? error.message : '');

export function installAipmReview(host: ReviewHost, options: ReviewOptions = {}) {
  let language: Language = host.getSessionContext()?.workLanguage ?? 'zh';
  const t = (zh: string, en: string) => (language === 'zh' ? zh : en);
  const state: {
    step: StepId | null;
    review: SectionReview | null;
    sections: Partial<Record<StepId, string>>;
    sentences: Sentences;
    modelTimedOut: boolean;
    error: string | null;
    loading: boolean;
  } = {
    step: null,
    review: null,
    sections: {},
    sentences: { kind: 'off' },
    modelTimedOut: false,
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
  const decision = () => options.decision?.() ?? state.review?.decision_used ?? null;

  // What the screen last showed for a review, so its status knob and counts move on change.
  let shown: {
    id: string;
    status: SectionReview['status'];
    delta?: SectionReview['delta'];
  } | null = null;
  function paint() {
    if (!root) return;
    if (state.review) {
      const review = state.review;
      const previous = shown?.id === review.id ? shown : null;
      shown = { id: review.id, status: shownStatus(review), delta: shownDelta(review) };
      root.replaceChildren(
        renderReview(root.ownerDocument, {
          previous,
          review: state.review,
          language,
          sections: state.sections,
          sentences: state.sentences,
          modelTimedOut: state.modelTimedOut,
          hasDecision: !!decision(),
          onAsk: (who) => void ask(who),
          onBack: () => state.step && host.openWorksheet(state.step),
          onOpenMaterial: (id) => host.openMaterialSplit(id),
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
    try {
      const found = await query('submissions.rule_check.recognition', {
        decision: SENTENCE_DECISION,
        products: [ref],
      });
      const body = dig(found, (v) => (typeof v.enabled === 'boolean' ? v : undefined)) as
        | { enabled: boolean; recognition?: PreviewRecognition | null }
        | undefined;
      if (!body?.enabled) return { kind: 'off' };
      return body.recognition?.units?.length
        ? { kind: 'ready', preview: body.recognition }
        : { kind: 'failed' };
    } catch (error) {
      return errorCode(error).includes('session_submitted')
        ? { kind: 'submitted' }
        : { kind: 'failed' };
    }
  }

  /** Shows a sheet's review; the same version reads its saved result, never a rerun. */
  async function open(step: StepId, ref?: ObjectRef) {
    const mine = ++token;
    language = host.getSessionContext()?.workLanguage ?? 'zh';
    shown = null;
    Object.assign(state, {
      sections: {},
      step,
      review: null,
      modelTimedOut: false,
      error: null,
      loading: true,
      sentences: { kind: 'off' },
    });
    paint();
    try {
      const client = host.getClient() as ReviewClient | null;
      if (!client?.sectionReviews) throw new Error('review_client_unavailable');
      const review = pickReview(await client.sectionReviews(step), ref);
      if (mine !== token) return;
      state.review = review;
      if (review) {
        const sections = await readSections(review.prd_ref).catch(() => ({}));
        if (mine !== token) return;
        state.sections = sections;
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
        follow(mine);
      }
    }
  }

  /** While the model is still looking, reread the same saved review now and then, and fill in its
   * verdicts when they arrive. Reading never starts a model call; leaving the screen stops it. */
  function follow(mine: number, tries = 0) {
    const review = state.review;
    if (!review || !state.step || modelPart(review).status !== 'running') return;
    if (tries >= FOLLOW_TRIES) {
      state.modelTimedOut = true;
      paint();
      return;
    }
    const step = state.step;
    setTimeout(async () => {
      if (mine !== token) return;
      const client = host.getClient() as ReviewClient | null;
      const page = await client?.sectionReviews(step).catch(() => null);
      if (mine !== token) return;
      // Revision 2 (with the model's items) supersedes revision 1 of the same review.
      const same = page?.items
        .map((item) => item.review)
        .filter((r) => r.id === review.id)
        .sort((a, b) => (b.revision ?? 1) - (a.revision ?? 1))[0];
      if (same) {
        state.review = same;
        paint();
      }
      follow(mine, tries + 1);
    }, FOLLOW_MS);
  }

  async function ask(who: Colleague) {
    const review = state.review;
    if (!review) return;
    // attachPrd is left to the host: on when this colleague has not seen the latest version.
    await host.askColleague({
      colleague: who,
      prefill: reviewSummaryForColleague(review, who, { language }),
      detail: reviewDetailForColleague(review, { language }),
    });
  }

  const feature: Feature = {
    render: () => '',
    mount(element) {
      root = element;
      const screen = host.currentScreen();
      if (screen.kind === 'review' && screen.step) void open(screen.step, screen.reviewRef);
      else paint();
      return () => {
        root = null;
        token++;
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
