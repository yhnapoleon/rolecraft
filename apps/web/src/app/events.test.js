import { afterEach, describe, expect, it } from 'vitest';
import { eventLine } from './events.js';
import { setPreference } from './i18n';
import { materialTitle } from './vocab.js';
import { readCatalog, referenceLabel } from '../reference-catalog';

afterEach(() => setPreference('zh'));

const ref = (kind, id) => ({ session_id: 's', kind, object_id: id, version: 1 });
// Server events as the live adapter projects them into the attempt (v2 types, refs kept).
const server = (seq, type, detail = {}, refs = []) => ({
  id: `server-${seq}`,
  server: true,
  type,
  seq,
  detail,
  refs,
});
const versions = (before, after) => ({ before_versions: before, after_versions: after });
function attempt() {
  const events = [
    server(1, 'material_read', { material_id: 'brief', materialId: 'brief', version: 1 }),
    server(2, 'test_assistant', {}, [ref('test', 't1')]),
    server(3, 'config_applied', { config_id: 'pilot', config_version: 2 }),
    server(4, 'initial_plan_applied', versions({ brief: 1, policy: 1 }, { brief: 1, policy: 2 })),
    server(5, 'business_requested', { request_id: 'r1', requested: { dev_days: 6 } }),
    server(6, 'demo_schedule_changed', versions({ demo: 1 }, { demo: 2 })),
    server(7, 'business_decided', { status: 'approved', granted: { dev_days: 6 } }),
    server(8, 'resource_grant_committed', { granted: { dev_days: 6 } }),
    server(9, 'business_decided', { status: 'rejected', granted: {} }),
    server(10, 'index_refreshed', versions({ policy: 1 }, { policy: 2 })),
    server(11, 'submitted', {}, [ref('submission', 'sub-1')]),
    server(12, 'revision_opened', {}, [ref('cycle', 'c2')]),
    server(13, 'submitted', {}, [ref('submission', 'sub-2')]),
    server(14, 'business_scope_requested', versions({ scope_note: 1 }, { scope_note: 2 })),
    server(15, 'business_counteroffer_accepted'),
    server(16, 'a_future_type', { anything: true }),
  ];
  return {
    world: { policyVersion: 2, indexVersion: 2 },
    backend: {
      materials: [
        { id: 'brief', version: 1, title: '经理委托：内部知识助手试点' },
        { id: 'policy', version: 2, title: '费用管理通知：差旅住宿标准' },
        { id: 'demo', version: 2, title: '经理日程：内部演示' },
        { id: 'scope_note', version: 2, title: '业务范围讨论纪要 SCOPE-01' },
      ],
    },
    tests: [{ id: 't1', question: '住宿报销上限是多少？', taskId: 'task-1' }],
    events,
  };
}
const line = (a, seq) =>
  eventLine(
    a,
    a.events.find((e) => e.seq === seq),
  );

