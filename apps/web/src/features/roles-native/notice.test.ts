import { afterEach, describe, expect, it } from 'vitest';
import { setPracticeLocale } from '../../app/i18n';
import { noticeText } from './chat-view';

describe('held reply notice', () => {
  afterEach(() => setPracticeLocale(null));

  it('names a help-review hold honestly, not as a fact check', () => {
    setPracticeLocale('zh');
    const help = noticeText('held', 'business_lead', 'role_help_unverified');
    expect(help).toContain('这次没有生成');
    expect(help).toContain('实时回复');
    expect(help).not.toContain('事实核对');
    setPracticeLocale('en');
    expect(noticeText('held', 'business_lead', 'role_help_unverified')).toContain('No live reply');
  });

  it('keeps the fact-check wording for other holds', () => {
    setPracticeLocale('zh');
    expect(noticeText('held', 'business_lead', 'role_output_blocked')).toContain('事实核对');
    expect(noticeText('held', 'business_lead')).toContain('事实核对');
  });
});
