import { afterEach, describe, expect, it } from 'vitest';
import { setPreference } from '../../app/i18n';
import reproduction from './fixtures/reproduction.zh.json';
import seeded from './fixtures/ticket-seeded.zh.json';
import {
  diffShort,
  reproductionVerdict,
  settingsDiff,
  type Experiment,
  type TicketDetail,
} from './model';

afterEach(() => setPreference('zh'));

const SEEDED = seeded as unknown as TicketDetail;
const REPRODUCTION = reproduction as unknown as Experiment;

describe('engineer desk · what a reproduction found', () => {
  it('ED-50 matching the record means the problem is still there (amber), never a green tick', () => {
    const verdict = reproductionVerdict(REPRODUCTION, SEEDED);
    expect(verdict.kind).toBe('still');
    expect(verdict.tone).toBe('warn');
    expect(verdict.label).toBe('问题还在');
    expect(verdict.sentence).toBe('仍引用差旅政策 v1，没有提醒。');
  });

  it('ED-51 a rerun that differs from the record says so in ink; a run without rows is not known', () => {
    const changed = reproductionVerdict(
      { ...REPRODUCTION, counts: { matched: 0, changed: 1, total: 1 } },
      SEEDED,
    );
    expect(changed).toMatchObject({ kind: 'differs', tone: 'ink', label: '和记录不同' });
    const empty = reproductionVerdict(
      { ...REPRODUCTION, status: 'failed', counts: { matched: 0, changed: 0, total: 0 } },
      SEEDED,
    );
    expect(empty).toMatchObject({ kind: 'error', tone: 'unknown' });
  });

  it('ED-52 in English the same facts read as work words', () => {
    setPreference('en');
    const verdict = reproductionVerdict(REPRODUCTION, SEEDED);
    expect(verdict.label).toBe('Still broken');
    expect(verdict.sentence).toBe('It still cites Travel policy v1 with no warning.');
  });
});

describe('engineer desk · changes as a diff', () => {
  it('ED-53 only differing settings, in the ticket’s field order, with values in words', () => {
    const rows = settingsDiff(
      SEEDED.baseline_config,
      {
        min_score: 0.2,
        freshness_guard: 'warn',
        domains: [...(SEEDED.baseline_config.domains as string[])].reverse(),
      },
      SEEDED.editable_fields,
    );
    expect(rows.map((r) => r.field)).toEqual(['freshness_guard', 'min_score']);
    expect(rows[0]).toMatchObject({ before: '不处理', after: '加提醒' });
    expect(rows[1]).toMatchObject({ before: '0.35', after: '0.2' });
    expect(diffShort(rows)).toBe('freshness_guard 不处理→加提醒 · min_score 0.35→0.2');
  });

  it('ED-54 a change given as before and after (from a trial or draft) reads the same way', () => {
    const rows = settingsDiff(
      SEEDED.baseline_config,
      { freshness_guard: { before: 'none', after: 'warn' } },
      SEEDED.editable_fields,
    );
    expect(rows).toEqual([
      { field: 'freshness_guard', name: '过期资料保护', before: '不处理', after: '加提醒' },
    ]);
  });
});
