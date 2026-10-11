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
  failedSealed: [
    '这次反馈没有完成，原提交仍保留；会话已封存，不能重新请求。',
    'This feedback did not complete. The submission is retained; the session is sealed, so feedback cannot be requested again.',
  ],
} satisfies Record<string, [zh: string, en: string]>;

export function readOnlyNoticeText(language: FeedbackLanguage): string {
  return feedbackText(language, ...COPY.sealed);
}

/** Practice reads on a sealed session fail because its package is no longer running. */
const SEALED_PRACTICE_CODES = new Set([
  'practice_language_unavailable',
  'practice_language_mismatch',
  'scenario_read_only',
]);

export function isSealedPracticeError(code: unknown): boolean {
  return typeof code === 'string' && SEALED_PRACTICE_CODES.has(code);
}

/** The practice panel's message when its read failed; the failure code is never shown. */
export function practiceUnavailableText(readOnly: boolean, language: FeedbackLanguage): string {
  return feedbackText(language, ...(readOnly ? COPY.practiceReadOnly : COPY.practiceUnavailable));
}

type Control = { disabled: boolean; title: string };
type Group = Pick<HTMLElement, 'querySelectorAll' | 'querySelector' | 'append' | 'ownerDocument'>;

/** Replace the status line and disable challenge, revision and re-request controls, stating
 * the reason. Idempotent: the feedback panel re-renders on every state change. */
export function sealReadOnly(
  nodes: {
    notice: HTMLElement;
    reports: Pick<HTMLElement, 'querySelectorAll'>;
    revisions: Group;
    /** "Feedback did not complete … you can request it again" and its button. */
    failedNote?: HTMLElement;
    retry?: Control;
  },
  readOnly: boolean,
  language: FeedbackLanguage,
): void {
  const { failedNote, retry } = nodes;
  if (!readOnly) {
    delete nodes.notice.dataset.readOnly;
    if (failedNote?.dataset.unsealedText !== undefined) {
      failedNote.textContent = failedNote.dataset.unsealedText;
      delete failedNote.dataset.unsealedText;
    }
    return;
  }
  const reason = readOnlyNoticeText(language);
  nodes.notice.textContent = reason;
  nodes.notice.dataset.readOnly = 'true';
  // A sealed session cannot request feedback again; never invite it.
  const failed = feedbackText(language, ...COPY.failedSealed);
  if (failedNote) {
    if (failedNote.dataset.unsealedText === undefined)
      failedNote.dataset.unsealedText = failedNote.textContent ?? '';
    failedNote.textContent = failed;
  }
  if (retry) {
    retry.disabled = true;
    retry.title = failed;
  }
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
