/** "By colleague": the same criteria, regrouped by whose question each one is. Nothing is
 * generated and no model is called; the rows are the review's own rows in another order. The
 * table is the redesign plan's (§4.4), keyed by the rubric criterion ids of
 * `features/feedback-native/criteria.ts`, never by their names. */
import type { ItemRow, ItemsView } from '../../features/feedback-native/feedback-items';
import { feedbackText, type FeedbackLanguage } from '../../features/feedback-native/localization';

export type Colleague = 'manager' | 'business' | 'technical';

export const COLLEAGUE_CRITERIA: Readonly<Record<Colleague, readonly string[]>> = {
  // Grace: goals, resources, trade-offs.
  manager: ['R3.capacity', 'R3.resources', 'R1.metrics', 'R6.operations', 'R6.alternatives'],
  // Chen: users, business, facts.
  business: ['R1.target', 'R2.unknowns', 'R2.support'],
  // Daniel: tests, configuration, failures, consistency.
  technical: [
    'R4.functional_tests',
    'R2.failure_analysis',
    'R4.staleness_test',
    'R5.adjustment',
    'R5.impact',
    'R6.consistency',
  ],
};

const OWNER = new Map(
  (Object.entries(COLLEAGUE_CRITERIA) as [Colleague, readonly string[]][]).flatMap(([who, ids]) =>
    ids.map((id) => [id, who] as const),
  ),
);

export const colleagueOf = (criterion: string): Colleague | null => OWNER.get(criterion) ?? null;

export interface ColleagueColumn {
  who: Colleague;
  name: string;
  /** What this colleague looks after, in a few words. */
  remit: string;
  /** Rows in the page's order: didn't hold up, can't tell yet, holds up. */
  rows: ItemRow[];
  counts: { unmet: number; unknown: number; met: number };
}

export function colleagueRemit(who: Colleague, language: FeedbackLanguage): string {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  return {
    manager: T('目标、资源、取舍', 'Goals, resources, trade-offs'),
    business: T('用户、业务、事实', 'Users, business, facts'),
    technical: T('测试、配置、失败、一致性', 'Tests, configuration, failures, consistency'),
  }[who];
}

export const COLLEAGUE_NAMES: Readonly<Record<Colleague, string>> = {
  manager: 'Grace',
  business: 'Chen',
  technical: 'Daniel',
};

/** Three columns, Grace · Chen · Daniel, with whatever does not apply left out. A criterion the
 * table does not name (an older rubric) goes to nobody and stays visible under "By status". */
export function byColleague(view: ItemsView, language: FeedbackLanguage): ColleagueColumn[] {
  const ordered = [...view.unmet, ...view.unknown, ...view.met];
  return (Object.keys(COLLEAGUE_CRITERIA) as Colleague[]).map((who) => {
    const rows = ordered.filter((row) => colleagueOf(row.criterion) === who);
    return {
      who,
      name: COLLEAGUE_NAMES[who],
      remit: colleagueRemit(who, language),
      rows,
      counts: {
        unmet: rows.filter((row) => row.mark === 'unmet').length,
        unknown: rows.filter((row) => row.mark === 'unknown').length,
        met: rows.filter((row) => row.mark === 'met').length,
      },
    };
  });
}

/** Rows no colleague owns; shown in a fourth, plain column so nothing silently disappears. */
export function unowned(view: ItemsView): ItemRow[] {
  return [...view.unmet, ...view.unknown, ...view.met].filter(
    (row) => colleagueOf(row.criterion) === null,
  );
}
