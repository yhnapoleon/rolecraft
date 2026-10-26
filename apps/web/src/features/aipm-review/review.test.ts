import { describe, expect, it, vi } from 'vitest';
import { asFake, fakeDocument } from '../results-native/fake-dom';
import {
  FIXTURE_PRD,
  fixtureModelReview,
  fixturePage,
  fixturePreview,
  fixtureReview,
} from './fixture';
import { backToSheet, installAipmReview, pickReview, type ReviewHost } from './index';
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
const coverage = (language: 'zh' | 'en') => fixtureReview(language).coverage ?? [];

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

describe('review content (L4 shared fixture)', () => {
  it('orders coverage wrong, missing, to check, covered', () => {
    expect(orderCoverage(coverage('zh')).map((c) => c.id)).toEqual([
      'need.metric_scope',
      'need.next_validation',
      'need.counterfact',
      'need.raw_evidence',
    ]);
  });

  it('keeps a model-only point at “to check” and points somewhere instead of answering', () => {
    const [counter] = coverage('zh').filter((c) => c.id === 'need.counterfact');
    const row = coverageRow({ ...counter, mark: 'missing' }, 'zh');
    expect(row.mark).toBe('unknown');
    expect(row.line).toBe('未接入模型 · 再看看：需求访谈 · 反对意见');
    expect(coverageRow({ ...counter, mark: 'missing' }, 'zh', 'running').line).toBe(
      '模型细看中… · 再看看：需求访谈 · 反对意见',
    );
  });

  it('says when the review is out of date, and why', () => {
    const review = fixtureReview('zh');
    expect(staleNote(review, 'zh', 4)).toBeNull();
    expect(staleNote(review, 'zh', 5)?.text).toBe('这份批改对应第 4 版，你已改动。');
    expect(staleNote(review, 'zh', 4, true)?.kind).toBe('edited');
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
    expect(reviewSummaryForColleague(fixtureReview('zh'), 'business', { language: 'zh' })).toBe(
      '我在写「验证真需求」第 4 版。批改说：这里把结单时长当成了人工工时；有误：指标口径。从业务口径看，你觉得我最该先核对哪一处？',
    );
    const en = reviewSummaryForColleague(fixtureReview('en'), 'technical', { language: 'en' });
    expect(en).toBe(
      'I’m writing “Validate the need”, version 4. The review says: Elapsed ticket time is used as labour time here; Wrong: Metric definition. From the system and test evidence, which part do you think I should check first?',
    );
    expect(en).not.toMatch(CJK);
  });

  it('asks each colleague for a direction, never for the fix', () => {
    for (const language of ['zh', 'en'] as const)
      for (const who of ['manager', 'business', 'technical'] as const) {
        const said = reviewSummaryForColleague(fixtureReview(language), who, { language });
        expect(said).toMatch(language === 'zh' ? /最该先核对哪一处？$/ : /should check first\?$/);
        expect(said).not.toMatch(/怎么改|改法|How should I fix|rewrite/i);
      }
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

  it('picks the asked-for review from a page, else the newest', () => {
    const page = fixturePage();
    expect(pickReview(page)?.id).toBe('review-need-4-en');
    expect(pickReview(page, { ...page.items[0].ref, version: 9 })).toBeNull();
  });
});

describe('review screen', () => {
  const draw = (language: 'zh' | 'en', over: Partial<Parameters<typeof renderReview>[1]> = {}) =>
    asFake(
      renderReview(fakeDocument(), {
        review: fixtureReview(language),
        language,
        sections: FIXTURE_PRD[language],
        sentences: { kind: 'off' },
        previousVersion: 3,
        ...over,
      }),
    );

  it('draws no lines with the recognition layer off, and says so', () => {
    const root = draw('zh');
    expect(root.textContent).toContain('逐句标注未开启');
    expect(root.byClass('rc-sentences')).toHaveLength(0);
  });

  it('puts the misconception first, coverage worst first, and colleagues to ask', () => {
    const onAsk = vi.fn();
    const onOpenMaterial = vi.fn();
    const root = draw('zh', { onAsk, onOpenMaterial });
    expect(root.byClass('aipm-review__mis')[0].dataset.first).toBe('');
    expect(root.byClass('fb-item').map((row) => row.dataset.feedbackItem)).toEqual([
      'need.metric_scope',
      'need.next_validation',
      'need.counterfact',
      'need.raw_evidence',
    ]);
    root.byClass('aipm-review__link')[0].click();
    expect(onOpenMaterial).toHaveBeenCalledWith('service_desk_sample');
    const asks = root.byClass('aipm-review__ask');
    expect(asks.map((b) => b.textContent)).toEqual(['问 Grace', '问 Chen']);
    asks[1].click();
    expect(onAsk).toHaveBeenCalledWith('business');
    expect(root.textContent).toContain('和第 3 版比');
    expect(root.textContent).toContain('不计入正式评分');
  });

  it('renders English without Chinese', () => {
    expect(draw('en').textContent).not.toMatch(CJK);
  });
});

describe('the model look', () => {
  const draw = (review: ReturnType<typeof fixtureReview>, modelTimedOut = false) =>
    asFake(
      renderReview(fakeDocument(), {
        review,
        language: 'zh',
        sections: FIXTURE_PRD.zh,
        sentences: { kind: 'off' },
        modelTimedOut,
      }),
    );

  it('says “no model connected” on the points only a model can judge', () => {
    const root = draw(fixtureModelReview('zh', 'not_configured'));
    expect(root.textContent).toContain('未接入模型 · 再看看：需求访谈 · 反对意见');
    expect(root.byClass('aipm-review__model-status')).toHaveLength(0);
  });

  it('lists rule results at once and says the model is still looking, or to come back', () => {
    const running = fixtureModelReview('zh', 'running');
    expect(draw(running).byClass('aipm-review__model-status')[0].textContent).toContain(
      '模型细看中',
    );
    expect(draw(running).byClass('fb-item')).toHaveLength(4);
    expect(draw(running, true).byClass('aipm-review__model-status')[0].textContent).toContain(
      '模型还在看，稍后回来查看',
    );
  });

  it('puts the model’s verdicts in place as advice, and recounts status and comparison', () => {
    const review = fixtureModelReview('zh', 'done');
    const root = draw(review);
    const model = root.byClass('fb-item').filter((row) => row.dataset.source === 'model');
    expect(model.map((row) => row.dataset.feedbackItem)).toEqual(['need.counterfact']);
    expect(model[0].dataset.coverage).toBe('missing');
    expect(model[0].textContent).toContain('模型判断 · 建议');
    expect(model[0].textContent).toContain('再看看：没写出会让试点停下的事实');
    expect(root.byClass('aipm-review__advised')[0].textContent).toContain('只引用了一次访谈');
    expect(root.textContent).toContain('交付时由正式反馈判断：指标与验收口径');
    expect(root.textContent).toContain('模型的判断只是建议');
    // Two missing points now (one by the model): gaps recounted from the merged coverage.
    expect(deltaLine(review, 'zh', 3)).toBe('和第 3 版比：引用 0 → 1 · 缺口 3 → 2 · 有误 0 → 2');
  });

  it('lets a model “wrong” count in status, comparison and the colleague summary', () => {
    const review = fixtureModelReview('zh', 'done');
    const items = (review.model_items ?? []).map((item) =>
      item.target === 'coverage' ? { ...item, mark: 'wrong' as const } : item,
    );
    const wrong = { ...review, model_items: items };
    expect(deltaLine(wrong, 'zh')).toContain('有误 0 → 3');
    expect(reviewSummaryForColleague(wrong, 'manager', { language: 'zh' })).toContain(
      '有误：会让我们不做的事实',
    );
  });

  it('shows an interrupted look’s own sentence instead of running forever', () => {
    const interrupted = {
      ...fixtureModelReview('zh', 'failed'),
      model_reason: '模型细看被中断；再点一次「交给批改」即可继续。',
    };
    expect(draw(interrupted).byClass('aipm-review__model-status')[0].textContent).toBe(
      '模型细看没有完成。模型细看被中断；再点一次「交给批改」即可继续。下面是规则判定。',
    );
  });

  it('says why the model look failed, and keeps the rule results', () => {
    const root = draw(fixtureModelReview('zh', 'failed'));
    expect(root.byClass('aipm-review__model-status')[0].textContent).toBe(
      '模型细看没有完成。模型超时。下面是规则判定。',
    );
    expect(root.byClass('fb-item')).toHaveLength(4);
  });
});

describe('installAipmReview', () => {
  const followHost = (
    reads: ReturnType<typeof fixtureReview>[],
    last: ReturnType<typeof fixtureReview>,
  ) => {
    const sectionReviews = vi.fn(async () => ({
      items: [{ ref: last.prd_ref, review: reads.shift() ?? last }],
      next_cursor: null,
    }));
    const host = {
      getSessionContext: () => ({ sessionId: 's', workLanguage: 'zh' as const, readOnly: false }),
      getClient: () => ({ sectionReviews }),
      getDataHost: () => null,
      readProgress: async () => ({}),
      registerFeature: () => () => undefined,
      currentScreen: () => ({ kind: 'review' }),
      openWorksheet: vi.fn(),
      openMaterialSplit: vi.fn(),
      askColleague: vi.fn(),
    } as unknown as ReviewHost;
    return { host, sectionReviews };
  };

  it('rereads a running model look every 2 s until revision 2 arrives, then stops', async () => {
    vi.useFakeTimers();
    const running = fixtureModelReview('zh', 'running');
    const done = fixtureModelReview('zh', 'done');
    const { host, sectionReviews } = followHost([running, running], done);
    const installed = installAipmReview(host);
    await installed.open('need');
    await vi.advanceTimersByTimeAsync(2000);
    expect(installed.state.review?.model_status).toBe('running');
    await vi.advanceTimersByTimeAsync(2000);
    expect(installed.state.review?.revision).toBe(2);
    const calls = sectionReviews.mock.calls.length;
    await vi.advanceTimersByTimeAsync(10000);
    expect(sectionReviews.mock.calls.length).toBe(calls);
    vi.useRealTimers();
  });

  it('gives up after about 60 s and says to come back later', async () => {
    vi.useFakeTimers();
    const running = fixtureModelReview('zh', 'running');
    const { host, sectionReviews } = followHost([], running);
    const installed = installAipmReview(host);
    await installed.open('need');
    await vi.advanceTimersByTimeAsync(62000);
    expect(installed.state.modelTimedOut).toBe(true);
    const calls = sectionReviews.mock.calls.length;
    expect(calls).toBe(31);
    await vi.advanceTimersByTimeAsync(10000);
    expect(sectionReviews.mock.calls.length).toBe(calls);
    vi.useRealTimers();
  });

  it('reads the review the screen asks for and asks colleagues through the host', async () => {
    const page = fixturePage();
    const asked: unknown[] = [];
    const askColleague = vi.fn(async () => undefined);
    const register = vi.fn(() => () => undefined);
    const host: ReviewHost = {
      getSessionContext: () => ({
        sessionId: 'fixture-session',
        workLanguage: 'en',
        readOnly: false,
      }),
      getClient: () => ({ sectionReviews: async () => page }),
      getDataHost: () => ({
        snapshot: () => ({ state: 'active' }),
        query: async (_operation: never, input: never) => {
          asked.push(input);
          return { enabled: false, recognition: null };
        },
      }),
      readProgress: async () => ({ steps: [{ id: 'need', sheet: { edited_since_review: true } }] }),
      registerFeature: register,
      currentScreen: () => ({ kind: 'review', step: 'need' }),
      openWorksheet: vi.fn(),
      openMaterialSplit: vi.fn(),
      askColleague,
    };
    const installed = installAipmReview(host);
    expect(register).toHaveBeenCalledWith('review', installed.feature);
    await installed.open('need');
    expect(installed.state.review?.id).toBe('review-need-4-en');
    expect(installed.state.edited).toBe(true);
    // No decision chosen: the sentence check still runs, with the fixed placeholder.
    expect(installed.state.sentences.kind).toBe('off');
    expect(asked).toContainEqual({
      decision: 'defer_with_conditions',
      products: [installed.state.review?.prd_ref],
    });
    await installed.ask('technical');
    expect(askColleague).toHaveBeenCalledWith({
      colleague: 'technical',
      prefill: expect.stringMatching(/^I’m writing “Validate the need”, version 4\./),
    });
  });
});
