import { afterEach, describe, expect, it } from 'vitest';
import { setPreference } from './i18n';
import { planWorkItems, syncStrategyWork, workCost, workItemChoice } from './pilot-config';

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
