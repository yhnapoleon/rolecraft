import { afterEach, describe, expect, it } from 'vitest';
import { setPreference } from './i18n';
import { CASE, say } from './vocab.js';

afterEach(() => setPreference('zh'));

describe('situation words and the work language', () => {
  it('keeps an English practice’s brief in English when the interface switches to Chinese', () => {
    setPreference('zh');
    const brief = CASE('pilot', 'en');
    expect(brief.quote).toMatch(/^I want our first colleagues using the knowledge assistant/);
    expect(brief.title).toBe('Is the knowledge assistant ready for a pilot?');
    expect(CASE('urgent', 'en').change).toBe('Launch moves from day 7 to day 5');
  });

  it('keeps a Chinese practice’s brief in Chinese when the interface switches to English', () => {
    setPreference('en');
    expect(CASE('pilot', 'zh').quote).toMatch(/^我希望第一批同事下周就能用上知识助手/);
    expect(CASE('capacity', 'zh').change).toBe('容量从 30 人降到 15 人');
  });

  it('follows the interface language outside a practice', () => {
    setPreference('zh');
    expect(CASE('pilot').title).toBe('知识助手，准备好试点了吗？');
    setPreference('en');
    expect(CASE('pilot').title).toBe('Is the knowledge assistant ready for a pilot?');
    expect(CASE('pilot', null).title).toBe('Is the knowledge assistant ready for a pilot?');
    expect(CASE('unknown', 'en')).toEqual({ title: 'unknown', quote: '', change: '', minutes: '' });
  });

  it('picks world text by the work language, or by the interface without one', () => {
    setPreference('zh');
    expect(say('en')('政策已更新', 'Policy updated')).toBe('Policy updated');
    expect(say(null)('政策已更新', 'Policy updated')).toBe('政策已更新');
    setPreference('en');
    expect(say('zh')('政策已更新', 'Policy updated')).toBe('政策已更新');
    expect(say(undefined)('政策已更新', 'Policy updated')).toBe('Policy updated');
  });
});
