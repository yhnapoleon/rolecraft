import { describe, expect, it } from 'vitest';
import { locale, onLocaleChange, setPracticeLocale, setPreference, T } from './i18n';

// One practice, one language: inside a practice the interface speaks the practice's language;
// outside it the preference decides again.
describe('practice locale', () => {
  it('overrides the preference while inside a practice and gives it back after', () => {
    setPreference('en');
    expect(setPracticeLocale('zh')).toBe(true);
    expect(locale()).toBe('zh');
    expect(T('继续', 'Continue')).toBe('继续');
    expect(setPracticeLocale('zh')).toBe(false);
    expect(setPracticeLocale(null)).toBe(true);
    expect(locale()).toBe('en');
  });

  it('keeps the practice language when the home preference changes underneath', () => {
    setPreference('zh');
    setPracticeLocale('en');
    setPreference('zh');
    expect(locale()).toBe('en');
    setPracticeLocale(null);
    expect(locale()).toBe('zh');
  });

  it('tells listeners once per change', () => {
    setPreference('en');
    setPracticeLocale(null);
    const seen: string[] = [];
    const off = onLocaleChange((l) => seen.push(l));
    setPracticeLocale('zh');
    setPracticeLocale('zh');
    setPracticeLocale(null);
    off();
    expect(seen).toEqual(['zh', 'en']);
  });
});
