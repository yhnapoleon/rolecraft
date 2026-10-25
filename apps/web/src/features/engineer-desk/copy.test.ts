import { afterEach, describe, expect, it } from 'vitest';
import { setPreference } from '../../app/i18n';
import { engineerCareerCardHtml } from './career-card';
import { ENGINEER_ERROR_CODES, engineerErrorText, valueText } from './copy';

afterEach(() => setPreference('zh'));

describe('engineer desk · error codes in plain words', () => {
  it('ED-01 every documented engineer error code has its own sentence in both languages', () => {
    const documented = [
      'engineer_signoff_requires_human',
      'engineer_ticket_requires_human',
      'engineer_review_budget_exhausted',
      'engineer_suite_unavailable',
      'engineer_impact_note_required',
      'engineer_impact_note_too_long',
      'engineer_draft_text_too_long',
      'engineer_test_selection_too_large',
      'engineer_setting_not_editable',
      'engineer_setting_value_invalid',
      'engineer_change_statement_invalid',
      'engineer_claim_incomplete',
      'engineer_trial_limit_reached',
      'engineer_baseline_unsupported',
      'engineer_review_changed',
    ];
    for (const code of documented) expect(ENGINEER_ERROR_CODES).toContain(code);
    const zh = documented.map((code) => engineerErrorText(code));
    setPreference('en');
    const en = documented.map((code) => engineerErrorText(code));
    expect(new Set(zh).size).toBe(documented.length);
    expect(new Set(en).size).toBe(documented.length);
    for (const text of [...zh, ...en]) {
      expect(text).not.toMatch(/engineer_|_/);
      expect(text.length).toBeGreaterThan(4);
    }
    expect(zh[0]).toBe('只有你本人能签字提交复核，Agent 不能代签。');
    expect(en[2]).toBe('This ticket’s 3 reviews are used up.');
  });

  it('ED-02 an unknown or missing code never shows the code itself', () => {
    expect(engineerErrorText('engineer_brand_new_code')).toBe('没有完成，输入还在，可以再试一次。');
    expect(engineerErrorText(undefined)).toBe('没有完成，输入还在，可以再试一次。');
    expect(engineerErrorText('response_unconfirmed')).toBe(
      '结果还没确认。输入还在，稍后再看一次再决定要不要重做。',
    );
    setPreference('en');
    expect(engineerErrorText('nope')).toBe(
      'That didn’t go through. Your input is kept; try again.',
    );
  });
});

describe('engineer desk · setting values in words', () => {
  it('ED-03 choice, set and boolean values read as the settings sheet names them', () => {
    expect(valueText('freshness_guard', 'warn')).toBe('加提醒');
    expect(valueText('freshness_guard', 'none')).toBe('不处理');
    expect(valueText('update_strategy', 'manual_policy')).toBe('政策转人工');
    expect(valueText('domains', ['stable_faq', 'policy_travel'])).toBe('办公 FAQ、差旅政策');
    expect(valueText('work_items', ['human_fallback'])).toBe('人工入口');
    expect(valueText('scope_filter', true)).toBe('开');
    expect(valueText('min_score', 0.2)).toBe('0.2');
    expect(valueText('prohibited_topics', [])).toBe('无');
    setPreference('en');
    expect(valueText('freshness_guard', 'fallback')).toBe('Hand off');
    expect(valueText('domains', ['onboarding', 'policy_leave'])).toBe('Onboarding, Leave policy');
    expect(valueText('scope_filter', false)).toBe('Off');
  });
});

describe('engineer desk · the home row', () => {
  // Phase 2: one role per practice; the card says who takes the product side (Grace).
  it('ED-44 names the product manager, not the internal "AIPM", and says Grace takes the product side', () => {
    const zh = engineerCareerCardHtml({ practice: false });
    expect(zh).toContain('修好产品经理测出的问题');
    expect(zh).toContain('Grace（AI 同事，产品侧）');
    expect(zh).not.toContain('engineer-take');
    setPreference('en');
    const en = engineerCareerCardHtml({ practice: true });
    expect(en).toContain('Fix what the product manager found');
    expect(en).toContain('Grace (AI colleague, product side)');
    expect(en).toContain('data-action="engineer-take"');
    expect(zh + en).not.toMatch(/AIPM/);
  });
});
