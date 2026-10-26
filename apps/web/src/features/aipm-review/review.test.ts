import { describe, expect, it, vi } from 'vitest';
import { asFake, fakeDocument } from '../results-native/fake-dom';
import { FIXTURE_PRD, fixturePreview, fixtureReview } from './fixture';
import { backToSheet, latestReview } from './index';
import {
  coverageRow,
  deltaLine,
  groupSentences,
  orderCoverage,
  reviewSummaryForColleague,
  sheetOfCriterion,
  staleNote,
} from './model';
import { renderReview } from './view';

const CJK = /[一-鿿]/;

describe('sentences into sections', () => {
  for (const language of ['zh', 'en'] as const) {
    it(`places each ${language} sentence in its one section, and guesses none`, () => {
      const groups = groupSentences(fixturePreview(language).units ?? [], FIXTURE_PRD[language]);
      expect(groups.bySection.need?.map((u) => u.index)).toEqual([1, 2, 3, 4, 5]);
      expect(groups.bySection.business?.map((u) => u.index)).toEqual([0]);
      expect(groups.unassigned.map((u) => u.index)).toEqual([6]);
    });
  }
});

describe('review content', () => {
  it('orders coverage wrong, missing, to check, covered', () => {
    expect(orderCoverage(fixtureReview('zh').coverage).map((c) => c.mark)).toEqual([
      'wrong',
      'missing',
      'to_check',
      'covered',
    ]);
  });

  it('keeps a model-only point at “to check” and points somewhere instead of answering', () => {
    const [missing] = fixtureReview('zh').coverage.filter((c) => c.id === 'counter');
    const row = coverageRow({ ...missing, mark: 'missing', check: 'model' }, 'zh');
    expect(row.mark).toBe('unknown');
    expect(row.line).toBe('待核对 · 再看看：INT-03 访谈里新同事怎么找答案');
  });

  it('says when the review is out of date, and why', () => {
    const review = fixtureReview('zh');
    expect(staleNote(review, 'zh', 4)).toBeNull();
    expect(staleNote(review, 'zh', 5)?.text).toBe('这份批改对应第 4 版，你已改动。');
    expect(
      staleNote({ ...review, stale: { reason: 'policy_changed', detail: '政策 v2' } }, 'zh', 4)
        ?.kind,
    ).toBe('recheck');
  });

  it('compares with the previous review', () => {
    expect(deltaLine(fixtureReview('zh'), 'zh', 3)).toBe(
      '和第 3 版比：引用 0 → 2 · 缺口 3 → 2 · 有误 0 → 1',
    );
  });

  it('writes a colleague summary as questions to discuss, in one language', () => {
    const zh = reviewSummaryForColleague(fixtureReview('zh'), 'business', { language: 'zh' });
    expect(zh).toBe(
      '我在写「验证真需求」第 4 版。批改说：把结单时长当成了人工工时（第 2 句）；有误：指标口径：数字的单位和统计范围。你怎么看？',
    );
    const en = reviewSummaryForColleague(fixtureReview('en'), 'technical', { language: 'en' });
    expect(en).toMatch(
      /^I’m writing “Validate the need”, version 4\. The review says: .+ What do you think\?$/,
    );
    expect(en).not.toMatch(CJK);
  });

  it('maps result-page criteria back to their sheet', () => {
    expect(sheetOfCriterion('R1.metrics')).toBe('need');
    expect(sheetOfCriterion('R3.capacity')).toBe('solution');
    expect(sheetOfCriterion('unknown')).toBeNull();
  });

  it('offers a way back to the sheet from a result-page criterion', () => {
    const open = vi.fn();
    const button = asFake(backToSheet(fakeDocument(), 'R1.metrics', 'zh', open));
    expect(button.textContent).toBe('回到 ③ 验证真需求');
    button.click();
    expect(open).toHaveBeenCalledWith('need');
    expect(asFake(backToSheet(fakeDocument(), 'R4.functional_tests', 'en', open)).textContent).toBe(
      'Back to ⑥ Evaluation, monitoring and rollback',
    );
    expect(backToSheet(fakeDocument(), 'X.unknown', 'zh', open)).toBeNull();
  });

  it('reads the newest review from a page', () => {
    const old = { ...fixtureReview('zh'), id: 'old', created_at: '2026-10-26T09:00:00+08:00' };
    expect(latestReview({ result: { items: [old, fixtureReview('zh')] } })?.id).toBe(
      'fixture-review-zh',
    );
  });
});

describe('review screen', () => {
  const draw = (language: 'zh' | 'en', onAsk = vi.fn()) =>
    asFake(
      renderReview(fakeDocument(), {
        review: fixtureReview(language),
        language,
        sections: FIXTURE_PRD[language],
        sentences: { kind: 'off' },
        previousVersion: 3,
        onAsk,
      }),
    );

  it('draws no lines with the recognition layer off, and says so', () => {
    const root = draw('zh');
    expect(root.textContent).toContain('逐句标注未开启');
    expect(root.byClass('rc-sentences')).toHaveLength(0);
  });

  it('puts the misconception first, coverage worst first, and three colleagues to ask', () => {
    const onAsk = vi.fn();
    const root = draw('zh', onAsk);
    expect(root.byClass('aipm-review__mis')[0].dataset.first).toBe('');
    expect(root.byClass('fb-item').map((row) => row.dataset.feedbackItem)).toEqual([
      'metric',
      'counter',
      'willing',
      'cited',
    ]);
    const asks = root.byClass('aipm-review__ask');
    expect(asks.map((b) => b.textContent)).toEqual([
      '问 Grace（附上第 4 版）',
      '问 Chen（附上第 4 版）',
      '问 Daniel（附上第 4 版）',
    ]);
    asks[2].click();
    expect(onAsk).toHaveBeenCalledWith('technical');
    expect(root.textContent).toContain('和第 3 版比');
    expect(root.textContent).toContain('不计入正式评分');
  });

  it('renders English without Chinese', () => {
    expect(draw('en').textContent).not.toMatch(CJK);
  });
});
