/** Feedback first screen (063-03): counts, the recorded rule-anchored range, model state and
 * one purpose question. Stored items stay unchanged behind one disclosure; nothing here scores
 * or totals; the range is read from the record (decision 5, 2026-10-11). */
import {
  renderShortResult,
  type ShortResultStatus,
  type ShortResultView,
} from '../results-native/short-result';
import { FEEDBACK_COPY, feedbackCopy, type FeedbackLanguage } from './localization';
import { scoreRangeNotes } from './score-range';
import type { Report, ReviewRecord, SelectedProduct } from './index';
import type { ObjectRef } from '../workspace/contract-types';
import { canonicalPurpose } from '../workspace/native-v4/form-values';

type Item = Report['items'][number];
/** The rubric's own purpose stages, sent as the values the review request accepts. */
export const PURPOSE_CHOICES = [
  'exploration',
  'option',
  'test_plan',
  'commitment',
  'result',
] as const;
export type PurposeChoice = (typeof PURPOSE_CHOICES)[number];
export const isPurposeChoice = (value: string): value is PurposeChoice =>
  (PURPOSE_CHOICES as readonly string[]).includes(value);
/** Stored or typed purposes that the review stages treat as one of the choices. */
const SAME_STAGE: Readonly<Record<string, PurposeChoice>> = {
  freeform: 'exploration',
  free_form: 'exploration',
  plan: 'test_plan',
};
/** The choice a stored product purpose or a typed label (either language) stands for. */
export function purposeChoiceOf(value: string | undefined): PurposeChoice | undefined {
  const text = value?.trim();
  if (!text) return undefined;
  const code = canonicalPurpose(text);
  const stage = SAME_STAGE[code] ?? code;
  if (isPurposeChoice(stage)) return stage;
  const folded = text.toLowerCase();
  return PURPOSE_CHOICES.find((choice) =>
    (['zh', 'en'] as const).some((l) => FEEDBACK_COPY[l][choice].toLowerCase() === folded),
  );
}
/** A stored purpose in the interface language; unrecognised text stays as written. */
export function purposeName(value: string, language: FeedbackLanguage): string {
  const choice = purposeChoiceOf(value);
  return choice ? feedbackCopy(language, choice) : value;
}
/** The purpose the reviewed versions already declare, when they all agree. */
export function declaredPurpose(
  subjects: readonly ObjectRef[],
  products: readonly SelectedProduct[],
): PurposeChoice | undefined {
  const found = subjects.map((ref) =>
    purposeChoiceOf(
      products.find((p) => p.product_id === ref.object_id && p.version === ref.version)?.purpose,
    ),
  );
  return found.length && found.every((p) => p && p === found[0]) ? found[0] : undefined;
}

/** The criteria rendered one by one in the panel. */
export const ruleItems = (report: Report): Item[] =>
  report.rule_items ?? report.items.filter((item) => item.source === 'verified_rule');
/** What counting a criterion needs: its finding, its source and whether it applied. */
export type Counted = Pick<Item, 'applicability' | 'label' | 'source'>;
const inapplicable = (item: Counted) =>
  item.label === 'NOT_APPLICABLE' || item.applicability === 'not_applicable';
const undetermined = (item: Counted) =>
  item.applicability === 'undetermined' || item.applicability === 'unknown';

/** How the first screen counts one criterion: decided by a rule, still pending, or left out. */
export function feedbackClass(
  item: Counted,
): 'verified' | 'pending' | 'undetermined' | 'notApplicable' {
  if (inapplicable(item)) return 'notApplicable';
  if (undetermined(item)) return 'undetermined';
  if (item.source === 'verified_rule' && item.label !== 'INSUFFICIENT') return 'verified';
  return 'pending';
}

export function feedbackCounts(items: readonly Counted[]) {
  const counts = {
    total: items.length,
    verified: 0,
    pending: 0,
    undetermined: 0,
    notApplicable: 0,
  };
  for (const item of items) counts[feedbackClass(item)]++;
  return counts;
}

/** Every criterion waits on a purpose the backend did not recognise. */
export function purposeUnknown(report: Report, review: ReviewRecord | undefined): boolean {
  if (report.subject.kind !== 'review' || !review || purposeChoiceOf(review.purpose)) return false;
  const items = ruleItems(report);
  return items.length > 0 && items.every(undetermined);
}

const key = (refs: readonly ObjectRef[]) =>
  refs
    .map((r) => [r.session_id, r.kind, r.object_id, r.version].join(':'))
    .sort()
    .join('|');
/** A later review of the same versions that already carries a recognised purpose. */
export function laterPurpose(
  review: ReviewRecord,
  reviews: readonly ReviewRecord[],
): PurposeChoice | undefined {
  const index = reviews.findIndex((r) => r.id === review.id && r.version === review.version);
  const later = reviews
    .slice(index + 1)
    .find((r) => key(r.subjects) === key(review.subjects) && purposeChoiceOf(r.purpose));
  return purposeChoiceOf(later?.purpose);
}

