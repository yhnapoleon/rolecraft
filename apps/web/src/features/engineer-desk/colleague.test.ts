import { beforeEach, describe, expect, it, vi } from 'vitest';
import { reasonText } from './colleague';
import { handedToGrace, keepGraceReply } from './grace-signal';

describe('AI colleagues on the page', () => {
  // The test runs without a DOM: a small in-memory storage stands in for the browser's.
  beforeEach(() => {
    const store = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
      clear: () => store.clear(),
    });
  });

  it('says why Daniel could not finish, in plain words, and keeps an unknown code as it is', () => {
    expect(reasonText('no_rule')).toMatch(/规则表|no rule/);
    expect(reasonText('something_new')).toBe('something_new');
  });

  it('remembers which review Grace already decided on, per practice', () => {
    keepGraceReply('s1', {
      at: '2026-10-25T00:00:00Z',
      ticketId: 't1',
      text: '已由 Grace 应用，配置从 v1 变为 v2。',
      result: 'applied',
      reviewId: 'r1',
    });
    expect(handedToGrace('s1', 'r1')?.result).toBe('applied');
    expect(handedToGrace('s1', 'r2')).toBeNull();
    expect(handedToGrace('s2', 'r1')).toBeNull();
  });
});
