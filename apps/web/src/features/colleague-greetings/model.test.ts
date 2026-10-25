import { describe, expect, it } from 'vitest';
import { ARRIVAL_DELAYS, greetingStore, introduction, orderFor } from './model';
function storage() {
  const map = new Map<string, string>();
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => {
      map.set(k, v);
    },
  };
}
describe('preset colleague greetings', () => {
  it('does not enrol old or recovered sessions merely because they have no messages', () => {
    expect(greetingStore(storage()).claim('old')).toBeNull();
  });
  it('claims an explicitly created practice once, including reloads and a new tab', () => {
    const s = storage(),
      book = greetingStore(s);
    book.prepare('new', 'pm');
    expect(book.claim('new')).toBe('pm');
    expect(book.claim('new')).toBeNull();
    const next = greetingStore(s);
    next.prepare('new', 'pm');
    expect(next.claim('new')).toBeNull();
  });
  it('keeps the engineer role and puts the commissioning colleague first', () => {
    const book = greetingStore(storage());
    book.prepare('eng', 'engineer');
    expect(book.claim('eng')).toBe('engineer');
    expect(orderFor('engineer')).toEqual(['manager', 'technical', 'business']);
    expect(orderFor('pm')).toEqual(['manager', 'business', 'technical']);
    expect(ARRIVAL_DELAYS).toEqual([0, 2600, 5400]);
  });
  it('works without storage, and never treats a revisit as a new practice', () => {
    const broken = {
      getItem: () => {
        throw Error('blocked');
      },
      setItem: () => {
        throw Error('blocked');
      },
    };
    const book = greetingStore(broken);
    book.prepare('new', 'engineer');
    expect(book.claim('new')).toBe('engineer');
    expect(book.claim('new')).toBeNull();
    expect(greetingStore(broken).claim('new')).toBeNull();
  });
  it.each(['pm', 'engineer'] as const)(
    'provides separate bilingual identities and actionable questions for %s',
    (job) => {
      for (const person of orderFor(job))
        for (const language of ['zh', 'en'] as const) {
          const m = introduction(job, person, language);
          expect(m.hello).toContain(m.name);
          expect(m.hello).toContain(m.title);
          expect(m.questions).toHaveLength(2);
          expect(m.body.length).toBeGreaterThan(30);
          if (language === 'en')
            expect(m.hello + m.body + m.questions.join('')).not.toMatch(/[\u4e00-\u9fff]/);
          expect(m.body).not.toMatch(/30|24|5 days|7 days/);
        }
    },
  );
  it('distinguishes the manager’s product handback role in an engineer practice', () => {
    expect(introduction('engineer', 'manager', 'en').body).toContain('receive your repair report');
    expect(introduction('pm', 'manager', 'en').body).toContain('recommendation and evidence');
  });
});
