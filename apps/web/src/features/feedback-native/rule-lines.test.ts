import { describe, expect, it } from 'vitest';
import { criterionLabels, type Report } from './index';
import { asFake, fakeDocument } from '../results-native/fake-dom';
import { itemDetail, renderRuleLines, ruleLines } from './rule-lines';
import { feedbackCounts } from './short-summary';

type Item = Report['items'][number];
const PREMISE = '本项仅核对明确承诺的受限范围及固定配置。';
const item = (
  criterion: string,
  explanation: string,
  label: string,
  extra: Partial<Item> = {},
): Item => ({
  criterion,
  explanation,
  label,
  source: label === 'INSUFFICIENT' ? 'pending' : 'verified_rule',
  applicability: label === 'NOT_APPLICABLE' ? 'not_applicable' : 'applicable',
  rule_bound:
    label === 'INSUFFICIENT' || label === 'NOT_APPLICABLE' ? null : { lower: label, upper: label },
  citations: [],
  ...extra,
});
const narrow: Item[] = [
  item('R3.capacity', `${PREMISE}\n按评价时点核对：固定配置人数20，有效容量30。`, 'MET'),
  item(
    'R4.staleness_test',
    `${PREMISE}\n完整记录内没有政策更新后、当前配置的相关动态复测。\n政策变更记录：有已激活变更。`,
    'NOT_MET',
  ),
  item(
    'R5.adjustment',
    `${PREMISE}\n已有相关配置调整；调整质量仍需核验。\n变更后实际相关配置调整 / 刷新 / 复测动作：2 次；次数不证明调整质量。`,
    'PARTIAL',
    { rule_bound: { lower: 'NOT_MET', upper: 'PARTIAL' } },
  ),
  item(
    'R6.alternatives',
    '核对真实的方案比较和取舍；普通文字与方案模板等价，停止也可以是备选。\n证据或语义尚未核实；保留未知，不按作品形式或未见记录判错。',
    'INSUFFICIENT',
  ),
  item(
    'R1.metrics',
    '核对与本次决定相称的成功、风险或停止标准。\n证据或语义尚未核实。',
    'INSUFFICIENT',
  ),
  item('R5.impact', '有相关变更时核对其影响；没有相关事件时本项不适用。', 'NOT_APPLICABLE'),
];

