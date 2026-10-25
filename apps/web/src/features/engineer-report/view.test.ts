import { describe, expect, it } from 'vitest';
import overreachEn from '../../../public/engineer/sample-overreach.en.json';
import overreachZh from '../../../public/engineer/sample-overreach.zh.json';
import rootCauseEn from '../../../public/engineer/sample-root-cause.en.json';
import rootCauseZh from '../../../public/engineer/sample-root-cause.zh.json';
import { ENGINEER_REPORT_COPY } from './copy';
// Earlier review outputs kept as UI-state fixtures (failing rows, new failures, a mismatched
// self-report): their probe results are not regression conclusions.
import fixedEn from './fixtures/earlier-target-fixed.en.json';
import fixedZh from './fixtures/earlier-target-fixed.zh.json';
import notFixedEn from './fixtures/earlier-target-not-fixed.en.json';
import notFixedZh from './fixtures/earlier-target-not-fixed.zh.json';
import { reviewViewOptions } from './page';
import type {
  EngineerCriterionConclusion,
  EngineerFinding,
  EngineerPublicReport,
  EngineerReviewRecord,
  EngineerRuleEvaluation,
} from './types';
import { engineerReportView, ruleFindingText, type EngineerReportView } from './view';

const sample = (raw: unknown) => raw as EngineerPublicReport;
const FIXED_ZH = sample(fixedZh);
const NOT_FIXED_ZH = sample(notFixedZh);
const FIXED_EN = sample(fixedEn);
const NOT_FIXED_EN = sample(notFixedEn);
/** The real signed reviews the sample page shows (engineer API read-back). */
const record = (raw: unknown) => raw as EngineerReviewRecord;
const ROOT_ZH = record(rootCauseZh);
const ROOT_EN = record(rootCauseEn);
const OVER_ZH = record(overreachZh);
const OVER_EN = record(overreachEn);
const SG = 'Asia/Singapore';

/** Identity and state fields the renderer uses as attributes, never as visible text. */
const NOT_TEXT = new Set([
  'id',
  'key',
  'kind',
  'state',
  'tone',
  'mark',
  'result',
  'language',
  'queryLanguage',
]);
/** Every string the view will put on screen. */
function strings(view: EngineerReportView): string[] {
  const out: string[] = [];
  const walk = (value: unknown) => {
    if (typeof value === 'string') out.push(value);
    else if (Array.isArray(value)) value.forEach(walk);
    else if (value && typeof value === 'object')
      for (const [key, inner] of Object.entries(value)) if (!NOT_TEXT.has(key)) walk(inner);
  };
  walk(view);
  return out;
}

const finding = (
  kind: EngineerFinding['kind'],
  status: EngineerFinding['status'],
  probe_ids: string[] = [],
): EngineerFinding => ({
  kind,
  status,
  probe_ids,
  visibility: 'public',
  description: ruleFindingText(kind, status, 'zh', probe_ids.length > 0),
});
const criterion = (
  c: Partial<EngineerCriterionConclusion> & Pick<EngineerCriterionConclusion, 'criterion'>,
): EngineerCriterionConclusion => ({
  status: 'concluded',
  basis: 'rule',
  label: 'MET',
  reason_codes: [],
  probe_ids: [],
  hidden_probes: 0,
  ...c,
});
const evaluation = (criteria: EngineerCriterionConclusion[]): EngineerRuleEvaluation => ({
  rubric_revision: 'engineer-rubric-v1-final-20261009',
  review_id: `review-${'c0ffee12'.padEnd(64, '0')}`,
  submission_hash: 'abad1dea'.padEnd(64, '0'),
  affects_score: false,
  criteria,
});
const e1 = (
  label: EngineerCriterionConclusion['label'],
  more: Partial<EngineerCriterionConclusion> = {},
) => evaluation([criterion({ criterion: 'E1.target_fixed', label, ...more })]);
const withReport = (changes: Partial<EngineerPublicReport>) =>
  ({ ...FIXED_ZH, ...changes }) as EngineerPublicReport;

