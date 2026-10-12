import type { Report } from './index';
import { feedbackCopy, type FeedbackLanguage } from './localization';

/** Coverage of currently readable, applicable criteria; never a score. */
export function feedbackCoverageText(
  report: Report,
  legacy: Report['items'],
  language: FeedbackLanguage,
): string {
  const items = report.items.filter(
    (item) =>
      item.label !== 'NOT_APPLICABLE' &&
      (item.applicability === undefined || item.applicability === 'applicable'),
  );
  // A 0/0 ratio says nothing; say plainly that no criterion applies yet.
  if (!items.length) return feedbackCopy(language, 'coverageEmpty');
  let verified = 0;
  let model = 0;
  for (const item of items) {
    if (item.source === 'verified_rule' && item.label !== 'INSUFFICIENT') {
      verified++;
      continue;
    }
    const registered = report.model_advice?.filter((entry) => entry.criterion === item.criterion);
    const hasAdvice = registered?.length
      ? registered.every((entry) => entry.status === 'completed' && entry.label !== 'INSUFFICIENT')
      : legacy.includes(item) && item.label !== 'INSUFFICIENT';
    if (hasAdvice) model++;
  }
  // 2026-10-12 item 3: the learner sees item counts only; weighted coverage stays in reports.
  return feedbackCopy(language, 'coverageLine', {
    verified,
    total: items.length,
    model,
    pending: items.length - verified - model,
  });
}