describe('feedback first screen', () => {
  it('states a premise shared by several items once and gives each checked item one line', () => {
    const view = ruleLines(narrow, criterionLabels('zh'), 'zh');
    expect(view.premises).toEqual([PREMISE]);
    expect(view.lines.map((line) => [line.mark, line.name, line.conclusion, line.fact])).toEqual([
      ['met', '人数与容量', '满足', '按评价时点核对：固定配置人数20，有效容量30。'],
      [
        'not_met',
        '政策更新后的复测',
        '未满足',
        '完整记录内没有政策更新后、当前配置的相关动态复测。',
      ],
      ['partial', '实际调整与复测', '未满足—部分满足', '已有相关配置调整；调整质量仍需核验。'],
    ]);
    expect(view.waiting).toEqual(['替代方案与取舍', '指标与验收口径']);
  });

  it('keeps the details without the shared premise and leaves other lines as recorded', () => {
    const view = ruleLines(narrow, criterionLabels('zh'), 'zh');
    expect(itemDetail(narrow[1], view.premises)).toBe(
      '完整记录内没有政策更新后、当前配置的相关动态复测。\n政策变更记录：有已激活变更。',
    );
    // A criterion-specific note is not a shared premise and stays in the details.
    expect(itemDetail(narrow[3], view.premises)).toBe(narrow[3].explanation);
    expect(itemDetail(narrow[5], view.premises)).toBe(narrow[5].explanation);
  });

  it('shows no premise when each item has its own note, and still states the finding', () => {
    const own = [
      item(
        'R3.capacity',
        '按明确承诺的用户范围与有效容量核验。\n固定配置人数20，有效容量30。',
        'MET',
      ),
      item('R3.resources', '核对当前有效承诺、获批资源和时限。\n所需/可用人日为5/3。', 'NOT_MET'),
    ];
    const view = ruleLines(own, criterionLabels('zh'), 'zh');
    expect(view.premises).toEqual([]);
    expect(view.lines.map((line) => line.fact)).toEqual([
      '固定配置人数20，有效容量30。',
      '所需/可用人日为5/3。',
    ]);
    expect(itemDetail(own[0], view.premises)).toBe(own[0].explanation);
  });

  it('uses a single-line explanation as its fact', () => {
    const view = ruleLines(
      [item('R3.capacity', '固定配置人数20，有效容量30。', 'MET')],
      criterionLabels('zh'),
      'zh',
    );
    expect(view.lines[0].fact).toBe('固定配置人数20，有效容量30。');
  });

  it('prefers a recorded submission fact when one is supplied', () => {
    const view = ruleLines(narrow, criterionLabels('zh'), 'zh', (row) =>
      row.criterion === 'R4.staleness_test' ? '配置 v2 之后还没测。' : undefined,
    );
    expect(view.lines[1].fact).toBe('配置 v2 之后还没测。');
    expect(view.lines[0].fact).toBe('按评价时点核对：固定配置人数20，有效容量30。');
  });

  it('lists and counts every criterion the way the status row does', () => {
    // Rule-checked without a recorded bound: still a checked line, marked by its finding.
    const unbound = item('R2.cost', 'note\n成本核对：已超出预算。', 'NOT_MET', {
      rule_bound: null,
    });
    const items = [...narrow, unbound];
    const view = ruleLines(items, criterionLabels('zh'), 'zh');
    const counts = feedbackCounts(items);
    expect(view.lines).toHaveLength(counts.verified);
    expect(view.waiting).toHaveLength(counts.pending + counts.undetermined);
    expect(view.lines.at(-1)).toMatchObject({
      criterion: 'R2.cost',
      mark: 'not_met',
      conclusion: '未满足',
      fact: '成本核对：已超出预算。',
    });
  });

  it('writes conclusions and names in the interface language', () => {
    const view = ruleLines(narrow, criterionLabels('en'), 'en');
    expect(view.lines.map((line) => [line.name, line.conclusion])).toEqual([
      ['Participants and capacity', 'Met'],
      ['Retesting after policy changes', 'Not met'],
      ['Actual adjustments and retesting', 'Not met—Partially met'],
    ]);
  });
});

describe('rendered first screen', () => {
  it('states the premise once, one line per checked item, then names the waiting ones', () => {
    const doc = fakeDocument();
    const node = renderRuleLines(
      doc as unknown as Document,
      ruleLines(narrow, criterionLabels('zh'), 'zh'),
      'zh',
    );
    const root = asFake(node as unknown as HTMLElement);
    expect(root.textContent.split(PREMISE).length - 1).toBe(1);
    expect(root.byTag('li').map((row) => row.textContent)).toEqual([
      '✓满足：人数与容量 · 按评价时点核对：固定配置人数20，有效容量30。',
      '✗未满足：政策更新后的复测 · 完整记录内没有政策更新后、当前配置的相关动态复测。',
      '◐未满足—部分满足：实际调整与复测 · 已有相关配置调整；调整质量仍需核验。',
    ]);
    // The status row above already counts the inapplicable items; they are not repeated here.
    expect(root.byTag('p').map((row) => row.textContent)).toEqual([
      `共同前提：${PREMISE}`,
      '待核验：替代方案与取舍、指标与验收口径',
    ]);
  });

  it('shows nothing when no item is rule-checked yet', () => {
    const pending = narrow.filter((row) => row.label === 'INSUFFICIENT');
    expect(
      renderRuleLines(
        fakeDocument() as unknown as Document,
        ruleLines(pending, criterionLabels('zh'), 'zh'),
        'zh',
      ),
    ).toBeUndefined();
  });
});
