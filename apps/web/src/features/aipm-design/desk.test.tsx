import { renderToString } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { AipmClient } from '../../aipm/client';
import type { AipmHost } from '../../aipm/host';
import type { AipmDesign, ProcessFeedback } from '../../aipm/types';
import { copy } from './copy';
import { CheckCard, DesignDesk, type DesignRead } from './desk';
import { installAipmDesign } from './install';
import { type AgentDraft, newRow, sectionCheck } from './model';

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
    readProgress: vi.fn(() => Promise.resolve(null)),
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
const agentDraft: AgentDraft = {
  id: 'd1',
  revision: 1,
  status: 'pending_owner_review',
  note: '按公司一页纸整理',
  business: { audience: 'internal', offering_explanation: 'x', task_goal: 'y' },
};

describe('AIPM design panel', () => {
  it('registers one design feature through the L1 host seam', () => {
    const host = fakeHost();
    installAipmDesign(host);
    expect(host.registerFeature).toHaveBeenCalledWith(
      'design',
      expect.objectContaining({ mount: expect.any(Function) }),
    );
    expect(host.features.design.render()).toContain('aipm-design-root');
  });
  it('opens only the current section: why, a labelled example, then a few choices', () => {
    const page = html(<DesignDesk host={fakeHost()} initial={null} step="business" />);
    expect(page.match(/aipm-design__open/g)).toHaveLength(1);
    const order = ['为什么写', '示例，不是标准答案', '这个助手服务谁'].map((t) => page.indexOf(t));
    expect(order.every((i, k) => i > 0 && (k === 0 || i > order[k - 1]))).toBe(true);
    expect(page).toContain('后面几步再填');
    expect(page).not.toContain('最后谁说了算');
  });
  it('shows an agent draft as awaiting the learner with adopt, edit and decline', () => {
    const page = html(
      <DesignDesk
        host={fakeHost()}
        initial={null}
        step="business"
        drafts={[{ ref, draft: agentDraft }]}
      />,
    );
    for (const t of [
      '来自你的 Agent · 待你确认',
      '采用',
      '修改后再用',
      '不采用',
      '按公司一页纸整理',
    ])
      expect(page).toContain(t);
  });
  it('walks triage one row at a time and keeps later choices hidden until an action is chosen', () => {
    const fresh = {
      ...read,
      design: { ...design, rows: [{ ...newRow('r2'), user_request: '解释怎样申请报销' }] },
      feedback: [],
    };
    const page = html(<DesignDesk host={fakeHost()} initial={fresh} step="boundary" />);
    expect(page).toContain('1 · 这项请求要做什么？');
    expect(page).not.toContain('2 · 交给哪种方式处理？');
    const chosen = html(<DesignDesk host={fakeHost()} initial={read} step="boundary" />);
    expect(chosen).toContain('2 · 交给哪种方式处理？');
    expect(chosen).toContain('有越权');
    expect(chosen).toContain('错的');
    expect(chosen).toContain('下一步：准备权限申请草稿');
  });
  it('keeps the English panel free of Chinese', () => {
    const page = html(
      <DesignDesk host={fakeHost('en')} initial={{ ...read, feedback: [] }} step="solution" />,
    );
    expect(page).toContain('Proposed design');
    expect(page).toContain('Open actual settings');
    expect(/[一-鿿]/.test(page.replace('报销最终批准', ''))).toBe(false);
  });
  it('renders the post-save card: wrong with its quote, never pretending a semantic verdict', () => {
    const c = copy('zh');
    const page = html(
      <CheckCard
        c={c}
        host={fakeHost()}
        check={sectionCheck('boundary', design, [violation], 'zh', 'r1')}
        next={{ label: '系统方案', go: () => {} }}
      />,
    );
    expect(page).toContain('错的');
    expect(page).toContain('Assistant has no approval authority');
    expect(page).not.toContain('对的');
    expect(page).toContain('语义待核对');
    expect(page).toContain('下一步：系统方案');
  });
});
