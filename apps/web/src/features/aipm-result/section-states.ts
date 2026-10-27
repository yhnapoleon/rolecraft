/** "Section reviews before delivery" on the AIPM result page: per section, the first
 * section review and the review of the delivered PRD version. Reads the stored reviews only;
 * it never creates a review and never changes the formal score. */
import type { AipmClient } from '../../aipm/client';
import type { ObjectRef, SectionReview, SectionReviewPage, StepId } from '../../aipm/types';
import type { SubmissionV2 } from '../../contracts-v2';
import { STEPS, shownStatus, statusName, stepName, text, type Language } from '../aipm-review/model';
import './section-states.css';

type Status = SectionReview['status'];
type Item = SectionReviewPage['items'][number];
export type ReviewPoint = { status: Status; version: number; ref: ObjectRef };
export type SectionState = {
  step: StepId;
  /** The section's earliest review, only when it was on an earlier PRD version. */
  first: ReviewPoint | null;
  /** The newest review of the delivered version. */
  delivered: ReviewPoint | null;
  /** What a click opens: the delivered review, else the earliest one; null when never reviewed. */
  open: ObjectRef | null;
};

const PAGE = 20;
const MAX_PAGES = 50;

/** The delivered PRD version: the submitted product whose object is the pilot PRD. */
export function deliveredVersion(submission: Pick<SubmissionV2, 'products'>, prdId: string | null) {
  if (!prdId) return null;
  return submission.products.find((p) => p.object_id === prdId)?.version ?? null;
}

/** Items arrive newest first. A review's own `stale: edited` flag only says a later PRD version
 * exists, which is true of every earlier review here, so it does not drop the review. */
export function sectionStates(items: readonly Item[], version: number): SectionState[] {
  return STEPS.map((step) => {
    const mine = items.filter((i) => i.review.step_id === step && i.review.prd_ref.version <= version);
    const point = (i: Item | undefined): ReviewPoint | null =>
      i ? { status: shownStatus(i.review), version: i.review.prd_ref.version, ref: i.ref } : null;
    const delivered = point(mine.find((i) => i.review.prd_ref.version === version));
    const earliest = point(mine.at(-1));
    const first = earliest && earliest.version < version ? earliest : null;
    return { step, first, delivered, open: (delivered ?? earliest)?.ref ?? null };
  });
}

/** Reads every page; the server returns at most 20 a page, newest first. */
export async function readAllReviews(client: Pick<AipmClient, 'sectionReviews'>) {
  const items: Item[] = [];
  let cursor: number | null = 0;
  for (let n = 0; cursor !== null && n < MAX_PAGES; n++) {
    const page: SectionReviewPage = await client.sectionReviews(undefined, cursor, PAGE);
    items.push(...page.items);
    cursor = page.next_cursor;
  }
  return items;
}

// ---- HTML -----------------------------------------------------------------------------

const esc = (value: unknown) =>
  String(value ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c,
  );
const versionName = (n: number, language: Language) => text(language, `第 ${n} 版`, `v${n}`);
/** "草稿（第 3 版）", read aloud the same way it reads on screen. */
const pointText = (p: ReviewPoint, language: Language) =>
  text(
    language,
    `${statusName(p.status, language)}（${versionName(p.version, language)}）`,
    `${statusName(p.status, language)} (${versionName(p.version, language)})`,
  );
const RANK: Readonly<Record<Status, number>> = { draft: 0, based: 1, solid: 2 };
/** The delivered review stands higher than the first one: the improvement the data shows. */
export const rose = (s: SectionState) =>
  !!s.first && !!s.delivered && RANK[s.delivered.status] > RANK[s.first.status];
const tag = (p: ReviewPoint, language: Language, rise = false) =>
  `<span class="aipm-states__tag" data-status="${p.status}"${rise ? ' data-rise="true"' : ''}>${esc(statusName(p.status, language))}</span>` +
  `<span class="aipm-states__ver">${esc(versionName(p.version, language))}</span>`;
const ARROW =
  '<svg class="aipm-states__arrow" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" focusable="false"><path d="M5 12h14M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const NOT_REVIEWED = (language: Language) =>
  text(language, '这一版没有批改过', 'Not reviewed on this version');
const NOT_REVIEWED_DELIVERED = (language: Language) =>
  text(language, '交付版没有再批改', 'Not reviewed again on the delivered version');

export function rowSentence(s: SectionState, language: Language) {
  const name = stepName(s.step, language);
  if (s.first && s.delivered)
    return text(
      language,
      `${name}：第一次批改 ${pointText(s.first, language)}，交付版 ${pointText(s.delivered, language)}`,
      `${name}: first review ${pointText(s.first, language)}, delivered ${pointText(s.delivered, language)}`,
    );
  if (s.first)
    return text(
      language,
      `${name}：第一次批改 ${pointText(s.first, language)}，${NOT_REVIEWED_DELIVERED(language)}`,
      `${name}: first review ${pointText(s.first, language)}; ${NOT_REVIEWED_DELIVERED(language).toLowerCase()}`,
    );
  if (s.delivered) return `${name}${text(language, '：', ': ')}${pointText(s.delivered, language)}`;
  return `${name}${text(language, '：', ': ')}${NOT_REVIEWED(language)}`;
}

function rowPath(s: SectionState, language: Language) {
  const quiet = (words: string) => `<span class="aipm-states__none">${esc(words)}</span>`;
  if (s.first && s.delivered)
    return `${tag(s.first, language)}${ARROW}${tag(s.delivered, language, rose(s))}`;
  if (s.first) return `${tag(s.first, language)}${ARROW}${quiet(NOT_REVIEWED_DELIVERED(language))}`;
  if (s.delivered) return tag(s.delivered, language);
  return quiet(NOT_REVIEWED(language));
}

