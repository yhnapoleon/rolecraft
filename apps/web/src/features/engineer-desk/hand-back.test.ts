import { afterEach, describe, expect, it } from 'vitest';
import { ApiError } from '../../api';
import { setPreference } from '../../app/i18n';
import overreachEn from '../../../public/engineer/sample-overreach.en.json';
import overreachZh from '../../../public/engineer/sample-overreach.zh.json';
import rootCauseEn from '../../../public/engineer/sample-root-cause.en.json';
import rootCauseZh from '../../../public/engineer/sample-root-cause.zh.json';
import { engineerReportView, type EngineerReviewRecord } from '../engineer-report';
import { reviewViewOptions } from '../engineer-report/page';
import {
  applyFailure,
  handBackChanges,
  handBackCommand,
  handBackSignal,
  outcomeCaution,
  outcomeClean,
  outcomeSentence,
  reviewResult,
} from './hand-back';

afterEach(() => setPreference('zh'));

const PILOT = {
  id: 'config-1',
  session_id: 's1',
  version: 3,
  config_version: 1,
  domains: ['stable_faq', 'onboarding', 'policy_travel'],
  freshness_guard: 'none' as const,
  min_score: 0.35,
  retrieval_limit: 1,
};

describe('engineer hand-back · what the product manager would update', () => {
  it('ED-70 only settings the pilot does not already have, with today’s value beside the reviewed one', () => {
    const rows = handBackChanges(
      {
        freshness_guard: { before: 'none', after: 'warn' },
        min_score: { before: 0.35, after: 0.35 },
        domains: { before: [], after: ['policy_travel', 'onboarding', 'stable_faq'] },
      },
      PILOT,
    );
    expect(rows).toEqual([
      {
        field: 'freshness_guard',
        name: '过期资料保护',
        current: '不处理',
        next: '加提醒',
        value: 'warn',
      },
    ]);
  });

  it('ED-71 a pilot already on these settings has nothing to update', () => {
    expect(
      handBackChanges(
        { freshness_guard: { before: 'none', after: 'warn' } },
        {
          ...PILOT,
          freshness_guard: 'warn',
        },
      ),
    ).toEqual([]);
  });

  it('ED-72 the command updates the current pilot settings with the changed ones only', () => {
    const rows = handBackChanges(
      {
        freshness_guard: { before: 'none', after: 'warn' },
        min_score: { before: 0.35, after: 0.2 },
      },
      PILOT,
    );
    expect(handBackCommand(PILOT, rows)).toEqual({
      base: {
        session_id: 's1',
        kind: 'config',
        object_id: 'config-1',
        version: 3,
        config_version: 1,
      },
      settings: { freshness_guard: 'warn', min_score: 0.2 },
    });
  });
});