export interface PurposePrompt {
  readonly name: string;
  readonly selected?: PurposeChoice;
  readonly disabled: boolean;
  readonly select: (purpose: PurposeChoice) => void;
  readonly submit: (purpose: PurposeChoice) => void;
}

export function purposePromptElement(
  doc: Document,
  language: FeedbackLanguage,
  prompt: PurposePrompt,
) {
  const T = (k: Parameters<typeof feedbackCopy>[1]) => feedbackCopy(language, k);
  const fieldset = doc.createElement('fieldset');
  fieldset.className = 'short-result__prompt';
  fieldset.dataset.purposePrompt = '';
  const legend = doc.createElement('legend');
  legend.textContent = T('purposeQuestion');
  const choices = doc.createElement('div');
  choices.className = 'short-result__choices';
  const submit = doc.createElement('button');
  submit.type = 'button';
  submit.className = 'btn';
  submit.textContent = T('purposeSubmit');
  let chosen = prompt.selected;
  submit.disabled = prompt.disabled || !chosen;
  for (const purpose of PURPOSE_CHOICES) {
    const label = doc.createElement('label');
    const input = doc.createElement('input');
    input.type = 'radio';
    input.name = prompt.name;
    input.value = purpose;
    input.checked = purpose === chosen;
    input.disabled = prompt.disabled;
    input.addEventListener('change', () => {
      chosen = purpose;
      prompt.select(purpose);
      submit.disabled = prompt.disabled;
    });
    const text = doc.createElement('span');
    text.textContent = T(purpose);
    label.append(input, text);
    choices.append(label);
  }
  submit.addEventListener('click', () => {
    if (chosen && !prompt.disabled) prompt.submit(chosen);
  });
  const note = doc.createElement('p');
  note.className = 'short-result__note';
  note.textContent = T('purposeNote');
  fieldset.append(legend, choices, submit, note);
  return fieldset;
}

export interface FeedbackShortInput {
  readonly report: Report;
  readonly language: FeedbackLanguage;
  readonly review?: ReviewRecord;
  readonly reviews?: readonly ReviewRecord[];
  /** The existing model-advice section, kept visible and unchanged. */
  readonly semantic: HTMLElement;
  /** One line per rule-checked criterion, shown before the model advice. */
  readonly lines?: Node;
  /** Existing facts, history, criteria and coverage nodes, folded unchanged. */
  readonly body: readonly Node[];
  readonly open: boolean;
  readonly onToggle: (open: boolean) => void;
  readonly prompt?: PurposePrompt;
}

export function feedbackShortResult(doc: Document, input: FeedbackShortInput): ShortResultView {
  const { report, language } = input;
  const T = (k: Parameters<typeof feedbackCopy>[1], n?: number) =>
    feedbackCopy(language, k, n === undefined ? undefined : { n });
  const counts = feedbackCounts(ruleItems(report));
  const facts = report.verified_facts?.[0]?.status;
  const statuses: ShortResultStatus[] = [];
  if (facts)
    statuses.push(
      facts === 'verified'
        ? { text: T('factsVerified'), tone: 'verified' }
        : { text: T(facts === 'partial' ? 'factsPartial' : 'factsUnknown'), tone: 'pending' },
    );
  if (counts.total) {
    statuses.push({
      text: T('verified', counts.verified),
      tone: counts.verified ? 'verified' : undefined,
    });
    if (counts.pending) statuses.push({ text: T('pending', counts.pending), tone: 'pending' });
    if (counts.undetermined)
      statuses.push({ text: T('undetermined', counts.undetermined), tone: 'pending' });
    if (counts.notApplicable)
      statuses.push({ text: T('notApplicable', counts.notApplicable), tone: 'unsupported' });
  }
  const unknown = purposeUnknown(report, input.review);
  // Once the same versions were reviewed again for a purpose, the question is answered.
  const later =
    unknown && input.review ? laterPurpose(input.review, input.reviews ?? []) : undefined;
  const actions: Node[] = [];
  if (input.lines) actions.push(input.lines);
  if (unknown && !later && input.prompt) actions.push(purposePromptElement(doc, language, input.prompt));
  actions.push(input.semantic);
  const lead = later
    ? feedbackCopy(language, 'purposeChosen', { purpose: feedbackCopy(language, later) })
    : unknown
      ? T('purposeUnknown', counts.total)
      : counts.total
        ? undefined
        : T('noItems');
  return renderShortResult(doc, {
    kind: report.subject.kind === 'review' ? 'review' : 'feedback',
    id: `${report.id}:${report.version}`,
    statusLabel: T('statusLabel'),
    statuses,
    lead,
    derivedLead: true,
    notes: scoreRangeNotes(doc, report, language),
    actions,
    more: {
      label: counts.total ? T('showItems', counts.total) : T('showRecords'),
      body: input.body,
      open: input.open,
      onToggle: input.onToggle,
    },
  });
}

/** Title line of a review card naming the purpose it was reviewed for, if known. */
export function reviewedAs(review: ReviewRecord | undefined, language: FeedbackLanguage) {
  return review && purposeChoiceOf(review.purpose)
    ? feedbackCopy(language, 'reviewedAs', { purpose: purposeName(review.purpose, language) })
    : undefined;
}
