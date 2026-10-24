import { describe, expect, it } from 'vitest';
import { copyText } from '../results-native/localization';
import { LENS_COPY } from './lens-copy';

// 197 n5 (2026-10-24): the sentence counts use the legend's own words.
describe('lens sentence counts say what the legend says', () => {
  const values = { s: 3, c: 0, u: 6 };
  it('counts in the legend’s words, the number kept with its word', () => {
    expect(copyText(LENS_COPY, 'en', 'counts', values)).toBe(
      '3 match the materials · 0 contradict them · 6 not known yet',
    );
    expect(copyText(LENS_COPY, 'zh', 'counts', values)).toBe(
      '与材料一致 3 · 与材料矛盾 0 · 还不知道 6',
    );
  });
  it('names the work sentence by sentence the same way', () => {
    expect(copyText(LENS_COPY, 'en', 'relation_counts', values)).toBe(
      'Your work, by sentence: 3 match the materials · 0 contradict them · 6 not known yet',
    );
    expect(copyText(LENS_COPY, 'zh', 'relation_counts', values)).toBe(
      '作品逐句：与材料一致 3 · 与材料矛盾 0 · 还不知道 6',
    );
    // The words the legend uses.
    expect(LENS_COPY.zh.legend).toContain('与材料矛盾');
    expect(LENS_COPY.zh.legend).toContain('还不知道');
  });
});
