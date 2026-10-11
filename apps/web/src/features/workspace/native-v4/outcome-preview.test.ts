import { describe, expect, it, vi } from 'vitest';
import { outcomeTables } from './outcome-copy';
import { outcomeView, previewEntries, type PreviewEntry } from './outcome-preview';
import type { FeedbackV2, _PreviewState } from '../../../contracts-v2';
import { regionHost } from '../../../v4-region-test-support';
import { WorkspaceSlotController } from './slot-controller';

const at = { business_seq: 3, workspace_revision: 2, storage_revision: 4 };
const ref = (kind: string, id: string, version = 1, config_version: number | null = null) => ({
  session_id: 's',
  kind,
  object_id: id,
  version,
  config_version,
});
const preview = (version: number, extra: Partial<FeedbackV2> = {}): FeedbackV2 => ({
  id: `f${version}`,
  session_id: 's',
  version: 1,
  subject: ref('product', 'p', version),
  evaluation: { path: 'runtime/evaluation.json', sha256: 'a'.repeat(64) },
  as_of: at,
  items: [],
  business_response: '未执行业务动作。',
  next_options: [],
  verified_coverage: 0,
  model_coverage: 0,
  preview_kind: 'rules',
  preview_language: 'zh',
  generation_status: 'waiting_model',
  basis_refs: [ref('product', 'p', version), ref('config', 'pilot', 1, 0)],
  clarification: ['「确认需求」的决定依据哪些资料或测试结果？'],
  missing_inputs: ['decision_evidence'],
  available_actions: [
    { operation: 'submissions.create', objects: [ref('product', 'p', version)] },
    { operation: 'configuration.apply', objects: [ref('config', 'pilot', 1, 0)] },
    { operation: 'work_products.shares.create', objects: [ref('product', 'p', version)] },
  ],
  outcomes: [
    {
      id: 'saved-input-1',
      kind: 'fact',
      summary: '已核实保存的作品版本（规则核实）。',
      basis_refs: [{ ...ref('product', 'p', version), observed_at_seq: 3 }],
    },
    {
      id: 'submission',
      kind: 'conditional_prediction',
      summary: '若明确提交，交付将固定这份作品第 1 版和第 0 版配置。',
      basis_refs: [{ ...ref('product', 'p', version), observed_at_seq: 3 }],
      conditions: ['提交前作品与配置保持不变。'],
      values: { version, config_version: 0 },
    },
    {
      id: 'acceptance',
      kind: 'pending_verification',
      summary: '经理是否接受、业务是否达成要在提交和评审后才能知道。',
      missing_inputs: ['submission_review'],
    },
  ],
  ...extra,
});
const state = (version: number, extra: Partial<_PreviewState> = {}): _PreviewState => ({
  feedback: ref('feedback', `f${version}`),
  status: 'current',
  changes: [],
  actual: [],
  superseded_by: null,
  checked_at: at,
  ...extra,
});
const stale = state(1, {
  status: 'stale',
  changes: [
    { condition: 'configuration', before: 0, after: 1, ref: ref('config', 'pilot', 2, 1) },
    { condition: 'materials', before: { demo: 1 }, after: { demo: 2 } },
    { condition: 'resources', before: { capacity: 30 }, after: { capacity: 60 } },
  ],
  actual: [
    {
      operation: 'configuration.apply',
      ref: ref('config', 'pilot', 2, 1),
      status: 'applied',
      values: { config_version: 1, changed: { participants: 30 } },
    },
    {
      operation: 'actions',
      ref: ref('business_request', 'r', 2),
      status: 'approved',
      at,
      values: { requested: { capacity: 60 }, granted: { capacity: 60 } },
    },
    {
      operation: 'tests.create',
      ref: ref('test', 't'),
      status: 'answered',
      at,
      values: { config_version: 1, count: 2 },
    },
    {
      operation: 'work_products.shares.create',
      ref: ref('share', 'sh'),
      status: 'shared',
      at,
      values: { recipient_role: 'supervisor', version: 1, count: 1 },
    },
  ],
});
const all = () => true;
const entries = (...rows: [FeedbackV2, _PreviewState][]): PreviewEntry[] =>
  rows.map(([preview, state]) => ({ preview, state }));

