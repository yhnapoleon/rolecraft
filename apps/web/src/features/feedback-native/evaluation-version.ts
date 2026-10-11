/** Which rubric produced a saved report. Read only from the stored provenance; never inferred. */
import { feedbackText, type FeedbackLanguage } from './localization';

type ReportProvenance = { id: string; provenance?: { evaluation_version?: string } | null };

/** Registered evaluation versions and their learner-facing names. */
const EVALUATION_VERSION_LABELS: Record<string, [zh: string, en: string]> = {
  'feedback-rubric-v2-final.1': [
    '评价标准：rubric-v2 定稿（2026-10-09）',
    'Rubric: rubric-v2 final (2026-10-09)',
  ],
  'feedback-rubric-v2-c2.1': [
    '评价标准：rubric-v2 候选 2（定稿前）',
    'Rubric: rubric-v2 candidate 2 (pre-final)',
  ],
};

export function evaluationVersionText(
  version: string | undefined,
  language: FeedbackLanguage,
): string {
  if (!version)
    return feedbackText(language, '评价标准版本：未记录', 'Rubric version: not recorded');
  const known = EVALUATION_VERSION_LABELS[version];
  return known
    ? feedbackText(language, ...known)
    : feedbackText(language, `评价标准：${version}`, `Rubric: ${version}`);
}

export function evaluationVersionLine(
  doc: Document,
  report: ReportProvenance,
  language: FeedbackLanguage,
): HTMLElement {
  const version = report.provenance?.evaluation_version;
  const line = doc.createElement('p');
  line.className = 'muted';
  line.dataset.rubricVersion = version ?? 'not_recorded';
  line.textContent = evaluationVersionText(version, language);
  return line;
}
