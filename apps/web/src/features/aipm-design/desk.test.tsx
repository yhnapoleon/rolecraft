import { renderToString } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { AipmClient } from '../../aipm/client';
import type { AipmHost } from '../../aipm/host';
import type { AipmDesign, ProcessFeedback } from '../../aipm/types';
import { DesignDesk, type DesignRead } from './desk';
import { installAipmDesign } from './install';
import { newRow } from './model';

const html = (node: React.ReactElement) => renderToString(node).replaceAll('<!-- -->', '');

/** FAKE DATA for component tests only; never a fallback for the real host. */
function fakeHost(language: 'zh' | 'en' = 'zh') {
  const features: Record<string, unknown> = {};
  return {
    getSessionContext: () => ({
      sessionId: 's',
      workLanguage: language,
      scenarioHash: 'fake',
      asOf: null,
      readOnly: false,
    }),
    getDataHost: () => null,
    getClient: () => null,
    readProgress: vi.fn(),
    readGuide: vi.fn(),
    command: vi.fn(),
    recover: vi.fn(),
    openMaterial: vi.fn(),
    openWork: vi.fn(),
    openColleague: vi.fn(),
    openSettings: vi.fn(),
    requestReview: vi.fn(),
    createWorkVersion: vi.fn(),
    refresh: vi.fn(),
    registerFeature: vi.fn((id: string, f: unknown) => {
      features[id] = f;
      return () => {};
    }),
    openFeature: vi.fn(),
    features,
  } as unknown as AipmHost<unknown, AipmClient> & {
    features: Record<string, { render(): string }>;
  };
}
const ref = { session_id: 's', kind: 'aipm_design', object_id: 'aipm-design', version: 1 };
const design: AipmDesign = {
  id: 'aipm-design',
  session_id: 's',
  revision: 1,
  rows: [
    {
      ...newRow('r1'),
      need_ref: 'expenses',
      user_request: '报销最终批准',
      target_action: 'approve',
      final_authority: 'ai',
      route: 'agent_confirmation',
      execution_support: 'plan_only',
    },
  ],
};
const violation: ProcessFeedback = {
  id: 'f1',
  input_ref: ref,
  step_id: 'boundary',
  section_or_row_id: 'r1',
  source: 'rule',
  finding: 'violation',
  message: '你把最终批准交给了 AI；当前助手没有审批权限。',
  checked_scope: '仅核对所选最终动作与当前审批权限。',
  basis_refs: [
    { ...ref, kind: 'material', observed_at_seq: 1, quote: 'Assistant has no approval authority' },
  ],
  stale: false,
};
const read: DesignRead = { ref, design, feedback: [violation] };

describe('AIPM design desk', () => {
  it('registers one design feature through the L1 host seam', () => {
    const host = fakeHost();
    installAipmDesign(host);
    expect(host.registerFeature).toHaveBeenCalledWith(
      'design',
      expect.objectContaining({ render: expect.any(Function), mount: expect.any(Function) }),
    );
    expect(host.features.design.render()).toContain('aipm-design-root');
  });
  it('shows the saved row with its rule feedback, label and quoted basis', () => {
    const page = html(<DesignDesk host={fakeHost()} initial={read} />);
    expect(page).toContain('规则核实 · 越过当前权限');
    expect(page).toContain('当前助手没有审批权限');
    expect(page).toContain('Assistant has no approval authority');
    expect(page).toContain('仅方案：本局没有执行能力');
    expect(page).not.toContain('已修改，保存后重新核对');
  });
  it('draws the saved version as proposed and keeps actual settings separate (en)', () => {
    const page = html(
      <DesignDesk host={fakeHost('en')} initial={{ ...read, feedback: [] }} initialTab="diagram" />,
    );
    expect(page).toContain('Drawn from saved version 1');
    expect(page).toContain('Proposal only; execution unavailable');
    expect(page).toContain('Open actual settings');
    expect(/[一-鿿]/.test(page.replace('报销最终批准', ''))).toBe(false);
  });
  it('lists all seven PRD sections in order', () => {
    const all = html(<DesignDesk host={fakeHost()} initial={null} initialTab="prd" />);
    const page = all.slice(all.indexOf('aipm-design__prd'));
    const order = [
      '看懂业务',
      '用户与相关方',
      '验证真需求',
      'AI 边界',
      '系统方案',
      '评测、监控与回退',
      '上线决策',
    ].map((t) => page.indexOf(t));
    expect(order.every((i, k) => i > 0 && (k === 0 || i > order[k - 1]))).toBe(true);
  });
});
