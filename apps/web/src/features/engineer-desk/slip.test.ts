import { afterEach, describe, expect, it } from 'vitest';
import { setPreference } from '../../app/i18n';
import seeded from './fixtures/ticket-seeded.zh.json';
import type { TargetTest, TicketDetail } from './model';
import { targetSlip } from './slip';

afterEach(() => setPreference('zh'));

const SEEDED = seeded as unknown as TicketDetail;
const target = (patch: Partial<TargetTest>): TicketDetail => ({
  ...SEEDED,
  target_tests: [{ ...SEEDED.target_tests[0], ...patch }],
});
/** A delivered practice whose index was refreshed: the recorded answer already says 400. */
const FIXED = target({
  answer_summary: '费用管理通知：国内出差住宿报销上限现为每人每晚400元。',
  citations: [{ object_id: 'notice', version: 1, quote: '…400元…' }],
  source_versions: {},
  indexed_versions: {},
});

describe('engineer intro · the "to fix" slip, one structure for every way in (G12)', () => {
  it('ED-R2-20 a stale answer: the assistant’s recorded answer, what is wrong, and the amber tag', () => {
    const slip = targetSlip(SEEDED);
    expect(slip.query).toBe('住宿报销上限是多少？');
    expect(slip.quote).toContain('500');
    expect(slip.wrong).toBe('仍引用差旅政策 v1，没有提醒。');
    expect(slip.stale).toBe('差旅政策 v2 / 索引 v1');
  });

  it('ED-R2-21 the same in English', () => {
    setPreference('en');
    const slip = targetSlip(SEEDED);
    expect(slip.wrong).toBe('It still cites Travel policy v1, with no warning.');
    expect(slip.stale).toBe('Travel policy v2 / index v1');
  });

  it('ED-R2-22 a recorded answer that is already right is not quoted: the ticket’s problem only', () => {
    const slip = targetSlip(FIXED);
    expect(slip.quote).toBeNull();
    expect(slip.stale).toBeNull();
    expect(slip.wrong).toBe('知识助手还在按旧版差旅政策回答，而且没有提醒资料可能已过期。');
    expect(JSON.stringify(slip)).not.toContain('400');
  });

  it('ED-R2-23 no ticket opened yet (a delivered practice): the situation’s question and problem, no quote', () => {
    setPreference('en');
    const slip = targetSlip(null);
    expect(slip.query).toBe('What is the hotel reimbursement limit per night?');
    expect(slip.quote).toBeNull();
    expect(slip.wrong).toBe(
      'The assistant still answers from the old travel policy, with no warning that it may be out of date.',
    );
  });

  it('ED-R2-24 tests product handed over: quoted, with what product found wrong; more targets counted', () => {
    const handed: TicketDetail = {
      ...target({ source_versions: {}, indexed_versions: {}, status: 'fallback', citations: [] }),
      source: 'tests',
    };
    const two = { ...handed, target_tests: [...handed.target_tests, handed.target_tests[0]] };
    const slip = targetSlip(two);
    expect(slip.quote).toContain('500');
    expect(slip.wrong).toBe('转人工，产品经理认为这条答得不对。');
    expect(slip.stale).toBeNull();
    expect(slip.more).toBe(1);
  });
});