describe('activity lines for server events', () => {
  it('says what happened in Chinese, never the event code', () => {
    const a = attempt();
    expect(a.events.map((e) => line(a, e.seq).text)).toEqual([
      '读了《经理委托：内部知识助手试点》v1',
      '测试：住宿报销上限是多少？',
      '试点设置已保存为配置 v2',
      '资料更新：《费用管理通知：差旅住宿标准》v2',
      '向 Grace 申请：开发人日 6',
      'Grace 改了演示安排：《经理日程：内部演示》v2',
      'Grace 批准了申请：开发人日 6',
      '资源已生效：开发人日 6',
      'Grace 没有批准这次申请',
      '助手索引已刷新：《费用管理通知：差旅住宿标准》v2',
      '第 1 次交付已提交',
      '开始修订',
      '第 2 次交付已提交',
      'Chen 转来新的范围请求：《业务范围讨论纪要 SCOPE-01》v2',
      '你接受了 Grace 的还价',
      '记录了一项变化',
    ]);
  });

  it('says the same in English', () => {
    setPreference('en');
    const a = attempt();
    expect(line(a, 2).text).toBe('Test: 住宿报销上限是多少？');
    // A document published in Chinese keeps its Chinese title in the English interface.
    expect(line(a, 4).text).toBe('Document updated: “费用管理通知：差旅住宿标准” v2');
    expect(line(a, 5).text).toBe('Asked Grace for: dev days 6');
    expect(line(a, 7).text).toBe('Grace approved: dev days 6');
    expect(line(a, 11).text).toBe('Delivery 1 submitted');
    expect(line(a, 12).text).toBe('Started a revision');
    expect(line(a, 16).text).toBe('A change was recorded');
  });

  it('opens the object each line is about', () => {
    const a = attempt();
    expect(line(a, 1).open).toEqual({ action: 'open-doc', id: 'brief' });
    expect(line(a, 2).open).toEqual({ action: 'open-run', id: 't1' });
    expect(line(a, 2).taskId).toBe('task-1');
    expect(line(a, 3).open).toEqual({ action: 'config' });
    expect(line(a, 4).open).toEqual({ action: 'open-doc', id: 'policy', compare: true });
    expect(line(a, 5).open).toEqual({ action: 'resources' });
    expect(line(a, 10).open).toEqual({ action: 'open-bench' });
    expect(line(a, 11).open).toEqual({ action: 'to-review' });
    expect(line(a, 16).open).toBeUndefined();
  });

  it('marks changes from outside as world events in every task scope', () => {
    const a = attempt();
    expect([4, 6, 7, 8, 9, 14, 15].every((seq) => line(a, seq).world)).toBe(true);
    expect([1, 2, 3, 5, 10, 11, 12].some((seq) => line(a, seq).world)).toBe(false);
  });

  it('tells changes in the world in the work language, your own actions in the interface language', () => {
    // An English practice seen in the Chinese interface (and the other way round).
    const a = attempt();
    const english = (seq) => eventLine(a, a.events.find((e) => e.seq === seq), 'en').text;
    expect(english(7)).toBe('Grace approved: dev days 6');
    expect(english(4)).toBe('Document updated: “费用管理通知：差旅住宿标准” v2');
    expect(english(3)).toBe('试点设置已保存为配置 v2');
    expect(english(5)).toBe('向 Grace 申请：开发人日 6');
    const policy = server(20, 'policy_updated', {
      material_versions: [{ material_id: 'policy', version: 2 }],
    });
    expect(eventLine(a, policy, 'en').text).toBe('Travel policy updated to v2');
    expect(eventLine(a, policy).text).toBe('差旅政策更新为 v2');
    setPreference('en');
    expect(eventLine(a, policy, 'zh').text).toBe('差旅政策更新为 v2');
    const chinese = (seq) => eventLine(a, a.events.find((e) => e.seq === seq), 'zh').text;
    expect(chinese(7)).toBe('Grace 批准了申请：开发人日 6');
    expect(chinese(3)).toBe('Pilot settings saved as config v2');
  });

  it('falls back to a plain sentence when the test or document is no longer readable', () => {
    const a = { ...attempt(), tests: [], backend: { materials: [] } };
    expect(line(a, 2).text).toBe('运行了一次测试');
    expect(line(a, 2).open).toBeUndefined();
    expect(line(a, 1).text).toBe('读了一份资料');
  });
});

describe('one name per document across the workbench', () => {
  // A document is named by the formal title of its current version, in both languages:
  // on the board, in the activity, on evidence and for the event that changed it.
  const practice = (titles) => ({
    a: {
      world: {},
      backend: {
        materials: [{ id: 'policy', version: 2, title: titles['policy:2'] }],
        materialTitles: titles,
      },
      tests: [],
      events: [
        server(1, 'material_read', { material_id: 'policy', materialId: 'policy', version: 1 }),
        server(4, 'initial_plan_applied', versions({ policy: 1 }, { policy: 2 })),
      ],
    },
    catalog: readCatalog({
      objects: [],
      events: [
        {
          id: 'ev-4',
          seq: 4,
          type: 'initial_plan_applied',
          refs: [],
          data: versions({ policy: 1 }, { policy: 2 }),
        },
      ],
      workspace: { material_titles: titles },
    }),
  });
  const policy = (version) => ({ session_id: 's', kind: 'material', object_id: 'policy', version });
  const history = { session_id: 's', kind: 'event', object_id: 'ev-4', version: 1 };
  it.each([
    [
      'zh',
      { 'policy:1': '差旅住宿与交通政策', 'policy:2': '费用管理通知：差旅住宿标准' },
      '读了《差旅住宿与交通政策》v1',
      '费用管理通知：差旅住宿标准',
    ],
    [
      'en',
      {
        'policy:1': 'Travel policy: hotels and taxis',
        'policy:2': 'Expense-management notice: hotel allowance',
      },
      'Read “Travel policy: hotels and taxis” v1',
      'Expense-management notice: hotel allowance',
    ],
  ])(
    '%s: the board, the activity and the evidence use the same name',
    (language, titles, read, name) => {
      setPreference(language);
      const { a, catalog } = practice(titles);
      expect(materialTitle(a.backend.materials[0])).toBe(name);
      expect(eventLine(a, a.events[0]).text).toBe(read);
      expect(referenceLabel(policy(1), catalog, language).full).toBe(`${titles['policy:1']} · v1`);
      expect(referenceLabel(policy(2), catalog, language).full).toBe(`${name} · v2`);
      expect(eventLine(a, a.events[1]).text).toBe(referenceLabel(history, catalog, language).full);
    },
  );
});
