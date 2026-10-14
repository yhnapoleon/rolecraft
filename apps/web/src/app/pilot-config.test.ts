import { afterEach, describe, expect, it } from 'vitest';
import { setPreference } from './i18n';
import type { EffectiveConfig } from '../contracts-v2';
import {
  configUse,
  planWorkItems,
  savedConfigNotice,
  syncStrategyWork,
  workCost,
  workItemChoice,
} from './pilot-config';

afterEach(() => setPreference('zh'));

describe('work the strategy needs', () => {
  it('includes real-time sync work with the real-time strategy and counts it once', () => {
    expect(planWorkItems('realtime', ['scope', 'fallback'])).toEqual([
      'scope',
      'fallback',
      'realtime',
    ]);
    expect(planWorkItems('realtime', ['realtime', 'fallback'])).toEqual(['realtime', 'fallback']);
    expect(planWorkItems('daily', ['scope', 'fallback'])).toEqual(['scope', 'fallback']);
    expect(workCost('realtime', ['scope', 'fallback'])).toBe(7);
    expect(workCost('realtime', ['realtime', 'fallback'])).toBe(6);
    expect(workCost('daily', ['scope', 'fallback'])).toBe(2);
  });

  it('shows the strategy-included work as chosen and locked, with the reason beside it', () => {
    const locked = workItemChoice('realtime', { update: 'realtime', workItems: ['fallback'] });
    expect(locked).toContain('checked');
    expect(locked).toContain('disabled');
    expect(locked).toContain('随策略自动包含');
    const free = workItemChoice('realtime', { update: 'daily', workItems: ['fallback'] });
    expect(free).not.toContain('checked');
    expect(free).not.toContain('disabled');
    setPreference('en');
    expect(workItemChoice('realtime', { update: 'realtime', workItems: [] })).toContain(
      'Included with this strategy',
    );
  });

  it('locks the strategy work when the strategy is chosen and gives the choice back after', () => {
    type Box = {
      value: string;
      checked: boolean;
      disabled: boolean;
      dataset: Record<string, string>;
      note: { hidden: boolean };
      parentElement: { querySelector: () => { hidden: boolean } };
    };
    const box = (value: string, checked: boolean): Box => {
      const note = { hidden: true };
      return {
        value,
        checked,
        disabled: false,
        dataset: {},
        note,
        parentElement: { querySelector: () => note },
      };
    };
    const boxes = [box('scope', true), box('fallback', true), box('realtime', false)];
    const form = { querySelectorAll: () => boxes } as unknown as HTMLFormElement;
    const realtime = boxes[2];
    syncStrategyWork(form, 'realtime');
    expect([realtime.checked, realtime.disabled, realtime.note.hidden]).toEqual([
      true,
      true,
      false,
    ]);
    expect(boxes.slice(0, 2).map((b) => [b.checked, b.disabled])).toEqual([
      [true, false],
      [true, false],
    ]);
    syncStrategyWork(form, 'daily');
    expect([realtime.checked, realtime.disabled, realtime.note.hidden]).toEqual([
      false,
      false,
      true,
    ]);
  });
});

const saved = {
  id: 'pilot',
  session_id: 's',
  version: 2,
  config_version: 1,
  domains: ['faq', 'policy'],
  participants: 20,
  launch_day: 7,
  update_strategy: 'realtime',
  fallback: 'human',
  scope_filter: true,
  work_items: ['scope_filter', 'human_fallback', 'realtime_sync'],
} as EffectiveConfig['requested'];
const used = (
  requested: Partial<EffectiveConfig['requested']>,
  effective: Partial<EffectiveConfig['requested']>,
  differences: Record<string, string>,
): EffectiveConfig => ({
  requested: { ...saved, ...requested },
  effective: { ...saved, ...requested, ...effective },
  differences,
});

describe('saved settings beside what tests actually use', () => {
  it('says nothing when tests use the saved settings', () => {
    expect(configUse(used({}, {}, {}), 3)).toBeNull();
    expect(savedConfigNotice(2, null)).toBe('试点设置 v2 已保存，下一次测试会用它。');
  });

  it('names the daily index and the unapproved developer-days behind real-time sync', () => {
    const use = configUse(
      used(
        {},
        { update_strategy: 'daily', work_items: ['scope_filter', 'human_fallback'] },
        {
          update_strategy: 'realtime_sync_not_provisioned',
          work_items: 'requested_work_exceeds_approved_budget',
        },
      ),
      3,
    );
    expect(use).toEqual({
      text: '测试实际用：每日索引 · 实时同步还没批到开发人日（已批准 3 人日）',
      unfunded: true,
    });
    expect(savedConfigNotice(2, use)).toBe(
      '试点设置 v2 已保存；测试实际用：每日索引 · 实时同步还没批到开发人日（已批准 3 人日）。',
    );
    setPreference('en');
    expect(
      configUse(
        used(
          {},
          { update_strategy: 'daily', work_items: ['scope_filter', 'human_fallback'] },
          { update_strategy: 'realtime_sync_not_provisioned' },
        ),
        3,
      )?.text,
    ).toBe(
      "Tests actually use: Daily index · Real-time sync isn't funded yet (3 developer-days approved)",
    );
  });

  it('tells apart work the plan never scheduled from work waiting for approval', () => {
    const unplanned = configUse(
      used(
        { work_items: ['human_fallback'] },
        { update_strategy: 'daily', scope_filter: false },
        {
          update_strategy: 'realtime_sync_not_provisioned',
          scope_filter: 'scope_filter_not_provisioned',
        },
      ),
      3,
    );
    expect(unplanned).toEqual({
      text: '测试实际用：每日索引、不过滤知识范围 · 方案里没安排实时同步、知识范围过滤',
      unfunded: false,
    });
  });

  it('ignores feasibility notes and name normalisation that do not change answers', () => {
    expect(
      configUse(
        used(
          { participants: 40, domains: ['faq', 'policy'] },
          { domains: ['faq', 'policy_travel'] },
          { participants: 'requested_participants_exceed_approved_capacity' },
        ),
        3,
      ),
    ).toBeNull();
  });
});
