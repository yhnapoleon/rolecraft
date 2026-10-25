import { describe, expect, it } from 'vitest';
import seeded from './fixtures/ticket-seeded.zh.json';
import type { TicketDetail } from './model';
import { deskStage, publishDesk } from './wire';

const SEEDED = seeded as unknown as TicketDetail;

describe('engineer hat · the practice’s name in the top bar (Stage.title)', () => {
  it('ED-R2-40 the engineer’s stage carries the ticket’s short name as a [zh, en] pair', () => {
    publishDesk('s-title', { ticket: SEEDED, candidate: {} });
    const stage = deskStage('s-title') as { title?: [string, string] };
    expect(stage.title).toEqual(['住宿上限排查 · 工程师', 'Hotel-limit fix · Engineer']);
  });

  it('ED-R2-41 a handed-over ticket names its tests; no ticket yet leaves the situation’s name', () => {
    publishDesk('s-tests', {
      ticket: {
        ...SEEDED,
        source: 'tests',
        target_tests: [...SEEDED.target_tests, ...SEEDED.target_tests],
      },
      candidate: {},
    });
    expect((deskStage('s-tests') as { title?: unknown }).title).toEqual([
      '2 条测试排查 · 工程师',
      '2 handed-over tests · Engineer',
    ]);
    expect((deskStage('s-none') as { title?: unknown }).title).toBeUndefined();
  });
});
