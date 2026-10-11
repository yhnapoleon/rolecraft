/** 2026-10-11 decision 5: show the range of the rule-anchored part, never a single total;
 * model advice is never scored. The range and every weight come from the stored record
 * (FeedbackV2.score_range, written from the installed rubric file); nothing is computed here. */
import type { _RuleScoreCriterion, _RuleScoreRange } from '../../contracts-v2';
import { feedbackCopy, type FeedbackLanguage } from './localization';

type RangeReport = {
  items: readonly unknown[];
  rule_items?: readonly unknown[] | null;
  score_range?: _RuleScoreRange | null;
  read_projection?: 'partial' | null;
  provenance?: { evaluation_version?: string } | null;
};
export type ScoreRangeKind = 'range' | 'empty' | 'version' | 'unrecorded' | 'withheld';

/** Evaluation versions whose installed rubric freezes weights, so a range is recorded. */
const RANGED_VERSIONS: ReadonlySet<string> = new Set(['feedback-rubric-v2-final.1']);
const EPSILON = 1e-6;

/** Points with at most one decimal. Range ends round outward so the shown range never
 * looks tighter than the recorded one. */
export function formatPoints(value: number, rounding: 'down' | 'up' | 'nearest' = 'nearest') {
  const tenths =
    rounding === 'down'
      ? Math.floor(value * 10 + EPSILON)
      : rounding === 'up'
        ? Math.ceil(value * 10 - EPSILON)
        : Math.round(value * 10);
  return Number.isInteger(tenths / 10) ? String(tenths / 10) : (tenths / 10).toFixed(1);
}

const ends = (lower: number, upper: number) =>
  upper - lower <= EPSILON
    ? { lower: formatPoints(lower), upper: formatPoints(upper) }
    : { lower: formatPoints(lower, 'down'), upper: formatPoints(upper, 'up') };
const fullWeight = (range: _RuleScoreRange) =>
  formatPoints(range.criteria.reduce((sum, row) => sum + row.weight, 0));

/** The first-screen line for one report, or nothing when it has no criteria at all. */
export function scoreRangeLine(
  report: RangeReport,
  language: FeedbackLanguage,
): { kind: ScoreRangeKind; text: string; note?: string } | undefined {
  if (!(report.rule_items ?? report.items).length) return undefined;
  const range = report.score_range;
  if (range) {
    if (range.lower == null || range.upper == null || range.denominator <= EPSILON)
      return { kind: 'empty', text: feedbackCopy(language, 'rangeEmpty') };
    const full = fullWeight(range);
    const denominator = formatPoints(range.denominator);
    const text = feedbackCopy(language, denominator === full ? 'rangeFull' : 'rangePart', {
      ...ends(range.lower, range.upper),
      denominator,
      full,
    });
    return { kind: 'range', text, note: feedbackCopy(language, 'rangeNote') };
  }
  if (report.read_projection === 'partial')
    return { kind: 'withheld', text: feedbackCopy(language, 'rangeWithheld') };
  return RANGED_VERSIONS.has(report.provenance?.evaluation_version ?? '')
    ? { kind: 'unrecorded', text: feedbackCopy(language, 'rangeUnrecorded') }
    : { kind: 'version', text: feedbackCopy(language, 'rangeVersion') };
}

/** Notes for the 124 short-result frame: the range (or why there is none) and its caveat. */
export function scoreRangeNotes(
  doc: Document,
  report: RangeReport,
  language: FeedbackLanguage,
): (string | Node)[] {
  const line = scoreRangeLine(report, language);
  if (!line) return [];
  const node = doc.createElement('span');
  node.dataset.scoreRange = line.kind;
  node.textContent = line.text;
  return line.note ? [node, line.note] : [node];
}

/** One criterion's weight share and how the rules anchor it; points only for rule results. */
export function criterionWeightText(
  report: Pick<RangeReport, 'score_range'>,
  criterion: string,
  language: FeedbackLanguage,
): string | undefined {
  const range = report.score_range;
  const row: _RuleScoreCriterion | undefined = range?.criteria.find(
    (entry) => entry.criterion === criterion,
  );
  if (!range || !row) return undefined;
  const values = { weight: formatPoints(row.weight), full: fullWeight(range) };
  if (row.status === 'anchored' && row.lower != null)
    return feedbackCopy(language, 'weightAnchored', { ...values, points: formatPoints(row.lower) });
  if (row.status === 'bounded' && row.lower != null && row.upper != null)
    return feedbackCopy(language, 'weightBounded', { ...values, ...ends(row.lower, row.upper) });
  if (row.status === 'not_applicable') return feedbackCopy(language, 'weightNotApplicable', values);
  return feedbackCopy(
    language,
    row.status === 'undetermined' ? 'weightUndetermined' : 'weightPending',
    values,
  );
}
