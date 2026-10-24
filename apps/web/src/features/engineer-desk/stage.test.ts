import { afterEach, describe, expect, it } from 'vitest';
import { setPreference } from '../../app/i18n';
import seeded from './fixtures/ticket-seeded.zh.json';
import signed from './fixtures/ticket-signed.zh.json';
import type { TicketDetail } from './model';
import { deskTarget, engineerStage } from './stage';

afterEach(() => setPreference('zh'));

const SEEDED = seeded as unknown as TicketDetail;
const SIGNED = signed as unknown as TicketDetail;
const [REPRO, TRIAL] = SIGNED.trials;
const DRAFT = SIGNED.latest_draft as NonNullable<TicketDetail['latest_draft']>;
const REVIEW = SIGNED.reviews[0];
const later = (iso: string, seconds: number) =>
  new Date(new Date(iso).getTime() + seconds * 1000).toISOString();

/** The ticket at a point of the flow: reproduced, trialled, drafted, signed. */
function at(stage: 'new' | 'reproduced' | 'trialled' | 'drafted' | 'signed'): TicketDetail {
  const order = ['new', 'reproduced', 'trialled', 'drafted', 'signed'];
  const reached = (s: string) => order.indexOf(stage) >= order.indexOf(s);
  return {
    ...SEEDED,
    trials: [...(reached('reproduced') ? [REPRO] : []), ...(reached('trialled') ? [TRIAL] : [])],
    drafts: reached('drafted') ? SIGNED.drafts : [],
    latest_draft: reached('drafted') ? DRAFT : null,
    reviews: reached('signed') ? SIGNED.reviews : [],
    review_budget: { used: reached('signed') ? 1 : 0, limit: 3 },
  };
}
const states = (s: ReturnType<typeof engineerStage>) => s.steps.map((x) => x.state);

