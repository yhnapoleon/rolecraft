import { describe, expect, it } from 'vitest';
import { diagram, emptySections, newRow, nextDesign, visibleFeedback } from './model';
import type { AipmDesign, ObjectRef, ProcessFeedback } from '../../aipm/types';
const ref: ObjectRef = { session_id: 's', kind: 'aipm_design', object_id: 'design', version: 1 };
const row0 = {
  ...newRow('row'),
  user_request: 'Explain approval',
  target_action: 'explain' as const,
  execution_support: 'supported' as const,
};
const design: AipmDesign = { id: 'design', session_id: 's', revision: 1, rows: [row0] };
describe('AIPM design model', () => {
  it('provides exactly seven independent sections without filling invented text', () => {
    expect(Object.keys(emptySections())).toEqual([
      'business',
      'stakeholders',
      'need',
      'boundary',
      'solution',
      'assurance',
      'decision',
    ]);
    expect(Object.values(emptySections()).every((value) => value === '')).toBe(true);
  });
  it('keeps row revision on unrelated PRD edits and increments only changed choices', () => {
    expect(
      nextDesign({ ...design, prd_ref: { ...ref, kind: 'product' } }, design).rows?.[0]?.revision,
    ).toBe(1);
    expect(
      nextDesign({ ...design, rows: [{ ...row0, target_action: 'approve' }] }, design).rows?.[0]
        ?.revision,
    ).toBe(2);
    expect(nextDesign(design, design).revision).toBe(2);
    expect(nextDesign(design, design).rows?.[0]?.execution_support).toBe('unknown');
  });
  it.each(['zh', 'en'] as const)(
    'draws four routes as proposals without an execution claim (%s)',
    (language) => {
      const rows = ['deterministic', 'retrieval_generation', 'agent_confirmation', 'human'].map(
        (route, i) => ({
          ...newRow(String(i)),
          route: route as NonNullable<AipmDesign['rows']>[number]['route'],
        }),
      );
      const lanes = diagram({ ...design, rows }, language);
      expect(lanes).toHaveLength(4);
      expect(lanes.every((lane) => lane.nodes.length >= 3)).toBe(true);
      expect(lanes[2].status).toBe(
        language === 'zh' ? '执行能力待核对' : 'Execution support unknown',
      );
      expect(
        language === 'en'
          ? lanes.every((lane) => !/[\u4e00-\u9fff]/.test(lane.nodes.join('')))
          : true,
      ).toBe(true);
    },
  );
  it('marks late and locally edited feedback stale without mutating the saved record', () => {
    const item: ProcessFeedback = {
      id: 'f',
      input_ref: ref,
      step_id: 'boundary',
      source: 'rule',
      finding: 'violation',
      message: 'Permission',
      checked_scope: 'fields',
      stale: false,
    };
    expect(visibleFeedback([item], { ...ref, version: 2 }, false)[0].stale).toBe(true);
    expect(visibleFeedback([item], ref, true)[0].stale).toBe(true);
    expect(item.stale).toBe(false);
  });
});
import { designChanged, failure, findRef, rowChanged } from './model';
describe('AIPM design edits', () => {
  it('marks only the edited row as changed', () => {
    const saved = { ...design, rows: [row0, { ...newRow('other') }] };
    const edited = {
      ...saved,
      rows: [{ ...saved.rows[0], final_authority: 'named_human_role' as const }, saved.rows[1]],
    };
    expect(rowChanged(edited.rows[0], saved)).toBe(true);
    expect(rowChanged(edited.rows[1], saved)).toBe(false);
    expect(designChanged(saved, saved)).toBe(false);
    expect(designChanged(edited, saved)).toBe(true);
  });
  it('reads host write results without trusting a failed status', () => {
    expect(
      findRef({ status: 'confirmed', result: { ref: { ...ref, kind: 'product' } } }, 'product')
        ?.kind,
    ).toBe('product');
    expect(failure({ status: 'failed', result: { code: 'version_conflict' } })).toBe(
      'version_conflict',
    );
    expect(failure({ status: 'confirmed' })).toBeNull();
  });
});
import { mergeDraft, sectionCheck } from './model';
describe('AIPM section checks', () => {
  const explain = {
    ...newRow('e'),
    need_ref: 'expenses',
    target_action: 'explain' as const,
    final_authority: 'named_human_role' as const,
    execution_support: 'supported' as const,
  };
  it('only server rules say right or wrong; the rest is pending', () => {
    const ok = sectionCheck('boundary', { ...design, rows: [explain] }, [], 'zh', 'e');
    expect(ok.right).toEqual(['按当前权限，没有发现越权。']);
    expect(ok.wrong).toEqual([]);
    expect(ok.pending).toContain('语义待核对');
    const free = sectionCheck(
      'boundary',
      { ...design, rows: [{ ...explain, execution_support: 'unknown' }] },
      [],
      'en',
      'e',
    );
    expect(free.right).toEqual([]);
    expect(free.missing.join(' ')).toContain('No verified basis');
  });
  it('lists plain missing fields for a business section', () => {
    const check = sectionCheck(
      'business',
      { ...design, business: { audience: 'unknown', offering_explanation: 'x', task_goal: '' } },
      [],
      'zh',
    );
    expect(check.missing).toEqual([
      '还没选这个助手服务谁。',
      '还没写这次要帮谁解决什么。',
      '还没引用原文；有人问起时不好核对。',
    ]);
    expect(check.right).toEqual([]);
  });
  it('adopting a draft upserts by id and leaves execution support to the server', () => {
    const merged = mergeDraft(
      { ...design, rows: [row0] },
      {
        id: 'd',
        revision: 1,
        status: 'pending_owner_review',
        rows: [{ ...row0, target_action: 'approve' }, newRow('new')],
      },
    );
    expect(merged.rows?.map((r) => [r.id, r.target_action, r.execution_support])).toEqual([
      ['row', 'approve', 'unknown'],
      ['new', 'unknown', 'unknown'],
    ]);
  });
});
