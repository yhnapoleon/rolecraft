import { describe, expect, it } from 'vitest';
import fixedZh from '../../../public/engineer/target-fixed-no-new-failures.zh.json';
import notFixedEn from '../../../public/engineer/target-not-fixed-new-failures.en.json';
import { asFake, fakeDocument, type FakeElement } from '../results-native/fake-dom';
import { renderEngineerReport } from './render';
import type { EngineerPublicReport } from './types';
import { engineerReportView } from './view';

const FIXED_ZH = fixedZh as unknown as EngineerPublicReport;
const NOT_FIXED_EN = notFixedEn as unknown as EngineerPublicReport;
const headings = (root: FakeElement) =>
  ['h2', 'h3', 'h4', 'h5'].flatMap((tag) => root.byTag(tag).map((h) => `${tag} ${h.textContent}`));

describe('engineer regression report · DOM', () => {
  it('ER-20 one paper sheet: verdict first, then public, hidden, checks; basis closed', () => {
    const doc = fakeDocument();
    const view = engineerReportView(FIXED_ZH, {
      language: 'zh',
      retrievalNote: '规则版检索',
      timeZone: 'UTC',
    });
    const root = asFake(renderEngineerReport(doc, view));
    expect(root.tagName).toBe('article');
    expect(root.dataset.engineerReport).toBe(FIXED_ZH.id);
    expect(headings(root)).toEqual([
      'h2 目标问题已修好',
      'h3 公开探针 · 4 条',
      'h3 隐藏探针 · 9 条',
      'h3 规则核对',
    ]);
    expect(root.byClass('er-verdict')[0].dataset.tone).toBe('good');
    expect(root.byClass('er-verdict__target')[0].textContent).toBe('账号密码忘了怎么重置？');
    const rows = root.byClass('er-probe');
    expect(rows.map((r) => r.dataset.result)).toEqual(['fail', 'pass', 'pass', 'pass']);
    // The result is spoken before the case number; the mark itself is hidden from readers.
    expect(rows[0].byClass('er-probe__id')[0].textContent).toBe('未通过：F01');
    expect(rows[0].byClass('er-probe__mark')[0].getAttribute('aria-hidden')).toBe('true');
    expect(rows[3].dataset.target).toBe('');
    expect(root.byClass('er-counts--comparison')).toHaveLength(0);
    expect(root.byClass('er-advice')[0].textContent).toBe('模型建议：等待模型接入不计分');
    expect(root.byClass('er-note--retrieval')[0].textContent).toBe('规则版检索');
    const details = root.byTag('details');
    expect(details).toHaveLength(1);
    expect(details[0].open).toBe(false);
    expect(details[0].byTag('summary')[0].textContent).toBe('查看依据');
    expect(root.byTag('button')).toHaveLength(0);
  });

  it('ER-21 hidden comparison and assessment draw only when supplied', () => {
    const doc = fakeDocument();
    const report = {
      ...NOT_FIXED_EN,
      hidden_comparison: { new_failures: 2, fixed: 1, still_failing: 3, unverified: 0 },
    };
    const view = engineerReportView(report, {
      language: 'en',
      evaluation: [
        { id: 'E1.target_fixed', label: 'NOT_MET', basis: 'rule' },
        { id: 'E5.remaining_explanation', label: null, basis: 'rule', status: 'waiting_model' },
      ],
    });
    const root = asFake(renderEngineerReport(doc, view, { headingLevel: 3 }));
    expect(headings(root)).toEqual([
      'h3 Target not fixed',
      'h4 Public probes · 4',
      'h4 Hidden probes · 9',
      'h4 Rule checks',
      'h4 Assessment',
    ]);
    const comparison = root.byClass('er-counts--comparison')[0];
    expect(comparison.byClass('er-count').map((c) => [c.textContent, c.dataset.tone])).toEqual([
      ['New failures2', 'bad'],
      ['Fixed1', 'good'],
      ['Still failing3', 'unknown'],
      ['Unverified0', 'unknown'],
    ]);
    const evaluation = root.byClass('er-evaluation')[0].byClass('er-check');
    expect(evaluation.map((r) => [r.textContent, r.dataset.mark])).toEqual([
      ['✕Target failures repairedNot met', 'not_met'],
      ['Unresolved items explainedAwaiting model verification', 'waiting'],
    ]);
    expect(root.byClass('er-tag').map((t) => t.textContent)).toEqual([
      'Target',
      'Also failed before',
      'New failure',
      'New failure',
    ]);
  });

  it('ER-22 keeps a host-owned open basis and reports toggles', () => {
    const toggled: boolean[] = [];
    const root = asFake(
      renderEngineerReport(fakeDocument(), engineerReportView(FIXED_ZH, { language: 'en' }), {
        basisOpen: true,
        onBasisToggle: (open) => toggled.push(open),
      }),
    );
    const details = root.byTag('details')[0];
    expect(details.open).toBe(true);
    details.open = false;
    details.dispatch('toggle');
    expect(toggled).toEqual([false]);
    expect(root.byClass('er-basis__value--code')[0].textContent).toBe('6b4cbd6a');
  });

  it('ER-23 markup-like text stays text', () => {
    const report = {
      ...FIXED_ZH,
      public_results: FIXED_ZH.public_results.map((row, i) =>
        i === 0 ? { ...row, query: '<img src=x onerror=alert(1)>' } : row,
      ),
    };
    const root = asFake(
      renderEngineerReport(fakeDocument(), engineerReportView(report, { language: 'zh' })),
    );
    const query = root.byClass('er-probe__query')[0];
    expect(query.textContent).toBe('<img src=x onerror=alert(1)>');
    expect(query.children).toHaveLength(0);
    expect(root.byTag('img')).toHaveLength(0);
  });
});
