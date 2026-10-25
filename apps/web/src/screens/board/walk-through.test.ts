import { afterEach, describe, expect, it, vi } from 'vitest';
import { setPracticeLocale } from '../../app/i18n';
import type { Attempt } from '../../shell';
import { entryPending, entryStory, installWalkThrough } from './walk-through';
afterEach(() => {
  vi.unstubAllGlobals();
  setPracticeLocale(null);
});
describe('the entry story', () => {
  it.each(['pm', 'engineer'] as const)(
    'gives %s one start action and a separate, skippable tour',
    (job) => {
      vi.stubGlobal('localStorage', { getItem: () => '{}' });
      const a = { id: `new-${job}` } as Attempt;
      installWalkThrough({
        current: () => a,
        fresh: () => true,
        job: () => job,
        policyTask: () => 'policy',
        refresh() {},
        prepareTour() {},
        finish() {},
        text: (zh) => zh,
      });
      for (const lang of ['zh', 'en'] as const) {
        setPracticeLocale(lang);
        const html = entryStory(a);
        expect(entryPending(a)).toBe(true);
        expect(html.match(/class="btn primary"/g)).toHaveLength(1);
        expect(html).toContain('data-action="walk-accept"');
        expect(html).toContain('<details');
        expect(html).toContain('Grace');
        expect(html).not.toContain('rc-greetings');
        if (lang === 'en') expect(html).not.toMatch(/[\u4e00-\u9fff]/);
      }
    },
  );
  it('does not replay after taking the commission, skipping the tour, or returning to an older session', () => {
    const a = { id: 'old' } as Attempt;
    installWalkThrough({
      current: () => a,
      fresh: () => true,
      job: () => 'pm',
      policyTask: () => null,
      refresh() {},
      prepareTour() {},
      finish() {},
      text: (zh) => zh,
    });
    for (const value of [{ taken: 'policy' }, { tour: 'skipped' }, { tour: 'done' }]) {
      vi.stubGlobal('localStorage', { getItem: () => JSON.stringify({ old: value }) });
      expect(entryStory(a)).toBe('');
    }
    vi.stubGlobal('localStorage', { getItem: () => '{}' });
    installWalkThrough({
      current: () => a,
      fresh: () => false,
      job: () => 'pm',
      policyTask: () => null,
      refresh() {},
      prepareTour() {},
      finish() {},
      text: (zh) => zh,
    });
    expect(entryStory(a)).toBe('');
  });
});
