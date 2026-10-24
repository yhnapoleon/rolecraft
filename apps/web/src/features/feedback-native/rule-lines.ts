/** Feedback first screen: one line per rule-checked criterion (conclusion and one fact), a
 * premise shared by several criteria stated once, and the criteria still waiting named on one
 * line (the status row above already counts them and the inapplicable ones). Stored explanations are never rewritten: a recorded explanation
 * is "note\nfinding\nobservations", and its own lines are only regrouped for reading. */
import { feedbackText, type FeedbackLanguage } from './localization';
import { feedbackClass } from './short-summary';
import type { Report } from './index';
import './rule-lines.css';

type Item = Report['items'][number];
export type RuleMark = 'met' | 'partial' | 'not_met';
export type RuleLine = {
  criterion: string;
  name: string;
  mark: RuleMark;
  conclusion: string;
  fact: string;
};
export type RuleLinesView = {
  /** Notes recorded identically at the start of several criteria. */
  premises: string[];
  lines: RuleLine[];
  /** Criteria still waiting for verification, by name. */
  waiting: string[];
};

const linesOf = (explanation: string) =>
  explanation
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);

/** First lines recorded by at least two criteria, in the order they first appear. */
function sharedPremises(items: readonly Item[]): string[] {
  const seen = new Map<string, number>();
  for (const item of items) {
    const lines = linesOf(item.explanation);
    if (lines.length > 1) seen.set(lines[0], (seen.get(lines[0]) ?? 0) + 1);
  }
  return [...seen].filter(([, count]) => count > 1).map(([line]) => line);
}

export function ruleLines(
  items: readonly Item[],
  names: Readonly<Record<string, string>>,
  language: FeedbackLanguage,
  /** A recorded fact about this criterion that takes priority over the explanation's finding. */
  factOf: (item: Item) => string | undefined = () => undefined,
): RuleLinesView {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  const labels: Record<string, string> = {
    MET: T('满足', 'Met'),
    PARTIAL: T('部分满足', 'Partially met'),
    NOT_MET: T('未满足', 'Not met'),
  };
  const name = (item: Item) => names[item.criterion] ?? T('具体反馈项', 'Feedback criterion');
  const premises = sharedPremises(items);
  const view: RuleLinesView = { premises, lines: [], waiting: [] };
  for (const item of items) {
    // The same classes the status row counts (short-summary.ts).
    const kind = feedbackClass(item);
    if (kind === 'notApplicable') continue;
    if (kind !== 'verified') view.waiting.push(name(item));
    else {
      // Without a recorded bound, the rule's finding is both ends of it.
      const bound = (item.rule_bound as { lower: string; upper: string } | null | undefined) ?? {
        lower: item.label,
        upper: item.label,
      };
      const lines = linesOf(item.explanation);
      view.lines.push({
        criterion: item.criterion,
        name: name(item),
        mark:
          bound.lower !== bound.upper
            ? 'partial'
            : bound.lower === 'MET'
              ? 'met'
              : bound.lower === 'NOT_MET'
                ? 'not_met'
                : 'partial',
        // A range is read out as words: "between partially met and met", never "A—B".
        conclusion:
          bound.lower === bound.upper
            ? (labels[bound.lower] ?? bound.lower)
            : T(
                `介于${labels[bound.lower] ?? bound.lower}和${labels[bound.upper] ?? bound.upper}之间`,
                `Between ${(labels[bound.lower] ?? bound.lower).toLowerCase()} and ${(labels[bound.upper] ?? bound.upper).toLowerCase()}`,
              ),
        fact: factOf(item) ?? lines[1] ?? lines[0] ?? '',
      });
    }
  }
  return view;
}

/** The recorded explanation without a premise already stated once at the top. */
export function itemDetail(item: Item, premises: readonly string[]): string {
  const lines = linesOf(item.explanation);
  return lines.length > 1 && premises.includes(lines[0])
    ? lines.slice(1).join('\n')
    : item.explanation;
}

const MARKS: Record<RuleMark, string> = { met: '✓', partial: '◐', not_met: '✗' };

export function renderRuleLines(
  doc: Document,
  view: RuleLinesView,
  language: FeedbackLanguage,
): HTMLElement | undefined {
  if (!view.lines.length) return undefined;
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '', className = '') => {
    const node = doc.createElement(tag);
    node.textContent = text;
    node.className = className;
    return node;
  };
  const root = el('div', '', 'rule-lines');
  root.dataset.ruleLines = '';
  for (const premise of view.premises)
    root.append(el('p', T('共同前提：', 'Shared premise: ') + premise, 'rule-lines__note'));
  const list = el('ul', '', 'rule-lines__items');
  list.setAttribute('aria-label', T('规则核实的各项', 'Rule-checked criteria'));
  for (const line of view.lines) {
    const row = el('li', '', 'rule-lines__item');
    row.dataset.mark = line.mark;
    const mark = el('span', MARKS[line.mark], 'rule-lines__mark');
    mark.setAttribute('aria-hidden', 'true');
    const words = el('span', '', 'rule-lines__text');
    words.append(
      el('span', line.conclusion + T('：', ': '), 'sr-only'),
      el('b', line.name),
      ` · ${line.fact}`,
    );
    row.append(mark, words);
    row.title = line.conclusion;
    list.append(row);
  }
  root.append(list);
  if (view.waiting.length)
    root.append(
      el(
        'p',
        T('待核验：', 'Awaiting verification: ') + view.waiting.join(T('、', ', ')),
        'rule-lines__note',
      ),
    );
  return root;
}