/** The sections nobody reviewed, as one quiet closing line. */
export function unreviewedLine(names: readonly string[], all: boolean, language: Language) {
  if (all) return text(language, '交付前没有批改任何一节。', 'No section was reviewed before delivery.');
  const list = names.join(text(language, '、', ', '));
  return text(
    language,
    `其余 ${names.length} 节交付前没有批改：${list}`,
    names.length === 1
      ? `One other section was not reviewed before delivery: ${list}`
      : `The other ${names.length} sections were not reviewed before delivery: ${list}`,
  );
}

/** Reviewed sections first, each a button opening its review; the rest folded into one line. */
export function sectionStatesHtml(states: readonly SectionState[], language: Language) {
  const reviewed = states.filter((s) => s.open);
  const rest = states.filter((s) => !s.open).map((s) => stepName(s.step, language));
  const rows = reviewed
    .map((s) => {
      const label = `${rowSentence(s, language)}${text(language, '。打开这一次批改', '. Open this review')}`;
      return (
        `<li><button type="button" class="aipm-states__row" data-states-step="${s.step}"${rose(s) ? ' data-rise="true"' : ''} aria-label="${esc(label)}">` +
        `<span class="aipm-states__name">${esc(stepName(s.step, language))}</span>` +
        `<span class="aipm-states__path" aria-hidden="true">${rowPath(s, language)}<span class="aipm-states__open">›</span></span>` +
        '</button></li>'
      );
    })
    .join('');
  const restLine = rest.length
    ? `<p class="aipm-states__rest">${esc(unreviewedLine(rest, !reviewed.length, language))}</p>`
    : '';
  return `<h2 class="aipm-states__title" id="aipm-states-title">${esc(
    text(language, '交付前的逐节批改', 'Section reviews before delivery'),
  )}</h2><p class="aipm-states__lead">${esc(
    text(
      language,
      '这是交付前各节的批改记录，不改变正式评分。',
      'These are the section reviews before delivery; they do not change the formal score.',
    ),
  )}</p>${rows ? `<ol class="aipm-states__list">${rows}</ol>` : ''}${restLine}`;
}

// ---- Mount ----------------------------------------------------------------------------

export type SectionStatesOptions = {
  client: Pick<AipmClient, 'sectionReviews'> | null | undefined;
  submission: Pick<SubmissionV2, 'products'> & Partial<Pick<SubmissionV2, 'id' | 'version'>>;
  prdId: string | null | undefined;
  language: Language;
  openReview: (step: StepId, reviewRef: ObjectRef) => void;
};

type Cached = { states: SectionState[]; at: number; running: boolean };
const cache = new Map<string, Cached>();
const pending = new Map<string, Promise<Cached>>();
/** Reviews whose model part is still running may still change their status; read again after this. */
const RUNNING_REREAD_MS = 3000;

type Host = Pick<HTMLElement, 'innerHTML' | 'hidden' | 'addEventListener' | 'setAttribute'> & {
  isConnected?: boolean;
  dataset: DOMStringMap;
  classList?: Pick<DOMTokenList, 'add'>;
};
const statesOf = new WeakMap<Host, { states: SectionState[]; openReview: SectionStatesOptions['openReview'] }>();

function draw(el: Host, states: SectionState[], options: SectionStatesOptions, arriving: boolean) {
  el.classList?.add('aipm-states');
  el.setAttribute('aria-labelledby', 'aipm-states-title');
  el.innerHTML = sectionStatesHtml(states, options.language);
  el.hidden = false;
  el.dataset.arriving = arriving ? 'true' : 'false';
  if (el.dataset.statesBound === 'true') return;
  el.dataset.statesBound = 'true';
  el.addEventListener('click', (event) => {
    const button = (event.target as Element | null)?.closest?.('[data-states-step]') as HTMLElement | null;
    const step = button?.dataset.statesStep as StepId | undefined;
    const current = statesOf.get(el);
    const ref = current?.states.find((s) => s.step === step)?.open;
    if (step && ref) current?.openReview(step, ref);
  });
}

/** Fills `el` with the section, or leaves it hidden when the read fails or nothing applies.
 * Safe to call on every render: a delivered submission's reviews are read once. */
export async function mountSectionStates(el: Host, options: SectionStatesOptions): Promise<void> {
  const version = deliveredVersion(options.submission, options.prdId ?? null);
  const hide = () => {
    el.hidden = true;
    el.innerHTML = '';
  };
  if (!options.client || version === null) return hide();
  const key = `${options.submission.id ?? ''}@${options.submission.version ?? ''}:${options.prdId}:${version}`;
  const known = cache.get(key);
  if (known) {
    statesOf.set(el, { states: known.states, openReview: options.openReview });
    draw(el, known.states, options, false);
    if (!known.running || Date.now() - known.at < RUNNING_REREAD_MS) return;
  } else hide();
  let read = pending.get(key);
  if (!read) {
    const client = options.client;
    read = readAllReviews(client).then((items) => ({
      states: sectionStates(items, version),
      at: Date.now(),
      running: items.some((i) => i.review.model_status === 'running'),
    }));
    pending.set(key, read);
  }
  try {
    const next = await read;
    cache.set(key, next);
    if (el.isConnected === false) return;
    statesOf.set(el, { states: next.states, openReview: options.openReview });
    draw(el, next.states, options, !known);
  } catch {
    // The section is an annotation; a failed read leaves the result page as it was.
    if (!known) hide();
  } finally {
    pending.delete(key);
  }
}

/** Tests only. */
export const resetSectionStatesCache = () => {
  cache.clear();
  pending.clear();
};
