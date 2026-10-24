import { describe, expect, it } from 'vitest';
import fixedEn from '../../../public/engineer/target-fixed-no-new-failures.en.json';
import fixedZh from '../../../public/engineer/target-fixed-no-new-failures.zh.json';
import notFixedEn from '../../../public/engineer/target-not-fixed-new-failures.en.json';
import notFixedZh from '../../../public/engineer/target-not-fixed-new-failures.zh.json';
import { ENGINEER_REPORT_COPY } from './copy';
import type { EngineerFinding, EngineerPublicReport } from './types';
import { engineerReportView, ruleFindingText, type EngineerReportView } from './view';

const sample = (raw: unknown) => raw as EngineerPublicReport;
const FIXED_ZH = sample(fixedZh);
const NOT_FIXED_ZH = sample(notFixedZh);
const FIXED_EN = sample(fixedEn);
const NOT_FIXED_EN = sample(notFixedEn);
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
      title: '目标问题已修好',
      detail: '按冻结预期通过。',
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
    expect(view.verdict).toMatchObject({
      state: 'not_fixed',
      tone: 'bad',
      title: '目标问题没修好',
      detail: '仍未通过：期望带提醒回答，实际没有给出回答。',
      targets: ['住宿报销上限是多少？'],
    });
    expect(view.publicSection.tally).toBe('通过 1 · 未通过 3');
    expect(
      view.publicSection.rows.map((r) => [r.id, r.tone, r.tags.map((t) => t.text), r.diff]),
    ).toEqual([
      ['F01', 'bad', ['目标', '改前也未通过'], '期望带提醒回答，实际没有给出回答'],
      ['F04', 'bad', ['新增失败'], '期望转人工，实际没有给出回答'],
      ['F05', 'bad', ['新增失败'], '期望转人工，实际没有给出回答'],
      ['F12', 'good', [], undefined],
    ]);
    expect(view.hiddenSection.counts.map((c) => c.value)).toEqual([4, 5, 0]);
    expect(view.checks.lines.map((l) => [l.tone, l.status])).toEqual([
      ['bad', '公开探针新增失败 2 条'],
      ['bad', '自报结果与实际不符'],
    ]);
  });

  it('ER-03 English samples read in English, with the same facts', () => {
    const fixed = engineerReportView(FIXED_EN, { language: 'en', timeZone: SG });
    expect(fixed.verdict.title).toBe('Target fixed');
    expect(fixed.verdict.targets).toEqual(['I forgot my account password. How do I reset it?']);
    expect(fixed.publicSection.rows[0].diff).toBe(
      'Expected an answer with a warning, got a direct answer; cites the travel policy v1 (now v2)',
    );
    expect(fixed.publicSection.rows[0].tags.map((t) => t.text)).toEqual(['Also failed before']);
    expect(fixed.hiddenSection.note).toBe('Hidden probes report counts only.');
    expect(fixed.advice.text).toBe('Model advice: waiting for model integration');
    const notFixed = engineerReportView(NOT_FIXED_EN, { language: 'en', timeZone: SG });
    expect(notFixed.verdict.detail).toBe(
      'Still failing: expected an answer with a warning, got no answer.',
    );
    expect(notFixed.checks.lines[0].status).toBe('New failures in public probes: 2');
    expect(notFixed.checks.lines[1].status).toBe('Self-report does not match the actual results');
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
    expect(engineerReportView(FIXED_ZH, { language: 'en' }).publicSection.sourceNote).toBe(
      'Chinese source',
    );
    expect(engineerReportView(FIXED_EN, { language: 'zh' }).publicSection.sourceNote).toBe(
      '英文原文',
    );
  });
});

describe('engineer regression report · states', () => {
  it('ER-06 target not yet verified when the public report carries no target result', () => {
    const none = engineerReportView(
      withReport({ findings: FIXED_ZH.findings.filter((f) => f.kind !== 'target_fix') }),
      { language: 'zh' },
    );
    expect(none.verdict).toMatchObject({
      state: 'unknown',
      tone: 'unknown',
      title: '目标问题待核',
      detail: '这份公开报告里没有目标问题的核验结果。',
      targets: [],
    });
    const unmatched = engineerReportView(
      withReport({ findings: [finding('target_fix', 'unverified')] }),
      {
        language: 'en',
      },
    );
    expect(unmatched.verdict.title).toBe('Target not yet verified');
    expect(unmatched.verdict.detail).toBe(
      'Some target tests have no matching trusted suite expectation.',
    );
  });

  it('ER-07 several targets: one still failing means not fixed, with a count', () => {
    const view = engineerReportView(
      withReport({
        findings: [finding('target_fix', 'pass', ['F12']), finding('target_fix', 'fail', ['F01'])],
      }),
      { language: 'zh' },
    );
    expect(view.verdict.state).toBe('not_fixed');
    expect(view.verdict.detail).toBe('2 个目标里 1 个还没修好。');
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
      ['新增失败', 1, 'bad'],
      ['修好', 2, 'good'],
      ['仍未通过', 3, 'unknown'],
      ['未核实', 0, 'unknown'],
    ]);
    expect(view.checks.lines[0]).toMatchObject({
      tone: 'bad',
      status: '新增失败 1 条（公开 0 · 隐藏 1）',
    });
    const clean = engineerReportView(
      withReport({
        hidden_comparison: { new_failures: 0, fixed: 0, still_failing: 4, unverified: 0 },
      }),
      { language: 'en' },
    );
    expect(clean.hiddenSection.comparison?.map((c) => c.tone)).toEqual([
      'unknown',
      'unknown',
      'unknown',
      'unknown',
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
      engineerReportView(FIXED_ZH, { language: 'zh', evaluation: [] }).evaluation,
    ).toBeUndefined();
    const view = engineerReportView(FIXED_ZH, {
      language: 'zh',
      evaluation: [
        { id: 'E1.target_fixed', label: 'MET', basis: 'rule' },
        { id: 'E2.no_regressions', label: 'NOT_MET', basis: 'rule' },
        { id: 'E3.change_consistency', label: 'PARTIAL', basis: 'rule' },
        { id: 'E4.reproducibility', label: 'INSUFFICIENT', basis: 'rule' },
        { id: 'E5.remaining_explanation', label: null, basis: 'rule', status: 'waiting_model' },
        { id: 'E9.unknown_code', label: 'NOT_APPLICABLE', basis: 'rule' },
      ],
    });
    expect(view.evaluation?.title).toBe('评价结论');
    expect(view.evaluation?.rows.map((r) => [r.title, r.labelText, r.tone, r.mark])).toEqual([
      ['目标失败已修复', '满足', 'good', 'met'],
      ['无回归', '未满足', 'bad', 'not_met'],
      ['修改说明与配置差异一致', '部分满足', 'ink', 'partial'],
      ['报告可复现', '还不知道', 'unknown', 'unknown'],
      ['对未修复项有说明', '等待模型核验', 'unknown', 'waiting'],
      ['评价项', '不适用', 'unknown', 'not_applicable'],
    ]);
    expect(strings(view)).not.toContain('E9.unknown_code');
    const en = engineerReportView(FIXED_ZH, {
      language: 'en',
      evaluation: [
        { id: 'E5.remaining_explanation', label: null, basis: 'rule', status: 'waiting_model' },
      ],
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
