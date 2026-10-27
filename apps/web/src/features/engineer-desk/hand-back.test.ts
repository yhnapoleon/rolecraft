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
  reviewDetails,
  targetNote,
  withTargetCheck,
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
      text: '住宿上限已修好 · 回归比较未完成',
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

it('keeps an unknown target distinct from failed or incomplete regression', () => {
 setPreference('en');
 const r = {target:'unknown' as const,compared:true,newFailures:0};
 expect(outcomeCaution(r)).toContain('still unverified');
 expect(outcomeCaution(r)).not.toContain('not fixed');
 expect(handBackSignal({at:'now',ticketId:'t',title:'tests',clean:false,newFailures:0,result:r}).text).toContain('target still unverified');
});

it('keeps public new failures out of the hidden regression count', () => {
 const ROOT = rootCauseEn as unknown as EngineerReviewRecord;
 const record = {...ROOT,report:{...ROOT.report,findings:ROOT.report.findings.map(f=>f.kind==='new_regression'?{...f,status:'fail' as const,probe_ids:['F01','F02']}:f),hidden_comparison:{new_failures:0,fixed:0,still_failing:0,unverified:0}}};
 const rows=reviewDetails(record,'en');
 expect(rows.find(r=>r.label==='Public regression')?.text).toContain('2 recorded new failures');
 expect(rows.find(r=>r.label==='Hidden regression')?.text).toContain('0 new failures');
});

describe('Daniel’s report · the target read from his rule check (QA S-3)', () => {
  const ROOT = rootCauseEn as unknown as EngineerReviewRecord;
  // The signed review cannot verify a handed-over question that carries no expectation.
  const unverified = {
    ...ROOT,
    report: {
      ...ROOT.report,
      findings: ROOT.report.findings.map((f) =>
        f.kind === 'target_fix' ? { ...f, status: 'unverified' as const } : f,
      ),
      hidden_comparison: { new_failures: 0, fixed: 2, still_failing: 0, unverified: 0 },
    },
  } as EngineerReviewRecord;
  const stale = (cleared: number, questions = 1) => ({
    failures: ['stale_unwarned' as const],
    questions,
    cleared,
  });

  it('a pick that cleared the failure reads as verified and adoptable, never "not recommended"', () => {
    setPreference('en');
    const review = reviewResult(unverified, 'en');
    expect(review.target).toBe('unknown');
    const r = withTargetCheck(review, stale(1));
    expect(r.target).toBe('fixed');
    expect(outcomeClean(r)).toBe(true);
    expect(outcomeSentence(r)).toBe(
      'Target: no longer cites an outdated source without a warning · verified',
    );
    expect(targetNote(r, true)).toBe(
      "Whether the answer's content is right is beyond a rule check: judge it with a regression case on the evaluation bench.",
    );
    expect(outcomeCaution(r)).toBe('');
    const rows = reviewDetails(unverified, 'en', stale(1));
    expect(rows.find((x) => x.label === 'Target verification')?.text).toBe(
      'Verified by rule: no longer cites an outdated source without a warning; answer content not verified',
    );
    const adoption = rows.find((x) => x.label === 'Adoption')?.text ?? '';
    expect(adoption).toMatch(/^Supports adoption: the target no longer fails as before/);
    expect(adoption).toContain('regression case on the evaluation bench');
    expect(JSON.stringify(rows)).not.toContain('not recommended');
    expect(handBackSignal({ at: 'now', ticketId: 't', title: 'tests', clean: true, newFailures: 0, result: r, colleague: 'Daniel' }).text).toBe(
      'The handed-over tests: failure cleared · nothing new fails',
    );
  });

  it('says the same in Chinese', () => {
    setPreference('zh');
    const r = withTargetCheck(reviewResult(unverified, 'zh'), stale(1));
    expect(outcomeSentence(r)).toBe('目标：不再在不提醒的情况下引用过期资料 · 已核实');
    expect(targetNote(r, true)).toBe('答案内容对不对，规则核实不了：在评测台写一道回归题来判。');
    const rows = reviewDetails(unverified, 'zh', stale(1));
    expect(rows[0].text).toBe('已核实（规则）：不再在不提醒的情况下引用过期资料；答案内容未核实');
    expect(rows[3].text.startsWith('可以采用：目标原来的问题已消除，没有新增失败。')).toBe(true);
  });

  it('a failure still there is "not fixed" with its reason, and the caution says so', () => {
    setPreference('en');
    const r = withTargetCheck(reviewResult(unverified, 'en'), stale(0));
    expect(r.target).toBe('not_fixed');
    expect(outcomeSentence(r)).toBe('Target: still cites an outdated source without a warning');
    expect(outcomeCaution(r)).toBe(
      'In this trial the target still cites an outdated source without a warning; updating the pilot does not clear it.',
    );
    expect(reviewDetails(unverified, 'en', stale(0))[3].text).toBe(
      'Adoption not recommended yet: the target still cites an outdated source without a warning',
    );
    const partial = withTargetCheck(reviewResult(unverified, 'en'), stale(1, 2));
    expect(outcomeSentence(partial)).toBe(
      'Target: 1 of 2 handed-over questions no longer cite an outdated source without a warning',
    );
  });

  it('a review that verified the target itself keeps its own reading; no check keeps "unknown" with a reason', () => {
    setPreference('en');
    const fixed = reviewResult(ROOT, 'en');
    expect(withTargetCheck(fixed, stale(0))).toBe(fixed);
    const unknown = withTargetCheck(reviewResult(unverified, 'en'), null);
    expect(unknown.target).toBe('unknown');
    expect(targetNote(unknown, true)).toContain('judge whether the target is fixed with a regression case');
    // The engineer's own report has no note.
    expect(targetNote(unknown, false)).toBe('');
    // Daniel's re-execution answered differently (say, retrieved nothing): no rule check, and
    // the note says why rather than claiming the failure is gone.
    expect(targetNote(unknown, true, { matched: 0, total: 1 })).toBe(
      'Daniel re-ran the handed-over questions on their original snapshot and got a different result from yours, so no rule can check their original failure; judge whether the target is fixed with a regression case on the evaluation bench.',
    );
  });
});
