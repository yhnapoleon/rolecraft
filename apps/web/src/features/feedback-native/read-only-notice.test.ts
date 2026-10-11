import { describe, expect, it } from 'vitest';
import { practiceUnavailableText, readOnlyNoticeText, sealReadOnly } from './read-only-notice';

type FakeControl = { disabled: boolean; title: string };

function group(controls: FakeControl[]) {
  const appended: { className?: string; textContent?: string; dataset: Record<string, string> }[] =
    [];
  return {
    appended,
    controls,
    querySelectorAll: () => controls,
    querySelector: (selector: string) =>
      selector === '[data-read-only-reason]' ? (appended[0] ?? null) : null,
    append: (node: (typeof appended)[number]) => appended.push(node),
    ownerDocument: { createElement: () => ({ dataset: {} }) },
  };
}

function fixture() {
  const response = group([
    { disabled: false, title: '' },
    { disabled: false, title: '' },
  ]);
  const revisions = group([{ disabled: false, title: '' }]);
  const notice = {
    textContent: '本次提交已保存，可以看反馈、提出异议或开始修订。',
    dataset: {} as Record<string, string>,
  };
  const reports = { querySelectorAll: () => [response] };
  return { response, revisions, notice, reports };
}

describe('read-only session wording', () => {
  it('names the sealed state in both languages', () => {
    expect(readOnlyNoticeText('zh')).toBe('这个会话已按原评价标准封存，可以查看反馈，不能再修改。');
    expect(readOnlyNoticeText('en')).toBe(
      'This session is sealed on its original rubric; feedback can be read but not changed.',
    );
  });

  it('never shows a practice error code', () => {
    expect(practiceUnavailableText(true, 'zh')).toBe('这个会话已切换为只读，补练请从新会话开始。');
    expect(practiceUnavailableText(true, 'en')).toBe(
      'This session is now read-only; start optional practice from a new session.',
    );
    expect(practiceUnavailableText(false, 'zh')).toBe('暂时读不到补练建议。');
    expect(practiceUnavailableText(false, 'en')).toBe(
      'Optional practice is temporarily unavailable.',
    );
    for (const readOnly of [true, false])
      for (const language of ['zh', 'en'] as const)
        expect(practiceUnavailableText(readOnly, language)).not.toMatch(/unavailable:|_/);
  });
});

describe('sealing the feedback controls', () => {
  it('replaces the status line and disables challenge and revision controls with the reason', () => {
    const f = fixture();
    const nodes = { notice: f.notice, reports: f.reports, revisions: f.revisions };
    sealReadOnly(nodes as never, true, 'en');
    sealReadOnly(nodes as never, true, 'en');
    const reason =
      'This session is sealed on its original rubric; feedback can be read but not changed.';
    expect(f.notice.textContent).toBe(reason);
    expect(f.notice.dataset.readOnly).toBe('true');
    for (const control of [...f.response.controls, ...f.revisions.controls])
      expect(control).toEqual({ disabled: true, title: reason });
    // Re-rendering does not stack reasons.
    expect(f.response.appended.map((n) => n.textContent)).toEqual([reason]);
    expect(f.revisions.appended.map((n) => n.dataset.readOnlyReason)).toEqual(['true']);
  });

  it('leaves an active session untouched', () => {
    const f = fixture();
    sealReadOnly(
      { notice: f.notice, reports: f.reports, revisions: f.revisions } as never,
      false,
      'zh',
    );
    expect(f.notice.textContent).toBe('本次提交已保存，可以看反馈、提出异议或开始修订。');
    expect(f.notice.dataset.readOnly).toBeUndefined();
    expect(f.response.controls.every((c) => !c.disabled)).toBe(true);
    expect(f.response.appended).toEqual([]);
  });
});
