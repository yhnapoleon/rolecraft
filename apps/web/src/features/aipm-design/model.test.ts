import { describe, expect, it } from 'vitest';
import { diagram, emptySections, escape, newRow, nextDesign, visibleFeedback } from './model';
import type { AipmDesign, ObjectRef, ProcessFeedback } from '../../aipm/types';
const ref: ObjectRef = { session_id: 's', kind: 'aipm_design', object_id: 'design', version: 1 };
const design: AipmDesign = { id: 'design', session_id: 's', revision: 1, rows: [{ ...newRow('row'), user_request: 'Explain approval', target_action: 'explain', execution_support: 'supported' }] };
describe('AIPM design model', () => {
  it('provides exactly seven independent sections without filling invented text', () => {
    expect(Object.keys(emptySections())).toEqual(['business','stakeholders','need','boundary','solution','assurance','decision']);
    expect(Object.values(emptySections()).every(value => value === '')).toBe(true);
  });
  it('keeps row revision on unrelated PRD edits and increments only changed choices', () => {
    expect(nextDesign({ ...design, prd_ref: { ...ref, kind: 'product' } }, design).rows![0].revision).toBe(1);
    expect(nextDesign({ ...design, rows: [{ ...design.rows![0], target_action: 'approve' }] }, design).rows![0].revision).toBe(2);
    expect(nextDesign(design, design).revision).toBe(2);
    expect(nextDesign(design, design).rows![0].execution_support).toBe('unknown');
  });
  it.each(['zh','en'] as const)('draws four routes as proposals without an execution claim (%s)', language => {
    const rows = ['deterministic','retrieval_generation','agent_confirmation','human'].map((route, i) => ({ ...newRow(String(i)), route: route as NonNullable<AipmDesign['rows']>[number]['route'] }));
    const lanes = diagram({ ...design, rows }, language);
    expect(lanes).toHaveLength(4);
    expect(lanes.every(lane => lane.nodes.length >= 3)).toBe(true);
    expect(lanes[2].status).toBe(language === 'zh' ? '执行能力待核对' : 'Execution support unknown');
    expect(language === 'en' ? lanes.every(lane => !/[\u4e00-\u9fff]/.test(lane.nodes.join(''))) : true).toBe(true);
  });
  it('marks late and locally edited feedback stale without mutating the saved record', () => {
    const item: ProcessFeedback = { id: 'f', input_ref: ref, step_id: 'boundary', source: 'rule', finding: 'violation', message: 'Permission', checked_scope: 'fields', stale: false };
    expect(visibleFeedback([item], { ...ref, version: 2 }, false)[0].stale).toBe(true);
    expect(visibleFeedback([item], ref, true)[0].stale).toBe(true);
    expect(item.stale).toBe(false);
  });
  it('escapes work and tool names before native HTML rendering', () => { expect(escape('<img onerror="x">')).toBe('&lt;img onerror=&quot;x&quot;&gt;'); });
});