describe('engineer regression report · real samples', () => {
  it('ER-01 fixed sample (zh): target fixed, a pre-existing failure explained, nothing new', () => {
    const view = engineerReportView(FIXED_ZH, { language: 'zh', timeZone: SG });
    expect(view.eyebrow).toBe('回归报告');
    expect(view.meta).toEqual(['2026-10-24 11:48', '复核完成']);
    expect(view.verdict).toMatchObject({
      state: 'fixed',
      tone: 'good',
      title: '目标修好了，没有新增失败',
      detail: '现在给出了委托记录的预期答案。',
      targets: ['账号密码忘了怎么重置？'],
    });
    expect(view.publicSection.title).toBe('公开探针 · 4 条');
    expect(view.publicSection.tally).toBe('通过 3 · 未通过 1');
    expect(view.publicSection.sourceNote).toBeUndefined();
    expect(
      view.publicSection.rows.map((r) => [r.id, r.resultText, r.tags.map((t) => t.text), r.diff]),
    ).toEqual([
      [
        'F01',
        '未通过',
        ['改前也未通过'],
        '期望带提醒回答，实际直接回答，引用差旅政策 v1（资料已是 v2）',
      ],
      ['F04', '通过', [], undefined],
      ['F05', '通过', [], undefined],
      ['F12', '通过', ['目标'], undefined],
    ]);
    expect(view.hiddenSection.title).toBe('隐藏探针 · 9 条');
    expect(view.hiddenSection.counts.map((c) => `${c.label} ${c.value}`)).toEqual([
      '通过 5',
      '未通过 4',
      '出错 0',
    ]);
    expect(view.hiddenSection.comparison).toBeUndefined();
    expect(view.hiddenSection.note).toBe('隐藏探针只给计数。');
    expect(view.checks.lines.map((l) => [l.tone, l.status, l.rule])).toEqual([
      ['good', '公开探针没有新增失败', '与相同固定条件下的基线结果比较。'],
      ['good', '自报结果与实际一致', '自报与实际公开探针结果逐项核对。'],
    ]);
    expect(view.advice).toEqual({
      tone: 'unknown',
      text: '模型建议：等待模型接入',
      scoreNote: '不计分',
    });
    expect(view.evaluation).toBeUndefined();
  });

  it('ER-02 not-fixed sample (zh): target still failing, two public probes newly failing, self-report differs', () => {
    const view = engineerReportView(NOT_FIXED_ZH, { language: 'zh', timeZone: SG });
    expect(view.meta[1]).toBe('复核完成，自报不符');
    // Two public probes newly fail, so the headline names both facts (ER-44).
    expect(view.verdict).toMatchObject({
      state: 'not_fixed',
      tone: 'warn',
      title: '目标没修好，另有 2 处新增失败',
      lines: [
        { tone: 'ink', text: 'F01 仍未通过：期望带提醒回答，实际没有给出回答' },
        { tone: 'warn', text: '2 个原来通过的公开探针现在失败' },
      ],
    });
    expect(view.publicSection.tally).toBe('通过 1 · 未通过 3');
    expect(
      view.publicSection.rows.map((r) => [r.id, r.tone, r.tags.map((t) => t.text), r.diff]),
    ).toEqual([
      ['F01', 'ink', ['目标', '改前也未通过'], '期望带提醒回答，实际没有给出回答'],
      ['F04', 'ink', ['新增失败'], '期望转人工，实际没有给出回答'],
      ['F05', 'ink', ['新增失败'], '期望转人工，实际没有给出回答'],
      ['F12', 'good', [], undefined],
    ]);
    expect(view.hiddenSection.counts.map((c) => c.value)).toEqual([4, 5, 0]);
    expect(view.checks.lines.map((l) => [l.tone, l.status])).toEqual([
      ['warn', '公开探针新增失败 2 条'],
      ['bad', '自报结果与实际不符'],
    ]);
  });

  it('ER-03 English samples read in English, with the same facts', () => {
    const root = engineerReportView(ROOT_EN.report, {
      ...reviewViewOptions(ROOT_EN, 'en'),
      timeZone: SG,
    });
    expect(root.verdict).toMatchObject({
      title: 'Target fixed, nothing new fails',
      detail: 'Now gives the expected answer recorded with the ticket.',
      targets: ['What is the hotel reimbursement limit per night?'],
    });
    expect(root.publicSection.rows.map((r) => [r.id, r.resultText])).toEqual([
      ['F01', 'Passed'],
      ['F04', 'Passed'],
      ['F05', 'Passed'],
      ['F12', 'Passed'],
    ]);
    expect(root.hiddenSection.note).toBe('Hidden probes report counts only.');
    expect(root.checks.lines.map((l) => l.status)).toEqual([
      'No new failures in public or hidden probes',
      'Self-report matches the actual results',
    ]);
    expect(root.advice.text).toBe('Model advice: waiting for model integration');
    expect(root.retrievalNote).toBe('Rule-based retrieval');
    const over = engineerReportView(OVER_EN.report, reviewViewOptions(OVER_EN, 'en'));
    expect(over.checks.lines[0]).toMatchObject({
      tone: 'warn',
      status: 'New failures: 1 (0 public · 1 hidden)',
    });
    expect(over.evaluation?.rows.map((r) => [r.title, r.labelText, r.reason, r.hidden])).toEqual([
      [
        'Target failures repaired',
        'Met',
        'Target failures now give the expected answer recorded with the ticket.',
        undefined,
      ],
      ['No regressions', 'Not met', 'New failures appeared.', '1 hidden'],
      [
        'Change explanation matches configuration diff',
        'Met',
        'The change explanation matches the configuration diff.',
        undefined,
      ],
      ['Report reproducible', 'Met', 'The self-report matches the rerun.', undefined],
      [
        'Unresolved items explained',
        'Awaiting model verification',
        'The semantic part will be checked once a model is connected.',
        undefined,
      ],
    ]);
  });

  it.each([
    ['zh fixed', FIXED_ZH],
    ['zh not fixed', NOT_FIXED_ZH],
    ['en fixed', FIXED_EN],
    ['en not fixed', NOT_FIXED_EN],
  ])('ER-04 rule copy matches the reviewer’s authored text word for word (%s)', (_name, report) => {
    for (const f of report.findings)
      expect(ruleFindingText(f.kind, f.status, report.work_language, f.probe_ids.length > 0)).toBe(
        f.description,
      );
  });

  it('ER-05 marks a probe question as source text when the report language differs from the page', () => {
    expect(engineerReportView(ROOT_ZH.report, { language: 'en' }).publicSection.sourceNote).toBe(
      'Chinese source',
    );
    expect(engineerReportView(ROOT_EN.report, { language: 'zh' }).publicSection.sourceNote).toBe(
      '英文原文',
    );
    expect(
      engineerReportView(ROOT_ZH.report, { language: 'zh' }).publicSection.sourceNote,
    ).toBeUndefined();
  });
});

