/** Feedback first screen (063-03): counts, model state and one purpose question.
 * Stored items stay unchanged behind one disclosure; nothing here scores or totals. */
import {
  renderShortResult,
  type ShortResultStatus,
  type ShortResultView,
} from '../results-native/short-result';
import { feedbackCopy, type FeedbackLanguage } from './localization';
import type { Report, ReviewRecord } from './index';
import type { ObjectRef } from '../workspace/contract-types';

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

/** The criteria rendered one by one in the panel. */
export const ruleItems = (report: Report): Item[] =>
  report.rule_items ?? report.items.filter((item) => item.source === 'verified_rule');
const inapplicable = (item: Item) =>
  item.label === 'NOT_APPLICABLE' || item.applicability === 'not_applicable';
const undetermined = (item: Item) =>
  item.applicability === 'undetermined' || item.applicability === 'unknown';

export function feedbackCounts(items: readonly Item[]) {
  const counts = {
    total: items.length,
    verified: 0,
    pending: 0,
    undetermined: 0,
    notApplicable: 0,
  };
  for (const item of items) {
    if (inapplicable(item)) counts.notApplicable++;
    else if (undetermined(item)) counts.undetermined++;
    else if (item.source === 'verified_rule' && item.label !== 'INSUFFICIENT') counts.verified++;
    else counts.pending++;
  }
  return counts;
}

/** Every criterion waits on a purpose the backend did not recognise. */
export function purposeUnknown(report: Report, review: ReviewRecord | undefined): boolean {
  if (report.subject.kind !== 'review' || !review || isPurposeChoice(review.purpose)) return false;
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
    .find((r) => key(r.subjects) === key(review.subjects) && isPurposeChoice(r.purpose));
  return later && isPurposeChoice(later.purpose) ? later.purpose : undefined;
}

export interface PurposePrompt {
  readonly name: string;
  readonly selected?: PurposeChoice;
  readonly disabled: boolean;
  readonly select: (purpose: PurposeChoice) => void;
  readonly submit: (purpose: PurposeChoice) => void;
}

function promptElement(doc: Document, language: FeedbackLanguage, prompt: PurposePrompt) {
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
  const actions: Node[] = [];
  if (unknown && input.review) {
    const later = laterPurpose(input.review, input.reviews ?? []);
    if (later) {
      const note = doc.createElement('p');
      note.className = 'short-result__note';
      note.textContent = feedbackCopy(language, 'purposeChosen', {
        purpose: feedbackCopy(language, later),
      });
      actions.push(note);
    } else if (input.prompt) actions.push(promptElement(doc, language, input.prompt));
  }
  actions.push(input.semantic);
  return renderShortResult(doc, {
    kind: report.subject.kind === 'review' ? 'review' : 'feedback',
    id: `${report.id}:${report.version}`,
    statusLabel: T('statusLabel'),
    statuses,
    lead: unknown ? T('purposeUnknown', counts.total) : counts.total ? undefined : T('noItems'),
    derivedLead: true,
    actions,
    more: {
      label: counts.total ? T('showItems', counts.total) : T('showRecords'),
      body: input.body,
      open: input.open,
      onToggle: input.onToggle,
    },
  });
}
