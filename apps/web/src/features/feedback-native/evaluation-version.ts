/** Which rubric produced a saved report. Read only from the stored provenance; never inferred.
 * The learner's feedback keeps it as a hidden record; "⋯ → About this workspace" shows it. */
import { noteAboutFact } from '../../app/about-facts';
import { feedbackText, type FeedbackLanguage } from './localization';

type ReportProvenance = {
  id: string;
  provenance?: { evaluation_version?: string } | null;
  subject?: { session_id?: string } | null;
};

/** Registered evaluation versions and their names. */
const EVALUATION_VERSION_NAMES: Record<string, [zh: string, en: string]> = {
  'feedback-rubric-v2-final.1': ['rubric-v2 定稿（2026-10-09）', 'rubric-v2 final (2026-10-09)'],
  'feedback-rubric-v2-c2.1': ['rubric-v2 候选 2（定稿前）', 'rubric-v2 candidate 2 (pre-final)'],
};

/** The rubric's name alone, e.g. "rubric-v2 定稿（2026-10-09）"; undefined when not recorded. */
export function evaluationVersionName(
  version: string | undefined,
  language: FeedbackLanguage,
): string | undefined {
  if (!version) return undefined;
  const known = EVALUATION_VERSION_NAMES[version];
  return known ? feedbackText(language, ...known) : version;
}

export function evaluationVersionText(
  version: string | undefined,
  language: FeedbackLanguage,
): string {
  const name = evaluationVersionName(version, language);
  return name
    ? feedbackText(language, `评价标准：${name}`, `Rubric: ${name}`)
    : feedbackText(language, '评价标准版本：未记录', 'Rubric version: not recorded');
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
  // A workbench internal: kept with the report, read in "About this workspace".
  line.hidden = true;
  noteAboutFact(report.subject?.session_id, 'rubric', {
    label: feedbackText(language, '评价标准', 'Rubric'),
    value:
      evaluationVersionName(version, language) ?? feedbackText(language, '未记录', 'Not recorded'),
  });
  return line;
}