describe('outcome preview model', () => {
  it('OUT-UI-01: summary first with version, rule status and the clarification', () => {
    const view = outcomeView(
      entries([preview(1), state(1)]),
      { version: 1, hasDraft: false },
      'zh',
      all,
    );
    expect(view?.main.heading).toBe('outcome 预览');
    expect(view?.main.version).toBe('按第 1 版计算');
    expect(view?.main.meta).toEqual(['规则核实', '语义判断：等待模型接入']);
    expect(view?.main.statusLabel).toBe('当前预览');
    expect(view?.main.questions).toEqual(['「确认需求」的决定依据哪些资料或测试结果？']);
    expect(view?.main.outcomes.map((o) => o.label)).toEqual(['事实', '条件预测', '待核验']);
    expect(view?.main.outcomes[2].waitsFor).toBe('提交并经过评审');
    expect(view?.main.basis).toBe('依据：已保存的第 1 版 · 第 0 版试点配置');
    expect(view?.earlier).toEqual([]);
  });

  it('OUT-UI-02: an earlier preview is labelled stale with every changed condition', () => {
    for (const [language, label, lines] of [
      [
        'zh',
        '旧预览，条件已变',
        ['试点配置第 0 版 → 第 1 版', '「演示日程」有新版本 v2', '资源变化：容量 30 → 60'],
      ],
      [
        'en',
        'Earlier preview, conditions changed',
        [
          'Pilot configuration v0 → v1',
          '“Demo schedule” has a new version: v2',
          'Resources changed: capacity 30 → 60',
        ],
      ],
    ] as const) {
      const view = outcomeView(
        entries([preview(1), stale]),
        { version: 1, hasDraft: false },
        language,
        all,
        { demo: language === 'en' ? 'Demo schedule' : '演示日程' },
      );
      expect(view?.main.status).toBe('stale');
      expect(view?.main.statusLabel).toBe(label);
      expect(view?.main.changes).toEqual(lines);
      expect(view?.main.refreshHint).toBeTruthy();
    }
  });

  it('OUT-UI-03: actual results sit beside the unchanged prediction', () => {
    const zh = outcomeView(
      entries([preview(1), stale]),
      { version: 1, hasDraft: false },
      'zh',
      all,
    );
    expect(zh?.main.actual).toEqual([
      '已应用第 1 版试点配置：试点人数 30',
      '资源申请已批准：容量 60',
      '已运行测试 2 次，最近一次已回答（第 1 版配置）',
      '第 1 版已分享给经理',
    ]);
    expect(zh?.main.outcomes[1].summary).toBe(
      '若明确提交，交付将固定这份作品第 1 版和第 0 版配置。',
    );
    const en = outcomeView(
      entries([preview(1), stale]),
      { version: 1, hasDraft: false },
      'en',
      all,
    );
    expect(en?.main.actual).toEqual([
      'Pilot configuration v1 applied: pilot users 30',
      'Resource request approved: capacity 60',
      'Test runs: 2; latest answered (configuration v1)',
      'v1 shared with the manager',
    ]);
  });

  it('OUT-UI-04: links open existing tools only when available; nothing is executed here', () => {
    const view = outcomeView(
      entries([preview(1), state(1)]),
      { version: 1, hasDraft: false },
      'en',
      all,
    );
    expect(view?.main.links).toEqual([
      { action: 'submit', label: 'Go to submission' },
      { action: 'config', label: 'Adjust pilot settings' },
    ]);
    const closed = outcomeView(
      entries([preview(1), state(1)]),
      { version: 1, hasDraft: false },
      'en',
      () => false,
    );
    expect(closed?.main.links).toEqual([]);
  });

  it('OUT-11: a newer saved version without its own preview keeps the old one, marked old', () => {
    const superseded = state(1, {
      status: 'stale',
      changes: [{ condition: 'input', before: 1, after: 2, ref: ref('product', 'p', 2) }],
    });
    const view = outcomeView(
      entries([preview(1), superseded]),
      { version: 2, hasDraft: true },
      'zh',
      all,
    );
    expect(view?.main.version).toBe('按第 1 版计算');
    expect(view?.main.changes).toEqual(['这份作品已保存第 2 版（预览按第 1 版）']);
    expect(view?.main.draftNote).toBe('预览对应已保存的第 1 版；草稿里未保存的修改不在其中。');
    const both = outcomeView(
      entries(
        [preview(1), { ...superseded, superseded_by: ref('feedback', 'f2') }],
        [preview(2), state(2)],
      ),
      { version: 2, hasDraft: false },
      'zh',
      all,
    );
    expect(both?.main.version).toBe('按第 2 版计算');
    expect(both?.earlier.map((row) => [row.label, row.view.statusLabel])).toEqual([
      ['第 1 版的预览', '旧预览，条件已变'],
    ]);
    expect(both?.earlier[0].view.newer).toBe('较新的版本已有自己的预览。');
    expect(both?.earlier[0].view.links).toEqual([]);
  });

  it('OUT-15: an absent model never reads as a semantic result', () => {
    const failed = outcomeView(
      entries([preview(1, { generation_status: 'failed' }), state(1)]),
      { version: 1, hasDraft: false },
      'en',
      all,
    );
    expect(failed?.main.meta).toEqual([
      'Rule-checked',
      'Semantic judgement: model check did not complete',
    ]);
    const none = outcomeView(
      entries([preview(1, { clarification: [] }), state(1)]),
      { version: 1, hasDraft: false },
      'en',
      all,
    );
    expect(none?.main.questions).toEqual([]);
  });

  it('reads only previews of this exact product and keeps their states aligned', () => {
    const page = { previews: [preview(1)], preview_states: [state(1)] };
    expect(previewEntries(page, 's', 'p').map((entry) => entry.state?.status)).toEqual(['current']);
    expect(previewEntries({ items: [] }, 's', 'p')).toEqual([]);
    expect(() => previewEntries(page, 'other', 'p')).toThrow('invalid_preview');
    expect(() => previewEntries(page, 's', 'q')).toThrow('invalid_preview');
    expect(() =>
      previewEntries({ previews: [preview(1)], preview_states: [state(2)] }, 's', 'p'),
    ).toThrow('invalid_preview_state');
  });

  it('keeps identical zh/en key sets for authored copy', () => {
    expect(Object.keys(outcomeTables.en).sort()).toEqual(Object.keys(outcomeTables.zh).sort());
    expect(Object.keys(outcomeTables.enTerms).sort()).toEqual(
      Object.keys(outcomeTables.zhTerms).sort(),
    );
  });

  it('OUT-08: previews are read from the versions list only, across pages, with no command', async () => {
    const host = regionHost();
    const row = (version: number) => ({
      session_id: 's',
      product_id: 'p',
      version,
      title: 'Decision',
      content: 'Draft',
      visibility: 'private',
    });
    const pageOf = (version: number, next: number | null) => ({
      schema_version: 2,
      items: [row(version)],
      as_of: at,
      next_cursor: next,
      shares: [],
      sharing_complete: true,
      previews: [preview(version)],
      preview_states: [state(version)],
    });
    vi.mocked(host.query).mockImplementation(
      async (_operation, input) =>
        ((input as { cursor?: number }).cursor ? pageOf(2, null) : pageOf(1, 1)) as never,
    );
    const read = await new WorkspaceSlotController(host).previews('p');
    expect(read.map((entry) => entry.preview.subject.version)).toEqual([1, 2]);
    expect(vi.mocked(host.query).mock.calls.map((call) => call[0])).toEqual([
      'work_products.versions.list',
      'work_products.versions.list',
    ]);
    expect(host.command).not.toHaveBeenCalled();
    expect(host.retry).not.toHaveBeenCalled();
  });

  it('OUT-14: withheld conditions read only as changed; P2-2 carried preview is noted', () => {
    const withheld = state(1, {
      status: 'stale',
      changes: [{ condition: 'resources' }, { condition: 'materials' }],
    });
    for (const [language, lines] of [
      ['zh', ['资源有变化', '资料有变化']],
      ['en', ['Resources changed', 'Materials changed']],
    ] as const)
      expect(
        outcomeView(entries([preview(1), withheld]), { version: 1, hasDraft: false }, language, all)
          ?.main.changes,
      ).toEqual(lines);
    const carried = outcomeView(
      entries([preview(1), state(1)]),
      { version: 2, hasDraft: false },
      'zh',
      all,
    );
    expect(carried?.main.statusLabel).toBe('当前预览');
    expect(carried?.main.carried).toBe('第 2 版内容与此相同，这条预览仍适用。');
    const exact = outcomeView(
      entries([preview(1), state(1)]),
      { version: 1, hasDraft: false },
      'en',
      all,
    );
    expect(exact?.main.carried).toBeNull();
  });
});
