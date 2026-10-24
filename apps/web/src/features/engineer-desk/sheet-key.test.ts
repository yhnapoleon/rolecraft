// The top bar's key while the sign-off sheet is in view (plan §13.1): the paper's own key ("hold
// to sign") takes the ink. The shell's key has no secondary look, so "go to sign-off" stays where
// it is and steps back as a key that says why (Stage.primary.disabledReason).
import { describe, expect, it } from 'vitest';
import seeded from './fixtures/ticket-seeded.zh.json';
import signed from './fixtures/ticket-signed.zh.json';
import type { TicketDetail } from './model';
import { deskStage, publishDesk } from './wire';

const SEEDED = seeded as unknown as TicketDetail;
const SIGNED = signed as unknown as TicketDetail;
const drafted: TicketDetail = {
  ...SEEDED,
  trials: SIGNED.trials.slice(0, 2),
  drafts: SIGNED.drafts,
  latest_draft: SIGNED.latest_draft,
  reviews: [],
  review_budget: { used: 0, limit: 3 },
};

describe('engineer hat · the top bar key while the sheet is in view', () => {
  it('ED-R3-10 out of view, "go to sign-off" is the key as usual', () => {
    publishDesk('s-sheet-out', { ticket: drafted, candidate: {} });
    const p = deskStage('s-sheet-out').primary;
    expect(p?.action).toBe('engineer.signoff.focus');
    expect(p?.disabledReason).toBeUndefined();
  });

  it('ED-R3-11 in view, the same key steps back and says the sheet is right here', () => {
    publishDesk('s-sheet-in', { ticket: drafted, candidate: {}, sheetInView: true });
    const p = deskStage('s-sheet-in').primary;
    expect(p?.action).toBe('engineer.signoff.focus');
    expect(p?.disabledReason).toEqual(['签字单就在下面', 'The sheet is right here']);
  });

  it('ED-R3-12 other keys do not step back while the sheet is in view', () => {
    publishDesk('s-sheet-new', { ticket: SEEDED, candidate: {}, sheetInView: true });
    const p = deskStage('s-sheet-new').primary;
    expect(p?.action).toBe('engineer.reproduce');
    expect(p?.disabledReason).toBeUndefined();
  });
});