describe('engineer regression report · states', () => {
  it('ER-06 target not yet verified when the public report carries no target result', () => {
    // No public target finding and no rubric E1: no target line at all.
    const none = engineerReportView(
      withReport({ findings: FIXED_ZH.findings.filter((f) => f.kind !== 'target_fix') }),
      { language: 'zh' },
    );
    expect(none.verdict).toBeUndefined();
    // A public target finding that could not be verified still decides, in grey.
    const unmatched = engineerReportView(
      withReport({ findings: [finding('target_fix', 'unverified')] }),
      {
        language: 'en',
      },
    );
    expect(unmatched.verdict).toMatchObject({
      source: 'public',
      state: 'unknown',
      tone: 'unknown',
      title: 'Not known yet whether the target is fixed',
      detail: 'Some target tests have no matching trusted suite expectation.',
    });
  });

  it('ER-07 several targets: one still failing means not fixed, with a count', () => {
    const view = engineerReportView(
      withReport({
        findings: [finding('target_fix', 'pass', ['F12']), finding('target_fix', 'fail', ['F01'])],
      }),
      { language: 'zh' },
    );
    expect(view.verdict?.state).toBe('not_fixed');
    expect(view.verdict?.detail).toBe('2 个目标里 1 个还没修好。');
  });

  it('ER-08 execution errors are grey and say what failed', () => {
    const rows = FIXED_ZH.public_results.map((row) =>
      row.probe_id === 'F04'
        ? {
            ...row,
            result: 'error' as const,
            error_code: 'engineer_baseline_execution_failed' as const,
          }
        : row,
    );
    const view = engineerReportView(
      withReport({
        public_results: rows,
        status: 'incomplete',
        findings: [
          ...FIXED_ZH.findings.filter((f) => f.probe_ids[0] !== 'F04'),
          finding('new_regression', 'unverified', ['F04']),
        ],
      }),
      { language: 'zh' },
    );
    const row = view.publicSection.rows.find((r) => r.id === 'F04');
    expect(row).toMatchObject({
      tone: 'unknown',
      resultText: '执行出错',
      diff: '原配置执行出错，无法比较',
    });
    expect(view.publicSection.tally).toBe('通过 2 · 未通过 1 · 出错 1');
    expect(view.meta.at(-1)).toBe('复核未完成');
    expect(view.checks.lines[0]).toMatchObject({
      tone: 'unknown',
      status: '有探针执行出错，比较不完整',
    });
  });

  it('ER-09 hidden comparison: shown with colour by meaning when present, absent otherwise', () => {
    const view = engineerReportView(
      withReport({
        hidden_comparison: { new_failures: 1, fixed: 2, still_failing: 3, unverified: 0 },
      }),
      { language: 'zh' },
    );
    expect(view.hiddenSection.comparison?.map((c) => [c.label, c.value, c.tone])).toEqual([
      ['新增失败', 1, 'warn'],
      ['修好', 2, 'good'],
      ['仍未通过', 3, 'ink'],
      ['未核实', 0, 'ink'],
    ]);
    expect(view.checks.lines[0]).toMatchObject({
      tone: 'warn',
      status: '新增失败 1 条（公开 0 · 隐藏 1）',
    });
    const clean = engineerReportView(
      withReport({
        hidden_comparison: { new_failures: 0, fixed: 0, still_failing: 4, unverified: 0 },
      }),
      { language: 'en' },
    );
    expect(clean.hiddenSection.comparison?.map((c) => c.tone)).toEqual([
      'ink',
      'ink',
      'ink',
      'ink',
    ]);
    expect(clean.checks.lines[0]).toMatchObject({
      tone: 'good',
      status: 'No new failures in public or hidden probes',
    });
    expect(
      engineerReportView(withReport({ hidden_comparison: null }), { language: 'zh' }).hiddenSection
        .comparison,
    ).toBeUndefined();
    expect(
      engineerReportView(FIXED_ZH, { language: 'zh' }).hiddenSection.comparison,
    ).toBeUndefined();
  });

  it('ER-10 claim check states other than matched and mismatch stay grey', () => {
    const missing = engineerReportView(withReport({ claim_check: 'not_provided' }), {
      language: 'zh',
    });
    expect(missing.checks.lines[1]).toMatchObject({ tone: 'unknown', status: '没有附自报结果' });
    const unverified = engineerReportView(withReport({ claim_check: 'unverified' }), {
      language: 'en',
    });
    expect(unverified.checks.lines[1]).toMatchObject({
      tone: 'unknown',
      status: 'Some probes errored; self-report not checkable',
    });
  });

  it.each([
    [null, 'unknown', '模型建议：等待模型接入'],
    ['waiting_model', 'unknown', '模型建议：等待模型接入'],
    ['unavailable', 'unknown', '模型建议：这次没有拿到'],
    ['invalid', 'unknown', '模型建议：返回无效，未采用'],
    ['timeout', 'unknown', '模型建议：超时，未采用'],
  ] as const)('ER-11 advice %s is one quiet grey line, not scored', (status, tone, text) => {
    const advice = status
      ? {
          status,
          text: null,
          model: null,
          affects_score: false as const,
          visibility: 'public' as const,
        }
      : null;
    const view = engineerReportView(withReport({ advice }), { language: 'zh' });
    expect(view.advice).toEqual({ tone, text, scoreNote: '不计分' });
  });

  it('ER-12 successful advice shows its text, says not scored, keeps the model identity under the basis', () => {
    const model = { kind: 'model' as const, sha256: 'ab12cd34'.padEnd(64, '0') };
    const success = (text: string | null) =>
      engineerReportView(
        withReport({
          advice: { status: 'success', text, model, affects_score: false, visibility: 'public' },
        }),
        { language: 'zh' },
      );
    const withText = success('先确认索引刷新时间。');
    expect(withText.advice).toEqual({
      tone: 'ink',
      text: '模型建议',
      body: '先确认索引刷新时间。',
      scoreNote: '不计分',
    });
    expect(withText.basis.rows.at(-1)).toEqual({ label: '模型', value: 'ab12cd34', code: true });
    expect(strings(withText).some((s) => s.includes(model.sha256))).toBe(false);
    expect(success(null).advice).toEqual({
      tone: 'ink',
      text: '模型建议已生成',
      scoreNote: '不计分',
    });
    // Advice text never appears unless the reviewer reports success.
    const stray = engineerReportView(
      withReport({
        advice: {
          status: 'timeout',
          text: '不该出现的文字',
          model: null,
          affects_score: false,
          visibility: 'public',
        },
      }),
      { language: 'zh' },
    );
    expect(strings(stray)).not.toContain('不该出现的文字');
  });

  it('ER-13 assessment section only when conclusions are supplied, labels in words', () => {
    expect(engineerReportView(FIXED_ZH, { language: 'zh' }).evaluation).toBeUndefined();
    expect(
      engineerReportView(FIXED_ZH, { language: 'zh', evaluation: evaluation([]) }).evaluation,
    ).toBeUndefined();
    const view = engineerReportView(FIXED_ZH, {
      language: 'zh',
      evaluation: evaluation([
        criterion({ criterion: 'E1.target_fixed', label: 'MET' }),
        criterion({ criterion: 'E2.no_regressions', label: 'NOT_MET' }),
        criterion({ criterion: 'E3.change_consistency', label: 'PARTIAL' }),
        criterion({ criterion: 'E4.reproducibility', label: 'INSUFFICIENT' }),
        criterion({
          criterion: 'E5.remaining_explanation',
          label: null,
          status: 'waiting_model',
          basis: 'semantic_advice',
        }),
        criterion({
          criterion: 'E9.unknown_code' as EngineerCriterionConclusion['criterion'],
          label: 'NOT_APPLICABLE',
        }),
      ]),
    });
    expect(view.evaluation?.title).toBe('评价结论');
    expect(view.evaluation?.aside).toBe('不计分');
    expect(view.evaluation?.rows.map((r) => [r.title, r.labelText, r.tone, r.mark])).toEqual([
      ['目标失败已修复', '满足', 'good', 'met'],
      ['无回归', '未满足', 'warn', 'not_met'],
      ['修改说明与配置差异一致', '部分满足', 'ink', 'partial'],
      ['报告可复现', '还不知道', 'unknown', 'unknown'],
      ['对未修复项有说明', '等待模型核验', 'unknown', 'waiting'],
      ['评价项', '不适用', 'ink', 'not_applicable'],
    ]);
    expect(strings(view)).not.toContain('E9.unknown_code');
    const en = engineerReportView(FIXED_ZH, {
      language: 'en',
      evaluation: evaluation([
        criterion({ criterion: 'E5.remaining_explanation', label: null, status: 'waiting_model' }),
      ]),
    });
    expect(en.evaluation?.rows[0]).toMatchObject({
      title: 'Unresolved items explained',
      labelText: 'Awaiting model verification',
    });
  });

  it('ER-14 retrieval wording appears only when the host supplies it', () => {
    expect(engineerReportView(FIXED_ZH, { language: 'zh' }).retrievalNote).toBeUndefined();
    expect(
      engineerReportView(FIXED_ZH, { language: 'zh', retrievalNote: '  ' }).retrievalNote,
    ).toBeUndefined();
    expect(
      engineerReportView(FIXED_ZH, { language: 'zh', retrievalNote: '规则版检索' }).retrievalNote,
    ).toBe('规则版检索');
  });

  it('ER-15 basis shows identities as 8-character prefixes, never a full hash', () => {
    const view = engineerReportView(FIXED_ZH, { language: 'zh' });
    expect(view.basis.label).toBe('查看依据');
    expect(view.basis.rows.map((r) => r.label)).toEqual([
      '场景',
      '探针套件',
      '原配置',
      '候选配置',
      '生效配置',
      '资料版本',
      '索引版本',
      '资料快照',
      '复核程序',
      '提交',
      '复核输入',
    ]);
    expect(view.basis.rows[0]).toEqual({ label: '场景', value: '6b4cbd6a', code: true });
    expect(view.basis.rows[7]).toEqual({
      label: '资料快照',
      value: '业务序号 5 · 工作区修订 4',
      code: false,
    });
    expect(strings(view).some((s) => /[0-9a-f]{9,}/.test(s))).toBe(false);
  });

  it('ER-16 never shows free text: finding descriptions are replaced by the authored rule copy', () => {
    const tampered = withReport({
      findings: FIXED_ZH.findings.map((f) => ({ ...f, description: '<b>学员写的说明</b>' })),
    });
    const view = engineerReportView(tampered, { language: 'zh' });
    expect(strings(view).some((s) => s.includes('学员写的说明'))).toBe(false);
    expect(view.checks.lines[0].rule).toBe('与相同固定条件下的基线结果比较。');
  });

  it('ER-17 unknown material IDs never show raw; a host can name them', () => {
    const rows = FIXED_ZH.public_results.map((row) =>
      row.probe_id === 'F01'
        ? {
            ...row,
            citations: [{ ...row.citations[0], object_id: 'tech_private' }],
            source_versions: { tech_private: 3 },
          }
        : row,
    );
    const view = engineerReportView(withReport({ public_results: rows }), { language: 'zh' });
    expect(view.publicSection.rows[0].diff).toBe(
      '期望带提醒回答，实际直接回答，引用资料 v1（资料已是 v3）',
    );
    const named = engineerReportView(withReport({ public_results: rows }), {
      language: 'zh',
      materialName: (id) => (id === 'tech_private' ? '诊断底稿' : undefined),
    });
    expect(named.publicSection.rows[0].diff).toContain('引用诊断底稿 v1');
  });
});