describe('engineer stage · the three steps and the one key', () => {
  it('ED-60 a new ticket: reproduce is current and is the key', () => {
    const stage = engineerStage(at('new'), { candidate: {} });
    expect(stage.steps.map((s) => s.id)).toEqual(['reproduce', 'fix', 'signoff']);
    expect(stage.steps.map((s) => s.label)).toEqual([
      ['复现', 'Reproduce'],
      ['修复与试跑', 'Fix & trial'],
      ['签字', 'Sign off'],
    ]);
    expect(states(stage)).toEqual(['current', 'todo', 'todo']);
    expect(stage.primary).toEqual({
      label: ['复现问题', 'Reproduce the problem'],
      action: 'engineer.reproduce',
    });
  });

  it('ED-61 reproduced: fix is current and a trial is next; a run by the Agent counts too', () => {
    const stage = engineerStage(at('reproduced'), { candidate: {} });
    expect(states(stage)).toEqual(['done', 'current', 'todo']);
    expect(stage.primary?.action).toBe('engineer.trial');
    const byAgent = {
      ...at('reproduced'),
      trials: [{ ...REPRO, executor: { id: 'external:x', kind: 'external_agent' } }],
    };
    expect(states(engineerStage(byAgent, { candidate: {} }))).toEqual(['done', 'current', 'todo']);
  });

  it('ED-62 trialled without a draft: draft is the key; the candidate edited after the trial asks for a trial again', () => {
    const tried = engineerStage(at('trialled'), {
      candidate: { freshness_guard: 'warn', min_score: 0.2 },
    });
    expect(states(tried)).toEqual(['done', 'current', 'todo']);
    expect(tried.primary).toEqual({
      label: ['起草提交', 'Draft a sign-off'],
      action: 'engineer.draft.open',
    });
    const edited = engineerStage(at('trialled'), { candidate: { freshness_guard: 'warn' } });
    expect(edited.primary?.action).toBe('engineer.trial');
    // An untouched candidate after an Agent's trial is not an edit.
    expect(engineerStage(at('trialled'), { candidate: {} }).primary?.action).toBe(
      'engineer.draft.open',
    );
  });

  it('ED-63 a draft of the last trial’s settings: fix is done, sign-off current, go to the sheet', () => {
    const stage = engineerStage(at('drafted'), { candidate: {} });
    expect(states(stage)).toEqual(['done', 'done', 'current']);
    expect(stage.primary).toEqual({
      label: ['去签字', 'Go to sign-off'],
      action: 'engineer.signoff.focus',
    });
  });

  it('ED-64 a trial newer than the draft, on other settings, asks for a new draft', () => {
    const ticket = {
      ...at('drafted'),
      trials: [
        ...at('drafted').trials,
        {
          ...TRIAL,
          id: 'trial-2',
          created_at: later(DRAFT.created_at, 60),
          config_hash: 'other',
          changed_fields: ['freshness_guard'],
          changes: { freshness_guard: { before: 'none', after: 'warn' } },
        },
      ],
    };
    const stage = engineerStage(ticket, { candidate: {} });
    expect(states(stage)).toEqual(['done', 'current', 'todo']);
    expect(stage.primary?.action).toBe('engineer.draft.open');
  });

  it('ED-65 signed with a new failure: sign-off stays current and the key is "fix it again"', () => {
    const stage = engineerStage(at('signed'), {
      candidate: {},
      outcomes: { [REVIEW.review_id]: 'regressed' },
    });
    expect(states(stage)).toEqual(['done', 'done', 'current']);
    expect(stage.primary).toEqual({
      label: ['再修一轮', 'Fix it again'],
      action: 'engineer.fix-again',
    });
  });

  it('ED-66 signed and everything holds: all three done; the key hands back to the product manager', () => {
    const stage = engineerStage(at('signed'), {
      candidate: {},
      outcomes: { [REVIEW.review_id]: 'clean' },
    });
    expect(states(stage)).toEqual(['done', 'done', 'done']);
    expect(stage.primary).toEqual({
      label: ['交回产品经理', 'Back to the product manager'],
      action: 'engineer.hand-back',
      id: REVIEW.review_id,
    });
  });

  it('ED-67 spent budgets keep the key visible but say why it can’t be used', () => {
    const full = { ...at('reproduced'), experiment_budget: { used: 50, limit: 50 } };
    expect(engineerStage(full, { candidate: {} }).primary).toEqual({
      label: ['试跑', 'Run a trial'],
      action: 'engineer.trial',
      disabledReason: [
        '这份委托已经试满 50 次。可以直接起草签字。',
        'This ticket has used all 50 runs. You can draft a sign-off now.',
      ],
    });
    const spent = { ...at('drafted'), review_budget: { used: 3, limit: 3 } };
    expect(engineerStage(spent, { candidate: {} }).primary?.disabledReason?.[0]).toBe(
      '这份委托的 3 次复核已经用完。',
    );
    const blocked = engineerStage(at('reproduced'), {
      candidate: {},
      blocked: ['先改正标红的设置。', 'Fix the setting marked in red first.'],
    });
    expect(blocked.primary?.disabledReason?.[0]).toBe('先改正标红的设置。');
  });
});

describe('engineer stage · an action pressed away from the desk', () => {
  it('ED-68 opens this practice’s ticket at the step the action belongs to', () => {
    expect(deskTarget('engineer.fix-again', 't1')).toBe('t1?step=fix');
    expect(deskTarget('engineer.trial', 't1')).toBe('t1?step=fix');
    expect(deskTarget('engineer.reproduce', 't1')).toBe('t1?step=reproduce');
    expect(deskTarget('engineer.signoff.focus', 't1')).toBe('t1?step=signoff');
    expect(deskTarget('engineer.draft.open', 't1')).toBe('t1?step=signoff');
    // No ticket known for this practice: the desk finds its own.
    expect(deskTarget('engineer.trial', undefined)).toBeUndefined();
  });
});
