/** Optional practice suggestions after feedback: what the suggested situations all revisit is
 * stated once, and each card says only why that situation is worth practising (the condition
 * it changes and what it checks that the others do not). Suggestions are shown as recorded. */
import { T } from './i18n';
import './practice-cards.css';

export type PracticeOption = {
  id: string;
  title: string;
  reason?: string;
  basis?: readonly { criterion: string }[];
};
export type PracticeCatalogEntry = { id: string; criteria?: readonly string[] };
export type PracticeCard = {
  id: string;
  title: string;
  /** Set only when the suggestions give different reasons. */
  reason: string;
  change: string;
  focus: string[];
};
export type PracticeCards = { reason: string; shared: string[]; cards: PracticeCard[] };

export function practiceCards(
  options: readonly PracticeOption[],
  catalog: readonly PracticeCatalogEntry[],
  names: Readonly<Record<string, string>>,
  change: (optionId: string) => string,
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
      return {
        id: option.id,
        title: option.title,
        reason: reason ? '' : (option.reason ?? ''),
        change: change(option.id),
        focus: [...new Set(own)].map(name),
      };
    }),
  };
}

/** "Each of these situations revisits: …" — empty when nothing is shared. */
export function practiceSharedLine(view: PracticeCards): string {
  if (!view.shared.length) return '';
  return (
    (view.cards.length > 1
      ? T('这些情境都会再核对：', 'Each of these situations revisits: ')
      : T('这个情境会再核对：', 'This situation revisits: ')) + view.shared.join(T('、', ', '))
  );
}

/** "What changes: … · Also checks: …" for one card. */
export function practiceCardLine(card: PracticeCard): string {
  return [
    card.change ? T('改变的条件：', 'What changes: ') + card.change : '',
    card.focus.length ? T('另外核对：', 'Also checks: ') + card.focus.join(T('、', ', ')) : '',
  ]
    .filter(Boolean)
    .join(' · ');
}
