import { describe, expect, it } from 'vitest';
import { readCatalog, referenceLabel } from './reference-catalog';

const ref = (kind: string, object_id: string, version = 1, extra: object = {}) => ({
  session_id: 's',
  kind,
  object_id,
  version,
  ...extra,
});
const object = (kind: string, id: string, content: object) => ({ ref: ref(kind, id), content });
// The timeline read as the host returns it (V2Response envelope).
const timeline = {
  schema_version: 2,
  result: {
    objects: [
      object('test', 't1', { query: '住宿报销上限是多少？' }),
      object('config', 'pilot', { config_version: 1 }),
      object('test', 't2', { query: '住宿报销上限是多少？' }),
      object('test', 't3', { query: '请假要提前几天申请？' }),
      object('submission', 'sub-1', {}),
      object('submission', 'sub-2', {}),
    ],
    events: [
      {
        id: 'ev-5',
        seq: 5,
        type: 'initial_plan_applied',
        refs: [],
        data: { before_versions: { policy: 1 }, after_versions: { policy: 2 } },
      },
      { id: 'ev-7', seq: 7, type: 'submitted', refs: [ref('submission', 'sub-1')], data: {} },
      { id: 'ev-9', seq: 9, type: 'submitted', refs: [ref('submission', 'sub-2')], data: {} },
    ],
    workspace: {
      material_titles: {
        'policy:1': '差旅住宿与交通政策',
        'policy:2': '费用管理通知：差旅住宿标准',
      },
    },
  },
};
const products = [
  { product_id: 'p1', version: 1, title: '试点决定草稿' },
  { product_id: 'p1', version: 2, title: '试点决定草稿' },
];
const catalog = readCatalog(timeline, products);

describe('evidence names the object and its version', () => {
  it('names documents, test runs, work, settings, deliveries and history in Chinese', () => {
    const text = (value: ReturnType<typeof ref>) => referenceLabel(value, catalog, 'zh').text;
    expect(text(ref('material', 'policy', 2))).toBe('费用管理通知：差旅住宿标准 · v2');
    // A document keeps its current name; the version says which one is meant.
    expect(text(ref('material', 'policy', 1))).toBe('差旅住宿与交通政策 · v1');
    expect(text(ref('test', 't2'))).toBe('测试：住宿报销上限是多少？ · 第 2 次');
    expect(text(ref('test', 't3'))).toBe('测试：请假要提前几天申请？ · 第 1 次');
    expect(text(ref('product', 'p1', 2))).toBe('作品《试点决定草稿》· v2');
    expect(text(ref('config', 'pilot', 3, { config_version: 2 }))).toBe('配置 v2');
    expect(text(ref('submission', 'sub-2'))).toBe('第 2 次交付');
    expect(text(ref('event', 'ev-5'))).toBe('资料更新：《费用管理通知：差旅住宿标准》v2');
  });

  it('names them in English too', () => {
    const text = (value: ReturnType<typeof ref>) => referenceLabel(value, catalog, 'en').text;
    expect(text(ref('material', 'policy', 2))).toBe('费用管理通知：差旅住宿标准 · v2');
    expect(text(ref('test', 't1'))).toBe('Test: 住宿报销上限是多少？ · run 1');
    expect(text(ref('product', 'p1', 1))).toBe('Work “试点决定草稿” · v1');
    expect(text(ref('config', 'pilot', 3, { config_version: 2 }))).toBe('Config v2');
    expect(text(ref('submission', 'sub-1'))).toBe('Delivery 1');
  });

  it('gives screen readers the full name with the action', () => {
    const long = readCatalog({
      objects: [
        object('test', 'long', {
          query: '如果员工出差时住在客户安排的酒店，超出标准的部分应该怎样报销？',
        }),
      ],
    });
    const label = referenceLabel(ref('test', 'long'), long, 'zh');
    expect(label.text.length).toBeLessThan(label.label.length);
    expect(label.text).toContain('…');
    expect(label.full).toBe(
      '测试：如果员工出差时住在客户安排的酒店，超出标准的部分应该怎样报销？ · 第 1 次',
    );
    expect(label.label).toBe(`打开依据：${label.full}`);
    expect(referenceLabel(ref('material', 'policy', 2), catalog, 'en').label).toBe(
      'Open evidence: 费用管理通知：差旅住宿标准 · v2',
    );
    const english = readCatalog({
      workspace: { material_titles: { 'policy:1': 'Travel policy: hotels and taxis' } },
    });
    expect(referenceLabel(ref('material', 'policy', 1), english, 'en').text).toBe(
      'Travel policy: hotels and taxis · v1',
    );
  });

  it('falls back to the kind and version when the object cannot be named', () => {
    const none = readCatalog(null);
    expect(referenceLabel(ref('material', 'policy', 2), none, 'zh').text).toBe('资料 · v2');
    expect(referenceLabel(ref('product', 'p9', 3), none, 'en').text).toBe('Work · v3');
    expect(referenceLabel(ref('event', 'ev-x'), none, 'zh').text).toBe('历史记录');
    expect(referenceLabel(ref('mystery', 'x', 4), none, 'zh').text).toBe('依据 · v4');
  });
});
