import { describe, expect, it } from 'vitest';
import { feedbackCoverageText } from './coverage';
import type { Report } from './index';

type Item = Report['items'][number];
const item = (criterion: string, extra: Partial<Item> = {}): Item => ({
  criterion,
  label: 'INSUFFICIENT',
  applicability: 'applicable',
  source: 'pending',
  explanation: '',
  citations: [],
  ...extra,
});
const report = (items: Item[]): Report => ({
  id: 'f1',
  version: 1,
  subject: { session_id: 's', kind: 'submission', object_id: 's1', version: 1 },
  items,
  rule_items: items,
  business_response: '',
  next_options: [],
});

// 2026-10-12 item 3: the learner sees item counts only ("已核实 3 项／共 11 项适用"), never a
// percentage; weighted coverage stays in reports.
describe('coverage line shows item counts, never a percentage', () => {
  const items = [
    item('R1.target', { source: 'verified_rule', label: 'MET' }),
    item('R1.metrics', { source: 'verified_rule', label: 'NOT_MET' }),
    item('R2.support'),
    item('R3.capacity', { applicability: 'not_applicable', label: 'NOT_APPLICABLE' }),
  ];
  it.each([
    ['zh', '已核实 2 项／共 3 项适用 · 模型建议 0 项 · 待核验 1 项'],
    ['en', 'Verified 2 of 3 applicable items · Model advice 0 · Pending verification 1'],
  ] as const)('%s', (language, text) => {
    const line = feedbackCoverageText(report(items), [], language);
    expect(line).toBe(text);
    expect(line).not.toMatch(/%|\d+\s*\/\s*\d+/);
  });
});
