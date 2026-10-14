import { afterEach, describe, expect, it } from 'vitest';
import { setPreference } from './i18n';
import { practiceCardLine, practiceCards, practiceSharedLine } from './practice-cards';

const names: Record<string, string> = {
  'R3.capacity': '人数与容量',
  'R3.resources': '资源与时间',
  'R4.staleness_test': '政策更新后的复测',
  'R5.adjustment': '实际调整与复测',
  'R6.alternatives': '替代方案与取舍',
};
const REASON = '可以在变化后的条件中，再核对这轮已有的规则发现。';
const basis = (...criteria: string[]) =>
  criteria.map((criterion) => ({
    criterion,
    explanation: '本项仅核对明确承诺的受限范围及固定配置。',
  }));
const urgent = {
  id: 'pm_pilot_urgent-zh',
  title: '期限提前的知识助手试点',
  reason: REASON,
  basis: basis('R4.staleness_test', 'R5.adjustment', 'R6.alternatives'),
};
const capacity = {
  id: 'pm_pilot_capacity15-zh',
  title: '容量收紧的知识助手试点',
  reason: REASON,
  basis: basis('R4.staleness_test', 'R5.adjustment', 'R6.alternatives'),
};
const catalog = [
  {
    id: urgent.id,
    criteria: ['R3.resources', 'R4.staleness_test', 'R5.adjustment', 'R6.alternatives'],
  },
  {
    id: capacity.id,
    criteria: ['R3.capacity', 'R4.staleness_test', 'R5.adjustment', 'R6.alternatives'],
  },
];
const change = (id: string) =>
  id.startsWith('pm_pilot_urgent') ? '上线从第 7 天提前到第 5 天' : '容量从 30 人降到 15 人';

describe('optional practice cards', () => {
  it('states the findings both situations revisit once and gives each card its own reason', () => {
    const view = practiceCards([urgent, capacity], catalog, names, change);
    expect(view.reason).toBe(REASON);
    expect(view.shared).toEqual(['政策更新后的复测', '实际调整与复测', '替代方案与取舍']);
    expect(view.cards.map((card) => [card.title, card.change, card.focus])).toEqual([
      ['期限提前的知识助手试点', '上线从第 7 天提前到第 5 天', ['资源与时间']],
      ['容量收紧的知识助手试点', '容量从 30 人降到 15 人', ['人数与容量']],
    ]);
  });

  it('lists a finding only one situation revisits on that card', () => {
    const view = practiceCards(
      [{ ...urgent, basis: basis('R3.resources', 'R4.staleness_test') }, capacity],
      catalog,
      names,
      change,
    );
    expect(view.shared).toEqual(['政策更新后的复测']);
    expect(view.cards[0].focus).toEqual(['资源与时间']);
    expect(view.cards[1].focus).toEqual(['实际调整与复测', '替代方案与取舍', '人数与容量']);
  });

  it('names what a single suggested situation revisits', () => {
    const view = practiceCards([urgent], catalog, names, change);
    expect(view.shared).toEqual(['政策更新后的复测', '实际调整与复测', '替代方案与取舍']);
    expect(view.cards[0].focus).toEqual(['资源与时间']);
  });

  it('keeps a card-specific reason on its card', () => {
    const view = practiceCards(
      [urgent, { ...capacity, reason: '可以换一个情境，为这轮尚待核验的事项补充可观察记录。' }],
      catalog,
      names,
      change,
    );
    expect(view.reason).toBe('');
    expect(view.cards.map((card) => card.reason)).toEqual([
      REASON,
      '可以换一个情境，为这轮尚待核验的事项补充可观察记录。',
    ]);
  });
});

describe('practice card wording', () => {
  afterEach(() => setPreference('zh'));
  it('says what all suggested situations revisit, then why each one is worth practising', () => {
    const view = practiceCards([urgent, capacity], catalog, names, change);
    expect(practiceSharedLine(view)).toBe(
      '这些情境都会再核对：政策更新后的复测、实际调整与复测、替代方案与取舍',
    );
    expect(view.cards.map(practiceCardLine)).toEqual([
      '改变的条件：上线从第 7 天提前到第 5 天 · 另外核对：资源与时间',
      '改变的条件：容量从 30 人降到 15 人 · 另外核对：人数与容量',
    ]);
    expect(practiceSharedLine(practiceCards([urgent], catalog, names, change))).toBe(
      '这个情境会再核对：政策更新后的复测、实际调整与复测、替代方案与取舍',
    );
    setPreference('en');
    expect(practiceSharedLine(view)).toBe(
      'Each of these situations revisits: 政策更新后的复测, 实际调整与复测, 替代方案与取舍',
    );
    expect(practiceCardLine(view.cards[0])).toBe(
      'What changes: 上线从第 7 天提前到第 5 天 · Also checks: 资源与时间',
    );
  });

  it('says nothing shared when the suggestions share no finding', () => {
    const view = practiceCards(
      [
        { ...urgent, basis: basis('R3.resources') },
        { ...capacity, basis: basis('R3.capacity') },
      ],
      catalog,
      names,
      change,
    );
    expect(practiceSharedLine(view)).toBe('');
  });
});