describe('engineer hand-back · what the review came to, in one sentence', () => {
  const ROOT = rootCauseEn as unknown as EngineerReviewRecord;
  const notFixed = (record: EngineerReviewRecord): EngineerReviewRecord => ({
    ...record,
    report: {
      ...record.report,
      findings: record.report.findings.map((f) =>
        f.kind === 'target_fix' ? { ...f, status: 'fail' as const } : f,
      ),
    },
  });

  it('ED-73 only a fixed target with the comparison done and nothing new failing is clean', () => {
    setPreference('en');
    const clean = reviewResult(ROOT, 'en');
    expect(clean).toEqual({ target: 'fixed', newFailures: 0, compared: true });
    expect(outcomeClean(clean)).toBe(true);
    expect(outcomeSentence(clean)).toBe('Target fixed, nothing new fails');
    const over = reviewResult(overreachEn as unknown as EngineerReviewRecord, 'en');
    expect(outcomeClean(over)).toBe(false);
    expect(outcomeSentence(over)).toBe('Target fixed, but 1 new failure');
    // Not fixed, nothing newly broken: never "fixed".
    const missed = reviewResult(notFixed(ROOT), 'en');
    expect(missed).toEqual({ target: 'not_fixed', newFailures: 0, compared: true });
    expect(outcomeClean(missed)).toBe(false);
    expect(outcomeSentence(missed)).toBe('Target not fixed');
    // The comparison could not finish: fixed, but not "nothing new fails".
    const open = reviewResult(
      {
        ...ROOT,
        report: {
          ...ROOT.report,
          hidden_comparison: { new_failures: 0, fixed: 2, still_failing: 0, unverified: 1 },
        },
      } as EngineerReviewRecord,
      'en',
    );
    expect(open).toEqual({ target: 'fixed', newFailures: 0, compared: false });
    expect(outcomeClean(open)).toBe(false);
    expect(outcomeSentence(open)).toBe('Target fixed; not yet known whether anything new fails');
    setPreference('zh');
    expect(outcomeSentence(clean)).toBe('目标修好了，没有新增失败');
    expect(outcomeSentence(missed)).toBe('目标没修好');
    expect(outcomeSentence({ target: 'not_fixed', newFailures: 2, compared: true })).toBe(
      '目标没修好，另有 2 处新增失败',
    );
  });

  it('ED-74 the report headline says the same sentence as the hand-back', () => {
    for (const [record, language] of [
      [rootCauseEn, 'en'],
      [rootCauseZh, 'zh'],
      [overreachEn, 'en'],
      [overreachZh, 'zh'],
    ] as const) {
      setPreference(language);
      const r = record as unknown as EngineerReviewRecord;
      const view = engineerReportView(r.report, reviewViewOptions(r, language));
      expect(view.verdict?.title).toBe(outcomeSentence(reviewResult(r, language)));
    }
  });

  it('ED-75 the caution before updating the pilot names what is actually wrong', () => {
    setPreference('en');
    expect(outcomeCaution({ target: 'fixed', newFailures: 0, compared: true })).toBe('');
    expect(outcomeCaution({ target: 'fixed', newFailures: 1, compared: true })).toBe(
      'This review has 1 new failure; updating brings it into the pilot.',
    );
    expect(outcomeCaution({ target: 'not_fixed', newFailures: 0, compared: true })).toBe(
      'In this review the target is not fixed; updating does not fix it in the pilot.',
    );
    expect(outcomeCaution({ target: 'fixed', newFailures: 0, compared: false })).toBe(
      'This review could not finish checking for new failures.',
    );
  });

  it('ED-76 the product board’s signal: a kicker, the conclusion in short, a tone', () => {
    setPreference('zh');
    const base = { at: '2026-10-24T12:00:00Z', ticketId: 't', clean: false, newFailures: 0 };
    const kicker = '工程复核 · 你签的';
    const seeded = (result: {
      target: 'fixed' | 'not_fixed';
      newFailures: number;
      compared: boolean;
    }) => handBackSignal({ ...base, title: 'seeded', result });
    expect(seeded({ target: 'fixed', newFailures: 0, compared: true })).toEqual({
      kicker,
      text: '住宿上限已修好 · 没有新增失败',
      tone: 'good',
    });
    expect(seeded({ target: 'fixed', newFailures: 1, compared: true }).text).toBe(
      '住宿上限已修好 · 新增 1 处失败',
    );
    expect(seeded({ target: 'not_fixed', newFailures: 0, compared: true })).toEqual({
      kicker,
      text: '住宿上限没修好',
      tone: 'warn',
    });
    expect(seeded({ target: 'not_fixed', newFailures: 2, compared: true }).text).toBe(
      '住宿上限没修好 · 新增 2 处失败',
    );
    expect(seeded({ target: 'fixed', newFailures: 0, compared: false })).toEqual({
      kicker,
      text: '住宿上限：复核没跑完',
      tone: 'warn',
    });
    // A tests ticket: its own subject, also after a reload.
    expect(
      handBackSignal({
        ...base,
        title: 'tests',
        result: { target: 'fixed', newFailures: 0, compared: true },
      }).text,
    ).toBe('交来的测试已修好 · 没有新增失败');
    expect(handBackSignal({ ...base, title: 'seeded', appliedVersion: 2, clean: true })).toEqual({
      kicker,
      text: '试点已更新到 v2',
      tone: 'good',
    });
    setPreference('en');
    expect(seeded({ target: 'fixed', newFailures: 2, compared: true }).text).toBe(
      'Hotel limit fixed · 2 new failures',
    );
    expect(seeded({ target: 'fixed', newFailures: 1, compared: true }).text).toBe(
      'Hotel limit fixed · 1 new failure',
    );
    expect(
      handBackSignal({
        ...base,
        title: 'tests',
        result: { target: 'not_fixed', newFailures: 0, compared: true },
      }).text,
    ).toBe('The handed-over tests not fixed');
  });

  it('ED-77 a pilot changed meanwhile asks to read it again; other refusals stay one sentence', () => {
    setPreference('zh');
    expect(applyFailure(new ApiError('x', 409, 'object_version_conflict'))).toEqual({
      conflict: true,
      text: '试点设置刚刚变过。重新读取后再确认。',
    });
    expect(applyFailure(new ApiError('x', 409, 'version_conflict')).conflict).toBe(true);
    const other = applyFailure(new ApiError('x', 500, 'internal'));
    expect(other.conflict).toBe(false);
    expect(other.text).toBe('没有完成，输入还在，可以再试一次。');
  });
});

describe('engineer hand-back · the revision the product manager opens (G13)', () => {
  it('ED-R2-13 the reason reads as the learner’s own sentence, in both languages', async () => {
    const { revisionReason } = await import('./hand-back');
    setPreference('zh');
    expect(revisionReason()).toBe('把工程复核修好的设置更新到试点');
    setPreference('en');
    expect(revisionReason()).toBe('put the engineering fix into the pilot');
  });
});
