/** The four decisions of a delivery, as paper options in the delivery panel. Names are the
 * delivery panel's own (the vocabulary every other surface follows); each carries one sentence
 * on what choosing it commits to. Radio inputs give the group its keyboard and screen-reader
 * behaviour; nothing here submits. */
import { feedbackText, type FeedbackLanguage } from './localization';
import './decision-cards.css';

export const DECISION_VALUES = ['launch', 'launch_narrow', 'defer_with_conditions', 'no_go'] as const;
export type DecisionValue = (typeof DECISION_VALUES)[number];

const COPY: Record<DecisionValue, { name: [string, string]; note: [string, string] }> = {
  launch: {
    name: ['按方案推进', 'Proceed with the proposal'],
    note: [
      '按方案里的人数和范围开放试点。',
      'Open the pilot to the people and scope in your proposal.',
    ],
  },
  launch_narrow: {
    name: ['缩小范围推进', 'Proceed with a limited scope'],
    note: [
      '先给更少的人、更窄的问题开放，其余等证据。',
      'Open to fewer people or fewer questions first; the rest waits for evidence.',
    ],
  },
  defer_with_conditions: {
    name: ['满足条件后再推进', 'Defer until conditions are met'],
    note: [
      '现在不开放，写清满足哪些条件再推进。',
      'Hold the launch and name the conditions that must be met first.',
    ],
  },
  no_go: {
    name: ['停止这项方案', 'Do not proceed with this proposal'],
    note: ['不做这个试点，并说明为什么停。', 'Stop this pilot and say why.'],
  },
};

export const isDecision = (value: string): value is DecisionValue =>
  (DECISION_VALUES as readonly string[]).includes(value);

/** A decision in words; an unknown code stays as written rather than being guessed. */
export function decisionName(value: string, language: FeedbackLanguage): string {
  return isDecision(value) ? feedbackText(language, ...COPY[value].name) : value;
}
export function decisionNote(value: DecisionValue, language: FeedbackLanguage): string {
  return feedbackText(language, ...COPY[value].note);
}

let groups = 0;

export interface DecisionCards {
  /** The group itself; its accessible name is "本次决定 / Your decision". */
  readonly element: HTMLElement;
  value: string;
  disabled: boolean;
}

/** Four paper options in one radio group. `onChange` runs on a person's choice only.
 * A hidden native select mirrors the choice for page scripts that drive the old control. */
export function mountDecisionCards(
  doc: Document,
  language: FeedbackLanguage,
  onChange: (value: string) => void,
): DecisionCards {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  const name = `decision-${++groups}`;
  const group = doc.createElement('div');
  group.className = 'decision-cards';
  group.setAttribute('role', 'radiogroup');
  group.setAttribute('aria-label', T('本次决定', 'Your decision'));
  group.dataset.decisionCards = '';
  const inputs: HTMLInputElement[] = [];
  for (const value of DECISION_VALUES) {
    const card = doc.createElement('label');
    card.className = 'decision-card';
    card.dataset.decision = value;
    const input = doc.createElement('input');
    input.type = 'radio';
    input.name = name;
    input.value = value;
    input.className = 'decision-card__input';
    const mark = doc.createElement('span');
    mark.className = 'decision-card__mark';
    mark.setAttribute('aria-hidden', 'true');
    const words = doc.createElement('span');
    words.className = 'decision-card__words';
    const title = doc.createElement('span');
    title.className = 'decision-card__name';
    title.textContent = decisionName(value, language);
    const note = doc.createElement('span');
    note.className = 'decision-card__note';
    note.textContent = decisionNote(value, language);
    words.append(title, note);
    card.append(input, mark, words);
    group.append(card);
    inputs.push(input);
  }
  const mirror = doc.createElement('select');
  mirror.hidden = true;
  mirror.tabIndex = -1;
  mirror.setAttribute('aria-hidden', 'true');
  for (const value of ['', ...DECISION_VALUES]) {
    const option = doc.createElement('option');
    option.value = value;
    option.textContent = value ? decisionName(value, language) : T('请选择本次决定', 'Choose a decision');
    mirror.append(option);
  }
  group.append(mirror);
  let current = '';
  const show = (value: string) => {
    current = isDecision(value) ? value : '';
    for (const input of inputs) {
      input.checked = input.value === current;
      input.closest('label')?.classList.toggle('is-chosen', input.checked);
    }
    mirror.value = current;
  };
  for (const input of inputs)
    input.addEventListener('change', () => {
      if (!input.checked) return;
      show(input.value);
      onChange(current);
    });
  mirror.addEventListener('change', () => {
    show(mirror.value);
    onChange(current);
  });
  return {
    element: group,
    get value() {
      return current;
    },
    set value(value: string) {
      show(value);
    },
    get disabled() {
      return inputs[0]?.disabled ?? false;
    },
    set disabled(off: boolean) {
      for (const input of inputs) input.disabled = off;
      mirror.disabled = off;
      group.classList.toggle('is-disabled', off);
      group.setAttribute('aria-disabled', String(off));
    },
  };
}