describe('engineer regression report · target line and rubric conclusions', () => {
  const NO_TARGET = withReport({
    findings: FIXED_ZH.findings.filter((f) => f.kind !== 'target_fix'),
  });

  it('ER-24 a public target finding decides the target line even when E1 disagrees', () => {
    const view = engineerReportView(FIXED_ZH, {
      language: 'zh',
      evaluation: e1('NOT_MET', { hidden_probes: 2 }),
    });
    expect(view.verdict).toMatchObject({
      source: 'public',
      state: 'fixed',
      title: '目标修好了，没有新增失败',
      detail: '现在给出了委托记录的预期答案。',
      targets: ['账号密码忘了怎么重置？'],
    });
  });

  it.each([
    ['MET', 'fixed', 'good', '目标修好了，没有新增失败'],
    ['NOT_MET', 'not_fixed', 'ink', '目标问题没修好'],
    ['PARTIAL', 'partial', 'ink', '目标问题部分修好'],
    ['INSUFFICIENT', 'unknown', 'unknown', '还不知道目标是否修好'],
    [null, 'unknown', 'unknown', '还不知道目标是否修好'],
  ] as const)(
    'ER-25 without a public target finding, E1 %s sets the target line',
    (label, state, tone, title) => {
      const view = engineerReportView(NO_TARGET, { language: 'zh', evaluation: e1(label) });
      expect(view.verdict).toEqual({
        source: 'evaluation',
        state,
        tone,
        title,
        detail: '',
        targets: [],
      });
    },
  );

  it('ER-26 E1 waiting for a model reads as waiting, in grey; not-applicable E1 shows no target line', () => {
    const waiting = engineerReportView(NO_TARGET, {
      language: 'en',
      evaluation: e1(null, { status: 'waiting_model' }),
    });
    expect(waiting.verdict).toMatchObject({
      state: 'waiting',
      tone: 'unknown',
      title: 'Target awaiting model verification',
    });
    expect(
      engineerReportView(NO_TARGET, { language: 'zh', evaluation: e1('NOT_APPLICABLE') }).verdict,
    ).toBeUndefined();
  });

  it('ER-27 E1 hidden targets appear as a count only', () => {
    const many = engineerReportView(NO_TARGET, {
      language: 'zh',
      evaluation: e1('NOT_MET', { hidden_probes: 2 }),
    });
    expect(many.verdict?.detail).toBe('目标在 2 条隐藏探针上');
    expect(many.verdict?.targets).toEqual([]);
    const one = engineerReportView(NO_TARGET, {
      language: 'en',
      evaluation: e1('MET', { hidden_probes: 1 }),
    });
    expect(one.verdict?.detail).toBe('Target is covered by 1 hidden probe');
    const several = engineerReportView(NO_TARGET, {
      language: 'en',
      evaluation: e1('MET', { hidden_probes: 3 }),
    });
    expect(several.verdict?.detail).toBe('Target is covered by 3 hidden probes');
    expect(
      engineerReportView(NO_TARGET, { language: 'zh', evaluation: e1('MET') }).verdict?.detail,
    ).toBe('');
  });

  it('ER-28 reason codes read as one sentence; unknown codes show nothing raw', () => {
    const view = engineerReportView(FIXED_ZH, {
      language: 'zh',
      evaluation: evaluation([
        criterion({
          criterion: 'E1.target_fixed',
          reason_codes: ['targets_repaired'],
          probe_ids: ['F12'],
        }),
        criterion({
          criterion: 'E2.no_regressions',
          label: 'NOT_MET',
          reason_codes: ['new_failures_found', 'secret_internal_code'],
          probe_ids: ['F04', 'F05'],
          hidden_probes: 2,
        }),
        criterion({
          criterion: 'E4.reproducibility',
          label: 'INSUFFICIENT',
          reason_codes: ['mystery_code'],
        }),
      ]),
    });
    const rows = view.evaluation?.rows ?? [];
    expect(rows.map((r) => [r.reason, r.probeIds, r.hidden])).toEqual([
      ['目标失败都已给出委托记录的预期答案。', ['F12'], undefined],
      ['出现了新增失败。', ['F04', 'F05'], '隐藏 2 条'],
      [undefined, [], undefined],
    ]);
    expect(strings(view).some((s) => /secret_internal_code|mystery_code/.test(s))).toBe(false);
    const en = engineerReportView(FIXED_ZH, {
      language: 'en',
      evaluation: evaluation([
        criterion({
          criterion: 'E4.reproducibility',
          label: 'INSUFFICIENT',
          reason_codes: ['claim_not_provided', 'verification_incomplete'],
        }),
      ]),
    });
    expect(en.evaluation?.rows[0].reason).toBe(
      'No self-report attached; some probes errored, so verification is incomplete.',
    );
  });

  it('ER-29 E3 field checks name each setting in words, unknown settings stay raw', () => {
    const view = engineerReportView(FIXED_ZH, {
      language: 'zh',
      evaluation: evaluation([
        criterion({
          criterion: 'E3.change_consistency',
          label: 'NOT_MET',
          reason_codes: ['changes_omitted'],
          field_checks: [
            { field: 'freshness_guard', status: 'matched' },
            { field: 'fallback', status: 'omitted' },
            { field: 'domains', status: 'before_mismatch' },
            { field: 'retrieval_limit', status: 'change_not_made' },
            { field: 'custom_knob', status: 'change_denied' },
          ],
        }),
      ]),
    });
    const row = view.evaluation?.rows[0];
    expect(row?.reason).toBe('修改说明漏了部分配置差异。');
    expect(row?.fieldChecks?.label).toBe('逐项核对 · 5 项');
    expect(row?.fieldChecks?.rows.map((r) => [r.field, r.code, r.status, r.tone])).toEqual([
      ['过期资料保护', false, '一致', 'good'],
      ['答不了或不确定时', false, '说明里没写', 'ink'],
      ['开放的知识', false, '改前的值不符', 'bad'],
      ['检索条数', false, '说改了，实际没改', 'bad'],
      ['custom_knob', true, '说没改，实际改了', 'bad'],
    ]);
    const en = engineerReportView(FIXED_ZH, {
      language: 'en',
      evaluation: evaluation([
        criterion({
          criterion: 'E3.change_consistency',
          field_checks: [
            { field: 'after', status: 'values_mismatch' },
            { field: 'min_score', status: 'after_mismatch' },
          ],
        }),
      ]),
    });
    expect(en.evaluation?.rows[0].fieldChecks?.rows.map((r) => `${r.field}: ${r.status}`)).toEqual([
      'after: Both values differ',
      'Minimum relevance: After value differs',
    ]);
    expect(
      engineerReportView(FIXED_ZH, { language: 'zh', evaluation: e1('MET') }).evaluation?.rows[0]
        .fieldChecks,
    ).toBeUndefined();
  });

  it('ER-30 E5 waits for a model; its precheck counts unexplained failures and names public ones', () => {
    const view = engineerReportView(FIXED_ZH, {
      language: 'zh',
      evaluation: evaluation([
        criterion({
          criterion: 'E5.remaining_explanation',
          status: 'waiting_model',
          basis: 'semantic_advice',
          label: null,
          precheck: { basis: 'rule', unexplained_probe_ids: ['F01'], unexplained_hidden: 3 },
        }),
      ]),
    });
    expect(view.evaluation?.rows[0]).toMatchObject({
      labelText: '等待模型核验',
      mark: 'waiting',
      tone: 'unknown',
      precheck: '还有 1 条公开、3 条隐藏的失败没有解释',
      probeIds: ['F01'],
    });
    const en = engineerReportView(FIXED_ZH, {
      language: 'en',
      evaluation: evaluation([
        criterion({
          criterion: 'E5.remaining_explanation',
          status: 'waiting_model',
          label: null,
          precheck: { basis: 'rule', unexplained_probe_ids: [], unexplained_hidden: 2 },
        }),
      ]),
    });
    expect(en.evaluation?.rows[0].precheck).toBe('Failures still unexplained: 0 public, 2 hidden');
    const explained = engineerReportView(FIXED_ZH, {
      language: 'zh',
      evaluation: evaluation([
        criterion({
          criterion: 'E5.remaining_explanation',
          status: 'waiting_model',
          label: null,
          precheck: { basis: 'rule', unexplained_probe_ids: [], unexplained_hidden: 0 },
        }),
      ]),
    });
    expect(explained.evaluation?.rows[0].precheck).toBeUndefined();
  });

  it('ER-31 the assessment identities go under the basis as short prefixes', () => {
    const view = engineerReportView(FIXED_ZH, { language: 'zh', evaluation: e1('MET') });
    expect(view.basis.rows.slice(-3)).toEqual([
      { label: '评分标准', value: 'engineer-rubric-v1-final-20261009', code: true },
      { label: '评价对应的复核', value: 'c0ffee12', code: true },
      { label: '评价对应的提交', value: 'abad1dea', code: true },
    ]);
    expect(strings(view).some((s) => /[0-9a-f]{9,}/.test(s))).toBe(false);
  });

  it.each([
    'targets_repaired',
    'targets_partially_repaired',
    'targets_not_repaired',
    'target_without_trusted_probe',
    'target_verification_incomplete',
    'target_baseline_not_failing',
    'no_targets',
    'new_failures_found',
    'no_new_failures',
    'regression_coverage_incomplete',
    'changes_match_diff',
    'changes_omitted',
    'change_claims_contradicted',
    'change_claims_not_provided',
    'claim_reproduced',
    'claim_contradicts_rerun',
    'claim_outside_public_suite',
    'claim_scope_partial',
    'claim_not_provided',
    'verification_incomplete',
    'waiting_model',
  ])('ER-34 reason code %s reads as an authored sentence in both languages', (code) => {
    for (const language of ['zh', 'en'] as const) {
      const view = engineerReportView(FIXED_ZH, {
        language,
        evaluation: evaluation([
          criterion({ criterion: 'E4.reproducibility', reason_codes: [code] }),
        ]),
      });
      const reason = view.evaluation?.rows[0].reason;
      expect(reason, `${code} (${language})`).toBeTruthy();
      expect(reason).not.toContain(code);
      expect(reason).toMatch(language === 'zh' ? /[\u4e00-\u9fff]。$/ : /^[A-Z].*\.$/);
    }
  });

  it('ER-35 not met is red only for a contradiction, amber for new failures, ink otherwise', () => {
    const view = engineerReportView(FIXED_ZH, {
      language: 'zh',
      evaluation: evaluation([
        criterion({
          criterion: 'E1.target_fixed',
          label: 'NOT_MET',
          reason_codes: ['targets_not_repaired'],
        }),
        criterion({
          criterion: 'E2.no_regressions',
          label: 'NOT_MET',
          reason_codes: ['new_failures_found'],
        }),
        criterion({
          criterion: 'E3.change_consistency',
          label: 'NOT_MET',
          reason_codes: ['change_claims_contradicted'],
        }),
        criterion({
          criterion: 'E4.reproducibility',
          label: 'NOT_MET',
          reason_codes: ['claim_contradicts_rerun'],
        }),
        criterion({
          criterion: 'E4.reproducibility',
          label: 'NOT_MET',
          reason_codes: ['claim_scope_partial'],
        }),
        criterion({
          criterion: 'E2.no_regressions',
          label: 'MET',
          reason_codes: ['no_new_failures'],
        }),
      ]),
    });
    expect(view.evaluation?.rows.map((r) => r.tone)).toEqual([
      'ink',
      'warn',
      'bad',
      'bad',
      'ink',
      'good',
    ]);
  });

  it('ER-36 public probes: did not pass is ink, newly failing is amber, failing before is a quiet fact', () => {
    const view = engineerReportView(NOT_FIXED_ZH, { language: 'zh' });
    expect(
      view.publicSection.rows.map((r) => [
        r.id,
        r.tone,
        r.tags.map((t) => [t.text, t.tone, !!t.quiet]),
      ]),
    ).toEqual([
      [
        'F01',
        'ink',
        [
          ['目标', 'ink', false],
          ['改前也未通过', 'ink', true],
        ],
      ],
      ['F04', 'ink', [['新增失败', 'warn', false]]],
      ['F05', 'ink', [['新增失败', 'warn', false]]],
      ['F12', 'good', []],
    ]);
    expect(view.verdict).toMatchObject({ state: 'not_fixed', tone: 'warn' });
    expect(view.verdict?.lines?.[0].tone).toBe('ink');
    const tones = strings(view);
    expect(tones).toContain('新增失败');
  });
});

