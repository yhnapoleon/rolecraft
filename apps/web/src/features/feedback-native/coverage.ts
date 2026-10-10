import type { Report } from './index';
import { feedbackText, type FeedbackLanguage } from './localization';

/** Coverage of currently readable, applicable criteria; never a score. */
export function feedbackCoverageText(
  report: Report,
  legacy: Report['items'],
  language: FeedbackLanguage,
): string {
  const T = (zh: string, en: string) => feedbackText(language, zh, en);
  const items = report.items.filter(
    (item) =>
      item.label !== 'NOT_APPLICABLE' &&
      (item.applicability === undefined || item.applicability === 'applicable'),
  );
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
  const ratio = (count: number): string => {
    const percent = items.length ? `${Math.round((count / items.length) * 100)}%` : '—';
    return `${count}/${items.length}${T(`（${percent}）`, ` (${percent})`)}`;
  };
  return (
    T('规则核实：', 'Verified by rules: ') +
    ratio(verified) +
    ' · ' +
    T('模型建议：', 'Model advice: ') +
    ratio(model) +
    ' · ' +
    T('待核验：', 'Pending verification: ') +
    ratio(items.length - verified - model)
  );
}
