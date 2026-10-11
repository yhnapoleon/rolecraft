/** Sessions bound to a package that is no longer installed are read-only on their original
 * rubric. Say so in plain words; never show a raw server error code to the learner. */
import { feedbackText, type FeedbackLanguage } from './localization';

declare module './index' {
  interface FeedbackNativeState {
    /** Server-confirmed: the session's package is no longer installed; writes are refused. */
    readOnly?: boolean;
  }
}

const COPY = {
  sealed: [
    '这个会话已按原评价标准封存，可以查看反馈，不能再修改。',
    'This session is sealed on its original rubric; feedback can be read but not changed.',
  ],
  practiceReadOnly: [
    '这个会话已切换为只读，补练请从新会话开始。',
    'This session is now read-only; start optional practice from a new session.',
  ],
  practiceUnavailable: ['暂时读不到补练建议。', 'Optional practice is temporarily unavailable.'],
} satisfies Record<string, [zh: string, en: string]>;

export function readOnlyNoticeText(language: FeedbackLanguage): string {
  return feedbackText(language, ...COPY.sealed);
}

/** The practice panel's message when its read failed; the failure code is never shown. */
export function practiceUnavailableText(readOnly: boolean, language: FeedbackLanguage): string {
  return feedbackText(language, ...(readOnly ? COPY.practiceReadOnly : COPY.practiceUnavailable));
}

type Control = { disabled: boolean; title: string };
type Group = Pick<HTMLElement, 'querySelectorAll' | 'querySelector' | 'append' | 'ownerDocument'>;

/** Replace the status line and disable challenge and revision controls, stating the reason.
 * Idempotent: the feedback panel re-renders on every state change. */
export function sealReadOnly(
  nodes: { notice: HTMLElement; reports: Pick<HTMLElement, 'querySelectorAll'>; revisions: Group },
  readOnly: boolean,
  language: FeedbackLanguage,
): void {
  if (!readOnly) {
    delete nodes.notice.dataset.readOnly;
    return;
  }
  const reason = readOnlyNoticeText(language);
  nodes.notice.textContent = reason;
  nodes.notice.dataset.readOnly = 'true';
  const groups: Group[] = [
    ...(nodes.reports.querySelectorAll('details[data-response-id]') as unknown as Group[]),
    nodes.revisions,
  ];
  for (const group of groups) {
    for (const control of group.querySelectorAll(
      'button, textarea, input, select',
    ) as unknown as Iterable<Control>) {
      control.disabled = true;
      control.title = reason;
    }
    if (!group.querySelector('[data-read-only-reason]')) {
      const note = group.ownerDocument.createElement('p');
      note.className = 'muted';
      note.dataset.readOnlyReason = 'true';
      note.textContent = reason;
      group.append(note);
    }
  }
}