describe('engineer regression report · signed review samples', () => {
  it('ER-38 root-cause sample (zh): target fixed, no new failures anywhere, every conclusion met', () => {
    const view = engineerReportView(ROOT_ZH.report, {
      ...reviewViewOptions(ROOT_ZH, 'zh'),
      timeZone: SG,
    });
    expect(view.meta).toEqual(['2026-10-24 15:37', '复核完成']);
    expect(view.verdict).toMatchObject({
      source: 'public',
      state: 'fixed',
      tone: 'good',
      title: '目标修好了，没有新增失败',
      detail: '现在给出了委托记录的预期答案。',
      targets: ['住宿报销上限是多少？'],
    });
    expect(view.publicSection.tally).toBe('通过 4 · 未通过 0');
    expect(view.publicSection.rows.map((r) => [r.id, r.tone, r.tags.map((t) => t.text)])).toEqual([
      ['F01', 'good', ['目标']],
      ['F04', 'good', []],
      ['F05', 'good', []],
      ['F12', 'good', []],
    ]);
    expect(view.hiddenSection.counts.map((c) => `${c.label} ${c.value}`)).toEqual([
      '通过 9',
      '未通过 0',
      '出错 0',
    ]);
    expect(view.hiddenSection.comparison?.map((c) => [c.label, c.value, c.tone])).toEqual([
      ['新增失败', 0, 'ink'],
      ['修好', 2, 'good'],
      ['仍未通过', 0, 'ink'],
      ['未核实', 0, 'ink'],
    ]);
    expect(view.checks.lines.map((l) => [l.tone, l.status])).toEqual([
      ['good', '公开与隐藏探针都没有新增失败'],
      ['good', '自报结果与实际一致'],
    ]);
    expect(view.evaluation?.rows.map((r) => [r.title, r.labelText, r.tone, r.reason])).toEqual([
      ['目标失败已修复', '满足', 'good', '目标失败都已给出委托记录的预期答案。'],
      ['无回归', '满足', 'good', '没有新增失败。'],
      ['修改说明与配置差异一致', '满足', 'good', '修改说明与实际配置差异一致。'],
      ['报告可复现', '满足', 'good', '自报结果与重跑一致。'],
      ['对未修复项有说明', '等待模型核验', 'unknown', '这一项的语义部分等模型接入后核验。'],
    ]);
    expect(
      view.evaluation?.rows[2].fieldChecks?.rows.map((r) => `${r.field}：${r.status}`),
    ).toEqual(['过期资料保护：一致']);
    expect(view.evaluation?.rows[4].precheck).toBeUndefined();
    expect(view.retrievalNote).toBe('规则版检索');
  });

  it('ER-39 hidden comparison with one new failure shows an amber count (overreach sample)', () => {
    const view = engineerReportView(OVER_ZH.report, reviewViewOptions(OVER_ZH, 'zh'));
    expect(view.verdict).toMatchObject({ state: 'fixed', title: '目标修好了，但新增 1 处失败' });
    expect(view.hiddenSection.counts.map((c) => c.value)).toEqual([8, 1, 0]);
    expect(view.hiddenSection.comparison?.map((c) => [c.label, c.value, c.tone])).toEqual([
      ['新增失败', 1, 'warn'],
      ['修好', 2, 'good'],
      ['仍未通过', 0, 'ink'],
      ['未核实', 0, 'ink'],
    ]);
    expect(view.checks.lines[0]).toMatchObject({
      tone: 'warn',
      status: '新增失败 1 条（公开 0 · 隐藏 1）',
    });
    const e2 = view.evaluation?.rows[1];
    expect([e2?.labelText, e2?.tone, e2?.reason, e2?.hidden]).toEqual([
      '未满足',
      'warn',
      '出现了新增失败。',
      '隐藏 1 条',
    ]);
    expect(view.evaluation?.rows[2].fieldChecks?.rows.map((r) => r.field)).toEqual([
      '最低相关度',
      '过期资料保护',
    ]);
    expect(view.evaluation?.rows[4].precheck).toBe('还有 0 条公开、1 条隐藏的失败没有解释');
  });

  it('ER-43 fixed one, broke one: the headline says both, the turn and its line in amber (overreach)', () => {
    const zh = engineerReportView(OVER_ZH.report, reviewViewOptions(OVER_ZH, 'zh'));
    expect(zh.verdict).toMatchObject({
      source: 'public',
      state: 'fixed',
      tone: 'warn',
      title: '目标修好了，但新增 1 处失败',
      turn: '但新增 1 处失败',
      detail: '',
      targets: [],
      lines: [
        { tone: 'good', text: 'F01 现在给出了委托记录的预期答案' },
        { tone: 'warn', text: '1 个原来通过的隐藏探针现在失败' },
      ],
    });
    const en = engineerReportView(OVER_EN.report, reviewViewOptions(OVER_EN, 'en'));
    expect(en.verdict).toMatchObject({
      state: 'fixed',
      tone: 'warn',
      title: 'Target fixed, but 1 new failure',
      turn: 'but 1 new failure',
      lines: [
        { tone: 'good', text: 'F01 now gives the expected answer recorded with the ticket.' },
        { tone: 'warn', text: '1 hidden probe that passed before now fails.' },
      ],
    });
  });

  it('ER-44 not fixed and new failures: the headline names both; the target line stays ink', () => {
    const zh = engineerReportView(NOT_FIXED_ZH, { language: 'zh' });
    expect(zh.verdict).toMatchObject({
      state: 'not_fixed',
      tone: 'warn',
      title: '目标没修好，另有 2 处新增失败',
      turn: '另有 2 处新增失败',
      lines: [
        { tone: 'ink', text: 'F01 仍未通过：期望带提醒回答，实际没有给出回答' },
        { tone: 'warn', text: '2 个原来通过的公开探针现在失败' },
      ],
    });
    const en = engineerReportView(NOT_FIXED_EN, { language: 'en' });
    expect(en.verdict).toMatchObject({
      title: 'Target not fixed, and 2 new failures',
      turn: 'and 2 new failures',
      lines: [
        { tone: 'ink', text: 'F01 still fails: expected an answer with a warning, got no answer.' },
        { tone: 'warn', text: '2 public probes that passed before now fail.' },
      ],
    });
    const both = engineerReportView(
      {
        ...NOT_FIXED_ZH,
        hidden_comparison: { new_failures: 1, fixed: 0, still_failing: 0, unverified: 0 },
      },
      { language: 'zh' },
    );
    expect(both.verdict?.lines?.[1].text).toBe('3 个原来通过的探针现在失败（公开 2 · 隐藏 1）');
  });

  it('ER-45 nothing broken: a plain headline, no amber turn, no lines, and no jargon', () => {
    const view = engineerReportView(ROOT_EN.report, reviewViewOptions(ROOT_EN, 'en'));
    expect(view.verdict?.tone).toBe('good');
    expect(view.verdict?.turn).toBeUndefined();
    expect(view.verdict?.lines).toBeUndefined();
    for (const language of ['zh', 'en'] as const)
      for (const value of Object.values(ENGINEER_REPORT_COPY[language]).filter(
        (v) => !/suite expectation|探针预期/.test(v),
      ))
        expect(value).not.toMatch(/frozen|冻结/);
  });

  it.each([
    ['root-cause zh', ROOT_ZH],
    ['root-cause en', ROOT_EN],
    ['overreach zh', OVER_ZH],
    ['overreach en', OVER_EN],
  ])(
    'ER-40 rule copy matches the reviewer’s authored text in the signed review (%s)',
    (_name, review) => {
      for (const f of review.report.findings)
        expect(
          ruleFindingText(f.kind, f.status, review.report.work_language, f.probe_ids.length > 0),
        ).toBe(f.description);
    },
  );

  it('ER-41 a signed review maps to report options: conclusions, and the retrieval mode by its short name', () => {
    expect(reviewViewOptions(ROOT_ZH, 'zh')).toEqual({
      language: 'zh',
      evaluation: ROOT_ZH.evaluation,
      retrievalNote: '规则版检索',
    });
    expect(reviewViewOptions(ROOT_EN, 'en').retrievalNote).toBe('Rule-based retrieval');
    const other = { ...ROOT_EN, retrieval: { mode: 'hybrid', note: 'Uses the hybrid retriever.' } };
    expect(reviewViewOptions(other, 'en').retrievalNote).toBe('Uses the hybrid retriever.');
    const none = { ...ROOT_EN, retrieval: null, evaluation: null };
    expect(reviewViewOptions(none, 'en')).toEqual({
      language: 'en',
      evaluation: null,
      retrievalNote: undefined,
    });
    // The submitter's own note never reaches the report.
    const view = engineerReportView(ROOT_EN.report, reviewViewOptions(ROOT_EN, 'en'));
    expect(strings(view).some((s) => s.includes(ROOT_EN.impact_note ?? '~'))).toBe(false);
  });
});

describe('engineer regression report · copy', () => {
  it('ER-18 both languages carry the same non-empty keys', () => {
    const zh = Object.keys(ENGINEER_REPORT_COPY.zh).sort();
    expect(Object.keys(ENGINEER_REPORT_COPY.en).sort()).toEqual(zh);
    for (const language of ['zh', 'en'] as const)
      for (const value of Object.values(ENGINEER_REPORT_COPY[language]))
        expect(value.trim()).not.toBe('');
  });

  it('ER-19 learner-facing copy avoids internal words', () => {
    for (const language of ['zh', 'en'] as const)
      for (const value of Object.values(ENGINEER_REPORT_COPY[language]))
        expect(value).not.toMatch(
          /模拟|训练|JSON|target_fix|new_regression|claim_|waiting_model|simulat|training/i,
        );
  });
});
