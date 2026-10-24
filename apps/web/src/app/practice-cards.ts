/** Optional practice suggestions after feedback: what the suggested situations all revisit is
 * stated once, and each card says only why that situation is worth practising (the condition
 * it changes and what it checks that the others do not). Suggestions are shown as recorded. */
import { T, locale, type Locale } from './i18n';
import './practice-cards.css';

export type PracticeOption = {
  id: string;
  title: string;
  reason?: string;
  basis?: readonly { criterion: string }[];
  /** The suggested practice's work language, as the server lists it. */
  work_language?: string;
};
export type PracticeCatalogEntry = { id: string; criteria?: readonly string[] };
export type PracticeCard = {
  id: string;
  title: string;
  /** Set only when the suggestions give different reasons. */
  reason: string;
  /** The condition the situation changes: world text, in the practice's work language. */
  change: string;
  /** That work language; the card's title (from the server) is in it too. */
  language: Locale | null;
  focus: string[];
};
export type PracticeCards = { reason: string; shared: string[]; cards: PracticeCard[] };

const workLanguage = (value: unknown): Locale | null =>
  value === 'zh' || value === 'en' ? value : null;

export function practiceCards(
  options: readonly PracticeOption[],
  catalog: readonly PracticeCatalogEntry[],
  names: Readonly<Record<string, string>>,
  change: (optionId: string, language: Locale | null) => string,
): PracticeCards {
  const findings = (option: PracticeOption) => (option.basis ?? []).map((row) => row.criterion);
  const criteria = (option: PracticeOption) =>
    catalog.find((entry) => entry.id === option.id)?.criteria ?? [];
  const shared = options.length
    ? findings(options[0]).filter((criterion) =>
        options.every((option) => findings(option).includes(criterion)),
      )
    : [];
  const reasons = [...new Set(options.map((option) => option.reason ?? ''))];
  const reason = reasons.length === 1 ? reasons[0] : '';
  const name = (criterion: string) => names[criterion] ?? criterion;
  return {
    reason,
    shared: shared.map(name),
    cards: options.map((option) => {
      const others = options.filter((other) => other !== option).flatMap(criteria);
      const own = [
        ...findings(option),
        ...criteria(option).filter((criterion) => !others.includes(criterion)),
      ].filter((criterion) => !shared.includes(criterion));
      const language = workLanguage(option.work_language);
      return {
        id: option.id,
        title: option.title,
        reason: reason ? '' : (option.reason ?? ''),
        change: change(option.id, language),
        language,
        focus: [...new Set(own)].map(name),
      };
    }),
  };
}

/** Criterion names inside a sentence: corner brackets in Chinese, single quotes in English (the
 * same marks the manager's revision note uses), so names that contain "and" stay readable. */
function namesList(names: readonly string[]): string {
  if (locale() !== 'en') return names.map((n) => `「${n}」`).join('、');
  const quoted = names.map((n) => `‘${n}’`);
  return quoted.length < 2
    ? quoted.join('')
    : `${quoted.slice(0, -1).join(', ')} and ${quoted[quoted.length - 1]}`;
}

/** The one line above the cards: "Optional. Both revisit ‘…’." — what every suggestion revisits,
 * said once. Empty when nothing is suggested. */
export function practiceSharedLine(view: PracticeCards): string {
  const n = view.cards.length;
  if (!n) return '';
  if (!view.shared.length) return T('可选。', 'Optional.');
  const list = namesList(view.shared);
  if (n === 1) return T(`可选。这个情境会再看${list}。`, `Optional. This situation revisits ${list}.`);
  if (n === 2) return T(`可选。两个情境都会再看${list}。`, `Optional. Both revisit ${list}.`);
  return T(`可选。这 ${n} 个情境都会再看${list}。`, `Optional. All ${n} revisit ${list}.`);
}

/** A changed condition as a sentence of its own, in the language it is written in. */
export function changeSentence(change: string, language: Locale | null): string {
  if (!change) return '';
  return change + ((language ?? locale()) === 'en' ? '.' : '。');
}

/** One card's line: "Launch moves from day 7 to day 5. Also checks ‘Resources and timing’." The
 * change is world text in the card's work language; "also checks" is a label in the interface
 * language. Two Chinese sentences sit side by side; any English one is set off by a space. */
export function practiceCardLine(card: PracticeCard): string {
  const change = changeSentence(card.change, card.language);
  const focus = card.focus.length
    ? T(`也会看${namesList(card.focus)}。`, `Also checks ${namesList(card.focus)}.`)
    : '';
  const bothChinese = (card.language ?? locale()) === 'zh' && locale() === 'zh';
  return [change, focus].filter(Boolean).join(bothChinese ? '' : ' ');
}
