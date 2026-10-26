import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { renderToString } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { StepId } from '../../aipm/types';
import type { DesignContent } from './sheet-model';
import { sendQuote, Worksheet, type WorksheetHost } from './worksheet';

const content = (language: 'zh' | 'en') =>
  JSON.parse(
    readFileSync(
      join(
        resolve(__dirname, '../../../../../scenarios/pm_pilot/aipm-phase1/public'),
        `design.${language}.json`,
      ),
      'utf8',
    ),
  ) as DesignContent;
const html = (node: React.ReactElement) => renderToString(node).replaceAll('<!-- -->', '');
/** FAKE DATA: a host for render tests only. */
const host = (language: 'zh' | 'en' = 'zh') =>
  ({
    getSessionContext: () => ({
      sessionId: 's',
      workLanguage: language,
      scenarioHash: 'x',
      asOf: null,
      readOnly: false,
    }),
    getDataHost: () => null,
    getClient: () => null,
    readProgress: vi.fn(),
    readGuide: vi.fn(() => Promise.resolve({})),
    command: vi.fn(),
    openMaterial: vi.fn(),
    openColleague: vi.fn(),
    openFeature: vi.fn(),
  }) as unknown as WorksheetHost;
const preload = (language: 'zh' | 'en', extra: object = {}) => ({
  content: content(language),
  saved: null,
  prd: null,
  drafts: [],
  titles: { demand: '支持台导出 SD-120' },
  ...extra,
});
const STEPS: StepId[] = [
  'business',
  'stakeholders',
  'need',
  'boundary',
  'solution',
  'assurance',
  'decision',
];

describe('worksheet', () => {
  it.each(STEPS)(
    '%s: one goal, angles, at most one choice and one big box, no sub-questions',
    (step) => {
      const page = html(<Worksheet host={host()} step={step} preload={preload('zh')} />);
      expect(page).toContain(content('zh').sheets[step].goal);
      expect(page).toContain('可以从这些角度入手');
      expect((page.match(/aipm-sheet__choice/g) ?? []).length).toBeLessThanOrEqual(1);
      expect((page.match(/aipm-sheet__paper"/g) ?? []).length).toBe(1);
      expect(page).not.toMatch(/问题 ?[1-9]|Question [1-9]/);
      for (const label of ['让我的 Agent 帮我写', '保存这一版', '请同事看看', '交给批改'])
        expect(page).toContain(label);
    },
  );
  it('shows structure blocks only on need (metric), boundary, solution and assurance', () => {
    const with_ = STEPS.filter((s) =>
      html(<Worksheet host={host()} step={s} preload={preload('zh')} />).includes(
        'aipm-sheet__structure',
      ),
    );
    expect(with_).toEqual(['need', 'boundary', 'solution', 'assurance']);
  });
  it('lists the solution choice from the learner’s own subheadings', () => {
    const prd = {
      ref: { session_id: 's', kind: 'product', object_id: 'prd', version: 3 },
      sections: { solution: '### 先做规则问答\n\n### 接入排班系统' },
    };
    const page = html(<Worksheet host={host()} step="solution" preload={preload('zh', { prd })} />);
    expect(page).toContain('先做规则问答');
    expect(page).toContain('接入排班系统');
    expect(page).toContain('已存第 3 版');
  });
  it('shows an agent section draft as awaiting the learner, with its id', () => {
    const drafts = [
      {
        ref: { session_id: 's', kind: 'aipm_design_draft', object_id: 'd1', version: 2 },
        draft: {
          id: 'd1',
          revision: 2,
          status: 'pending_owner_review',
          prd_sections: { need: 'Agent 写的段落' },
        },
      },
    ];
    const page = html(<Worksheet host={host()} step="need" preload={preload('zh', { drafts })} />);
    expect(page).toContain('data-draft-id="d1"');
    expect(page).toContain('来自你的 Agent · 待你确认');
    expect(page).toContain('采用');
    expect(page).toContain('不用');
    expect(
      html(<Worksheet host={host()} step="business" preload={preload('zh', { drafts })} />),
    ).not.toContain('data-draft-id');
  });
  it('links the last review and keeps angle hints hidden until hover', () => {
    const openReview = vi.fn();
    const withReview = { ...host(), openReview } as unknown as WorksheetHost;
    const last = {
      at: '2026-10-26T15:44:00Z',
      version: 1,
      ref: { session_id: 's', kind: 'aipm_section_review', object_id: 'r', version: 1 },
    };
    const page = html(
      <Worksheet host={withReview} step="need" preload={preload('zh', { lastReview: last })} />,
    );
    expect(page).toMatch(/class="aipm-sheet__review-link"[^>]*>上次批改 .* · 第 1 版 ›</);
    expect(page).toContain('role="tooltip"');
    expect(page).not.toContain('data-show="true"');
  });
  it('reports that a quote was not delivered when no sheet is open', () => {
    const ref = {
      session_id: 's',
      kind: 'material',
      object_id: 'demand',
      version: 1,
      observed_at_seq: 0,
      quote: 'x',
    };
    expect(sendQuote(ref, '《SD-120》v1')).toBe(false);
  });
  it('keeps the English sheet free of Chinese', () => {
    for (const step of STEPS) {
      const page = html(
        <Worksheet host={host('en')} step={step} preload={preload('en', { titles: {} })} />,
      );
      expect(/[一-鿿]/.test(page), step).toBe(false);
    }
  });
});
